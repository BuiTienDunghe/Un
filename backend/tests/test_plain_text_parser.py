"""A .txt or .md arrives in whatever encoding the author's editor used.

The reader used to decode everything as UTF-8 with errors="replace". Measured on
29/09/2026 with one Vietnamese legal paragraph: UTF-16 (Notepad's "Unicode") came
back as noise (character error rate 1.19) and Windows-1258 lost 35% of its
characters, silently — both files indexed, neither findable.
"""
import codecs
import unicodedata
from pathlib import Path

import pytest

from app.parsers.plain_text_parser import PlainTextParser

VI = ("Điều 1. Phạm vi điều chỉnh\n"
      "Luật này quy định về quyền và nghĩa vụ của cơ quan, tổ chức, cá nhân trong việc bảo vệ dữ liệu cá nhân.")
TONES = {"̀", "́", "̃", "̉", "̣"}


def _parse(tmp_path: Path, data: bytes) -> str:
    path = tmp_path / "doc.txt"
    path.write_bytes(data)
    return PlainTextParser().parse(path)[0][1]


def _windows_1258(text: str) -> bytes:
    """How Windows-1258 stores Vietnamese: a precomposed base vowel plus a combining tone mark."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        try:
            out.append(ch.encode("cp1258"))
            continue
        except UnicodeEncodeError:
            pass
        parts = unicodedata.normalize("NFD", ch)
        base = unicodedata.normalize("NFC", "".join(c for c in parts if c not in TONES))
        out.append((base + "".join(c for c in parts if c in TONES)).encode("cp1258"))
    return b"".join(out)


@pytest.mark.parametrize("data", [
    VI.encode("utf-8"),
    codecs.BOM_UTF8 + VI.encode("utf-8"),
    VI.encode("utf-16"),                               # Notepad "Unicode": little-endian with BOM
    codecs.BOM_UTF16_BE + VI.encode("utf-16-be"),
    VI.encode("utf-16-le"),                            # no BOM: recognised by where the NUL bytes sit
    VI.encode("utf-16-be"),
], ids=["utf-8", "utf-8-bom", "utf-16-le-bom", "utf-16-be-bom", "utf-16-le", "utf-16-be"])
def test_every_unicode_encoding_reads_back_the_same_text(tmp_path: Path, data: bytes):
    assert _parse(tmp_path, data) == VI


def test_windows_1258_is_decoded_and_its_tone_marks_composed(tmp_path: Path):
    text = _parse(tmp_path, _windows_1258(VI))
    # NFC matters as much as the decoding: 1258 writes "ệ" as "ê" + a combining dot, and
    # a query typed on any Vietnamese keyboard is precomposed, so an uncomposed
    # document would decode "correctly" and still never match.
    assert text == VI and unicodedata.is_normalized("NFC", text)


def test_a_few_damaged_bytes_keep_a_utf8_file_utf8(tmp_path: Path):
    body = ((VI + "\n") * 40).encode("utf-8")
    cut = body.index(b"\n", 200) + 1                   # between lines, not inside a multi-byte letter
    damaged = body[:cut] + b"\xff" + body[cut:]        # one stray byte in ~6 KB

    text = _parse(tmp_path, damaged)

    # Falling back to 1258 here would turn every Vietnamese letter into noise.
    assert text.count("�") == 1 and text.count("Điều 1. Phạm vi điều chỉnh") == 40
