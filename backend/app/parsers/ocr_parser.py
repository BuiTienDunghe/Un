from __future__ import annotations

from pathlib import Path

import fitz

from app.parsers.base_parser import BaseParser
from app.services.ocr_service import OCRService


class OcrParser(BaseParser):
    """Thin PDF adapter around the shared OCRService."""

    def __init__(self, ocr_service: OCRService, dpi: int = 200) -> None:
        self.ocr_service, self.dpi = ocr_service, dpi

    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        document = fitz.open(str(path))
        try:
            page_numbers = list(range(1, len(document) + 1))
        finally:
            document.close()
        return [(number, result.text) for number, result in self.ocr_service.recognize_pdf_pages(path, self.dpi, page_numbers)]

    def parse_pages(self, path: Path, page_numbers: list[int]) -> list[tuple[int, str]]:
        return [(number, result.text) for number, result in self.ocr_service.recognize_pdf_pages(path, self.dpi, page_numbers)]
