"""Validated OCR evidence; tables retain headers, raw output is never rewritten.

Coordinates are normalized to 0..1000. Derived text lines/rows have no invented box.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser


PIPELINE_VERSION = "ocr-evidence-v2"
MARKER = re.compile(r"!\[([a-z_]+\+?)\]\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
VISUAL_KINDS = frozenset({"image", "chart", "header_image", "footer_image"})
OVIS_KINDS = frozenset("abstract algorithm aside_text chart content display_formula doc_title figure_title footer footer_image footnote formula_number header header_image image inline_formula number paragraph_title reference_content seal table text vertical_text vision_footnote".split())


@dataclass(frozen=True)
class OcrBlock:
    id: str
    page: int
    kind: str
    text: str
    bbox: tuple[float, float, float, float] | None = None
    parent_id: str | None = None
    origin: str = "ocr"
    source_ids: tuple[str, ...] = ()

    def payload(self, page: int | None = None) -> dict:
        value = asdict(self)
        if page is not None:
            value.update(page=page, id=re.sub(r"^p\d+", f"p{page}", self.id))
            if self.parent_id:
                value["parent_id"] = re.sub(r"^p\d+", f"p{page}", self.parent_id)
            value["source_ids"] = [re.sub(r"^p\d+", f"p{page}", key) for key in self.source_ids]
        return value


def _box(value) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) for v in value
    ):
        raise ValueError("OCR bounding box must contain four numbers")
    x1, y1, x2, y2 = value
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError("OCR bounding box is outside normalized page coordinates")
    return tuple(value)


class _Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], [], None
        self.spans, self.span, self.depth = {}, (1, 1), 0
        self.in_row = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth > 1:
                raise ValueError("Nested OCR tables require explicit review")
        if tag == "tr":
            if self.in_row:
                raise ValueError("Unclosed OCR table row")
            self.in_row = True
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
            attrs = dict(attrs)
            self.span = (int(attrs.get("rowspan", 1)), int(attrs.get("colspan", 1)))
            if any(not 1 <= size <= 100 for size in self.span):
                raise ValueError("OCR table span is too large")
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append((" ".join("".join(self.cell).split()), *self.span))
            self.cell = None
        elif tag == "tr":
            if not self.in_row or self.cell is not None:
                raise ValueError("Incomplete OCR table row")
            self.in_row = False
            index, column, expanded = len(self.rows), 0, []
            for content, rowspan, colspan in self.row:
                while (index, column) in self.spans:
                    expanded.append(self.spans.pop((index, column)))
                    column += 1
                for offset in range(colspan):
                    expanded.append(content)
                    for delta in range(1, rowspan):
                        self.spans[index + delta, column + offset] = content
                column += colspan
            while (index, column) in self.spans:
                expanded.append(self.spans.pop((index, column)))
                column += 1
            if expanded:
                self.rows.append(expanded)
            if len(self.rows) > 500 or len(expanded) > 100:
                raise ValueError("OCR table exceeds evidence budget")
        elif tag == "table":
            if self.in_row:
                raise ValueError("Unclosed OCR table row")
            self.depth -= 1


def table_rows(text: str) -> list[list[str]]:
    if "<table" in text.lower():
        parser = _Table()
        parser.feed(text)
        if parser.depth or parser.cell is not None or parser.in_row:
            raise ValueError("Incomplete OCR HTML table")
        return parser.rows
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    if "\t" in lines[0]:
        rows = [[cell.strip() for cell in line.split("\t")] for line in lines]
    elif "|" in lines[0]:
        rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines
                if not re.fullmatch(r"[\s|:\-]+", line)]
    else:
        return []
    return rows if len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows) else []


def table_has_header(text: str) -> bool:
    if "<table" not in text.lower():
        return True  # TSV/Markdown adapters use their first line as the header.
    first = re.search(r"<tr\b[^>]*>(.*?)</tr>", text, re.I | re.S)
    return bool(first and re.search(r"<th\b", first[1], re.I))


def _with_rows(blocks: list[OcrBlock]) -> tuple[OcrBlock, ...]:
    result = []
    for block in blocks:
        result.append(block)
        if block.kind != "table":
            continue
        rows = table_rows(block.text)
        if len(rows) < 2:
            continue
        header = rows[0] if table_has_header(block.text) else None
        for index, row in enumerate(rows[1:] if header else rows, 1):
            if header and len(row) != len(header):
                continue
            result.append(OcrBlock(f"{block.id}r{index}", block.page, "table_row",
                " | ".join(f"{key or 'Cột ' + str(column + 1)}: {value}" for column, (key, value)
                           in enumerate(zip(header, row))) if header else " | ".join(row),
                           None, block.id, "table_structure"))
    # Keep aligned text columns together for readers without vision. No inferred
    # coordinates: every group points back to the actual source blocks.
    clusters = []
    for block in blocks:
        if block.bbox is None or block.kind.rstrip("+") in {"table", *VISUAL_KINDS} or block.bbox[2] - block.bbox[0] > 450:
            continue
        cluster = next((items for items in clusters if abs(items[0].bbox[0] - block.bbox[0]) <= 60), None)
        if cluster is None:
            cluster = []
            clusters.append(cluster)
        cluster.append(block)
    candidates = [items for items in clusters if len(items) >= 2]
    for index, items in enumerate(candidates, 1):
        left = items[0].bbox[0]
        top, bottom = min(item.bbox[1] for item in items), max(item.bbox[3] for item in items)
        peer = any(abs(other[0].bbox[0] - left) >= 250 and
                   min(bottom, max(item.bbox[3] for item in other)) > max(top, min(item.bbox[1] for item in other))
                   for other in candidates if other is not items)
        if peer:
            ordered = sorted(items, key=lambda item: item.bbox[1])
            result.append(OcrBlock(f"p{items[0].page}g{index}", items[0].page, "layout_group",
                "\n".join(item.text for item in ordered), origin="layout_group", source_ids=tuple(item.id for item in ordered)))
    return tuple(result)


def parse_evidence(raw: str, contract: str = "text", page: int = 1) -> tuple[OcrBlock, ...]:
    blocks = []
    if contract == "ovis_json":
        records = json.loads(raw)
        if not isinstance(records, list) or len(records) > 1000:
            raise ValueError("OCR structured response must be a bounded JSON array")
        for item in records:
            if not isinstance(item, dict) or not {"bbox", "category", "content"} <= set(item):
                raise ValueError("Invalid OCR structured block")
            if item["category"] not in OVIS_KINDS or not isinstance(item["content"], str):
                raise ValueError("Invalid OCR block category/content")
            box = _box(item["bbox"])
            if item["content"].strip():
                blocks.append(OcrBlock(f"p{page}b{len(blocks)+1}", page, item["category"], item["content"].strip(), box))
    elif contract == "lighton_grounding":
        markers = list(MARKER.finditer(raw))
        if raw.strip() and (not markers or raw[:markers[0].start()].strip()):
            raise ValueError("OCR grounding response is missing block markers")
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
            text = raw[marker.end():end].strip()
            box = _box(tuple(map(int, marker.groups()[1:])))
            if text:
                blocks.append(OcrBlock(f"p{page}b{len(blocks)+1}", page, marker[1], text, box))
    elif contract == "text":
        # Keep tables together; plain OCR lines have no geometric coordinates.
        pieces = re.split(r"(<table\b[^>]*>.*?</table>)", raw, flags=re.I | re.S)
        chunks = []
        for piece in pieces:
            if re.match(r"\s*<table\b", piece, re.I):
                chunks.append(("table", piece.strip()))
            else:
                pending = []
                for line in piece.splitlines() + [""]:
                    if "\t" in line or "|" in line:
                        pending.append(line)
                        continue
                    if pending:
                        text = "\n".join(pending)
                        chunks.append(("table" if table_rows(text) else "text", text))
                        pending = []
                    if line.strip():
                        chunks.append(("text", line.strip()))
        blocks = [OcrBlock(f"p{page}b{index}", page, kind, text) for index, (kind, text) in enumerate(chunks, 1)]
    else:
        raise ValueError(f"Unsupported OCR output contract: {contract}")
    return _with_rows(blocks)


def document_text(blocks: tuple[OcrBlock, ...]) -> str:
    """Derived rows repeat table headers for retrieval, but are not duplicated in page text."""
    parts = []
    for block in blocks:
        if block.parent_id is not None or block.origin == "layout_group" or block.kind.rstrip("+") in VISUAL_KINDS:
            continue
        text = block.text
        if block.kind == "table":
            rows = table_rows(text)
            if len(rows) >= 2 and table_has_header(text) and all(len(row) == len(rows[0]) for row in rows):
                def line(row):
                    return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"
                text = "\n".join([line(rows[0]), line(["---"] * len(rows[0])), *(line(row) for row in rows[1:])])
        parts.append(text)
    return "\n\n".join(parts)


def native_evidence(source, page_number: int) -> tuple[OcrBlock, ...]:
    import fitz

    with fitz.open(source) as document:
        page = document[page_number - 1]
        result = []
        for entry in page.get_text("blocks", sort=True):
            if entry[6] != 0 or not entry[4].strip():
                continue
            box = tuple(round(value / dimension * 1000, 3) for value, dimension
                        in zip(entry[:4], (page.rect.width, page.rect.height) * 2))
            result.append(OcrBlock(f"p{page_number}b{len(result)+1}", page_number, "text", entry[4].strip(),
                                   tuple(max(0, min(1000, value)) for value in box), origin="native"))
        return tuple(result)
