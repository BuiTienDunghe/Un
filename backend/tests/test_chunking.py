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
