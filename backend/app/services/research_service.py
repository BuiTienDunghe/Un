"""Không gian Nghiên cứu: dự án → paper (một Document sẵn có) → highlight, tóm tắt, kết nối.

Thiết kế (spec .scratch/research-space/spec.md):
- Paper = dòng `research_papers` trỏ tới một `documents`; tải lên, OCR, chunk, trích
  dẫn dùng lại PostgresDocumentService và RagService — không có pipeline thứ hai.
- Tóm tắt / insight là MỘT lượt gọi Ollama ra JSON (`format` = JSON schema, `think:false`,
  theo mẫu discord_memory_extractor), vai trò `general`, kết quả cache trên dòng; gọi tay.
- Metadata và mục lục đọc thẳng từ PDF bằng PyMuPDF — hàm thuần ở đầu tệp, test không
  cần Postgres/Ollama.
- Quyền: `owner` là user_id khi bật tài khoản và người gọi là member; None = thấy tất cả
  (tắt tài khoản, admin, service lane) — y như conversations.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import fitz
import httpx
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.llm_clients.ollama_client import OllamaModelNotLoadedError, OllamaTimeoutError, OllamaUnavailableError
from app.postgres.models import Document, IngestionRun, Message, ResearchAnnotation, ResearchCluster, ResearchEdge, ResearchPaper, ResearchProject, ResearchThread, new_id
from app.postgres.repositories import PostgresDocumentRepository
from app.schemas.research_schema import PaperSummary, ProjectInsights
from app.services import document_pages
from app.services.postgres_document_service import DocumentAlreadyIndexingError, DocumentNotFoundError, SourceUnavailableError


# ── Lỗi ───────────────────────────────────────────────────────────────────────
class ResearchError(Exception):
    pass


class ProjectNotFoundError(ResearchError):
    pass


class PaperNotFoundError(ResearchError):
    pass


class ClusterNotFoundError(ResearchError):
    pass


class EdgeNotFoundError(ResearchError):
    pass


class AnnotationNotFoundError(ResearchError):
    pass


class SummaryMissingError(ResearchError):
    """Chưa paper nào trong dự án có tóm tắt → không có gì để rút insight."""


class NotIndexedError(ResearchError):
    """Paper chưa có chữ (chưa lập chỉ mục) → không tóm tắt / không hỏi được."""


class FetchUnsupportedError(ResearchError):
    """Thêm paper theo link/DOI/tiêu đề: máy chủ chạy offline."""


class InvalidEdgeError(ResearchError):
    pass


class ThreadNotFoundError(ResearchError):
    pass


class ThreadMismatchError(ResearchError):
    """Luồng tồn tại nhưng không thuộc scope/id gửi kèm."""


# ── Hàm thuần: metadata, mục lục, prompt, xuất ───────────────────────────────
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4})\.(\d{4,5})(?:v\d+)?", re.IGNORECASE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)")
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
FIGURE_RE = re.compile(r"^(Fig\.?|Figure|Table)\s*(\d+)", re.IGNORECASE)
SUMMARY_TEXT_CAP = 12_000
SUMMARY_TIMEOUT_SECONDS = 180.0
CHAT_SCOPE_CAP = 100


def short_name_from_title(title: str | None, fallback: str = "paper") -> str:
    """Phần trước dấu `:` của tiêu đề, ≤ 24 ký tự, cắt ở ranh giới từ."""
    source = (title or "").strip() or fallback
    head = source.split(":", 1)[0].strip() or source
    if len(head) <= 24:
        return head
    cut = head[:24]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip() or head[:24]


def _page_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """Mỗi dòng chữ ngang của trang: text, cỡ chữ lớn nhất, toạ độ y."""
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if abs(direction[0]) < 0.9:  # chữ xoay (watermark arXiv bên lề)
                continue
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = " ".join(span["text"].strip() for span in spans)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            lines.append({"text": text, "size": max(float(span.get("size", 0)) for span in spans), "y": float(line["bbox"][1]), "chars": len(text)})
    lines.sort(key=lambda item: item["y"])
    return lines


def _looks_like_title(text: str) -> bool:
    return len(text) >= 4 and not ARXIV_RE.search(text) and not re.fullmatch(r"[\d\W]+", text)


def extract_metadata(pdf_path: Path) -> dict[str, Any]:
    """Tiêu đề = dòng cỡ chữ lớn nhất trang 1 (gộp các dòng kề cùng cỡ); tác giả =
    dòng ngay dưới; arXiv id + năm từ watermark; DOI; năm dự phòng từ chữ trang 1
    hoặc ngày tạo tệp. Mọi trường có thể None — không bịa."""
    result: dict[str, Any] = {"title": None, "authors": None, "year": None, "arxiv_id": None, "doi": None}
    try:
        document = fitz.open(str(pdf_path))
    except Exception:
        return result
    try:
        if len(document) == 0:
            return result
        page = document[0]
        text = page.get_text("text") or ""
        lines = _page_lines(page)
        candidates = [line for line in lines if _looks_like_title(line["text"])]
        if candidates:
            top = max(line["size"] for line in candidates)
            title_lines: list[dict[str, Any]] = []
            started = False
            for line in lines:
                if line["size"] >= top - 0.5 and _looks_like_title(line["text"]):
                    title_lines.append(line)
                    started = True
                elif started:
                    break
            if title_lines:
                result["title"] = " ".join(line["text"] for line in title_lines)[:300]
                after = [line for line in lines if line["y"] > title_lines[-1]["y"]]
                authors: list[str] = []
                size = None
                for line in after:
                    lowered = line["text"].lower()
                    if lowered.startswith("abstract") or "@" in line["text"]:
                        break
                    if size is None:
                        size = line["size"]
                        authors.append(line["text"])
                        if not line["text"].rstrip().endswith(",") and " and " not in lowered:
                            break
                        continue
                    if abs(line["size"] - size) > 0.5:
                        break
                    authors.append(line["text"])
                    if not line["text"].rstrip().endswith(","):
                        break
                if authors:
                    result["authors"] = " ".join(authors)[:500]
        if not result["title"]:
            meta_title = (document.metadata or {}).get("title") or ""
            if meta_title.strip() and not meta_title.lower().endswith((".pdf", ".dvi", ".tex")):
                result["title"] = meta_title.strip()[:300]
        arxiv = ARXIV_RE.search(text)
        if arxiv:
            result["arxiv_id"] = f"{arxiv.group(1)}.{arxiv.group(2)}"
            result["year"] = 2000 + int(arxiv.group(1)[:2])
        doi = DOI_RE.search(text)
        if doi:
            result["doi"] = doi.group(1).rstrip(".,;)")
        if result["year"] is None:
            years = [int(match) for match in YEAR_RE.findall(text)]
            if years:
                result["year"] = years[0]
            else:
                created = (document.metadata or {}).get("creationDate") or ""
                match = re.search(r"D:((?:19|20)\d{2})", created)
                if match:
                    result["year"] = int(match.group(1))
    finally:
        document.close()
    return result


def _body_font_size(document: fitz.Document, max_pages: int = 30) -> float:
    sizes: Counter[float] = Counter()
    for index in range(min(len(document), max_pages)):
        for line in _page_lines(document[index]):
            sizes[round(line["size"] * 2) / 2] += line["chars"]
    return sizes.most_common(1)[0][0] if sizes else 10.0


def outline_from_sizes(document: fitz.Document, max_pages: int = 60) -> list[dict[str, Any]]:
    """Dự phòng khi PDF không có bookmark: dòng có cỡ chữ ≥ 1,15× cỡ thân, ≤ 80 ký tự."""
    body = _body_font_size(document)
    toc: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for index in range(min(len(document), max_pages)):
        lines = _page_lines(document[index])
        # Trang 1: dòng cỡ lớn nhất là tiêu đề bài báo, không phải một mục.
        title_size = max((line["size"] for line in lines if _looks_like_title(line["text"])), default=0.0) if index == 0 else None
        for line in lines:
            text = line["text"]
            if line["size"] < body * 1.15 or len(text) > 80 or not _looks_like_title(text):
                continue
            if title_size is not None and line["size"] >= title_size - 0.5:
                continue
            key = (text.lower(), index + 1)
            if key in seen:
                continue
            seen.add(key)
            level = 1 if line["size"] >= body * 1.4 else 2
            toc.append({"title": text, "page": index + 1, "level": level})
    return toc


def figures_from_pages(document: fitz.Document, max_pages: int = 200) -> list[dict[str, Any]]:
    """Lần đầu xuất hiện `Figure n` / `Fig. n` / `Table n` ở đầu dòng mỗi trang."""
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(min(len(document), max_pages)):
        for raw in (document[index].get_text("text") or "").splitlines():
            match = FIGURE_RE.match(raw.strip())
            if not match:
                continue
            kind = "Table" if match.group(1).lower().startswith("tab") else "Figure"
            label = f"{kind} {match.group(2)}"
            if label in seen:
                continue
            seen.add(label)
            figures.append({"label": label, "page": index + 1})
    return figures


def build_outline(pdf_path: Path) -> dict[str, Any]:
    try:
        document = fitz.open(str(pdf_path))
    except Exception:
        return {"toc": [], "figures": []}
    try:
        toc = [{"title": str(title).strip(), "page": int(page), "level": int(level)} for level, title, page in document.get_toc() if int(page) > 0]
        if not toc:
            toc = outline_from_sizes(document)
        return {"toc": toc, "figures": figures_from_pages(document)}
    finally:
        document.close()


def prune_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Bỏ các khoá Ollama 0.32.x không nuốt được khi dựng ngữ pháp (như discord_memory_extractor)."""
    unsupported = {"allOf", "title", "minLength", "maxLength", "format", "minimum", "maximum", "default"}

    def sanitize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: sanitize(item) for key, item in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    pruned = sanitize(schema)
    pruned["additionalProperties"] = False
    if "properties" in pruned:
        pruned["required"] = list(pruned["properties"].keys())
    return pruned


def select_summary_text(pages: list[str], cap: int = SUMMARY_TEXT_CAP) -> str:
    """Ưu tiên 3 trang đầu + 2 trang cuối, trần `cap` ký tự; trang trùng chỉ lấy một lần."""
    texts = [(index + 1, (text or "").strip()) for index, text in enumerate(pages) if (text or "").strip()]
    if not texts:
        return ""
    chosen = texts[:3] + [item for item in texts[-2:] if item not in texts[:3]]
    budget = cap
    parts: list[str] = []
    for number, text in chosen:
        if budget <= 0:
            break
        piece = text[:budget]
        parts.append(f"[Trang {number}]\n{piece}")
        budget -= len(piece)
    return "\n\n".join(parts)


SUMMARY_SYSTEM_PROMPT = (
    "Bạn là trợ lý đọc bài báo khoa học cho một nhà nghiên cứu Việt Nam. "
    "Chỉ dùng thông tin có trong văn bản được cung cấp; chỗ không có thông tin thì ghi "
    "\"không nêu trong phần đã đọc\". Trả lời bằng tiếng Việt, giữ nguyên thuật ngữ và tên "
    "mô hình / bộ dữ liệu bằng tiếng Anh. Trả về đúng một đối tượng JSON theo schema, không "
    "thêm lời dẫn."
)

SUMMARY_FIELD_GUIDE = (
    "Các trường: brief (2–3 câu nói bài này làm gì và vì sao đáng đọc); problem (bài toán); "
    "idea (ý tưởng / phương pháp chính); result (kết quả chính, kèm số nếu có); limits (hạn chế "
    "tác giả nêu hoặc bạn thấy rõ); input (đầu vào của mô hình / hệ); compute (tài nguyên tính "
    "toán, GPU, thời gian train nếu nêu); datasets (bộ dữ liệu dùng); code (mã nguồn công khai "
    "ở đâu, hoặc \"không nêu\"); questions (đúng 3 câu hỏi mở đáng hỏi tác giả)."
)


def summary_messages(title: str | None, text: str) -> list[dict[str, str]]:
    heading = f"Tiêu đề: {title}\n\n" if title else ""
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": f"{SUMMARY_FIELD_GUIDE}\n\n{heading}Văn bản trích từ bài báo:\n\n{text}"},
    ]


INSIGHTS_SYSTEM_PROMPT = (
    "Bạn là trợ lý tổng hợp cho một kho bài báo nghiên cứu. Dựa trên các tóm tắt được cung "
    "cấp (và chỉ chúng), viết bằng tiếng Việt: overview (kho này nói về gì, 2–3 câu); central "
    "(bài / ý tưởng trung tâm mà các bài khác xoay quanh, nêu tên ngắn của bài); trend (xu "
    "hướng chung bạn thấy); gap (khoảng trống chưa bài nào giải quyết). Trả về đúng một đối "
    "tượng JSON theo schema, không thêm lời dẫn."
)


def insights_messages(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    lines = []
    for entry in entries:
        brief = str((entry.get("summary") or {}).get("brief") or "").strip()
        lines.append(f"- [{entry.get('short_name')}] {entry.get('title') or ''} ({entry.get('year') or '?'}): {brief}")
    return [
        {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
        {"role": "user", "content": "Các bài trong kho:\n" + "\n".join(lines)},
    ]


def _bibtex_key(short_name: str, year: int | None) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "", short_name or "") or "paper"
    return f"{base}{year or ''}"


def _bibtex_escape(value: str) -> str:
    return value.replace("{", "\\{").replace("}", "\\}")


def bibtex_for(papers: list[dict[str, Any]]) -> str:
    """@article{<short_name><year>, title, author, year, eprint, doi, url} — chỉ ghi trường có."""
    entries: list[str] = []
    used: Counter[str] = Counter()
    for paper in papers:
        key = _bibtex_key(str(paper.get("short_name") or ""), paper.get("year"))
        used[key] += 1
        if used[key] > 1:
            key = f"{key}{chr(ord('a') + used[key] - 2)}"
        fields: list[tuple[str, str]] = []
        if paper.get("title"):
            fields.append(("title", _bibtex_escape(str(paper["title"]))))
        if paper.get("authors"):
            fields.append(("author", _bibtex_escape(str(paper["authors"]))))
        if paper.get("year"):
            fields.append(("year", str(paper["year"])))
        if paper.get("venue"):
            fields.append(("journal", _bibtex_escape(str(paper["venue"]))))
        if paper.get("arxiv_id"):
            fields.append(("eprint", str(paper["arxiv_id"])))
            fields.append(("archivePrefix", "arXiv"))
        if paper.get("doi"):
            fields.append(("doi", str(paper["doi"])))
        if paper.get("url"):
            fields.append(("url", str(paper["url"])))
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
        entries.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def export_markdown(paper: dict[str, Any], annotations: list[dict[str, Any]]) -> str:
    """Tiêu đề, meta, tóm tắt (nếu có), highlight theo trang, ghi chú tự do."""
    lines: list[str] = [f"# {paper.get('title') or paper.get('short_name') or 'Paper'}", ""]
    meta = [
        ("Tác giả", paper.get("authors")), ("Năm", paper.get("year")), ("Nơi đăng", paper.get("venue")),
        ("arXiv", paper.get("arxiv_id")), ("DOI", paper.get("doi")), ("URL", paper.get("url")),
        ("Trạng thái", paper.get("status")), ("Sao", paper.get("stars")),
    ]
    for label, value in meta:
        if value not in (None, "", 0):
            lines.append(f"- **{label}:** {value}")
    if paper.get("tags"):
        lines.append(f"- **Tag:** {', '.join(str(tag) for tag in paper['tags'])}")
    lines.append("")
    summary = paper.get("summary") or {}
    if summary:
        lines += ["## Tóm tắt AI", ""]
        labels = [("brief", "Tóm lược"), ("problem", "Bài toán"), ("idea", "Ý tưởng"), ("result", "Kết quả"), ("limits", "Hạn chế"), ("input", "Đầu vào"), ("compute", "Tính toán"), ("datasets", "Dữ liệu"), ("code", "Mã nguồn")]
        for key, label in labels:
            if summary.get(key):
                lines.append(f"**{label}.** {summary[key]}")
                lines.append("")
        if summary.get("questions"):
            lines.append("**Câu hỏi mở:**")
            lines += [f"- {question}" for question in summary["questions"]]
            lines.append("")
    if annotations:
        lines += ["## Highlight", ""]
        for annotation in sorted(annotations, key=lambda item: (int(item.get("page") or 0), str(item.get("created_at") or ""))):
            quote = str(annotation.get("quote") or "").strip()
            note = str(annotation.get("note") or "").strip()
            entry = f"- «{quote}»"
            if note:
                entry += f" — {note}"
            entry += f" — tr. {annotation.get('page')}"
            lines.append(entry)
        lines.append("")
    if paper.get("note_md"):
        lines += ["## Ghi chú", "", str(paper["note_md"]).rstrip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def paper_stages(document_status: str, metadata_at: Any, outline: Any, summary: Any) -> dict[str, str]:
    """`stages.ocr` suy từ trạng thái Document; ba việc còn lại là done/pending."""
    if document_status == "indexed":
        ocr = "done"
    elif document_status in {"processing", "uploaded"}:
        ocr = "running"
    elif document_status == "failed":
        ocr = "failed"
    else:
        ocr = "pending"
    return {
        "ocr": ocr,
        "metadata": "done" if metadata_at else "pending",
        "outline": "done" if outline is not None else "pending",
        "summary": "done" if summary else "pending",
    }


def parse_json_object(content: str) -> dict[str, Any]:
    """JSON model trả về, chịu được rào ```json ... ``` và chữ thừa quanh ngoặc."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("model không trả về đối tượng JSON")
    return value


THREAD_TITLE_CAP = 80


def thread_title_from_question(question: str, cap: int = THREAD_TITLE_CAP) -> str | None:
    """Tiêu đề tự đặt = câu hỏi đầu, gộp khoảng trắng, cắt `cap` ký tự; None khi rỗng."""
    text = " ".join(question.split())
    if not text:
        return None
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def attach_paper_refs(messages: list[dict[str, Any]], paper_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Gắn paper_id / short_name / color_index / page (= page_start) vào từng trích dẫn
    theo document_id; paper không còn trong dự án → ba trường None, page vẫn có."""
    out: list[dict[str, Any]] = []
    for message in messages:
        sources = []
        for source in message.get("sources") or []:
            ref = paper_map.get(str(source.get("document_id")), {})
            sources.append({**source, "paper_id": ref.get("paper_id"), "short_name": ref.get("short_name"), "color_index": ref.get("color_index"), "page": source.get("page_start")})
        out.append({**message, "sources": sources})
    return out


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return datetime.now(UTC)


# ── Dịch vụ ───────────────────────────────────────────────────────────────────
class ResearchService:
    def __init__(self, session_factory: sessionmaker, document_service, *, ollama_base_url: str, model_router=None, http_post=None, conversation_store=None) -> None:
        self.sessions = session_factory
        self.documents = document_service
        self.conversations = conversation_store  # auxiliary_store: đọc / xoá conversation đứng sau một luồng
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.router = model_router if model_router is not None else getattr(document_service, "router", None)
        self._post = http_post or httpx.post
        self._page_counts: dict[str, int | None] = {}

    # ── quyền ────────────────────────────────────────────────────────────
    @staticmethod
    def _owner_uuid(owner: str | None) -> UUID | None:
        if owner is None:
            return None
        try:
            return UUID(str(owner))
        except ValueError:
            return UUID(int=0)  # không khớp dòng nào → 404 như "không tồn tại"

    def _project(self, session, project_id: str, owner: str | None) -> ResearchProject:
        project = session.get(ResearchProject, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        owner_uuid = self._owner_uuid(owner)
        if owner_uuid is not None and project.owner_user_id != owner_uuid:
            raise ProjectNotFoundError(project_id)
        return project

    def _paper(self, session, paper_id: str, owner: str | None) -> tuple[ResearchPaper, ResearchProject]:
        paper = session.get(ResearchPaper, paper_id)
        if paper is None:
            raise PaperNotFoundError(paper_id)
        try:
            project = self._project(session, paper.project_id, owner)
        except ProjectNotFoundError as error:
            raise PaperNotFoundError(paper_id) from error
        return paper, project

    # ── hàng paper ───────────────────────────────────────────────────────
    def _total_pages(self, document: Document | None, run: IngestionRun | None) -> int | None:
        if document is None:
            return None
        if run is not None and run.total_pages:
            return int(run.total_pages)
        if document.id not in self._page_counts:
            try:
                path, _ = self.documents.source_file(document.id)
                self._page_counts[document.id] = document_pages.page_count(path)
            except (DocumentNotFoundError, SourceUnavailableError):
                self._page_counts[document.id] = None
        return self._page_counts[document.id]

    def _paper_rows(self, session, papers: list[ResearchPaper]) -> list[dict[str, Any]]:
        if not papers:
            return []
        document_ids = {paper.document_id for paper in papers}
        documents = {document.id: document for document in session.scalars(select(Document).where(Document.id.in_(document_ids)))}
        repo = PostgresDocumentRepository(session)
        runs = {document_id: repo.latest_run(document_id) for document_id in document_ids}
        counts = dict(session.execute(select(ResearchAnnotation.paper_id, func.count()).where(ResearchAnnotation.paper_id.in_([paper.id for paper in papers])).group_by(ResearchAnnotation.paper_id)).all())
        return [self._paper_row(paper, documents.get(paper.document_id), runs.get(paper.document_id), int(counts.get(paper.id, 0))) for paper in papers]

    def _paper_row(self, paper: ResearchPaper, document: Document | None, run: IngestionRun | None, annotation_count: int) -> dict[str, Any]:
        document_status = document.status if document is not None else "deleted"
        return {
            "id": paper.id, "document_id": paper.document_id, "short_name": paper.short_name, "title": paper.title,
            "authors": paper.authors, "venue": paper.venue, "year": paper.year, "arxiv_id": paper.arxiv_id, "doi": paper.doi,
            "url": paper.url, "cluster_id": paper.cluster_id, "status": paper.status, "stars": paper.stars,
            "last_page": paper.last_page, "tags": list(paper.tags or []), "total_pages": self._total_pages(document, run),
            "annotation_count": annotation_count, "has_summary": bool(paper.summary), "document_status": document_status,
            "indexed": document_status == "indexed",
            "stages": paper_stages(document_status, paper.metadata_at, paper.outline, paper.summary),
            "added_at": _iso(paper.added_at) or "", "updated_at": _iso(paper.updated_at) or "",
        }

    @staticmethod
    def _annotation_row(annotation: ResearchAnnotation) -> dict[str, Any]:
        return {
            "id": annotation.id, "paper_id": annotation.paper_id, "page": annotation.page, "rects": list(annotation.rects or []),
            "color": annotation.color, "quote": annotation.quote, "note": annotation.note, "section": annotation.section,
            "created_at": _iso(annotation.created_at) or "", "updated_at": _iso(annotation.updated_at) or "",
        }

    @staticmethod
    def _edge_row(edge: ResearchEdge) -> dict[str, Any]:
        return {
            "id": edge.id, "a_paper_id": edge.a_paper_id, "b_paper_id": edge.b_paper_id, "type": edge.type, "explain": edge.explain,
            "quote": edge.quote, "quote_src": edge.quote_src, "confidence": edge.confidence, "source": edge.source,
            "created_at": _iso(edge.created_at) or "",
        }

    @staticmethod
    def _cluster_row(cluster: ResearchCluster) -> dict[str, Any]:
        return {"id": cluster.id, "name": cluster.name, "color_index": cluster.color_index, "position": cluster.position}

    # ── dự án ────────────────────────────────────────────────────────────
    def list_projects(self, owner: str | None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            query = select(ResearchProject).order_by(ResearchProject.updated_at.desc())
            owner_uuid = self._owner_uuid(owner)
            if owner_uuid is not None:
                query = query.where(ResearchProject.owner_user_id == owner_uuid)
            projects = list(session.scalars(query))
            if not projects:
                return []
            ids = [project.id for project in projects]
            totals = dict(session.execute(select(ResearchPaper.project_id, func.count()).where(ResearchPaper.project_id.in_(ids)).group_by(ResearchPaper.project_id)).all())
            reads = dict(session.execute(select(ResearchPaper.project_id, func.count()).where(ResearchPaper.project_id.in_(ids), ResearchPaper.status == "read").group_by(ResearchPaper.project_id)).all())
            return [
                {"id": project.id, "name": project.name, "description": project.description, "paper_count": int(totals.get(project.id, 0)), "read_count": int(reads.get(project.id, 0)), "updated_at": _iso(project.updated_at) or ""}
                for project in projects
            ]

    def create_project(self, owner: str | None, name: str, description: str | None) -> dict[str, Any]:
        with self.sessions.begin() as session:
            now = _now()
            project = ResearchProject(id=new_id("prj"), owner_user_id=self._owner_uuid(owner), name=name.strip(), description=description, created_at=now, updated_at=now)
            session.add(project)
            session.flush()
            return self._project_detail(session, project)

    def _project_detail(self, session, project: ResearchProject) -> dict[str, Any]:
        clusters = list(session.scalars(select(ResearchCluster).where(ResearchCluster.project_id == project.id).order_by(ResearchCluster.position, ResearchCluster.name)))
        papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project.id).order_by(ResearchPaper.added_at)))
        edges = list(session.scalars(select(ResearchEdge).where(ResearchEdge.project_id == project.id).order_by(ResearchEdge.created_at)))
        return {
            "id": project.id, "name": project.name, "description": project.description, "insights": project.insights,
            "insights_at": _iso(project.insights_at), "clusters": [self._cluster_row(cluster) for cluster in clusters],
            "papers": self._paper_rows(session, papers), "edges": [self._edge_row(edge) for edge in edges],
            "updated_at": _iso(project.updated_at) or "",
        }

    def get_project(self, owner: str | None, project_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            return self._project_detail(session, self._project(session, project_id, owner))

    def patch_project(self, owner: str | None, project_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            if "name" in changes and changes["name"]:
                project.name = str(changes["name"]).strip()
            if "description" in changes:
                project.description = changes["description"]
            project.updated_at = _now()
            session.flush()
            return self._project_detail(session, project)

    def delete_project(self, owner: str | None, project_id: str) -> None:
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            session.delete(project)  # cascade ở DB: clusters, papers, annotations, edges; documents giữ

    def _touch_project(self, session, project_id: str) -> None:
        project = session.get(ResearchProject, project_id)
        if project is not None:
            project.updated_at = _now()

    # ── cụm ──────────────────────────────────────────────────────────────
    def create_cluster(self, owner: str | None, project_id: str, name: str, color_index: int) -> dict[str, Any]:
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            position = session.scalar(select(func.coalesce(func.max(ResearchCluster.position), -1)).where(ResearchCluster.project_id == project.id)) + 1
            cluster = ResearchCluster(id=new_id("clu"), project_id=project.id, name=name.strip(), color_index=color_index, position=position)
            session.add(cluster)
            project.updated_at = _now()
            session.flush()
            return self._cluster_row(cluster)

    def _cluster(self, session, cluster_id: str, owner: str | None) -> ResearchCluster:
        cluster = session.get(ResearchCluster, cluster_id)
        if cluster is None:
            raise ClusterNotFoundError(cluster_id)
        try:
            self._project(session, cluster.project_id, owner)
        except ProjectNotFoundError as error:
            raise ClusterNotFoundError(cluster_id) from error
        return cluster

    def patch_cluster(self, owner: str | None, cluster_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            cluster = self._cluster(session, cluster_id, owner)
            if changes.get("name"):
                cluster.name = str(changes["name"]).strip()
            if changes.get("color_index") is not None:
                cluster.color_index = int(changes["color_index"])
            if changes.get("position") is not None:
                cluster.position = int(changes["position"])
            self._touch_project(session, cluster.project_id)
            session.flush()
            return self._cluster_row(cluster)

    def delete_cluster(self, owner: str | None, cluster_id: str) -> None:
        with self.sessions.begin() as session:
            cluster = self._cluster(session, cluster_id, owner)
            for paper in session.scalars(select(ResearchPaper).where(ResearchPaper.cluster_id == cluster.id)):
                paper.cluster_id = None
            self._touch_project(session, cluster.project_id)
            session.delete(cluster)

    # ── kết nối ──────────────────────────────────────────────────────────
    def create_edge(self, owner: str | None, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            a_id, b_id = str(payload["a_paper_id"]), str(payload["b_paper_id"])
            if a_id == b_id:
                raise InvalidEdgeError("Hai đầu của một kết nối phải là hai paper khác nhau.")
            papers = {paper.id for paper in session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project.id, ResearchPaper.id.in_([a_id, b_id])))}
            if papers != {a_id, b_id}:
                raise PaperNotFoundError(a_id if a_id not in papers else b_id)
            edge = ResearchEdge(id=new_id("edg"), project_id=project.id, a_paper_id=a_id, b_paper_id=b_id, type=str(payload["type"]), explain=payload.get("explain"), quote=payload.get("quote"), quote_src=payload.get("quote_src"), confidence=None, source="manual", created_at=_now())
            session.add(edge)
            project.updated_at = _now()
            session.flush()
            return self._edge_row(edge)

    def delete_edge(self, owner: str | None, edge_id: str) -> None:
        with self.sessions.begin() as session:
            edge = session.get(ResearchEdge, edge_id)
            if edge is None:
                raise EdgeNotFoundError(edge_id)
            try:
                self._project(session, edge.project_id, owner)
            except ProjectNotFoundError as error:
                raise EdgeNotFoundError(edge_id) from error
            self._touch_project(session, edge.project_id)
            session.delete(edge)

    # ── bibtex ───────────────────────────────────────────────────────────
    def bibtex(self, owner: str | None, project_id: str) -> str:
        with self.sessions() as session:
            project = self._project(session, project_id, owner)
            papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project.id).order_by(ResearchPaper.added_at)))
            return bibtex_for([{"short_name": paper.short_name, "title": paper.title, "authors": paper.authors, "year": paper.year, "venue": paper.venue, "arxiv_id": paper.arxiv_id, "doi": paper.doi, "url": paper.url} for paper in papers])

    # ── thêm paper ───────────────────────────────────────────────────────
    async def add_paper_files(self, owner: str | None, project_id: str, files: list[UploadFile], max_bytes: int) -> list[dict[str, Any]]:
        """Mỗi tệp: tạo Document qua đúng service của POST /documents (+ xếp hàng lập chỉ
        mục nếu mới), rồi gắn vào dự án. Tệp trùng nội dung với document đã có trong
        dự án → trả paper cũ. ValueError (loại tệp) và OverflowError (quá lớn) nổi lên
        cho router đổi thành 415/413 — chữ ký giống /documents/upload."""
        with self.sessions() as session:
            self._project(session, project_id, owner)
        rows: list[dict[str, Any]] = []
        for file in files:
            document_id = await self._upload_document(file, max_bytes)
            if not document_id:
                continue
            rows.append(self.attach_paper(owner, project_id, document_id, filename=file.filename))
        return rows

    async def _upload_document(self, file: UploadFile, max_bytes: int) -> str | None:
        result = await self.documents.upload(file, max_bytes)
        if result.get("action_required") and result.get("conflict") == "same_name_different_hash":
            # Tên trùng, nội dung khác: giữ cả hai (tên mới có hậu tố), như người dùng chọn "keep_both".
            await file.seek(0)
            result = await self.documents.upload(file, max_bytes, decision="keep_both")
        document_id = str(result.get("document_id") or "")
        if not document_id or result.get("cancelled"):
            return None
        # Các xung đột còn lại đều có nghĩa "document này đã sở hữu đúng bytes đó" → dùng lại.
        status = str(result.get("status") or "")
        if result.get("duplicate") is False or status == "uploaded":
            try:
                self.documents.enqueue_index(document_id)
            except (DocumentAlreadyIndexingError, SourceUnavailableError):
                pass
        return document_id

    def attach_paper(self, owner: str | None, project_id: str, document_id: str, filename: str | None = None) -> dict[str, Any]:
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            document = session.get(Document, document_id)
            if document is None or document.status in {"deleting", "deleted"}:
                raise DocumentNotFoundError(document_id)
            existing = session.scalar(select(ResearchPaper).where(ResearchPaper.project_id == project.id, ResearchPaper.document_id == document.id))
            if existing is not None:
                return self._paper_rows(session, [existing])[0]
            metadata, metadata_at, outline = self._extract(document)
            display = filename or document.original_filename or "paper"
            title = metadata.get("title") or Path(display).stem
            now = _now()
            paper = ResearchPaper(
                id=new_id("pap"), project_id=project.id, document_id=document.id, short_name=short_name_from_title(title, Path(display).stem[:24] or "paper"),
                title=metadata.get("title") or Path(display).stem, authors=metadata.get("authors"), year=metadata.get("year"), arxiv_id=metadata.get("arxiv_id"),
                doi=metadata.get("doi"), url=f"https://arxiv.org/abs/{metadata['arxiv_id']}" if metadata.get("arxiv_id") else None,
                status="unread", stars=0, last_page=1, tags=[], outline=outline, metadata_at=metadata_at, added_at=now, updated_at=now,
            )
            session.add(paper)
            project.updated_at = now
            session.flush()
            return self._paper_rows(session, [paper])[0]

    def _extract(self, document: Document) -> tuple[dict[str, Any], datetime | None, dict[str, Any] | None]:
        try:
            path, _ = self.documents.source_file(document.id)
        except (DocumentNotFoundError, SourceUnavailableError):
            return {}, None, None
        if path.suffix.lower() != ".pdf":
            return {}, _now(), None
        return extract_metadata(path), _now(), build_outline(path)

    # ── paper ────────────────────────────────────────────────────────────
    def get_paper(self, owner: str | None, paper_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            paper, _ = self._paper(session, paper_id, owner)
            row = self._paper_rows(session, [paper])[0]
            annotations = list(session.scalars(select(ResearchAnnotation).where(ResearchAnnotation.paper_id == paper.id).order_by(ResearchAnnotation.page, ResearchAnnotation.created_at)))
            row.update({
                "summary": paper.summary, "summary_model": paper.summary_model, "summary_at": _iso(paper.summary_at),
                "outline": paper.outline, "note_md": paper.note_md, "annotations": [self._annotation_row(annotation) for annotation in annotations],
            })
            return row

    def patch_paper(self, owner: str | None, paper_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            paper, project = self._paper(session, paper_id, owner)
            if "cluster_id" in changes and changes["cluster_id"] is not None:
                cluster = session.get(ResearchCluster, changes["cluster_id"])
                if cluster is None or cluster.project_id != project.id:
                    raise ClusterNotFoundError(str(changes["cluster_id"]))
            for key, value in changes.items():
                if key == "short_name" and value:
                    paper.short_name = str(value).strip()[:64]
                elif key == "tags":
                    paper.tags = [str(tag).strip() for tag in (value or []) if str(tag).strip()]
                elif key in {"status", "stars", "last_page", "note_md", "cluster_id", "title", "authors", "venue", "year", "arxiv_id", "doi", "url"}:
                    setattr(paper, key, value)
            paper.updated_at = _now()
            project.updated_at = paper.updated_at
            session.flush()
            return self._paper_rows(session, [paper])[0]

    def delete_paper(self, owner: str | None, paper_id: str) -> None:
        with self.sessions.begin() as session:
            paper, project = self._paper(session, paper_id, owner)
            project.updated_at = _now()
            session.delete(paper)  # annotations + edges cascade ở DB; Document giữ

    def outline(self, owner: str | None, paper_id: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            paper, _ = self._paper(session, paper_id, owner)
            if paper.outline is not None:
                return paper.outline
            try:
                path, _ = self.documents.source_file(paper.document_id)
            except (DocumentNotFoundError, SourceUnavailableError):
                return {"toc": [], "figures": []}
            outline = build_outline(path) if path.suffix.lower() == ".pdf" else {"toc": [], "figures": []}
            paper.outline = outline
            return outline

    # ── tóm tắt / insight ────────────────────────────────────────────────
    def _general_model(self) -> tuple[str, dict[str, Any]]:
        config = (getattr(self.router, "models", None) or {}).get("general", {}) if self.router is not None else {}
        name = str(config.get("name") or "")
        if not name:
            raise OllamaModelNotLoadedError("Chưa cấu hình model vai trò general.")
        options: dict[str, Any] = {"temperature": 0.2}
        if "context" in config:
            options["num_ctx"] = config["context"]
        return name, options

    def _json_call(self, messages: list[dict[str, str]], schema: dict[str, Any], timeout: float) -> tuple[dict[str, Any], str]:
        model, options = self._general_model()
        base: dict[str, Any] = {"model": model, "stream": False, "think": False, "options": options, "messages": messages}
        for format_value in (prune_schema(schema), "json"):
            payload = {**base, "format": format_value}
            try:
                response = self._post(f"{self.ollama_base_url}/api/chat", json=payload, timeout=timeout)
            except httpx.TimeoutException as error:
                raise OllamaTimeoutError("Ollama không trả lời trước hạn 180 giây.") from error
            except httpx.HTTPError as error:
                raise OllamaUnavailableError("Không kết nối được Ollama.") from error
            if response.status_code == 404:
                raise OllamaModelNotLoadedError(f"Model {model} chưa có trong Ollama. Chạy: ollama pull {model}")
            if response.status_code in {400, 422} and format_value != "json":
                continue  # Ollama cũ không nuốt JSON schema → thử format "json" trơn
            if response.status_code >= 400:
                raise OllamaUnavailableError(f"Ollama trả về {response.status_code}.")
            content = response.json().get("message", {}).get("content")
            if not isinstance(content, str):
                raise OllamaUnavailableError("Ollama trả về nội dung không hợp lệ.")
            try:
                return parse_json_object(content), model
            except (ValueError, json.JSONDecodeError) as error:
                raise OllamaUnavailableError("Model không trả về JSON hợp lệ.") from error
        raise OllamaUnavailableError("Ollama từ chối cả hai định dạng JSON.")

    def _page_texts(self, session, document_id: str) -> list[str]:
        document = session.get(Document, document_id)
        if document is None or not document.active_version_id:
            return []
        pages = PostgresDocumentRepository(session).pages_for_version(document.active_version_id)
        return [page.selected_text or "" for page in pages]

    def generate_summary(self, owner: str | None, paper_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            paper, _ = self._paper(session, paper_id, owner)
            title, document_id = paper.title, paper.document_id
            text = select_summary_text(self._page_texts(session, document_id))
        if not text.strip():
            raise NotIndexedError(paper_id)
        raw, model = self._json_call(summary_messages(title, text), PaperSummary.model_json_schema(), SUMMARY_TIMEOUT_SECONDS)
        summary = PaperSummary.model_validate({**{key: raw.get(key, "") for key in PaperSummary.model_fields if key != "questions"}, "questions": [str(item) for item in (raw.get("questions") or []) if str(item).strip()][:3]}).model_dump()
        with self.sessions.begin() as session:
            paper, project = self._paper(session, paper_id, owner)
            paper.summary, paper.summary_model, paper.summary_at = summary, model, _now()
            paper.updated_at = paper.summary_at
            project.updated_at = paper.summary_at
            return {"summary": summary, "summary_model": model, "summary_at": _iso(paper.summary_at)}

    def generate_insights(self, owner: str | None, project_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            project = self._project(session, project_id, owner)
            papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project.id, ResearchPaper.summary.isnot(None)).order_by(ResearchPaper.added_at)))
            entries = [{"short_name": paper.short_name, "title": paper.title, "year": paper.year, "summary": paper.summary} for paper in papers if paper.summary]
        if not entries:
            raise SummaryMissingError(project_id)
        raw, _model = self._json_call(insights_messages(entries), ProjectInsights.model_json_schema(), SUMMARY_TIMEOUT_SECONDS)
        insights = ProjectInsights.model_validate({key: str(raw.get(key, "") or "") for key in ProjectInsights.model_fields}).model_dump()
        with self.sessions.begin() as session:
            project = self._project(session, project_id, owner)
            project.insights, project.insights_at = insights, _now()
            project.updated_at = project.insights_at
            return {"insights": insights, "insights_at": _iso(project.insights_at)}

    # ── highlight ────────────────────────────────────────────────────────
    def list_annotations(self, owner: str | None, paper_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            paper, _ = self._paper(session, paper_id, owner)
            rows = session.scalars(select(ResearchAnnotation).where(ResearchAnnotation.paper_id == paper.id).order_by(ResearchAnnotation.page, ResearchAnnotation.created_at))
            return [self._annotation_row(row) for row in rows]

    def create_annotation(self, owner: str | None, paper_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            paper, project = self._paper(session, paper_id, owner)
            now = _now()
            annotation = ResearchAnnotation(id=new_id("ann"), paper_id=paper.id, page=int(payload["page"]), rects=list(payload["rects"]), color=str(payload["color"]), quote=str(payload["quote"]), note=payload.get("note"), section=payload.get("section"), created_at=now, updated_at=now)
            session.add(annotation)
            paper.updated_at = now
            project.updated_at = now
            session.flush()
            return self._annotation_row(annotation)

    def _annotation(self, session, annotation_id: str, owner: str | None) -> tuple[ResearchAnnotation, ResearchPaper, ResearchProject]:
        annotation = session.get(ResearchAnnotation, annotation_id)
        if annotation is None:
            raise AnnotationNotFoundError(annotation_id)
        try:
            paper, project = self._paper(session, annotation.paper_id, owner)
        except PaperNotFoundError as error:
            raise AnnotationNotFoundError(annotation_id) from error
        return annotation, paper, project

    def patch_annotation(self, owner: str | None, annotation_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            annotation, paper, project = self._annotation(session, annotation_id, owner)
            if "note" in changes:
                annotation.note = changes["note"]
            if changes.get("color"):
                annotation.color = str(changes["color"])
            annotation.updated_at = _now()
            paper.updated_at = project.updated_at = annotation.updated_at
            session.flush()
            return self._annotation_row(annotation)

    def delete_annotation(self, owner: str | None, annotation_id: str) -> None:
        with self.sessions.begin() as session:
            annotation, paper, project = self._annotation(session, annotation_id, owner)
            paper.updated_at = project.updated_at = _now()
            session.delete(annotation)

    # ── xuất ─────────────────────────────────────────────────────────────
    def export_markdown(self, owner: str | None, paper_id: str) -> str:
        detail = self.get_paper(owner, paper_id)
        return export_markdown(detail, detail["annotations"])

    # ── luồng chat lưu được ──────────────────────────────────────────────
    def _thread(self, session, thread_id: str, owner: str | None) -> tuple[ResearchThread, ResearchProject]:
        thread = session.get(ResearchThread, thread_id)
        if thread is None:
            raise ThreadNotFoundError(thread_id)
        try:
            project = self._project(session, thread.project_id, owner)
        except ProjectNotFoundError as error:
            raise ThreadNotFoundError(thread_id) from error
        return thread, project

    def _thread_scope(self, session, scope: str, target_id: str, owner: str | None) -> tuple[ResearchProject, ResearchPaper | None]:
        if scope == "paper":
            paper, project = self._paper(session, target_id, owner)
            return project, paper
        return self._project(session, target_id, owner), None

    def _message_counts(self, session, conversation_ids: list[str]) -> dict[str, int]:
        if not conversation_ids:
            return {}
        rows = session.execute(select(Message.conversation_id, func.count()).where(Message.conversation_id.in_(conversation_ids)).group_by(Message.conversation_id)).all()
        return {conversation_id: int(count) for conversation_id, count in rows}

    @staticmethod
    def _thread_row(thread: ResearchThread, message_count: int) -> dict[str, Any]:
        return {
            "id": thread.id, "scope": "paper" if thread.paper_id else "project", "project_id": thread.project_id, "paper_id": thread.paper_id,
            "conversation_id": thread.conversation_id, "title": thread.title, "message_count": message_count,
            "created_at": _iso(thread.created_at) or "", "updated_at": _iso(thread.updated_at) or "", "last_message_at": _iso(thread.last_message_at),
        }

    def list_threads(self, owner: str | None, scope: str, target_id: str) -> list[dict[str, Any]]:
        """Mới nhất trước: coalesce(last_message_at, created_at) giảm dần — luồng vừa tạo
        chưa có tin đứng đầu thay vì bị NULL đẩy xuống cuối."""
        with self.sessions() as session:
            project, paper = self._thread_scope(session, scope, target_id, owner)
            query = select(ResearchThread).where(ResearchThread.paper_id == paper.id) if paper is not None else select(ResearchThread).where(ResearchThread.project_id == project.id, ResearchThread.paper_id.is_(None))
            threads = list(session.scalars(query.order_by(func.coalesce(ResearchThread.last_message_at, ResearchThread.created_at).desc(), ResearchThread.created_at.desc())))
            counts = self._message_counts(session, [thread.conversation_id for thread in threads if thread.conversation_id])
            return [self._thread_row(thread, counts.get(thread.conversation_id or "", 0)) for thread in threads]

    def create_thread(self, owner: str | None, scope: str, target_id: str, title: str | None) -> dict[str, Any]:
        with self.sessions.begin() as session:
            project, paper = self._thread_scope(session, scope, target_id, owner)
            now = _now()
            thread = ResearchThread(id=new_id("thr"), project_id=project.id, paper_id=paper.id if paper is not None else None, title=(title or "").strip() or None, created_at=now, updated_at=now)
            session.add(thread)
            session.flush()
            return self._thread_row(thread, 0)

    def _paper_map(self, session, project_id: str) -> dict[str, dict[str, Any]]:
        """document_id → {paper_id, short_name, color_index} cho MỌI paper của dự án (kể cả
        chưa index) — trích dẫn cũ vẫn tìm được paper của nó."""
        papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project_id)))
        clusters = {cluster.id: cluster for cluster in session.scalars(select(ResearchCluster).where(ResearchCluster.project_id == project_id))}
        return {paper.document_id: {"paper_id": paper.id, "short_name": paper.short_name, "color_index": clusters[paper.cluster_id].color_index if paper.cluster_id in clusters else None} for paper in papers}

    def get_thread(self, owner: str | None, thread_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            thread, project = self._thread(session, thread_id, owner)
            paper_map = self._paper_map(session, project.id)
            conversation = self.conversations.get_conversation(thread.conversation_id) if thread.conversation_id and self.conversations is not None else None
            messages = attach_paper_refs(list(conversation.get("messages") or []), paper_map) if conversation else []
            return {**self._thread_row(thread, len(messages)), "messages": messages}

    def patch_thread(self, owner: str | None, thread_id: str, title: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            thread, _ = self._thread(session, thread_id, owner)
            thread.title = title.strip()
            thread.updated_at = _now()
            session.flush()
            counts = self._message_counts(session, [thread.conversation_id] if thread.conversation_id else [])
            return self._thread_row(thread, counts.get(thread.conversation_id or "", 0))

    def delete_thread(self, owner: str | None, thread_id: str) -> None:
        with self.sessions.begin() as session:
            thread, _ = self._thread(session, thread_id, owner)
            conversation_id = thread.conversation_id
            session.delete(thread)
        if conversation_id and self.conversations is not None:
            self.conversations.delete_conversation(conversation_id)  # False (đã xoá trước) là bình thường

    def thread_for_chat(self, owner: str | None, thread_id: str, scope: str, target_id: str) -> str | None:
        """conversation_id của luồng (None khi chưa có tin). ThreadMismatchError khi luồng
        không thuộc scope/id gửi kèm; ThreadNotFoundError (kể cả không phải chủ) trước."""
        with self.sessions() as session:
            thread, _ = self._thread(session, thread_id, owner)
            matches = (thread.paper_id == target_id) if scope == "paper" else (thread.paper_id is None and thread.project_id == target_id)
            if not matches:
                raise ThreadMismatchError(thread_id)
            return thread.conversation_id

    def record_thread_turn(self, thread_id: str, conversation_id: str | None, question: str) -> None:
        """Sau khi luồng có conversation: ghi conversation_id (lần đầu), tiêu đề từ câu hỏi
        đầu nếu chưa có, và last_message_at = now. Người gọi phải nuốt lỗi — không được
        làm đứt luồng token."""
        with self.sessions.begin() as session:
            thread = session.get(ResearchThread, thread_id)
            if thread is None:
                return
            if conversation_id and not thread.conversation_id:
                thread.conversation_id = conversation_id
            if thread.title is None:
                thread.title = thread_title_from_question(question)
            thread.last_message_at = thread.updated_at = _now()


    # ── hỏi AI: phạm vi tài liệu ─────────────────────────────────────────
    def chat_scope(self, owner: str | None, scope: str, target_id: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
        """(document_ids đã index, {document_id: {paper_id, short_name, color_index}}).
        NotIndexedError khi không paper nào có chỉ mục."""
        with self.sessions() as session:
            if scope == "paper":
                paper, project = self._paper(session, target_id, owner)
                papers = [paper]
            else:
                project = self._project(session, target_id, owner)
                papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.project_id == project.id).order_by(ResearchPaper.added_at)))
            if not papers:
                raise NotIndexedError(target_id)
            documents = {document.id: document for document in session.scalars(select(Document).where(Document.id.in_({paper.document_id for paper in papers}), Document.status == "indexed"))}
            clusters = {cluster.id: cluster for cluster in session.scalars(select(ResearchCluster).where(ResearchCluster.project_id == project.id))}
            indexed = [paper for paper in papers if paper.document_id in documents][:CHAT_SCOPE_CAP]
            if not indexed:
                raise NotIndexedError(target_id)
            mapping = {
                paper.document_id: {"paper_id": paper.id, "short_name": paper.short_name, "color_index": clusters[paper.cluster_id].color_index if paper.cluster_id in clusters else None}
                for paper in indexed
            }
            return [paper.document_id for paper in indexed], mapping


def compose_question(question: str, quote: str | None) -> str:
    """Ghép đoạn trích vào câu hỏi — dạng «Đoạn trích: "…"\\n\\nCâu hỏi: …»."""
    quote = (quote or "").strip()
    if not quote:
        return question.strip()
    return f'Đoạn trích: "{quote}"\n\nCâu hỏi: {question.strip()}'
