from pathlib import Path

import pytest

from app.parsers.smart_parser import SmartParser


def test_ocr_checkpoint_runs_before_and_after_each_page(monkeypatch, tmp_path: Path):
    parser = SmartParser.__new__(SmartParser)
    parser.ocr_service = object(); parser.ocr_config = {"enabled": True, "min_text_characters": 80, "min_alphanumeric_ratio": 0.45}; parser.last_warnings = []
    monkeypatch.setattr("app.parsers.ocr_parser.OcrParser.parse_pages", lambda self, path, numbers: [(numbers[0], f"ocr {numbers[0]}")])
    calls = []
    result = parser._apply_ocr_fallback(tmp_path / "x.pdf", [(1, "", "native"), (2, "", "native")], checkpoint=lambda: calls.append(1) is None)
    assert [item[1] for item in result] == ["ocr 1", "ocr 2"]
    assert len(calls) == 4


def test_ocr_checkpoint_stops_before_next_page(monkeypatch, tmp_path: Path):
    parser = SmartParser.__new__(SmartParser)
    parser.ocr_service = object(); parser.ocr_config = {"enabled": True, "min_text_characters": 80, "min_alphanumeric_ratio": 0.45}; parser.last_warnings = []
    monkeypatch.setattr("app.parsers.ocr_parser.OcrParser.parse_pages", lambda self, path, numbers: [(numbers[0], "ocr")])
    checks = iter([True, True, False])
    with pytest.raises(PermissionError):
        parser._apply_ocr_fallback(tmp_path / "x.pdf", [(1, "", "native"), (2, "", "native")], checkpoint=lambda: next(checks))
