from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import io
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.services.model_router import ModelRouter
from app.stores.auxiliary_store import AuxiliaryStore
from app.services.ocr_evidence import PIPELINE_VERSION, OcrBlock, document_text, parse_evidence
from app.services.ocr_profiles import ocr_prompt


# Measured on pages with no text: glm-ocr answers "markdown", Qwen a sentence saying so. Neither
# is the page's content, and either would be indexed as if it were.
NO_TEXT_ANSWER = re.compile(
    r"markdown|(?:trong (?:ảnh|hình)(?: này)? )?không có (?:chữ|văn bản)(?: nào)?(?: trong (?:ảnh|hình)(?: này)?(?:[,;:][^\n]{0,120})?)?\W*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OcrResult:
    text: str
    model: str
    config_hash: str
    cache_hit: bool
    raw_text: str | None = None
    blocks: tuple[OcrBlock, ...] = ()
    warnings: tuple[str, ...] = ()


class OcrEvidenceError(ValueError):
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


class OCRService:
    """Single OCR core shared by RAG fallback and the OCR evaluation console."""

    def __init__(self, router: ModelRouter, store: AuxiliaryStore | object | None = None) -> None:
        self.router, self.store = router, store

    def config_hash(self, dpi: int) -> str:
        config = self.router.models.get("ocr", {})
        fingerprint = {"pipeline": PIPELINE_VERSION, "config": config, "prompt": ocr_prompt(config), "dpi": dpi}
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
            if cached.startswith("OCR-EVIDENCE-V1\n"):
                payload = json.loads(cached.split("\n", 1)[1])
                return self._result(payload["raw_text"], model, config_hash, True, config)
            return self._result(cached, model, config_hash, True, config)
        if allow_mock and os.getenv("MOCK_OCR", "").lower() == "true":
            return OcrResult("[MOCK OCR] simulated OCR output.", model, config_hash, False)
        image = self._prepare(png, config)
        encoded = base64.b64encode(image).decode("ascii")
        text, model = self.router.ocr(encoded, prompt=ocr_prompt(config))
        result = self._result(text, model, config_hash, False, config)
        if self.store and result.text:
            envelope = "OCR-EVIDENCE-V1\n" + json.dumps({"raw_text": text}, ensure_ascii=False)
            if hasattr(self.store, "save_ocr_cache_with_key") and isinstance(revision, str) and revision:
                self.store.save_ocr_cache_with_key(image_hash, "ollama", model, revision, config_hash, envelope)
            elif hasattr(self.store, "save_ocr_cache"):
                self.store.save_ocr_cache(f"{model}:{config_hash}", image_hash, envelope)
        return result

    @staticmethod
    def _prepare(png: bytes, config: dict) -> bytes:
        edge = config.get("max_image_edge")
        if edge is None:
            return png
        if isinstance(edge, bool) or not isinstance(edge, int) or not 512 <= edge <= 4096:
            raise ValueError("OCR max_image_edge must be in [512,4096]")
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(png)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((edge, edge))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

    @staticmethod
    def _result(raw: str, model: str, config_hash: str, hit: bool, config: dict) -> OcrResult:
        cleaned = raw.strip()
        if NO_TEXT_ANSWER.fullmatch(cleaned):
            cleaned = ""
        try:
            blocks = parse_evidence(cleaned, str(config.get("output_contract", "text"))) if cleaned else ()
        except (ValueError, TypeError, KeyError) as error:
            raise OcrEvidenceError(f"Invalid OCR evidence: {error}", raw) from error
        return OcrResult(document_text(blocks), model, config_hash, hit, raw, blocks)

    def recognize_pdf_pages(self, source: Path, dpi: int, page_numbers: list[int]) -> list[tuple[int, OcrResult]]:
        return [(number, self.recognize_png(png, dpi)) for number, png in self.render_pages(source, dpi, page_numbers)]
