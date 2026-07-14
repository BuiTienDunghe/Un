from app.utils.vi_tokenizer import tokenize_vietnamese


def test_vietnamese_tokenizer_preserves_compound_words():
    tokens = tokenize_vietnamese("Học sinh đang đến trường.")

    assert "học_sinh" in tokens
    assert "học" not in tokens
    assert "sinh" not in tokens
