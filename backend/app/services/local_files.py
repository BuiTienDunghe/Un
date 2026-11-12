"""The agent's tools for files on this machine, batch 1: read only (laptop agent, 12/11/2026).

The owner names a few folders (AGENT_LOCAL_FILES_ROOTS, separated by ";"). The model sees each one
by its own name, and a path under it as "<name>/<sub/path>": never a drive letter or the Windows
account name. Every path it writes is resolved (links and junctions followed) and must still land
inside the folder it names. A link that points out of a folder is refused, and a name search
never walks into one.

Only the owner's web chat turn may use these tools. The /chat route puts LOCAL_FILES_KEY in the
turn's context, and no other caller does. Without the key the tools are neither offered to the
model nor run. A file's text was written by whoever wrote the file, so the loop marks it as data,
like every other tool result (agent_service, D5).

The loop gives a tool no timeout of its own (agent_service, TOOL_TIMEOUT), so these tools bound
themselves: entries looked at and seconds spent by a listing or a search, file size, PDF pages and
seconds.

Not in batch 1: reading on by the code ("đọc nốt"), searching inside files, OCR of scanned pages,
writing.
"""
from __future__ import annotations

import json
import os
import re
import stat
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from loguru import logger

from app.services.agent_service import BAD_ARGUMENTS, TOOL_FAILED, TOOL_UNAVAILABLE_HERE, AgentTool, ToolOutput, ToolRegistry, _bounded

# Put in a turn's tool context by the /chat route alone (routers/chat.py), for the machine's owner.
LOCAL_FILES_KEY = "local_files"
# Right after read_document (15) and before the Discord tools (20+).
LIST_ORDER, READ_ORDER = 17, 18
LIST_LABEL = "Đang xem tệp trên máy…"
READ_LABEL = "Đang đọc tệp trên máy…"

LIST_MAX_ENTRIES = 40
# Entries looked at by one call (one folder, or a whole name search) and the seconds it may take.
LIST_MAX_SCANNED = 2000
SEARCH_MAX_SCANNED = 5000
SCAN_MAX_SECONDS = 3.0
SEARCH_MAX_DEPTH = 8
FILE_MAX_BYTES = 20_000_000
PDF_MAX_PAGES = 300
PDF_MAX_SECONDS = 20.0
CACHED_FILES = 4
# Windows device names: "Documents/CON" must never be opened.
RESERVED_NAMES = re.compile(r"^(?:con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)(?:\..*)?$", re.IGNORECASE)

TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm", ".yaml", ".yml",
    ".ini", ".cfg", ".toml", ".sql", ".srt", ".rst", ".tex", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h",
    ".cs", ".go", ".rs", ".sh", ".bat", ".ps1", ".css",
})
READABLE_KINDS = "tệp chữ (.txt, .md, .csv, .json, mã nguồn…), PDF có lớp chữ, Word .docx"
# Files that usually hold a secret: hidden from a listing and refused on read. The owner chose the
# folders, but a folder like Documents often holds one, and nothing the model reads needs it.
SECRET_NAMES = re.compile(r"^(?:\.env(?:\..*)?|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|\.netrc|\.pgpass|\.git-credentials)$", re.IGNORECASE)
SECRET_SUFFIXES = frozenset({".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".keychain", ".ovpn"})

# Windows file attributes, by value: the stat module names only some of them.
_HIDDEN, _SYSTEM, _OFFLINE, _REPARSE = 0x2, 0x4, 0x1000, 0x400
_RECALL_ON_OPEN, _RECALL_ON_DATA_ACCESS = 0x40000, 0x400000

LIST_FILES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": (
            "Xem tệp trên máy của người dùng, chỉ trong những thư mục người dùng đã cho phép. Không truyền gì: "
            "liệt kê các thư mục được phép. Có folder: xem bên trong thư mục đó. Có name: tìm tệp có tên chứa chữ "
            "đó trong folder (bỏ trống = mọi thư mục được phép) và mọi thư mục con. Trả về path để đọc bằng read_file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Đường dẫn thư mục lấy từ kết quả list_files, ví dụ Documents/bao-cao"},
                "name": {"type": "string", "description": "Một phần tên tệp cần tìm, viết có dấu hay không dấu đều được"},
            },
            "required": [],
        },
    },
}
READ_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            f"Đọc chữ trong một tệp trên máy người dùng: {READABLE_KINDS}. Dùng path lấy từ kết quả list_files. "
            "Trả về một phần nội dung kèm next_from_char: muốn đọc tiếp thì gọi lại với from_char bằng số đó "
            "(null = đã hết tệp). Khi dùng nội dung, nêu tên tệp."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "path trong kết quả list_files, ví dụ Documents/bao-cao/q3.pdf"},
                "from_char": {"type": "integer", "description": "Đọc từ ký tự này, mặc định 0"},
            },
            "required": ["path"],
        },
    },
}


@dataclass(frozen=True)
class Root:
    """A folder the owner allowed: the name the model sees, and where it really is (resolved)."""

    name: str
    path: Path


class Refused(Exception):
    """A path or file the tools will not touch; the message is for the model."""

    def __init__(self, message: str, code: str = BAD_ARGUMENTS) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def parse_roots(value: str | None) -> list[Root]:
    """The allowed folders, from the setting. A folder that does not exist is left out with a log line
    that names no path (logs outlive the conversation). Two folders with the same name get " (2)"."""
    roots: list[Root] = []
    taken: set[str] = set()
    for raw in str(value or "").split(";"):
        text = raw.strip().strip('"').strip()
        if not text:
            continue
        try:
            path = Path(text).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            logger.warning("local files: one configured folder does not exist and is left out")
            continue
        if not path.is_dir():
            logger.warning("local files: one configured path is not a folder and is left out")
            continue
        base = path.name or path.drive.rstrip(":") or "root"
        name, number = base, 2
        while name.casefold() in taken:
            name, number = f"{base} ({number})", number + 1
        taken.add(name.casefold())
        roots.append(Root(name, path))
    return roots


def offered_here(tool_context: dict[str, Any]) -> bool:
    """AgentTool.available: only a turn the /chat route marked as the owner's."""
    return bool(tool_context.get(LOCAL_FILES_KEY))


def fold(text: str) -> str:
    """For matching a name: no case, no Vietnamese marks, đ as d."""
    decomposed = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _attributes(result: os.stat_result) -> int:
    return int(getattr(result, "st_file_attributes", 0) or 0)


def _cloud_only(result: os.stat_result) -> bool:
    """A OneDrive file whose content is not on this disk: reading it would start a download."""
    return bool(_attributes(result) & (_OFFLINE | _RECALL_ON_OPEN | _RECALL_ON_DATA_ACCESS))


def _secret(name: str) -> bool:
    return bool(SECRET_NAMES.match(name)) or Path(name).suffix.lower() in SECRET_SUFFIXES


def _hidden(name: str, result: os.stat_result) -> bool:
    return name.startswith((".", "~$", "$")) or bool(_attributes(result) & (_HIDDEN | _SYSTEM))


def _inside(path: Path, root: Root) -> bool:
    return path == root.path or root.path in path.parents


def _lexically_under(absolute: str, root: Root) -> str | None:
    """The part of `absolute` below `root`, by its letters alone (no disk or network touched), or None.
    os.path.abspath and normcase are string work on Windows (GetFullPathNameW does no I/O)."""
    folded, base = os.path.normcase(absolute), os.path.normcase(str(root.path))
    if folded == base:
        return ""
    prefix = base if base.endswith(os.sep) else base + os.sep
    return absolute[len(prefix):] if folded.startswith(prefix) else None


class _Budget:
    """How many entries one call may still look at, and until when."""

    def __init__(self, entries: int, seconds: float) -> None:
        self.left, self.deadline, self.exhausted = entries, monotonic() + seconds, False

    def take(self) -> bool:
        if self.left <= 0 or monotonic() > self.deadline:
            self.exhausted = True
            return False
        self.left -= 1
        return True


class LocalFiles:
    """The two tools over one set of allowed folders. Text read from a file is kept for the next
    call (CACHED_FILES files, keyed by path, size and modified time): reading on should not parse
    a PDF again."""

    def __init__(self, roots: list[Root]) -> None:
        self.roots = list(roots)
        self._cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self._lock = threading.Lock()

    # ── paths ──────────────────────────────────────────────────────────────

    def _root_names(self) -> str:
        return ", ".join(root.name for root in self.roots)

    def shown(self, root: Root, path: Path) -> str:
        """The path as the model sees it."""
        relative = path.relative_to(root.path).as_posix()
        return root.name if relative == "." else f"{root.name}/{relative}"

    def resolve(self, written: object) -> tuple[Root, Path]:
        """A path the model wrote -> (its allowed folder, the real path). Refused unless it exists and,
        with every link followed, is inside an allowed folder, and no folder on the way is hidden.

        Nothing outside an allowed folder is touched to decide this: an absolute path is first matched
        against the folders by its letters alone. Resolving `\\\\host\\share\\a.txt` first would already
        open a network connection (with the Windows login) and could hang on its timeout."""
        text = str(written or "").strip().strip('"').replace("\\", "/")
        if not text:
            raise Refused("Thiếu đường dẫn. Gọi list_files để lấy path.")
        outside = Refused(f"Đường dẫn này nằm ngoài các thư mục được phép ({self._root_names()}), nên không mở.")
        head = text.strip("/").partition("/")[0]
        named = next((root for root in self.roots if root.name.casefold() == head.casefold()), None)
        # "/Documents/a.txt" is the model adding a slash to a shown path, not a path from the disk's top.
        if named is None and (text.startswith("/") or re.match(r"^[A-Za-z]:", text)):
            absolute = os.path.abspath(text)
            found = next(((root, rest) for root in self.roots if (rest := _lexically_under(absolute, root)) is not None), None)
            if found is None:
                raise outside
            named, rest = found
            parts = [part for part in rest.replace("\\", "/").split("/") if part not in ("", ".")]
        else:
            if named is None:
                raise Refused(f"Không có thư mục được phép tên {head!r}. Chỉ có: {self._root_names()}.")
            parts = [part for part in text.strip("/").partition("/")[2].split("/") if part not in ("", ".")]
        if ".." in parts:
            raise Refused("Đường dẫn không được có '..'. Dùng đúng path trong kết quả list_files.")
        # A ":" would switch drive ("D:") or open a hidden stream ("a.txt:x"); a device name opens a device.
        # Windows drops trailing spaces and dots: "CON " is CON.
        if any(":" in part or RESERVED_NAMES.match(part.rstrip(" .")) for part in parts):
            raise outside
        candidate = named.path.joinpath(*parts)
        try:
            # Outside first, existing second: behind a link that points out of the folder, "không có tệp"
            # would otherwise tell which files exist out there. `candidate` is under the folder by its
            # letters here, so this touches nothing outside it but what such a link points to.
            if not _inside(candidate.resolve(strict=False), named):
                raise outside
            real = candidate.resolve(strict=True)
        except FileNotFoundError:
            raise Refused("Không có tệp hay thư mục này. Gọi list_files để xem tên đúng.") from None
        except (OSError, RuntimeError):
            raise Refused("Không mở được đường dẫn này.") from None
        # With every link followed: a link inside the folder may point out of it.
        if not _inside(real, named):
            raise outside
        self._refuse_hidden(named, real)
        return named, real

    def _refuse_hidden(self, root: Root, real: Path) -> None:
        """Every folder from the allowed one down to `real`, and `real` itself, must be one a listing would
        show: a hidden folder (AppData, .ssh, .docker) is not reachable by typing its path either."""
        current = root.path
        for part in real.relative_to(root.path).parts:
            current = current / part
            if _secret(part):
                raise Refused("Tệp này thường chứa mật khẩu hay khoá bí mật nên không đọc.")
            try:
                result = current.stat(follow_symlinks=False)
            except OSError:
                raise Refused("Không mở được đường dẫn này.") from None
            if _hidden(part, result):
                raise Refused("Đây là tệp hay thư mục ẩn của hệ thống nên không mở.")

    # ── list_files ─────────────────────────────────────────────────────────

    def _entry(self, root: Root, path: Path, result: os.stat_result, is_dir: bool) -> dict[str, object]:
        entry: dict[str, object] = {"path": self.shown(root, path), "type": "folder" if is_dir else "file"}
        if not is_dir:
            entry["size_kb"] = max(1, round(result.st_size / 1024)) if result.st_size else 0
            if _cloud_only(result):
                entry["cloud_only"] = True
        try:
            entry["modified"] = datetime.fromtimestamp(result.st_mtime).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            pass  # a date before 1970 raises on Windows; one odd file must not break the whole listing
        return entry

    def _children(self, root: Root, folder: Path, budget: _Budget) -> list[tuple[Path, os.stat_result, bool]]:
        """A folder's visible children, each still inside `root` once links are followed, as many as
        `budget` allows. Raises OSError when the folder itself cannot be opened."""
        children: list[tuple[Path, os.stat_result, bool]] = []
        with os.scandir(folder) as entries:
            for item in entries:
                if not budget.take():
                    break
                try:
                    result = item.stat(follow_symlinks=False)
                    if _hidden(item.name, result) or _secret(item.name):
                        continue
                    path = Path(item.path)
                    if item.is_symlink() or _attributes(result) & _REPARSE:
                        real = path.resolve(strict=True)
                        if not _inside(real, root):
                            continue
                        result, path = real.stat(), real
                        if _hidden(real.name, result) or _secret(real.name):
                            continue
                    is_dir = stat.S_ISDIR(result.st_mode)
                    if is_dir or stat.S_ISREG(result.st_mode):
                        children.append((path, result, is_dir))
                except OSError:
                    continue
        return children

    def list_files(self, service: Any, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        if not offered_here(tool_context or {}):
            return service._error(TOOL_UNAVAILABLE_HERE, "list_files chỉ dùng được khi chủ máy chat trên trang web.")
        folder = str(arguments.get("folder") or "").strip()
        name = str(arguments.get("name") or "").strip()
        try:
            if not folder and not name:
                entries = [{"path": root.name, "type": "folder"} for root in self.roots]
                return self._fit(service, {"folders": entries, "note": "Các thư mục người dùng cho phép xem."}, "folders")
            starts = [self.resolve(folder)] if folder else [(root, root.path) for root in self.roots]
        except Refused as refused:
            return service._error(refused.code, refused.message)
        for _, path in starts:
            if not path.is_dir():
                return service._error(BAD_ARGUMENTS, "folder phải là một thư mục. Muốn đọc tệp thì dùng read_file.")
        if name:
            return self._search(service, starts, name)
        root, path = starts[0]
        budget = _Budget(LIST_MAX_SCANNED, SCAN_MAX_SECONDS)
        try:
            children = sorted(self._children(root, path, budget), key=lambda child: (not child[2], fold(child[0].name)))
        except OSError:
            return service._error(BAD_ARGUMENTS, "Không mở được thư mục này (không có quyền xem). Nói với người dùng là chưa xem được.")
        entries = [self._entry(root, child, result, is_dir) for child, result, is_dir in children]
        payload: dict[str, object] = {"folder": self.shown(root, path), "entries": entries}
        if budget.exhausted:
            payload["note"] = "Thư mục quá nhiều mục, mới xem được một phần; tìm đúng tệp bằng name."
        elif not entries:
            payload["note"] = "Thư mục trống."
        return self._fit(service, payload, "entries")

    def _search(self, service: Any, starts: list[tuple[Root, Path]], name: str) -> ToolOutput:
        wanted = fold(name)
        budget = _Budget(SEARCH_MAX_SCANNED, SCAN_MAX_SECONDS)
        found: list[dict[str, object]] = []
        # The budget stops the whole search; a folder too deep only makes it incomplete.
        complete = True
        for root, start in starts:
            if budget.exhausted:
                break
            queue: list[tuple[Path, int]] = [(start, 0)]
            visited: set[Path] = set()
            while queue and not budget.exhausted:
                folder, depth = queue.pop(0)
                if folder in visited:
                    continue
                visited.add(folder)
                try:
                    children = self._children(root, folder, budget)
                except OSError:
                    continue
                for child, result, is_dir in sorted(children, key=lambda c: fold(c[0].name)):
                    if wanted in fold(child.name):
                        found.append(self._entry(root, child, result, is_dir))
                    if is_dir:
                        if depth + 1 < SEARCH_MAX_DEPTH:
                            queue.append((child, depth + 1))
                        else:
                            complete = False
        payload: dict[str, object] = {"name": name, "entries": found}
        if not complete or budget.exhausted:
            payload["note"] = "Chưa tìm hết vì thư mục quá nhiều tệp; thu hẹp bằng folder."
        elif not found:
            payload["note"] = "Không có tệp nào có tên chứa chữ này."
        return self._fit(service, payload, "entries")

    def _fit(self, service: Any, payload: dict[str, object], key: str) -> ToolOutput:
        """At most LIST_MAX_ENTRIES items and tool_result_max_chars characters, whole items only, with
        how many were left out: a cut JSON would leave the model nothing to read."""
        items = list(payload[key])  # type: ignore[arg-type]
        limit = int(getattr(service, "tool_result_max_chars", 2400))
        shown = items[:LIST_MAX_ENTRIES]

        def text(count: int) -> str:
            body = {**payload, key: shown[:count]}
            if len(items) > count:
                body["more"] = len(items) - count
                body.setdefault("note", "Còn nữa; thu hẹp bằng folder hoặc name.")
            return json.dumps(body, ensure_ascii=False)

        count = len(shown)
        while count > 0 and len(text(count)) > limit:
            count -= 1
        return text(count), None, None

    # ── read_file ──────────────────────────────────────────────────────────

    def read_file(self, service: Any, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        if not offered_here(tool_context or {}):
            return service._error(TOOL_UNAVAILABLE_HERE, "read_file chỉ dùng được khi chủ máy chat trên trang web.")
        try:
            root, path = self.resolve(arguments.get("path"))
            if path.is_dir():
                raise Refused("Đây là thư mục. Gọi list_files với folder này để xem bên trong.")
            result = path.stat()
            if not stat.S_ISREG(result.st_mode):
                raise Refused("Đây không phải một tệp thường nên không đọc.")
            if _secret(path.name):
                raise Refused("Tệp này thường chứa mật khẩu hay khoá bí mật nên không đọc.")
            if _cloud_only(result):
                raise Refused("Tệp này chỉ có trên OneDrive, chưa tải về máy, nên chưa đọc. Người dùng mở tệp một lần để tải về.", TOOL_UNAVAILABLE_HERE)
            if result.st_size > FILE_MAX_BYTES:
                raise Refused(f"Tệp lớn hơn {FILE_MAX_BYTES // 1_000_000} MB nên chưa đọc.", TOOL_UNAVAILABLE_HERE)
            text = self._text(path, result)
        except Refused as refused:
            return service._error(refused.code, refused.message)
        except OSError as error:
            logger.warning("local files: read failed: {}", type(error).__name__)
            return service._error(TOOL_FAILED, "Không mở được tệp này (đang bị khoá hoặc không có quyền). Nói với người dùng là chưa đọc được.", type(error).__name__)
        shown = self.shown(root, path)
        if not text.strip():
            note = (
                "Tệp PDF này không có lớp chữ (thường là ảnh quét) nên chưa đọc được. Người dùng có thể tải nó lên trang Tài liệu để nhận dạng chữ."
                if path.suffix.lower() == ".pdf" else "Tệp trống."
            )
            return json.dumps({"path": shown, "result": note}, ensure_ascii=False), None, None
        start = _bounded(arguments.get("from_char"), 0, 0)
        if start >= len(text):
            return json.dumps({"path": shown, "result": "đã hết tệp", "total_chars": len(text)}, ensure_ascii=False), None, None
        return self._slice(service, shown, text, start), None, None

    def _slice(self, service: Any, shown: str, text: str, start: int) -> str:
        """As much of the text from `start` as fits read_result_max_chars once written as JSON, ending at a
        space or line break when one is near, with where to read on."""
        limit = int(getattr(service, "read_result_max_chars", 6000))

        def body(end: int) -> str:
            following = end if end < len(text) else None
            return json.dumps({
                "path": shown, "total_chars": len(text), "from_char": start,
                "content": text[start:end], "next_from_char": following,
            }, ensure_ascii=False)

        end = min(len(text), start + limit)
        while end > start + 1 and len(body(end)) > limit:
            end = max(start + 1, end - (len(body(end)) - limit))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if cut > start and end - cut < 200:
                end = cut + 1
        return body(end)

    def _text(self, path: Path, result: os.stat_result) -> str:
        key = (str(path), result.st_size, result.st_mtime_ns)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        text = _extract(path)
        with self._lock:
            self._cache[key] = text
            while len(self._cache) > CACHED_FILES:
                self._cache.popitem(last=False)
        return text


def _extract(path: Path) -> str:
    """The text of one file, by kind. Native parsers only: the OCR path would start a model."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        from app.parsers.plain_text_parser import decode_text

        # Windows line ends cost the model a character each and add nothing.
        return decode_text(path.read_bytes()).replace("\r\n", "\n")
    if suffix == ".docx":
        from app.parsers.docx_parser import DocxParser

        try:
            return "\n\n".join(text for _, text in DocxParser().parse(path))
        except Exception as error:  # a broken or locked .docx is a refusal, not a crash
            raise Refused("Không đọc được tệp Word này (hỏng hoặc không phải .docx thật).") from error
    if suffix == ".pdf":
        return _pdf_text(path)
    raise Refused(f"Chưa đọc được loại tệp {suffix or 'không đuôi'}. Đọc được: {READABLE_KINDS}.", TOOL_UNAVAILABLE_HERE)


def _pdf_text(path: Path) -> str:
    """Page by page, each marked with its number so the answer can cite it. PyMuPDF's plain text, not
    the markdown the indexer makes: that one takes seconds a page, and a turn has 90 s in all."""
    import fitz

    try:
        document = fitz.open(path)
    except Exception as error:
        raise Refused("Không mở được tệp PDF này (hỏng hoặc không phải PDF thật).") from error
    with document:
        if document.needs_pass:
            raise Refused("Tệp PDF này có mật khẩu nên chưa đọc.", TOOL_UNAVAILABLE_HERE)
        deadline = monotonic() + PDF_MAX_SECONDS
        pages, count = [], 0
        for number in range(min(document.page_count, PDF_MAX_PAGES)):
            # The first page always, so a slow file reads as cut short, never as a scan with no text.
            if number and monotonic() > deadline:
                break
            text = document.load_page(number).get_text("text", sort=True).strip()
            count = number + 1
            if text:
                pages.append(f"[Trang {count}]\n{text}")
        if pages and document.page_count > count:
            pages.append(f"[Chỉ đọc {count} trang đầu trên {document.page_count} trang]")
    return "\n\n".join(pages)


def register(registry: ToolRegistry, roots_setting: str | None) -> list[Root]:
    """Add list_files and read_file when at least one configured folder exists. Returns the folders."""
    roots = parse_roots(roots_setting)
    if not roots:
        logger.warning("local files: switched on but no usable folder in AGENT_LOCAL_FILES_ROOTS; tools not added")
        return []
    tools = LocalFiles(roots)
    registry.register(AgentTool(LIST_FILES_SCHEMA, tools.list_files, LIST_LABEL, available=offered_here), LIST_ORDER)
    registry.register(AgentTool(READ_FILE_SCHEMA, tools.read_file, READ_LABEL, available=offered_here), READ_ORDER)
    logger.info("local files: {} folder(s) allowed", len(roots))
    return roots
