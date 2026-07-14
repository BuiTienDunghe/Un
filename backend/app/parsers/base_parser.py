from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        """Return (page, text) pairs."""
