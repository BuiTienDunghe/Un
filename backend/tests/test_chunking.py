from app.utils.chunking import chunk_text


def test_chunking_preserves_all_content_without_cutting_short_text():
    text = "Đây là đoạn đầu. Đây là đoạn thứ hai. Đây là đoạn cuối."

    chunks = chunk_text(text, chunk_size=40, chunk_overlap=10)

    assert len(chunks) >= 2
    assert "đoạn đầu" in " ".join(chunks)
    assert "đoạn cuối" in " ".join(chunks)
