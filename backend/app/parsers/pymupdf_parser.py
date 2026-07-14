from pathlib import Path

import pymupdf4llm

from app.parsers.base_parser import BaseParser


class PyMuPDFParser(BaseParser):
    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        pages = pymupdf4llm.to_markdown(str(path), page_chunks=True)
        result: list[tuple[int | None, str]] = []
        for index, page in enumerate(pages, start=1):
            text = page.get("text", "") if isinstance(page, dict) else str(page)
            result.append((index, text))
        return result
