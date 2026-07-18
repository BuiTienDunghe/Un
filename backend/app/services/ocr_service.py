from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.services.model_router import ModelRouter
from app.stores.auxiliary_store import AuxiliaryStore


@dataclass(frozen=True)
class OcrResult:
    text: str
    model: str
    config_hash: str
    cache_hit: bool


class OCRService:
    """Single OCR core shared by RAG fallback and the OCR evaluation console."""

    def __init__(self, router: ModelRouter, store: AuxiliaryStore | object | None = None) -> None:
        self.router, self.store = router, store

    def config_hash(self, dpi: int) -> str:
        config = self.router.models.get("ocr", {})
        fingerprint = {
            "model": config.get("name"), "temperature": config.get("temperature"),
            "context": config.get("context"), "prompt": config.get("prompt", "Text Recognition:"), "dpi": dpi,
        }
        return hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()

    def render_pages(self, source: Path, dpi: int, page_numbers: list[int] | None = None) -> list[tuple[int, bytes]]:
        document = fitz.open(str(source))
        try:
            selected = page_numbers or list(range(1, len(document) + 1))
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
            return [(number, document[number - 1].get_pixmap(matrix=matrix, colorspace=fitz.csRGB).tobytes("png")) for number in selected]
        finally:
            document.close()

    def recognize_png(self, png: bytes, dpi: int, *, allow_mock: bool = False) -> OcrResult:
        config = self.router.models.get("ocr", {})
        model = str(config.get("name", "unconfigured"))
        config_hash = self.config_hash(dpi)
        image_hash = hashlib.sha256(png).hexdigest()
        # PostgreSQL cache keys intentionally require an explicit model revision.
        # Current models.yaml has none, so PostgreSQL mode safely treats cache as
        # a miss instead of manufacturing a revision from the model name.
        revision = config.get("revision")
        if self.store and hasattr(self.store, "get_ocr_cache_with_key") and isinstance(revision, str) and revision:
            cached = self.store.get_ocr_cache_with_key(image_hash, "ollama", model, revision, config_hash)
        elif self.store and hasattr(self.store, "get_ocr_cache"):
            cached = self.store.get_ocr_cache(f"{model}:{config_hash}", image_hash)
        else:
            cached = None
        if cached is not None:
            return OcrResult(cached, model, config_hash, True)
        if allow_mock and os.getenv("MOCK_OCR", "").lower() == "true":
            return OcrResult("[MOCK OCR] simulated OCR output.", model, config_hash, False)
        encoded = base64.b64encode(png).decode("ascii")
        text, model = self.router.ocr(encoded, prompt=str(config.get("prompt", "Text Recognition:")))
        cleaned = text.strip()
        if self.store and cleaned:
            if hasattr(self.store, "save_ocr_cache_with_key") and isinstance(revision, str) and revision:
                self.store.save_ocr_cache_with_key(image_hash, "ollama", model, revision, config_hash, cleaned)
            elif hasattr(self.store, "save_ocr_cache"):
                self.store.save_ocr_cache(f"{model}:{config_hash}", image_hash, cleaned)
        return OcrResult(cleaned, model, config_hash, False)

    def recognize_pdf_pages(self, source: Path, dpi: int, page_numbers: list[int]) -> list[tuple[int, OcrResult]]:
        return [(number, self.recognize_png(png, dpi)) for number, png in self.render_pages(source, dpi, page_numbers)]
