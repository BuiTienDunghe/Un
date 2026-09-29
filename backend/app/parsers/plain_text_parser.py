import codecs
import unicodedata
from pathlib import Path

from app.parsers.base_parser import BaseParser

# UTF-32 before UTF-16: the UTF-32-LE mark begins with the UTF-16-LE one.
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


class PlainTextParser(BaseParser):
    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        return [(None, decode_text(path.read_bytes()))]


def decode_text(data: bytes) -> str:
    """Decode a .txt/.md in the encoding its editor actually wrote.

    Until 29/09/2026 this was UTF-8 with errors="replace" for every file: a
    Vietnamese paragraph saved by Notepad as "Unicode" (UTF-16) came back as noise,
    and one saved as Windows-1258 lost 35% of its characters, both silently.
    Order: a byte-order mark says it outright; UTF-16 without a mark shows itself
    by where the NUL bytes sit; then UTF-8, which a legacy file almost never
    passes by accident; then Windows-1258, the Vietnamese Windows code page.
    """
    for bom, codec in _BOMS:
        if data.startswith(bom):
            return data.decode(codec, errors="replace")
    utf16 = _utf16_without_bom(data)
    if utf16:
        return data.decode(utf16, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    loose = data.decode("utf-8", errors="replace")
    # A UTF-8 file with a few damaged bytes stays UTF-8: re-reading it as 1258 would
    # turn every Vietnamese letter into noise to rescue one character. A real 1258
    # file fails on nearly every accented letter, far above one in a thousand.
    if loose.count("�") <= max(1, len(loose) // 1000):
        return loose
    # 1258 stores "ệ" as "ê" plus a combining dot; queries are typed precomposed, so
    # without NFC the text would decode correctly and still never match.
    return unicodedata.normalize("NFC", data.decode("cp1258", errors="replace"))


def _utf16_without_bom(data: bytes) -> str | None:
    """ASCII and most Latin letters have a zero high byte in UTF-16, so a BOM-less
    UTF-16 file has NULs on one side of every pair and almost none on the other.
    UTF-8 text never contains NUL."""
    if len(data) < 4 or len(data) % 2:
        return None
    half = len(data) // 2
    even, odd = data[0::2].count(0), data[1::2].count(0)
    if odd > 0.3 * half and even < 0.05 * half:
        return "utf-16-le"
    if even > 0.3 * half and odd < 0.05 * half:
        return "utf-16-be"
    return None
