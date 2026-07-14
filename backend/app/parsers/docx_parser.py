from pathlib import Path

from docx import Document

from app.parsers.base_parser import BaseParser


class DocxParser(BaseParser):
    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        document = Document(path)
        return [(None, "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()))]
