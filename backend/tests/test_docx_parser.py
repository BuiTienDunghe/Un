"""T17: the .docx reader must hand the chunker what the chunker looks for.

Fixtures are built with python-docx rather than committed as binaries: the
repository is public, and a generated document states the structure under test
in the test itself.
"""
from pathlib import Path

from docx import Document
from docx.oxml import parse_xml

from app.parsers.docx_parser import DocxParser
from app.utils.chunking import chunk_pages


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'


def _build(path: Path) -> Path:
    document = Document()
    document.add_heading("Guide", level=1)
    document.add_paragraph("Opening paragraph of the guide body.")
    document.add_heading("Setup", level=2)
    document.add_paragraph("Install the tool before anything else.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Model"
    table.cell(0, 1).text = "BLEU"
    table.cell(1, 0).text = "Transformer"
    table.cell(1, 1).text = "41.8"
    document.add_paragraph("Closing paragraph after the table.")
    document.save(path)
    return path


def test_docx_keeps_document_order_headings_and_tables(tmp_path: Path):
    text = DocxParser().parse(_build(tmp_path / "doc.docx"))[0][1]

    # Heading styles become the "#" markers chunking._HEADING_PATTERN needs.
    assert "# Guide" in text and "## Setup" in text
    # The table survives at all -- document.paragraphs alone dropped it.
    assert "| Model | BLEU |" in text and "| Transformer | 41.8 |" in text
    # And it is a markdown table, so chunking._table_blocks can repeat the header.
    assert "| --- | --- |" in text
    # Document order: the table sits between its two surrounding paragraphs.
    assert text.index("Install the tool") < text.index("| Model") < text.index("Closing paragraph")


def test_docx_chunks_carry_heading_path_and_table_block_type(tmp_path: Path):
    pages = DocxParser().parse(_build(tmp_path / "doc.docx"))
    # Small budget, no overlap: _make_chunk only labels a chunk whose blocks all
    # share one heading path, and overlap would carry the preceding paragraph
    # into the table chunk and make it "mixed".
    chunks = chunk_pages([(page, body, "native") for page, body in pages], 12, 0)

    assert any(chunk.heading_path == ("Guide", "Setup") for chunk in chunks)
    table = [chunk for chunk in chunks if chunk.block_type == "table"]
    assert len(table) == 1 and "| Transformer | 41.8 |" in table[0].content
    assert table[0].heading_path == ("Guide", "Setup")
    # A .docx has no fixed pagination and Word writes no page break here.
    assert all(chunk.page_start is None for chunk in chunks)


def test_docx_cell_text_cannot_forge_a_column_or_end_the_table(tmp_path: Path):
    path = tmp_path / "pipe.docx"
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Header"
    table.cell(0, 1).text = "Other"
    table.cell(1, 0).text = "a | b"          # a literal pipe
    table.cell(1, 1).text = "line1\nline2"   # a newline inside the cell
    document.save(path)

    text = DocxParser().parse(path)[0][1]

    assert r"a \| b" in text
    assert "| line1 line2 |" in text
    assert all(line.startswith("|") for line in text.splitlines() if line.strip())


def test_docx_textbox_is_read_once_not_twice(tmp_path: Path):
    """Word stores a shape twice: mc:Choice and a legacy mc:Fallback copy."""
    path = tmp_path / "textbox.docx"
    document = Document()
    paragraph = document.add_paragraph("Body paragraph.")
    boxed = (
        f'<w:r {W} {MC}><mc:AlternateContent>'
        f'<mc:Choice Requires="wps"><w:txbxContent><w:p><w:r><w:t>BOXED SUMMARY</w:t></w:r></w:p></w:txbxContent></mc:Choice>'
        f'<mc:Fallback><w:txbxContent><w:p><w:r><w:t>BOXED SUMMARY</w:t></w:r></w:p></w:txbxContent></mc:Fallback>'
        f'</mc:AlternateContent></w:r>'
    )
    paragraph._p.append(parse_xml(boxed))
    document.save(path)

    text = DocxParser().parse(path)[0][1]

    assert text.count("BOXED SUMMARY") == 1
    assert "Body paragraph." in text


# ── automatic numbering and equations (29/09/2026) ────────────────────────────
# Word keeps a list number in numbering.xml, not in the paragraph, and an equation
# in m:oMath, which python-docx's Paragraph.text does not read. Both vanished: a
# Vietnamese legal .docx lost every "Điều 1." / "1." / "a)" it numbered
# automatically — the words citations are made of — and a formula line kept only
# its label. Measured on a generated document before this change.

M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def _legal_numbering(document) -> int:
    """A three-level list shaped like a Vietnamese law: Điều 1. / 1. / a)."""
    numbering = document.part.numbering_part.element
    levels = (("decimal", "Điều %1."), ("decimal", "%2."), ("lowerLetter", "%3)"))
    abstract = parse_xml(
        f'<w:abstractNum {W} w:abstractNumId="90">'
        + "".join(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/></w:lvl>'
                  for i, (fmt, text) in enumerate(levels))
        + "</w:abstractNum>")
    first_num = numbering.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num")
    if first_num is not None:
        first_num.addprevious(abstract)                # schema order: every abstractNum before any num
    else:
        numbering.append(abstract)
    numbering.append(parse_xml(f'<w:num {W} w:numId="90"><w:abstractNumId w:val="90"/></w:num>'))
    return 90


def _numbered(paragraph, num_id: int, level: int):
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = level
    num_pr.get_or_add_numId().val = num_id
    return paragraph


def test_docx_writes_out_automatic_numbers_and_list_items_do_not_become_headings(tmp_path: Path):
    path = tmp_path / "list.docx"
    document = Document()
    document.add_heading("Hồ sơ đề nghị", level=1)
    document.add_paragraph("Hồ sơ gồm các giấy tờ sau:")
    for item in ("Đơn đề nghị theo mẫu", "Bản sao giấy tờ tùy thân", "Hai ảnh 4x6"):
        document.add_paragraph(item, style="List Number")
    document.add_paragraph("Nộp tại bộ phận một cửa", style="List Bullet")
    document.add_paragraph("Thời hạn giải quyết là mười ngày làm việc.")
    document.save(path)

    pages = DocxParser().parse(path)
    text = pages[0][1]

    assert "- 1. Đơn đề nghị theo mẫu" in text
    assert "- 2. Bản sao giấy tờ tùy thân" in text and "- 3. Hai ảnh 4x6" in text
    assert "- Nộp tại bộ phận một cửa" in text
    # "1. Đơn đề nghị theo mẫu" alone matches chunking._HEADING_PATTERN (a numbered
    # line without closing punctuation is a heading there); the "- " keeps a list
    # item a list item, so the heading path stays the real one.
    chunks = chunk_pages([(page, body, "native") for page, body in pages], 480, 0)
    assert {chunk.heading_path for chunk in chunks} == {("Hồ sơ đề nghị",)}


def test_docx_multilevel_numbering_counts_restarts_and_formats_each_level(tmp_path: Path):
    path = tmp_path / "law.docx"
    document = Document()
    num_id = _legal_numbering(document)
    for level, body in ((0, "Phạm vi điều chỉnh"),
                        (1, "Luật này quy định về dữ liệu cá nhân."),
                        (2, "cơ quan nhà nước;"),
                        (2, "tổ chức, cá nhân."),
                        (1, "Luật này không áp dụng cho dữ liệu đã công khai."),
                        (0, "Đối tượng áp dụng"),
                        (1, "Cơ quan, tổ chức, cá nhân Việt Nam.")):
        _numbered(document.add_paragraph(body), num_id, level)
    _numbered(document.add_heading("Hiệu lực thi hành", level=2), num_id, 0)
    document.save(path)

    lines = [line for line in DocxParser().parse(path)[0][1].splitlines() if line.strip()]

    assert lines == [
        "- Điều 1. Phạm vi điều chỉnh",
        "- 1. Luật này quy định về dữ liệu cá nhân.",
        "- a) cơ quan nhà nước;",
        "- b) tổ chức, cá nhân.",
        "- 2. Luật này không áp dụng cho dữ liệu đã công khai.",
        "- Điều 2. Đối tượng áp dụng",
        "- 1. Cơ quan, tổ chức, cá nhân Việt Nam.",      # a new Điều restarts its clauses
        "## Điều 3. Hiệu lực thi hành",                    # a heading keeps its # and gains its number
    ]


def test_docx_numbered_paragraph_in_a_merged_cell_is_counted_once(tmp_path: Path):
    """row.cells hands a merged cell back once per column it spans."""
    path = tmp_path / "merged.docx"
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Cột A", "Cột B"
    merged = table.cell(1, 0).merge(table.cell(1, 1))
    merged.paragraphs[0].text = "Mục trong ô gộp"
    merged.paragraphs[0].style = document.styles["List Number"]
    document.add_paragraph("Mục sau bảng", style="List Number")
    document.save(path)

    text = DocxParser().parse(path)[0][1]

    assert "- 1. Mục trong ô gộp" in text and "- 2. Mục sau bảng" in text


def test_docx_reads_equations_in_place(tmp_path: Path):
    path = tmp_path / "math.docx"
    document = Document()
    inline = document.add_paragraph("Công thức tính phí: ")
    inline._p.append(parse_xml(f'<m:oMath {M}><m:r><m:t>P=a×n+b</m:t></m:r></m:oMath>'))
    inline.add_run(" (đồng).")
    display = document.add_paragraph()
    display._p.append(parse_xml(
        f'<m:oMathPara {M}><m:oMath>'
        '<m:f><m:num><m:r><m:t>a+b</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f>'
        '<m:r><m:t>+</m:t></m:r>'
        '<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>'
        '</m:oMath></m:oMathPara>'))
    document.save(path)

    text = DocxParser().parse(path)[0][1]

    assert "Công thức tính phí: P=a×n+b (đồng)." in text
    assert "(a+b)/2+x^2" in text
