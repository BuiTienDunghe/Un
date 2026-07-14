from __future__ import annotations

import base64
import json
import os
import shutil
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import UploadFile

from app.services.model_router import ModelRouter
from app.services.monitoring_service import system_metrics
from app.services.ocr_metrics_service import evaluate_ocr
from app.stores.sqlite_store import SQLiteStore


class OcrJobService:
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self, router: ModelRouter, runs_path: Path, store: SQLiteStore) -> None:
        self.router, self.runs_path, self.store = router, runs_path, store
        self.jobs: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self._active: str | None = None

    async def create(self, file: UploadFile, dpi: int, page_range: str | None, output_format: str) -> dict[str, object]:
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
        job: dict[str, object] = {"id": job_id, "filename": file.filename or filename, "suffix": suffix, "path": str(root / "input" / filename), "root": str(root), "dpi": dpi, "page_range": page_range, "output_format": output_format, "status": "queued", "stage": "Queued", "progress": 0, "current_page": 0, "total_pages": 0, "events": [], "logs": [], "pages": [], "timings": {}, "cancel": False, "created_at": time.time(), "model": str(self.router.models.get("ocr", {}).get("name", "unconfigured"))}
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
                job["status"] = "failed"; self._event(job, "Rejected", 0, "Another OCR job is currently running", "ERROR"); return
            self._active = job_id
        started = time.perf_counter()
        try:
            job["status"] = "running"; self._event(job, "Reading document", 5, "File accepted")
            source = Path(str(job["path"])); suffix = str(job["suffix"])
            pages = self._pages(source, suffix, int(job["dpi"]), job.get("page_range") if isinstance(job.get("page_range"), str) else None)
            job["total_pages"] = len(pages)
            if not pages: raise ValueError("No pages selected")
            for index, (number, png) in enumerate(pages, start=1):
                if job["cancel"]: job["status"] = "cancelled"; self._event(job, "Cancelled", int((index - 1) / len(pages) * 100), "Stopped at safe page boundary", "WARNING"); return
                job["current_page"] = number
                progress = 10 + int((index - 1) / len(pages) * 80)
                self._event(job, "OCR inference", progress, f"Processing page {number}/{len(pages)}")
                page_started = time.perf_counter()
                encoded = base64.b64encode(png).decode("ascii")
                if os.getenv("MOCK_OCR", "").lower() == "true": text = f"[MOCK OCR] Page {number}: simulated OCR output."
                else: text, _ = self.router.ocr(encoded)
                page_dir = Path(str(job["root"])) / "pages" / f"page_{number:04d}"; page_dir.mkdir()
                (page_dir / "original.png").write_bytes(png)
                (page_dir / "text.txt").write_text(text, encoding="utf-8")
                (page_dir / "result.md").write_text(text, encoding="utf-8")
                payload = {"page": number, "text": text, "markdown": text, "extraction_method": "mock" if os.getenv("MOCK_OCR", "").lower() == "true" else "glm-ocr"}
                (page_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                job["pages"].append({**payload, "image_url": f"/api/ocr/jobs/{job_id}/files/pages/page_{number:04d}/original.png", "duration_seconds": round(time.perf_counter() - page_started, 3)})  # type: ignore[index]
            job["status"] = "completed"; self._event(job, "Completed", 100, "All selected pages processed")
        except Exception as error:
            job["status"] = "failed"; self._event(job, "Failed", int(job.get("progress", 0)), str(error), "ERROR")
        finally:
            job["timings"] = {"total_seconds": round(time.perf_counter() - started, 3)}; job["metrics"] = system_metrics()
            self._save(job)
            with self._lock: self._active = None

    @staticmethod
    def _pages(source: Path, suffix: str, dpi: int, page_range: str | None) -> list[tuple[int, bytes]]:
        if suffix != ".pdf": return [(1, source.read_bytes())]
        document = fitz.open(str(source))
        try:
            selected = OcrJobService._select_pages(len(document), page_range)
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
            return [(number, document[number - 1].get_pixmap(matrix=matrix, colorspace=fitz.csRGB).tobytes("png")) for number in selected]
        finally: document.close()

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
