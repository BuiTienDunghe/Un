from __future__ import annotations

import base64
from pathlib import Path

# pyrefly: ignore [missing-import]
import fitz  # PyMuPDF — installed alongside pymupdf4llm

from app.parsers.base_parser import BaseParser
from app.services.model_router import ModelRouter


class OcrParser(BaseParser):
    """OCR parser that renders PDF pages to images and sends them to a vision model."""

    # Render at 200 DPI — good balance between quality and speed
    DPI = 200

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        """Parse a PDF by rendering each page to an image and running OCR."""
        document = fitz.open(str(path))
        result: list[tuple[int | None, str]] = []
        try:
            for page_index in range(len(document)):
                page = document[page_index]
                image_base64 = self._render_page_base64(page)
                text, _ = self.router.ocr(image_base64)
                result.append((page_index + 1, text.strip()))
        finally:
            document.close()
        return result

    def parse_pages(self, path: Path, page_numbers: list[int]) -> list[tuple[int, str]]:
        """OCR only specific pages (1-indexed)."""
        document = fitz.open(str(path))
        result: list[tuple[int, str]] = []
        try:
            for page_number in page_numbers:
                page = document[page_number - 1]
                image_base64 = self._render_page_base64(page)
                text, _ = self.router.ocr(image_base64)
                result.append((page_number, text.strip()))
        finally:
            document.close()
        return result

    @classmethod
    def _render_page_base64(cls, page: fitz.Page) -> str:
        """Render a fitz page to a PNG image and return as base64 string."""
        matrix = fitz.Matrix(cls.DPI / 72, cls.DPI / 72)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
        png_bytes = pixmap.tobytes("png")
        return base64.b64encode(png_bytes).decode("ascii")
