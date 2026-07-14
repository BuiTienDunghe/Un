from pathlib import Path

from app.parsers.base_parser import BaseParser


class PlainTextParser(BaseParser):
    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        return [(None, path.read_text(encoding="utf-8", errors="replace"))]
