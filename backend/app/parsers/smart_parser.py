from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.parsers.base_parser import BaseParser
from app.parsers.docx_parser import DocxParser
from app.parsers.plain_text_parser import PlainTextParser
from app.parsers.pymupdf_parser import PyMuPDFParser

if TYPE_CHECKING:
    from app.services.model_router import ModelRouter


class SmartParser:
    """Native parsing with a GLM-OCR fallback for PDF pages lacking readable text."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.parsers: dict[str, BaseParser] = {
            ".pdf": PyMuPDFParser(), ".docx": DocxParser(), ".txt": PlainTextParser(), ".md": PlainTextParser(),
        }
        self.router = router
        self.ocr_config = router.models.get("ocr", {}) if router else {}

    def parse(self, path: Path) -> list[tuple[int | None, str, str]]:
        parser = self.parsers.get(path.suffix.lower())
        if parser is None:
            raise ValueError(f"Unsupported file type: {path.suffix}")
        pages = [(page, text, "native") for page, text in parser.parse(path)]
        if path.suffix.lower() != ".pdf" or self.router is None or not self.ocr_config.get("enabled", False):
            return pages
        return self._apply_ocr_fallback(path, pages)

    def _apply_ocr_fallback(self, path: Path, pages: list[tuple[int | None, str, str]]) -> list[tuple[int | None, str, str]]:
        from app.parsers.ocr_parser import OcrParser

        needed = [page for page, text, _ in pages if page is not None and self._needs_ocr(text, int(self.ocr_config.get("min_text_characters", 80)), float(self.ocr_config.get("min_alphanumeric_ratio", 0.45)))]
        if not needed:
            return pages
        logger.info("OCR fallback triggered for {}/{} pages: {}", len(needed), len(pages), needed)
        extracted = dict(OcrParser(self.router).parse_pages(path, needed))
        return [(page, extracted[page], "ocr") if page in extracted else (page, text, method) for page, text, method in pages]

    @staticmethod
    def _needs_ocr(text: str, min_text_characters: int = 80, min_alphanumeric_ratio: float = 0.45) -> bool:
        normalized = "".join(text.split())
        if len(normalized) < min_text_characters:
            return True
        return sum(character.isalnum() for character in normalized) / len(normalized) < min_alphanumeric_ratio
