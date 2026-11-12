"""The agent's tools that change files on this machine, batch 2 (laptop agent, 12/11/2026).

Three tools, each waiting for the owner's approval before it runs (AgentTool.requires_approval):
write_file (create or overwrite a text file), move_file (rename or move a file), delete_file (moves
the file into the backup store). The owner's choices, 12/11:
- these three tools; an Undo button on the card, good for 3 days; pending approvals kept in memory,
  so a restart cancels them;
- after the first review: Undo refuses a file changed by hand since the assistant wrote it; reopening
  a conversation shows its cards again; script files and a changed extension are allowed, with a
  red warning on the card.

What protects the files:
- The same folders and rules as reading (local_files.py), plus rules for a new file's name.
- Checked twice: when the model asks (a wrong call goes back to the model, the owner is not asked)
  and when the owner approves. If what would happen changed in between, it does not run.
- Before anything is lost, it is kept: an overwritten file's old content is copied, a deleted file
  is moved, into data/local-files-backup/<change>/kept/, beside a change.json that no file name can
  collide with. A move loses nothing, so it is only recorded. An Undo keeps what it replaces in the
  same place, and a change folder is removed KEEP after its last event (the change, or its Undo).
- What runs is what the owner was shown: the run compares the plan it is about to carry out with the
  plan that was approved.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from loguru import logger

from app.services.agent_service import TOOL_FAILED, TOOL_UNAVAILABLE_HERE, AgentTool, ToolOutput
from app.services.approvals import APPROVAL_UNAVAILABLE, ApprovalError, ApprovalNotice
from app.services.local_files import (
    FILE_MAX_BYTES, LOCAL_FILES_KEY, RESERVED_NAMES, TEXT_SUFFIXES, LocalFiles, Missing, Refused, Root, _cloud_only,
    _inside, _secret, offered_here,
)

# One order for the three: the registry then lists them by name, right after read_file (18) and
# before the Discord tools (20+).
WRITE_TOOLS_ORDER = 19
KEEP = timedelta(days=3)
APPROVAL_TTL_SECONDS = 600.0
MAX_PENDING = 5
SETTLED_KEPT = 50
WRITE_MAX_CHARS = 50_000
DELETE_MAX_BYTES = 200_000_000
NAME_MAX_CHARS = 255
# Put in the context of an approved run by the gate alone: the plan the owner saw.
APPROVED_PLAN_KEY = "_approved_plan"
KEPT = "kept"
_ID = re.compile(r"^[0-9a-f]{32}$")
# Characters Windows refuses in a name: better refused before the owner is asked than after.
_FORBIDDEN_IN_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')
# Kinds that run when opened: allowed (owner's choice), with a warning on the card.
RUNNABLE_SUFFIXES = frozenset({
    ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".hta", ".py", ".pyw", ".sh", ".exe",
    ".com", ".msi", ".scr", ".lnk", ".reg", ".jar", ".url", ".html", ".htm",
})

WRITE_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Tạo tệp chữ mới hoặc ghi đè toàn bộ một tệp chữ (.txt, .md, .csv, .json…) trên máy người dùng, trong "
            "thư mục được phép. Người dùng phải duyệt trước khi tệp được ghi; bản cũ được giữ để hoàn tác. Thư mục "
            "chứa tệp phải có sẵn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Đường dẫn tệp, bắt đầu bằng tên thư mục được phép, ví dụ Documents/ghi-chu.md"},
                "content": {"type": "string", "description": "Toàn bộ nội dung mới của tệp"},
            },
            "required": ["path", "content"],
        },
    },
}
MOVE_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_file",
        "description": (
            "Đổi tên hoặc chuyển một tệp trên máy người dùng sang chỗ khác trong các thư mục được phép. Người dùng "
            "phải duyệt trước. Không ghi đè lên tệp đã có."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "path của tệp, lấy từ kết quả list_files"},
                "to": {"type": "string", "description": "Thư mục đích (giữ tên tệp) hoặc đường dẫn mới đầy đủ, ví dụ Documents/cu/bao-cao.pdf"},
            },
            "required": ["path", "to"],
        },
    },
}
DELETE_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_file",
        "description": "Xoá một tệp trên máy người dùng. Người dùng phải duyệt trước; tệp được giữ 3 ngày để hoàn tác.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "path của tệp, lấy từ kết quả list_files"}},
            "required": ["path"],
        },
    },
}
WRITE_TOOLS = ("write_file", "move_file", "delete_file")


@dataclass(frozen=True)
class Plan:
    """What a call would do, worked out without touching anything: shown to the owner, and compared at
    run time with what would happen then."""

    tool: str
    summary: str
    path: str
    to: str | None = None
    overwrites: bool = False
    content: str | None = None
    warning: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _writable_then_retry(function: Callable[[str], Any], path: str, _: object) -> None:
    """shutil.rmtree's onerror: Windows will not remove a read-only file until it is made writable."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


class Backups:
    """One folder per change under `folder`: change.json beside a kept/ folder holding what was kept.
    A change is removed `keep` after its last event (the change, or its Undo)."""

    def __init__(self, folder: Path, keep: timedelta = KEEP, clock: Callable[[], datetime] = _now) -> None:
        self.folder = folder
        self.keep = keep
        self.clock = clock

    def _changes(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return [path for path in self.folder.iterdir() if path.is_dir() and (path / "change.json").is_file()]

    @staticmethod
    def read(folder: Path) -> dict[str, Any]:
        record = json.loads((folder / "change.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not _ID.match(str(record.get("id"))) or "at" not in record:
            raise ValueError("not a change record")
        datetime.fromisoformat(str(record["at"]))
        return record

    @staticmethod
    def last_event(record: dict[str, Any]) -> datetime:
        return max(datetime.fromisoformat(str(record[key])) for key in ("at", "undone_at") if record.get(key))

    def prune(self) -> int:
        cutoff = self.clock() - self.keep
        removed = 0
        for path in self._changes():
            try:
                if self.last_event(self.read(path)) < cutoff:
                    shutil.rmtree(path, onerror=_writable_then_retry)
                    removed += 1
            except (OSError, ValueError, KeyError, TypeError) as error:
                logger.warning("local files: a backup could not be checked or removed: {}", type(error).__name__)
        return removed

    def open(self, record: dict[str, Any]) -> tuple[str, Path]:
        """A new change folder with its kept/ folder and its record; (change id, folder)."""
        self.prune()
        change_id = uuid4().hex
        at = self.clock()
        folder = self.folder / f"{at:%Y%m%d-%H%M%S}-{change_id}"
        (folder / KEPT).mkdir(parents=True)
        self.write(folder, {"id": change_id, "at": at.isoformat(), **record})
        return change_id, folder

    @staticmethod
    def write(folder: Path, record: dict[str, Any]) -> None:
        (folder / "change.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    def find(self, change_id: str) -> tuple[Path, dict[str, Any]]:
        if not _ID.match(str(change_id)):
            raise Refused("Không có thay đổi nào mang mã đó.")
        for path in self._changes():
            if path.name.endswith(f"-{change_id}"):
                try:
                    return path, self.read(path)
                except (OSError, ValueError, KeyError, TypeError):
                    raise Refused("Sổ ghi của thay đổi này bị hỏng nên không hoàn tác tự động được.") from None
        raise Refused("Không có thay đổi nào mang mã đó, hoặc nó đã quá 3 ngày nên bản cũ đã bị xoá.")

    def for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """The changes made in one conversation, newest last, as the cards show them."""
        cutoff = self.clock() - self.keep
        found = []
        for path in self._changes():
            try:
                record = self.read(path)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if record.get("conversation_id") != conversation_id or record.get("state") not in ("done", "undone"):
                continue
            if self.last_event(record) < cutoff:
                continue  # past its time, waiting for the next prune: nothing left to show

            undoable = record["state"] == "done" and datetime.fromisoformat(record["at"]) >= cutoff
            found.append({
                "id": record["id"], "at": record["at"], "summary": record.get("summary") or "", "warning": record.get("warning"),
                "state": record["state"], "undoable": undoable,
            })
        return sorted(found, key=lambda item: item["at"])


def _atomic_write(target: Path, content: str) -> None:
    """Written beside the target, then swapped in: a failure halfway leaves the old file whole."""
    temporary = target.with_name(f".~un-{uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_copy(source: Path, target: Path) -> None:
    temporary = target.with_name(f".~un-{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _runnable_warning(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    return f"Tệp {suffix} là loại chạy được khi mở. Chỉ duyệt nếu anh/chị đã đọc và tin nội dung." if suffix in RUNNABLE_SUFFIXES else None


class LocalFileWrites:
    """The three tools and Undo, over the same allowed folders as reading."""

    def __init__(self, files: LocalFiles, backups: Backups) -> None:
        self.files = files
        self.backups = backups
        self._lock = threading.Lock()

    # ── where a new or existing file may be ────────────────────────────────

    def _new(self, written: object) -> tuple[Root, Path, str]:
        """A path for a file that may not exist yet -> (folder, real path, shown path). Its folder must exist
        and pass every reading rule; its name must be a plain visible name Windows accepts."""
        text = str(written or "").strip().strip('"').replace("\\", "/").rstrip("/")
        parent, _, name = text.rpartition("/")
        if not parent or not name:
            raise Refused("Cần đường dẫn có cả tên thư mục được phép, ví dụ Documents/ghi-chu.md.")
        bare = name.rstrip(" .")
        if (
            not bare or bare != name or _FORBIDDEN_IN_NAME.search(name) or name.startswith((".", "~$", "$"))
            or RESERVED_NAMES.match(bare) or _secret(name) or len(name) > NAME_MAX_CHARS
        ):
            raise Refused('Tên tệp này không dùng được (ẩn, dành cho hệ thống, quá dài, hoặc có ký tự cấm như < > : " | ? *).')
        root, folder = self.files.resolve(parent)
        if not folder.is_dir():
            raise Refused("Phần trước tên tệp phải là một thư mục.")
        real = folder / name
        if not _inside(real, root):
            raise Refused("Đường dẫn này nằm ngoài các thư mục được phép, nên không ghi.")
        return root, real, self.files.shown(root, real)

    def _existing_file(self, written: object) -> tuple[Root, Path, os.stat_result]:
        root, real = self.files.resolve(written)
        result = real.stat()
        if real.is_dir() or not real.is_file():
            raise Refused("Đây không phải một tệp. Thư mục chưa chuyển hay xoá được.")
        if _cloud_only(result):
            raise Refused("Tệp này chỉ có trên OneDrive, chưa tải về máy, nên chưa làm được.", TOOL_UNAVAILABLE_HERE)
        return root, real, result

    def _exists(self, written: object) -> bool:
        """True or False inside an allowed folder; any other refusal (outside, hidden…) is raised."""
        try:
            self.files.resolve(written)
            return True
        except Missing:
            return False

    # ── plans ──────────────────────────────────────────────────────────────

    def check(self, tool: str, arguments: dict[str, Any]) -> Plan:
        """What this call would do now, or Refused with a sentence for the model. Touches nothing."""
        if tool == "write_file":
            return self._plan_write(arguments)
        if tool == "move_file":
            return self._plan_move(arguments)
        if tool == "delete_file":
            return self._plan_delete(arguments)
        raise Refused(f"Không có công cụ ghi {tool}.")

    def _plan_write(self, arguments: dict[str, Any]) -> Plan:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise Refused("write_file cần `content` là nội dung chữ của tệp.")
        if len(content) > WRITE_MAX_CHARS:
            raise Refused(f"Nội dung dài quá {WRITE_MAX_CHARS} ký tự nên chưa ghi.")
        if self._exists(arguments.get("path")):
            root, real, result = self._existing_file(arguments.get("path"))
            if real.suffix.lower() not in TEXT_SUFFIXES:
                raise Refused("Chỉ ghi đè được tệp chữ (.txt, .md, .csv, .json…), không ghi đè Word, PDF hay ảnh.")
            if result.st_size > FILE_MAX_BYTES:
                raise Refused(f"Tệp cũ lớn hơn {FILE_MAX_BYTES // 1_000_000} MB nên chưa ghi đè.", TOOL_UNAVAILABLE_HERE)
            shown = self.files.shown(root, real)
            return Plan(
                "write_file", f"Ghi đè tệp {shown} bằng {len(content)} ký tự mới (bản cũ được giữ 3 ngày)", shown,
                overwrites=True, content=content, warning=_runnable_warning(real.name),
            )
        root, real, shown = self._new(arguments.get("path"))
        if real.suffix.lower() not in TEXT_SUFFIXES:
            raise Refused("Chỉ tạo được tệp chữ (.txt, .md, .csv, .json…).")
        return Plan("write_file", f"Tạo tệp mới {shown} ({len(content)} ký tự)", shown, content=content, warning=_runnable_warning(real.name))

    def _plan_move(self, arguments: dict[str, Any]) -> Plan:
        root, real, _ = self._existing_file(arguments.get("path"))
        source = self.files.shown(root, real)
        destination = str(arguments.get("to") or "").strip().strip('"').replace("\\", "/").rstrip("/")
        if not destination:
            raise Refused("move_file cần `to`: thư mục đích, hoặc đường dẫn mới đầy đủ.")
        if self._exists(destination):
            to_root, to_real = self.files.resolve(destination)
            if not to_real.is_dir():
                raise Refused("Đã có tệp ở chỗ đích; chuyển không được ghi đè. Chọn tên khác.")
            destination = f"{self.files.shown(to_root, to_real)}/{real.name}"
            if self._exists(destination):
                raise Refused("Thư mục đích đã có tệp cùng tên; chuyển không được ghi đè. Chọn tên khác.")
        _, new_real, target = self._new(destination)
        if target == source:
            raise Refused("Chỗ đích trùng chỗ cũ.")
        old_suffix, new_suffix = real.suffix.lower(), new_real.suffix.lower()
        warnings = []
        if old_suffix != new_suffix:
            warnings.append(f"Đuôi tệp đổi từ {old_suffix or '(không có)'} sang {new_suffix or '(không có)'}.")
        if _runnable_warning(new_real.name):
            warnings.append(_runnable_warning(new_real.name))
        return Plan("move_file", f"Chuyển {source} sang {target}", source, to=target, warning=" ".join(warnings) or None)

    def _plan_delete(self, arguments: dict[str, Any]) -> Plan:
        root, real, result = self._existing_file(arguments.get("path"))
        if result.st_size > DELETE_MAX_BYTES:
            raise Refused(f"Tệp lớn hơn {DELETE_MAX_BYTES // 1_000_000} MB nên chưa xoá qua trợ lý.", TOOL_UNAVAILABLE_HERE)
        shown = self.files.shown(root, real)
        return Plan("delete_file", f"Xoá tệp {shown} (giữ 3 ngày để hoàn tác)", shown)

    # ── running an approved call ───────────────────────────────────────────

    def runner(self, tool: str) -> Callable[[Any, dict[str, Any], dict[str, Any] | None], ToolOutput]:
        def run(service: Any, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
            context = tool_context or {}
            approved = context.get(APPROVED_PLAN_KEY)
            if not offered_here(context) or not isinstance(approved, Plan):
                return service._error(TOOL_UNAVAILABLE_HERE, f"{tool} chỉ chạy sau khi chủ máy duyệt trên trang web.")
            try:
                with self._lock:
                    plan = self.check(tool, arguments)
                    if plan != approved:
                        raise Refused("Tệp đã thay đổi từ lúc xin duyệt nên không làm. Nhờ lại nếu vẫn cần.")
                    folder, record = self._prepare(plan, context.get("conversation_id"))
                    self._carry_out(plan, folder)
            except Refused as refused:
                return service._error(refused.code, refused.message)
            except OSError as error:
                logger.warning("local files: {} failed: {}", tool, type(error).__name__)
                return service._error(TOOL_FAILED, "Không làm được (tệp đang mở ở chương trình khác, hoặc không có quyền). Chưa có gì thay đổi.", type(error).__name__)
            # The disk has changed now: a record that cannot be closed must not read as "nothing changed".
            try:
                Backups.write(folder, {**record, "state": "done"})
            except OSError as error:
                logger.warning("local files: {} done but its record could not be closed: {}", tool, type(error).__name__)
                return json.dumps({"done": plan.summary, "note": "Đã làm, nhưng chưa ghi được sổ hoàn tác; bản cũ vẫn nằm trong thư mục bản cũ."}, ensure_ascii=False), None, None
            return json.dumps({"done": plan.summary, "change_id": record["id"]}, ensure_ascii=False), None, None

        return run

    def _prepare(self, plan: Plan, conversation_id: object) -> tuple[Path, dict[str, Any]]:
        record: dict[str, Any] = {
            "tool": plan.tool, "path": plan.path, "to": plan.to, "summary": plan.summary, "warning": plan.warning,
            "conversation_id": conversation_id if isinstance(conversation_id, str) else None, "state": "saving",
        }
        if plan.tool == "write_file":
            content = (plan.content or "").encode("utf-8")
            record.update(created=not plan.overwrites, written_sha256=hashlib.sha256(content).hexdigest(), written_size=len(content))
        change_id, folder = self.backups.open(record)
        return folder, {**record, "id": change_id, "at": Backups.read(folder)["at"]}

    def _carry_out(self, plan: Plan, folder: Path) -> None:
        kept = folder / KEPT
        if plan.tool == "write_file":
            if plan.overwrites:
                _, real, _ = self._existing_file(plan.path)
                shutil.copy2(real, kept / real.name)
            else:
                _, real, _ = self._new(plan.path)
            _atomic_write(real, plan.content or "")
        elif plan.tool == "move_file":
            _, real, _ = self._existing_file(plan.path)
            _, target, _ = self._new(plan.to)
            shutil.move(str(real), str(target))
        else:
            _, real, _ = self._existing_file(plan.path)
            shutil.move(str(real), str(kept / real.name))

    # ── Undo ───────────────────────────────────────────────────────────────

    def undo(self, change_id: str) -> str:
        """Put back what one change did; returns a sentence for the owner. Refused when the place it would
        put a file back is taken, or the file was changed by hand since the assistant wrote it. What an
        Undo replaces is kept too, in the change's kept/ folder."""
        with self._lock:
            folder, record = self.backups.find(change_id)
            if record.get("state") != "done":
                raise Refused("Thay đổi này đã được hoàn tác, hoặc chưa làm xong, nên không hoàn tác được.")
            if datetime.fromisoformat(record["at"]) < self.backups.clock() - self.backups.keep:
                raise Refused("Thay đổi này đã quá 3 ngày nên không hoàn tác được.")
            kept = folder / KEPT
            tool, path = record.get("tool"), str(record.get("path") or "")
            if tool == "write_file":
                current = self._exists(path)
                if current:
                    _, real, _ = self._existing_file(path)
                    if _sha256_file(real) != record.get("written_sha256"):
                        raise Refused(
                            f"Tệp {path} đã bị sửa sau khi trợ lý ghi nên không hoàn tác tự động, để khỏi mất phần đã sửa. "
                            "Bản trước khi trợ lý ghi vẫn nằm trong thư mục bản cũ (data/local-files-backup)."
                        )
                if record.get("created"):
                    if current:
                        shutil.move(str(real), str(kept / f"undone-{real.name}"))
                    sentence = f"Đã hoàn tác: bỏ tệp {path} mà trợ lý đã tạo (vẫn giữ một bản trong thư mục bản cũ)."
                else:
                    saved = kept / Path(path).name
                    if current:
                        shutil.copy2(real, kept / f"undone-{real.name}")
                    else:
                        _, real, _ = self._new(path)
                    _atomic_copy(saved, real)
                    sentence = f"Đã hoàn tác: tệp {path} trở về bản trước khi trợ lý ghi."
            elif tool == "move_file":
                _, moved, _ = self._existing_file(record.get("to"))
                if self._exists(path):
                    raise Refused(f"Đã có tệp khác ở {path} nên chưa chuyển về được.")
                _, back, _ = self._new(path)
                shutil.move(str(moved), str(back))
                sentence = f"Đã hoàn tác: chuyển {record.get('to')} về lại {path}."
            elif tool == "delete_file":
                if self._exists(path):
                    raise Refused(f"Đã có tệp khác ở {path} nên chưa đưa tệp cũ về được.")
                _, back, _ = self._new(path)
                shutil.move(str(kept / Path(path).name), str(back))
                sentence = f"Đã hoàn tác: tệp {path} đã trở lại."
            else:
                raise Refused("Không hoàn tác được loại thay đổi này.")
            Backups.write(folder, {**record, "state": "undone", "undone_at": self.backups.clock().isoformat()})
            return sentence


@dataclass
class Pending:
    id: str
    tool: str
    arguments: dict[str, Any]
    plan: Plan
    conversation_id: str | None
    expires_at: float
    status: str = "pending"
    result: dict[str, Any] | None = None


class LocalApprovals:
    """The approval gate for the owner's web chat (app.services.approvals.ApprovalGate), in memory.

    Only the three write tools come here from the owner's turn; any other tool goes to `fallback` (the
    Discord gate, when that one is on) unchanged. Approving moves a call pending -> running under a lock,
    so two clicks run it at most once."""

    def __init__(
        self,
        writes: LocalFileWrites,
        run_approved: Callable[[str, dict[str, Any], dict[str, Any] | None], ToolOutput],
        *,
        record_message: Callable[[str, str], None] | None = None,
        fallback: Any = None,
        ttl_seconds: float = APPROVAL_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.writes = writes
        self.run_approved = run_approved
        self.record_message = record_message
        self.fallback = fallback
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._pending: dict[str, Pending] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = self.clock()
        for item in self._pending.values():
            if item.status == "pending" and item.expires_at <= now:
                item.status = "expired"
        settled = [key for key, item in self._pending.items() if item.status not in ("pending", "running")]
        for key in settled[:-SETTLED_KEPT]:
            del self._pending[key]

    def request(self, tool_name: str, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ApprovalNotice:
        context = tool_context or {}
        if tool_name not in WRITE_TOOLS:
            if self.fallback is not None:
                return self.fallback.request(tool_name, arguments, tool_context)
            raise ApprovalError(APPROVAL_UNAVAILABLE, f"{tool_name} cần người dùng duyệt nhưng ở đây chưa duyệt được nên chưa làm.")
        if not offered_here(context):
            raise ApprovalError(APPROVAL_UNAVAILABLE, f"{tool_name} chỉ dùng được khi chủ máy chat trên trang web.")
        shown = json.loads(json.dumps(arguments, ensure_ascii=False))
        try:
            plan = self.writes.check(tool_name, shown)
        except Refused as refused:
            raise ApprovalError(refused.code, refused.message) from None
        with self._lock:
            self._expire()
            for item in self._pending.values():
                if item.status == "pending" and item.plan == plan:
                    return self._notice(item)
            if sum(item.status == "pending" for item in self._pending.values()) >= MAX_PENDING:
                raise ApprovalError("TOO_MANY_PENDING", f"Đang có {MAX_PENDING} việc chờ duyệt. Nói người dùng duyệt hoặc từ chối bớt rồi hãy nhờ thêm.")
            conversation_id = context.get("conversation_id")
            item = Pending(uuid4().hex, tool_name, shown, plan, conversation_id if isinstance(conversation_id, str) else None, self.clock() + self.ttl_seconds)
            self._pending[item.id] = item
        return self._notice(item)

    def _notice(self, item: Pending) -> ApprovalNotice:
        minutes = max(1, round(self.ttl_seconds / 60))
        return ApprovalNotice(item.id, (
            f"Mình cần bạn duyệt trước khi làm việc này: {item.plan.summary}.\n"
            f"Bấm Duyệt hoặc Từ chối ở thẻ bên dưới. Sau {minutes} phút không duyệt thì việc này bị huỷ và không chạy."
        ))

    def _get(self, approval_id: str) -> Pending:
        if not _ID.match(str(approval_id)) or approval_id not in self._pending:
            raise ApprovalError("APPROVAL_NOT_FOUND", "Không có việc chờ duyệt nào mang mã đó (có thể máy chủ đã khởi động lại).")
        return self._pending[approval_id]

    def get(self, approval_id: str) -> dict[str, Any]:
        with self._lock:
            self._expire()
            return self._payload(self._get(approval_id))

    def pending_for(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._expire()
            return [self._payload(item) for item in self._pending.values() if item.status == "pending" and item.conversation_id == conversation_id]

    def _payload(self, item: Pending) -> dict[str, Any]:
        left = max(0, round(item.expires_at - self.clock()))
        return {
            "id": item.id, "tool": item.tool, "status": item.status, "summary": item.plan.summary,
            "plan": {key: value for key, value in asdict(item.plan).items() if value is not None},
            "seconds_left": left if item.status == "pending" else 0, "result": item.result,
        }

    def _note(self, item: Pending, text: str) -> None:
        if item.conversation_id and self.record_message is not None:
            try:
                self.record_message(item.conversation_id, text)
            except Exception as error:  # what happened on disk must not be hidden by a missing note
                logger.warning("local files: could not note an approval in the conversation: {}", type(error).__name__)

    def decide(self, approval_id: str, approve: bool) -> dict[str, Any]:
        with self._lock:
            self._expire()
            item = self._get(approval_id)
            if item.status == "expired":
                raise ApprovalError("APPROVAL_EXPIRED", "Việc này đã quá hạn duyệt nên bị huỷ, không chạy.")
            if item.status != "pending":
                raise ApprovalError("APPROVAL_NOT_PENDING", "Việc này đã được xử lý rồi.")
            if not approve:
                item.status = "denied"
                payload = self._payload(item)
            else:
                item.status = "running"
                payload = None
        if payload is not None:
            self._note(item, f"Bạn đã từ chối: {item.plan.summary}. Chưa làm gì.")
            return payload
        context = {LOCAL_FILES_KEY: True, APPROVED_PLAN_KEY: item.plan, "conversation_id": item.conversation_id}
        try:
            text, code, _ = self.run_approved(item.tool, item.arguments, context)
        except Exception as error:
            logger.warning("approved {} failed: {}", item.tool, type(error).__name__)
            text, code = json.dumps({"error": "Không làm được do lỗi hệ thống. Chưa chắc đã có gì thay đổi."}, ensure_ascii=False), TOOL_FAILED
        try:
            result = json.loads(text)
        except (TypeError, ValueError):
            result = {"error": str(text)}
        with self._lock:
            item.status = "done" if code is None else "failed"
            item.result = result
        if code is None:
            self._note(item, f"Đã làm sau khi bạn duyệt: {item.plan.summary}.")
        else:
            self._note(item, f"Chưa làm được: {item.plan.summary}. Lý do: {result.get('error', 'lỗi không rõ')}")
        return self._payload(item)


def register(agent: Any, roots: list[Root], backup_folder: Path, record_message: Callable[[str, str], None] | None = None) -> LocalApprovals | None:
    """Add the three tools and make `agent.approvals` the gate for them (the previous gate, if any, keeps
    every other call). None, and nothing added, when the backup folder overlaps an allowed folder."""
    folder = backup_folder.resolve()
    if any(_inside(folder, root) or _inside(root.path, Root(root.name, folder)) for root in roots):
        logger.warning("local files: the backup folder overlaps an allowed folder; write tools not added")
        return None
    backups = Backups(folder)
    backups.prune()
    writes = LocalFileWrites(LocalFiles(roots), backups)
    for schema in (WRITE_FILE_SCHEMA, MOVE_FILE_SCHEMA, DELETE_FILE_SCHEMA):
        name = schema["function"]["name"]
        agent.registry.register(
            AgentTool(schema, writes.runner(name), "Đang chuẩn bị việc cần duyệt…", requires_approval=True, available=offered_here),
            WRITE_TOOLS_ORDER,
        )
    gate = LocalApprovals(writes, agent.run_approved, record_message=record_message, fallback=agent.approvals)
    agent.approvals = gate
    logger.info("local files: write tools added, backups kept {} days", KEEP.days)
    return gate
