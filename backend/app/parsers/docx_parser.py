from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from app.parsers.base_parser import BaseParser


# T17: Word marks a heading with a paragraph STYLE, not with the "#" prefix the
# chunker looks for, so styled headings used to reach chunking as plain text and
# every .docx chunk came out with heading_path = NULL.  Both the display name
# ("Heading 2") and the style id ("Heading2") are checked because the name is
# localized in non-English Word installs while the id usually is not.
_HEADING_LEVEL = re.compile(r"heading\s*([1-9])", re.IGNORECASE)
_TITLE_STYLES = {"title", "subtitle"}
_MAX_HEADING_LEVEL = 6  # chunking._HEADING_PATTERN accepts #{1,6}

_TXBX_CONTENT = qn("w:txbxContent")
# python-docx's nsmap has no "mc" prefix, so the markup-compatibility namespace
# is spelled out here.
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_TEXT_CHILDREN = {_W + "r", _W + "hyperlink"}          # exactly what CT_P.text reads
_MATH_BLOCKS = {_M + "oMath", _M + "oMathPara"}
_BULLET = "•"                                      # label() sentinel: a bullet, not a number


class DocxParser(BaseParser):
    """Read a .docx the way the chunker expects to be fed.

    `document.paragraphs` alone silently drops every table, every text box and
    every heading level: measured on three real documents it recovered 79-92%
    of the body text, and the missing part was concentrated in exactly the
    high-value content (results tables, session summary boxes).  This walks the
    body in document order instead, renders tables as markdown pipe rows that
    chunking._is_table_line recognizes, and restores heading markers.

    Pages stay None: a .docx has no fixed pagination, and none of the sample
    documents carried even a rendered page break to approximate one.
    """

    def parse(self, path: Path) -> list[tuple[int | None, str]]:
        document = Document(path)
        numbering = _Numbering.of(document)
        blocks: list[str] = []
        for item in _iter_body(document):
            if isinstance(item, Paragraph):
                blocks.extend(_paragraph_blocks(item, numbering))
            else:
                blocks.extend(_table_blocks(item, numbering))
        return [(None, "\n\n".join(blocks))]


def _iter_body(parent: DocxDocument | _Cell):
    """Yield Paragraph and Table children in document order.

    python-docx exposes `.paragraphs` and `.tables` as two separate flat lists,
    which loses both the interleaving and any table nested inside a cell.
    """
    element = parent.element.body if isinstance(parent, DocxDocument) else parent._tc
    for child in element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _heading_prefix(paragraph: Paragraph) -> str:
    style = paragraph.style
    name, style_id = (style.name or ""), (style.style_id or "")
    match = _HEADING_LEVEL.search(name) or _HEADING_LEVEL.search(style_id)
    if match:
        return "#" * min(int(match.group(1)), _MAX_HEADING_LEVEL) + " "
    return "# " if name.strip().lower() in _TITLE_STYLES else ""


def _paragraph_blocks(paragraph: Paragraph, numbering: _Numbering | None = None) -> list[str]:
    blocks: list[str] = []
    # Asked before the emptiness check: Word shows and spends a number on an empty
    # numbered paragraph too, so skipping it would shift every number after it.
    label = numbering.label(paragraph) if numbering is not None else None
    text = _paragraph_text(paragraph).strip()
    if text:
        # A heading spanning several lines would break the "#" convention, and
        # the chunker treats one heading as one line.
        text = " ".join(text.split())
        prefix = _heading_prefix(paragraph)
        if label:
            text = text if label == _BULLET else f"{label} {text}"
            # A numbered heading keeps its "#". A list item gets "- ": written as
            # "1. Đơn đề nghị theo mẫu" it matches chunking._HEADING_PATTERN (a
            # numbered line without closing punctuation is a heading there), and
            # every list item would open a heading of its own.
            prefix = prefix or "- "
        blocks.append(prefix + text)
    blocks.extend(_textbox_blocks(paragraph))
    return blocks


def _paragraph_text(paragraph: Paragraph) -> str:
    """Paragraph.text plus any equation, in document order.

    Paragraph.text reads only the w:r and w:hyperlink children, so an m:oMath
    between two runs vanished and a formula line kept only its label. A paragraph
    without math takes the original path unchanged."""
    p = paragraph._p
    if not any(child.tag in _MATH_BLOCKS for child in p.iterchildren()):
        return paragraph.text
    parts: list[str] = []
    for child in p.iterchildren():
        if child.tag in _TEXT_CHILDREN:
            parts.append(child.text)
        elif child.tag in _MATH_BLOCKS:
            try:
                parts.append(_math_text(child))
            except Exception:   # a structure this reader got wrong still keeps its symbols
                parts.append("".join(t.text or "" for t in child.iter(_M + "t")))
    return "".join(parts)


def _math_text(element) -> str:
    """OMML as one line that a reader and BM25 both handle: (a+b)/2, x^2, √(x).
    Anything not listed falls back to its text in order, so nothing is dropped."""
    tag = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
    if tag == "t":
        return element.text or ""
    if tag.endswith("Pr"):              # rPr, fPr, naryPr, ...: formatting only
        return ""

    def inner(name: str) -> str:
        child = element.find(_M + name)
        return _math_text(child) if child is not None else ""

    def prop(container: str, name: str, default: str) -> str:
        props = element.find(_M + container)
        node = props.find(_M + name) if props is not None else None
        return node.get(_M + "val", default) if node is not None else default

    if tag == "f":
        return f"{_group(inner('num'))}/{_group(inner('den'))}"
    if tag == "sSup":
        return f"{_group(inner('e'))}^{_group(inner('sup'))}"
    if tag == "sSub":
        return f"{_group(inner('e'))}_{_group(inner('sub'))}"
    if tag == "sSubSup":
        return f"{_group(inner('e'))}_{_group(inner('sub'))}^{_group(inner('sup'))}"
    if tag == "rad":
        degree = inner("deg")
        return (f"root({degree})" if degree else "√") + f"({inner('e')})"
    if tag == "nary":
        sub, sup = inner("sub"), inner("sup")
        return (prop("naryPr", "chr", "∫") + (f"_{_group(sub)}" if sub else "")
                + (f"^{_group(sup)}" if sup else "") + " " + inner("e"))
    if tag == "d":
        items = (_math_text(e) for e in element.findall(_M + "e"))
        return prop("dPr", "begChr", "(") + prop("dPr", "sepChr", "|").join(items) + prop("dPr", "endChr", ")")
    if tag == "func":
        return f"{inner('fName')} {inner('e')}".strip()
    if tag in ("limLow", "limUpp"):
        return f"{inner('e')}{'_' if tag == 'limLow' else '^'}{_group(inner('lim'))}"
    if tag == "eqArr":
        return "; ".join(_math_text(e) for e in element.findall(_M + "e"))
    if tag == "m":
        rows = (", ".join(_math_text(e) for e in row.findall(_M + "e")) for row in element.findall(_M + "mr"))
        return "[" + "; ".join(rows) + "]"
    if tag == "oMathPara":
        return " ".join(_math_text(child) for child in element.findall(_M + "oMath"))
    return "".join(_math_text(child) for child in element)


def _group(text: str) -> str:
    return text if re.fullmatch(r"[\w.,]+", text) else f"({text})"


@dataclass(frozen=True)
class _Level:
    start: int
    fmt: str
    text: str
    legal: bool


class _Numbering:
    """Word's automatic numbers, recomputed in document order.

    The number shown beside a list item is not in the paragraph: the paragraph (or
    its style) names a list and a level in numbering.xml, and Word counts. A
    Vietnamese law numbered this way lost every "Điều 1." / "1." / "a)" — the words
    a citation is made of. Counters live per abstract list, which is what Word
    continues across list instances; a startOverride restarts its level the first
    time that instance is used, and a deeper level restarts after any item above
    it. Rare forms (numStyleLink indirection, lvlRestart limits) are not modelled
    and simply fall back to no number, as before."""

    def __init__(self, levels: dict, num_to_abstract: dict, overrides: dict, style_levels: dict) -> None:
        self._levels, self._num_to_abstract = levels, num_to_abstract
        self._overrides, self._style_levels = overrides, style_levels
        self._counters: dict[str, dict[int, int]] = {}
        self._restarted: set[str] = set()

    @classmethod
    def of(cls, document) -> _Numbering | None:
        try:
            root = document.part.numbering_part.element
        except Exception:
            return None
        levels: dict[str, dict[int, _Level]] = {}
        style_levels: dict[tuple[str, str], int] = {}
        for abstract in root.findall(_W + "abstractNum"):
            abstract_id = abstract.get(_W + "abstractNumId")
            by_level: dict[int, _Level] = {}
            for lvl in abstract.findall(_W + "lvl"):
                ilvl = int(lvl.get(_W + "ilvl", "0"))
                start = _val(lvl, "start")
                by_level[ilvl] = _Level(int(start) if start and start.lstrip("-").isdigit() else 1,
                                        _val(lvl, "numFmt") or "decimal", _val(lvl, "lvlText") or "",
                                        lvl.find(_W + "isLgl") is not None)
                linked_style = _val(lvl, "pStyle")
                if linked_style:
                    style_levels[(abstract_id, linked_style)] = ilvl
            levels[abstract_id] = by_level
        num_to_abstract: dict[str, str | None] = {}
        overrides: dict[str, dict[int, int]] = {}
        for num in root.findall(_W + "num"):
            num_id = num.get(_W + "numId")
            num_to_abstract[num_id] = _val(num, "abstractNumId")
            for override in num.findall(_W + "lvlOverride"):
                start = _val(override, "startOverride")
                if start and start.isdigit():
                    overrides.setdefault(num_id, {})[int(override.get(_W + "ilvl", "0"))] = int(start)
        return cls(levels, num_to_abstract, overrides, style_levels)

    def label(self, paragraph: Paragraph) -> str | None:
        try:
            return self._label(paragraph)
        except Exception:   # numbering is decoration: never let it cost the paragraph
            return None

    def _label(self, paragraph: Paragraph) -> str | None:
        num_id, ilvl, style_id = _num_pr(paragraph)
        if not num_id or num_id == "0":
            return None
        abstract_id = self._num_to_abstract.get(num_id)
        levels = self._levels.get(abstract_id) if abstract_id is not None else None
        if not levels:
            return None
        if ilvl is None:
            ilvl = self._style_levels.get((abstract_id, style_id), 0)
        level = levels.get(ilvl)
        if level is None:
            return None
        counters = self._counters.setdefault(abstract_id, {})
        if num_id in self._overrides and num_id not in self._restarted:
            self._restarted.add(num_id)
            for restarted, start in self._overrides[num_id].items():
                counters[restarted] = start - 1
                for deeper in [k for k in counters if k > restarted]:
                    del counters[deeper]
        counters[ilvl] = counters.get(ilvl, level.start - 1) + 1
        for deeper in [k for k in counters if k > ilvl]:
            del counters[deeper]
        if level.fmt == "bullet":
            return _BULLET
        if level.fmt == "none":
            return ""

        def number(match: re.Match[str]) -> str:
            k = int(match.group(1)) - 1
            owner = levels.get(k)
            value = counters.get(k, owner.start if owner else 1)
            return _format_number(value, "decimal" if level.legal else (owner.fmt if owner else "decimal"))

        return re.sub(r"%([1-9])", number, level.text).strip()


def _val(element, name: str) -> str | None:
    child = element.find(_W + name)
    return child.get(_W + "val") if child is not None else None


def _num_pr(paragraph: Paragraph) -> tuple[str | None, int | None, str | None]:
    """(numId, ilvl, style id) from the paragraph, then up its style chain."""
    num_id = ilvl = None
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        num_id = p_pr.numPr.numId.val if p_pr.numPr.numId is not None else None
        ilvl = p_pr.numPr.ilvl.val if p_pr.numPr.ilvl is not None else None
    style = paragraph.style
    style_id = style.style_id if style is not None else None
    seen: set[str] = set()                  # a damaged file can make basedOn circular
    while style is not None and (num_id is None or ilvl is None) and style.style_id not in seen:
        seen.add(style.style_id)
        s_pr = style.element.pPr
        if s_pr is not None and s_pr.numPr is not None:
            if num_id is None and s_pr.numPr.numId is not None:
                num_id = s_pr.numPr.numId.val
            if ilvl is None and s_pr.numPr.ilvl is not None:
                ilvl = s_pr.numPr.ilvl.val
        style = style.base_style
    return (str(num_id) if num_id is not None else None), (int(ilvl) if ilvl is not None else None), style_id


def _format_number(value: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        letters = chr(ord("a") + (value - 1) % 26) * ((value - 1) // 26 + 1)
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("lowerRoman", "upperRoman"):
        roman = _roman(value)
        return roman.lower() if fmt == "lowerRoman" else roman
    if fmt == "decimalZero":
        return f"{value:02d}"
    return str(value)


def _roman(value: int) -> str:
    out = []
    for amount, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                           (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        count, value = divmod(value, amount)
        out.append(symbol * count)
    return "".join(out)


def _textbox_blocks(paragraph: Paragraph) -> list[str]:
    """Text inside shapes/text boxes, which `Paragraph.text` never returns.

    Word wraps a modern shape in mc:AlternateContent and writes the SAME text
    twice: once under mc:Choice and once as a legacy VML copy under
    mc:Fallback. Taking both would duplicate the content, so the fallback copy
    is skipped.
    """
    blocks: list[str] = []
    for container in paragraph._p.iter(_TXBX_CONTENT):
        if any(ancestor.tag == _MC_FALLBACK for ancestor in container.iterancestors()):
            continue
        lines = [" ".join(node.text.split()) for node in container.iter(qn("w:t")) if node.text and node.text.strip()]
        if lines:
            blocks.append(" ".join(lines))
    return blocks


def _cell_text(cell: _Cell, numbering: _Numbering | None = None) -> str:
    """One table cell flattened to a single pipe-safe line."""
    parts: list[str] = []
    for item in _iter_body(cell):
        if isinstance(item, Paragraph):
            parts.extend(_paragraph_blocks(item, numbering))
        else:  # a table nested inside this cell
            parts.extend(_table_blocks(item, numbering))
    # Newlines would end the table block early and "|" would forge a column.
    return " ".join(" ".join(parts).split()).replace("|", "\\|")


def _table_blocks(table: Table, numbering: _Numbering | None = None) -> list[str]:
    """Render a table as markdown pipe rows.

    chunking._is_table_line only accepts a line starting with "|" and holding
    at least two of them, and chunking._table_blocks repeats the header row on
    every split when the second line is a "---" separator — so emitting that
    separator is what keeps a long table readable after chunking.
    """
    # row.cells repeats a merged cell once per grid column it spans. The text is
    # repeated as before, but it is read once: reading it twice would also count
    # a numbered paragraph inside it twice.
    read: dict = {}

    def text_of(cell: _Cell) -> str:
        if cell._tc not in read:
            read[cell._tc] = _cell_text(cell, numbering)
        return read[cell._tc]

    rows = [[text_of(cell) for cell in row.cells] for row in table.rows]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return []
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return ["\n".join(lines)]
