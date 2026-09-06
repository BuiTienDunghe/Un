from app.utils.chunking import chunk_pages, chunk_text, count_tokens


def test_chunking_preserves_all_content_without_dropping_text():
    text = "First sentence. Second sentence. Final sentence."

    chunks = chunk_text(text, chunk_size=5, chunk_overlap=1)

    assert len(chunks) >= 2
    assert "First sentence" in " ".join(chunks)
    assert "Final sentence" in " ".join(chunks)


def test_chunking_keeps_heading_table_header_and_cross_page_locations():
    # The prose on page 2 is what carries a chunk across the page boundary. That used
    # to be the table's job, which only worked because a paragraph was merged into the
    # table chunk -- the one thing the chunk_pages loop promises not to do.
    chunks = chunk_pages([
        (1, "# Chapter 2\n\nOpening explanation before the table.", "native"),
        (2, "Continued on the next page.\n\n| Column A | Column B |\n| --- | --- |\n| value one | 1 |\n| value two | 2 |", "ocr"),
    ], chunk_tokens=8, overlap_tokens=2)

    assert any(chunk.page_start == 1 and chunk.page_end == 2 for chunk in chunks)
    table_chunks = [chunk for chunk in chunks if chunk.block_type == "table"]
    assert table_chunks
    assert all("| Column A | Column B |" in chunk.content for chunk in table_chunks)
    assert all(count_tokens(chunk.content) >= 1 for chunk in chunks)


def test_a_table_starts_its_own_chunk_and_keeps_the_prose_that_follows():
    # Measured 06/09/2026 on the 82-question gate: isolating every table into its own
    # chunk lost the questions whose answer sits in a table (the backup interval, the
    # GPU model), because a 100-token table shares few words with the question while
    # the sentence explaining it shares many. So the prose *before* a table is flushed
    # and not carried in as overlap, and the prose *after* it may join up to the budget.
    chunks = chunk_pages([
        (1, "Prose before the table.\n\n| A | B |\n| --- | --- |\n| one | 1 |\n\nProse after the table.", "native"),
    ], chunk_tokens=200, overlap_tokens=20)

    assert len(chunks) == 2
    assert chunks[0].content.startswith("Prose before")
    table_chunk = chunks[1]
    assert "| one | 1 |" in table_chunk.content
    assert "Prose before" not in table_chunk.content
    assert "Prose after" in table_chunk.content


def test_chunks_never_exceed_the_token_budget():
    body = " ".join(f"Sentence number {n} carries a little filler text." for n in range(400))

    chunks = chunk_pages([(None, body, "native")], 480, 80)

    assert len(chunks) > 1
    assert [chunk for chunk in chunks if count_tokens(chunk.content) > 480] == []


def test_a_sentence_longer_than_the_budget_is_sliced_not_emitted_whole():
    """A run with no sentence boundary still has to respect chunk_tokens."""
    body = "Intro sentence. " + " ".join(f"item{n}" for n in range(900))

    chunks = chunk_pages([(None, body, "native")], 480, 80)

    assert max(count_tokens(chunk.content) for chunk in chunks) <= 480


def test_overlap_carries_tokens_not_whole_blocks():
    """Regression: a chunk must never be a superset of the one before it.

    _overlap_blocks used to carry each trailing block whole, so a 300-token block
    became the "80-token" overlap and the next chunk re-emitted all of it.
    """
    body = "\n\n".join(" ".join(f"para{p}word{w}" for w in range(300)) for p in range(4))

    contents = [chunk.content for chunk in chunk_pages([(None, body, "native")], 480, 80)]

    assert len(contents) > 2
    for earlier, later in zip(contents, contents[1:]):
        assert earlier not in later
        assert later not in earlier


def test_overlap_repeats_only_the_tail_of_the_previous_chunk():
    body = "\n\n".join(" ".join(f"p{p}w{w}" for w in range(300)) for p in range(3))

    contents = [chunk.content for chunk in chunk_pages([(None, body, "native")], 480, 80)]

    shared = set(contents[0].split()) & set(contents[1].split())
    assert shared, "consecutive chunks should still share an overlap"
    assert len(shared) <= 80

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


def test_numbered_clauses_are_body_not_headings():
    """A Vietnamese legal article must survive chunking.

    Its every line is a numbered clause, and the numbered-heading branch used to
    match all of them: no body text was left, chunk_pages returned nothing, and
    the document was rejected as "containing no readable text" while being
    entirely readable. Measured on 2 947 documents of Zalo Legal 2021, that took
    out 32.6% of the corpus and 37% of its judged-relevant documents.
    """
    article = (
        "# Điều 2. Đối tượng áp dụng\n"
        "\n"
        "1. Đấu giá viên, tổ chức đấu giá tài sản, Hội đồng đấu giá tài sản.\n"
        "2. Tổ chức mà Nhà nước sở hữu 100% vốn điều lệ do Chính phủ thành lập.\n"
        "3. Người có tài sản đấu giá, người tham gia đấu giá, người trúng đấu giá.\n"
    )
    chunks = chunk_pages([(None, article, "text")], 480, 80)
    assert chunks, "an article of numbered clauses produced no chunks"
    body = " ".join(chunk.content for chunk in chunks)
    assert "Đấu giá viên" in body
    assert "Chính phủ thành lập" in body
    # The `#` line is still a heading; the clauses beneath it are not.
    assert chunks[0].heading_path == ("Điều 2. Đối tượng áp dụng",)


def test_short_numbered_titles_are_still_headings():
    """The rule the change had to preserve.

    "1. Introduction" is a heading and must stay one. What separates it from a
    legal clause is the sentence-ending punctuation, not the number, and the
    change must not sweep real numbered headings into the body.

    Asserted on the matcher rather than on heading_path, because numbered
    headings have never reached heading_path — their title is dropped from the
    body without being recorded anywhere. That is a separate, pre-existing gap,
    unchanged by this commit and verified identical before and after it.
    """
    from app.utils.chunking import _heading_match

    assert _heading_match("1. Introduction")
    assert _heading_match("2.1 Setup")
    assert _heading_match("### Markdown heading")
    # A clause: a full sentence carrying a number.
    assert _heading_match("1. Thông tư này có hiệu lực thi hành từ ngày 02 tháng 3 năm 2015.") is None
    assert _heading_match("2. Bãi bỏ Quyết định số 62/2006/QĐ-NHNN;") is None

    document = "1. Introduction\n\nSome prose under the first heading that is long enough to be a chunk.\n"
    chunks = chunk_pages([(None, document, "text")], 480, 80)
    assert chunks
    body = " ".join(chunk.content for chunk in chunks)
    assert "Some prose" in body
    assert "1. Introduction" not in body, "a real numbered heading should not stay in the body"


def test_overlap_locations_still_contain_the_text_they_label():
    # A paragraph over the budget is split into fragments, and every fragment
    # inherits the whole paragraph's start/end while carrying a slice of its text.
    # Scaling that span by the tail's share of the fragment pointed the overlap
    # block at a different passage — 14.5% of chunks on the legal corpus. The
    # tail only survives when the next blocks are short enough to sit beside it,
    # so a long paragraph followed by short ones is the shape that exposes it.
    long_paragraph = "\n".join(f"dòng {i} của điều khoản thứ nhất, viết dài để vượt ngân sách một mảnh." for i in range(40))
    short_paragraphs = "\n\n".join(f"Mục {i} ngắn." for i in range(12))
    body = "# T\n\n" + long_paragraph + "\n\n" + short_paragraphs + "\n"
    chunks = chunk_pages([(None, body, "text")], 480, 80)
    assert len(chunks) > 1
    squash = lambda s: "".join(ch for ch in s if not ch.isspace())
    for chunk in chunks:
        for block_text, location in zip(chunk.content.split("\n\n"), chunk.locations):
            claimed = squash(body[location.start:location.end])
            assert squash(block_text)[:60] in claimed, (location, block_text[:60])
