from app.utils.chunking import chunk_pages, chunk_text, count_tokens


def test_chunking_preserves_all_content_without_dropping_text():
    text = "First sentence. Second sentence. Final sentence."

    chunks = chunk_text(text, chunk_size=5, chunk_overlap=1)

    assert len(chunks) >= 2
    assert "First sentence" in " ".join(chunks)
    assert "Final sentence" in " ".join(chunks)


def test_chunking_keeps_heading_table_header_and_cross_page_locations():
    chunks = chunk_pages([
        (1, "# Chapter 2\n\nOpening explanation before the table.", "native"),
        (2, "| Column A | Column B |\n| --- | --- |\n| value one | 1 |\n| value two | 2 |", "ocr"),
    ], chunk_tokens=8, overlap_tokens=2)

    assert any(chunk.page_start == 1 and chunk.page_end == 2 for chunk in chunks)
    table_chunks = [chunk for chunk in chunks if chunk.block_type == "table"]
    assert table_chunks
    assert all("| Column A | Column B |" in chunk.content for chunk in table_chunks)
    assert all(count_tokens(chunk.content) >= 1 for chunk in chunks)


def test_chunk_metadata_heading_parts_and_token_count_t15():
    """T15: the chunker exposes heading parts as a tuple plus its own token count."""
    chunks = chunk_pages([
        (1, "# Guide\n\n## Setup\n\nInstall the tool before anything else.", "native"),
    ], chunk_tokens=50, overlap_tokens=5)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.heading_path == ("Guide", "Setup")
    assert chunk.section_title == "Setup"
    assert chunk.token_count == count_tokens(chunk.content)
    assert chunk.locations and chunk.locations[0].page == 1


def test_chunk_metadata_without_headings_stays_none():
    chunks = chunk_pages([(None, "A single paragraph with no heading at all.", "native")], 50, 5)

    assert len(chunks) == 1
    assert chunks[0].heading_path is None
    assert chunks[0].section_title is None
    assert chunks[0].token_count == count_tokens(chunks[0].content)
