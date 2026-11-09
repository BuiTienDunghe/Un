from __future__ import annotations

import json
import os
import shutil
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.parsers.pymupdf_parser import PyMuPDFParser
from app.parsers.smart_parser import SmartParser
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService
from app.services.ocr_evidence import native_evidence, parse_evidence
from app.services.ocr_reader import read_evidence


class OcrPromotionError(Exception):
    """Compatibility error returned when an OCR run cannot be promoted."""
from app.services.monitoring_service import system_metrics
from app.services.ocr_metrics_service import evaluate_ocr
from app.stores.auxiliary_store import AuxiliaryStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.postgres_document_service import PostgresDocumentService


class OcrJobService:
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self, router: ModelRouter, runs_path: Path, store: AuxiliaryStore, ocr_service: OCRService | None = None) -> None:
        self.router, self.runs_path, self.store = router, runs_path, store
        self.ocr_service = ocr_service or OCRService(router, store)
        self.jobs: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self._active: str | None = None

    async def create(self, file: UploadFile, dpi: int, page_range: str | None, output_format: str, force_ocr: bool = False) -> dict[str, object]:
        suffix = Path(file.filename or "upload").suffix.lower()
        if suffix not in self.allowed:
            raise ValueError("UNSUPPORTED_OCR_FILE")
        content = await file.read()
        if not content:
            raise ValueError("EMPTY_FILE")
        if not self._is_valid_content(suffix, content):
            raise ValueError("INVALID_OCR_FILE_CONTENT")
        job_id = f"ocr_{uuid4().hex}"
        root = self.runs_path / job_id
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "pages").mkdir()
        filename = f"input{suffix}"
        (root / "input" / filename).write_bytes(content)
        job: dict[str, object] = {"id": job_id, "filename": file.filename or filename, "suffix": suffix, "path": str(root / "input" / filename), "root": str(root), "dpi": dpi, "page_range": page_range, "output_format": output_format, "force_ocr": force_ocr, "status": "queued", "stage": "Queued", "progress": 0, "current_page": 0, "total_pages": 0, "events": [], "logs": [], "pages": [], "timings": {}, "cancel": False, "created_at": time.time(), "model": str(self.router.models.get("ocr", {}).get("name", "unconfigured")), "ocr_config_hash": self.ocr_service.config_hash(dpi)}
        self.jobs[job_id] = job
        self._save(job)
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return self.view(job_id)

    def _event(self, job: dict[str, object], stage: str, progress: int, message: str, level: str = "INFO") -> None:
        event = {"at": time.time(), "stage": stage, "progress": progress, "message": message, "level": level}
        job["stage"], job["progress"] = stage, progress
        job["events"].append(event)  # type: ignore[index]
        job["logs"].append(event)  # type: ignore[index]

    def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        with self._lock:
            if self._active:
                job["status"] = "failed"; self._event(job, "Rejected", 0, "Another OCR job is currently running", "ERROR")
                self._save(job)
                return
            self._active = job_id
        started = time.perf_counter()
        try:
            job["status"] = "running"; self._event(job, "Reading document", 5, "File accepted")
            source = Path(str(job["path"])); suffix = str(job["suffix"])
            pages = self._pages(source, suffix, int(job["dpi"]), job.get("page_range") if isinstance(job.get("page_range"), str) else None)
            job["total_pages"] = len(pages)
            if not pages: raise ValueError("No pages selected")
            native = self._native_pages(source, suffix) if not job.get("force_ocr") else {}
            for index, (number, png) in enumerate(pages, start=1):
                if job["cancel"]: job["status"] = "cancelled"; self._event(job, "Cancelled", int((index - 1) / len(pages) * 100), "Stopped at safe page boundary", "WARNING"); return
                job["current_page"] = number
                progress = 10 + int((index - 1) / len(pages) * 80)
                self._event(job, "OCR inference", progress, f"Processing page {number}/{len(pages)}")
                page_started = time.perf_counter()
                if number in native:
                    text, model, config_hash, cache_hit, method = native[number], None, None, False, "native"
                    blocks = [block.payload() for block in native_evidence(source, number)]
                    raw, warnings = text, []
                else:
                    result = self.ocr_service.recognize_png(png, int(job["dpi"]), allow_mock=True)
                    text = f"[MOCK OCR] Page {number}: simulated OCR output." if os.getenv("MOCK_OCR", "").lower() == "true" else result.text
                    model, config_hash, cache_hit, method = result.model, result.config_hash, result.cache_hit, "ocr"
                    blocks = [block.payload(number) for block in (result.blocks or parse_evidence(text))]
                    raw, warnings = result.raw_text if result.raw_text is not None else text, list(result.warnings)
                page_dir = Path(str(job["root"])) / "pages" / f"page_{number:04d}"; page_dir.mkdir()
                (page_dir / "original.png").write_bytes(png)
                (page_dir / "text.txt").write_text(text, encoding="utf-8")
                (page_dir / "result.md").write_text(text, encoding="utf-8")
                (page_dir / "raw.txt").write_text(raw, encoding="utf-8")
                payload = {"page": number, "text": text, "markdown": text, "extraction_method": method, "model": model, "ocr_config_hash": config_hash, "cache_hit": cache_hit, "blocks": blocks, "warnings": warnings}
                (page_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                job["pages"].append({**payload, "image_url": f"/api/ocr/jobs/{job_id}/files/pages/page_{number:04d}/original.png", "duration_seconds": round(time.perf_counter() - page_started, 3)})  # type: ignore[index]
                self._save(job)
            job["status"] = "completed"; self._event(job, "Completed", 100, "All selected pages processed")
        except Exception as error:
            if isinstance(getattr(error, "raw_text", None), str):
                (Path(str(job["root"])) / "failed-raw.txt").write_text(error.raw_text, encoding="utf-8")
            job["status"] = "failed"; self._event(job, "Failed", int(job.get("progress", 0)), str(error), "ERROR")
        finally:
            job["timings"] = {"total_seconds": round(time.perf_counter() - started, 3)}; job["metrics"] = system_metrics()
            self._save(job)
            with self._lock: self._active = None

    def _native_pages(self, source: Path, suffix: str) -> dict[int, str]:
        """Pages whose own text is good enough, by the test the library already uses. 13 pages of a
        paper with real text took the model five minutes at full GPU to copy out."""
        if suffix != ".pdf" or os.getenv("MOCK_OCR", "").lower() == "true":
            return {}
        config = self.router.models.get("ocr", {})
        minimum, ratio = int(config.get("min_text_characters", 80)), float(config.get("min_alphanumeric_ratio", 0.45))
        return {page: text for page, text in PyMuPDFParser().parse(source) if page is not None and not SmartParser._needs_ocr(text, minimum, ratio)}

    def _pages(self, source: Path, suffix: str, dpi: int, page_range: str | None) -> list[tuple[int, bytes]]:
        if suffix != ".pdf": return [(1, source.read_bytes())]
        import fitz
        document = fitz.open(str(source))
        try: selected = self._select_pages(len(document), page_range)
        finally: document.close()
        return self.ocr_service.render_pages(source, dpi, selected)

    @staticmethod
    def _is_valid_content(suffix: str, content: bytes) -> bool:
        signatures = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
        if suffix == ".webp":
            return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        return content.startswith(signatures[suffix])

    @staticmethod
    def _select_pages(total: int, page_range: str | None) -> list[int]:
        if not page_range: return list(range(1, total + 1))
        selected: set[int] = set()
        for part in page_range.split(","):
            bounds = [int(item.strip()) for item in part.split("-")]
            start, end = (bounds[0], bounds[-1]) if len(bounds) <= 2 else (_ for _ in ()).throw(ValueError("Invalid page range"))
            selected.update(range(start, end + 1))
        if not selected or min(selected) < 1 or max(selected) > total: raise ValueError(f"Page range must be within 1-{total}")
        return sorted(selected)

    def view(self, job_id: str) -> dict[str, object]:
        if job_id not in self.jobs:
            for item in self.store.list_ocr_runs():
                if item["id"] == job_id:
                    job = json.loads(str(item["result_json"])); self.jobs[job_id] = job; break
            else: raise KeyError(job_id)
        job = self.jobs[job_id]
        return {key: value for key, value in job.items() if key not in {"path", "root", "cancel"}}

    def cancel(self, job_id: str) -> dict[str, object]:
        if job_id not in self.jobs: raise KeyError(job_id)
        self.jobs[job_id]["cancel"] = True; self._event(self.jobs[job_id], "Cancelling", int(self.jobs[job_id]["progress"]), "Cancellation requested", "WARNING")
        return self.view(job_id)

    def evaluate(self, job_id: str, ground_truth: str) -> dict[str, object]:
        job = self.jobs.get(job_id)
        if not job: raise KeyError(job_id)
        actual = "\n\n".join(str(page["text"]) for page in job["pages"])  # type: ignore[index]
        result = evaluate_ocr(ground_truth, actual); job["evaluation"] = result
        self._save(job)
        return result

    def ask(self, job_id: str, question: str, page_numbers: list[int] | None = None) -> dict:
        job = self.view(job_id)
        if job["status"] != "completed":
            raise OcrPromotionError("OCR run must be completed before asking about its evidence")
        blocks, pages = [], job.get("pages", [])
        available = {page["page"] for page in pages}
        if page_numbers and not set(page_numbers) <= available:
            raise ValueError("Requested OCR page does not exist")
        for page in pages:
            if page_numbers and page["page"] not in page_numbers:
                continue
            blocks.extend(page.get("blocks") or [block.payload() for block in
                parse_evidence(str(page["text"]), page=int(page["page"]))])
        result = read_evidence(self.router, question, blocks)
        result.update(job_id=job_id, question=question)
        return result

    def promote(self, job_id: str, document_service: PostgresDocumentService) -> dict[str, object]:
        self.view(job_id)  # hydrate an archived job if necessary
        try:
            return document_service.promote_ocr_run(self.jobs[job_id])
        except (ValueError, OverflowError) as error:
            raise OcrPromotionError(str(error)) from error

    def export(self, job_id: str) -> Path:
        job = self.jobs.get(job_id)
        if not job: raise KeyError(job_id)
        root = Path(str(job["root"])); archive = root / f"{job_id}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for file in root.rglob("*"):
                if file.is_file() and file != archive: output.write(file, file.relative_to(root))
        return archive

    def delete(self, job_id: str) -> None:
        job = self.jobs.pop(job_id, None)
        if job: shutil.rmtree(Path(str(job["root"])), ignore_errors=True)
        self.store.delete_ocr_run(job_id)

    def list_history(self) -> list[dict[str, object]]:
        return [{key: value for key, value in json.loads(str(item["result_json"])).items() if key not in {"path", "root", "cancel", "events", "logs", "pages"}} for item in self.store.list_ocr_runs()]

    def _save(self, job: dict[str, object]) -> None:
        self.store.save_ocr_run(str(job["id"]), str(job["filename"]), str(job["status"]), str(job["model"]), json.dumps(job, ensure_ascii=False, default=str))
