from app.parsers.smart_parser import SmartParser


def test_ocr_quality_gate_flags_empty_or_garbled_native_text():
    assert SmartParser._needs_ocr("")
    assert SmartParser._needs_ocr("@ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @")


def test_ocr_quality_gate_keeps_sufficient_native_text():
    text = "This page contains readable native text. " * 8

    assert not SmartParser._needs_ocr(text)
