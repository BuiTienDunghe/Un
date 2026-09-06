from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable


_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$|^(?P<number>\d+(?:\.\d+){0,5})[.)]?\s+(?P<number_title>.+?)\s*$")
# A heading is a label; a clause is a sentence. The numbered branch above exists
# for "1. Introduction" and "2.1 Setup", but it also matches "1. Thông tư này có
# hiệu lực..." — and Vietnamese legal texts are written entirely as numbered
# clauses, so every line became a heading, no body survived, and the document was
# rejected with "Document contains no readable text" while being perfectly
# readable. Measured on 2 947 documents of Zalo Legal 2021: 32.6% of the corpus
# produced no chunks at all, taking 37% of the judged-relevant documents with it.
# Ending punctuation is what separates the two, and it carries the whole effect:
# adding a length cap changed nothing (0.6% either way), so there is no fitted
# threshold here. See .scratch/chunker-numbered-clause/spec.md.
_SENTENCE_ENDINGS = (".", ";", ":", "!", "?")


def _heading_match(line: str) -> re.Match[str] | None:
    match = _HEADING_PATTERN.match(line)
    if match and match.group("number") and not match.group("hashes"):
        title = (match.group("number_title") or "").strip()
        if title.endswith(_SENTENCE_ENDINGS):
            return None
    return match
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class ChunkLocation:
    page: int | None
    start: int
    end: int


@dataclass(frozen=True)
class DocumentChunk:
    content: str
    page_start: int | None
    page_end: int | None
    locations: tuple[ChunkLocation, ...]
    # T15: ordered heading parts ("A", "B"), matching the JSONB list[str]
    # column. Display surfaces join with " > "; never store the joined form.
    heading_path: tuple[str, ...] | None
    section_title: str | None
    block_type: str
    extraction_method: str
    # P4-2: generated situating context. Only the retrieval indexes (embedding
    # input and BM25 tokens) see it; `content` stays the citation text.
    retrieval_context: str | None = None
    # T15: size of `content` alone (not retrieval_context) in count_tokens
    # units — the same budget unit chunk_tokens is expressed in.
    token_count: int | None = None


def combined_retrieval_text(retrieval_context: str | None, content: str) -> str:
    """The text a retrieval index represents a chunk by (context + content).

    Contextual retrieval only works when BOTH the embedding and BM25 see the
    same prefixed text, so every index-side call sites this one helper.
    """
    return f"{retrieval_context}\n\n{content}" if retrieval_context else content


@dataclass(frozen=True)
class _Block:
    text: str
    page: int | None
    start: int
    end: int
    heading_path: tuple[str, ...]
    block_type: str
    extraction_method: str


def count_tokens(text: str) -> int:
    """Count tokenizer-like units without depending on a remote model at indexing time.

    This Unicode-aware fallback deliberately counts words, punctuation and formula symbols
    independently. It is configurable and deterministic; benchmark it against the selected
    embedding model before changing production limits.
    """
    return len(_TOKEN_PATTERN.findall(text))


def chunk_pages(
    pages: Iterable[tuple[int | None, str, str]],
    chunk_tokens: int = 480,
    overlap_tokens: int = 80,
) -> list[DocumentChunk]:
    """Create semantic, token-budgeted chunks across page boundaries.

    Order is heading -> paragraph/table/formula -> sentence -> token fallback. Page data is
    retained as locations rather than used as a hard chunk boundary.
    """
    if chunk_tokens < 1:
        raise ValueError("chunk_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than chunk_tokens")
    blocks = _blocks_from_pages(pages, chunk_tokens)
    result: list[DocumentChunk] = []
    current: list[_Block] = []

    def emit() -> None:
        nonlocal current
        if current:
            result.append(_make_chunk(current))
            current = _overlap_blocks(current, overlap_tokens)

    for block in blocks:
        for fragment in _fit_block(block, chunk_tokens):
            # Tables are retrieval units of their own: never merge a neighbouring
            # paragraph into a table chunk, and never use table rows as overlap.
            if fragment.block_type == "table" and current:
                # Flush the prose before a table and drop the carried overlap: a
                # prose tail glued to a table is a chunk of two unrelated things,
                # and carried past a large table it was emitted alone as an
                # 80-token sliver. The table itself stays in the accumulator so
                # the prose that follows it — usually the sentence explaining it —
                # can join, which is what lets a question find a value in a table.
                emit()
                current = []
            if current and count_tokens(_join_blocks(current + [fragment])) > chunk_tokens:
                emit()
                # Carried overlap never justifies an over-budget chunk: give it up
                # oldest-first until the incoming fragment fits beside it.
                while current and count_tokens(_join_blocks(current + [fragment])) > chunk_tokens:
                    current.pop(0)
            current.append(fragment)
    if current:
        result.append(_make_chunk(current))
    return result


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Compatibility wrapper for callers that only need text chunks.

    ``chunk_size`` and ``chunk_overlap`` now mean token budgets, not character counts.
    """
    return [chunk.content for chunk in chunk_pages([(None, text, "native")], chunk_size, chunk_overlap)]


def normalize_chunk(chunk: DocumentChunk | tuple[str, int | None, str]) -> DocumentChunk:
    """Convert legacy (content, page, extraction_method) tuples during migration/tests."""
    if isinstance(chunk, DocumentChunk):
        return chunk
    content, page, extraction_method = chunk
    return DocumentChunk(content, page, page, (ChunkLocation(page, 0, len(content)),), None, None, "paragraph", extraction_method, token_count=count_tokens(content))


def _blocks_from_pages(pages: Iterable[tuple[int | None, str, str]], table_token_limit: int) -> list[_Block]:
    blocks: list[_Block] = []
    headings: list[str] = []
    for page, text, extraction_method in pages:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
        position = 0
        paragraph: list[tuple[str, int, int]] = []
        table: list[tuple[str, int, int]] = []

        def flush_paragraph() -> None:
            nonlocal paragraph
            if paragraph:
                body = " ".join(line.strip() for line, _, _ in paragraph).strip()
                if body:
                    blocks.append(_Block(body, page, paragraph[0][1], paragraph[-1][2], tuple(headings), _block_type(body), extraction_method))
            paragraph = []

        def flush_table() -> None:
            nonlocal table
            if table:
                table_text = "\n".join(line.strip() for line, _, _ in table)
                blocks.extend(_table_blocks(table_text, page, table[0][1], table[-1][2], tuple(headings), extraction_method, table_token_limit))
            table = []

        for raw_line in lines:
            line_start, position = position, position + len(raw_line)
            line = raw_line.strip()
            if not line:
                flush_paragraph(); flush_table()
                continue
            heading = _heading_match(line)
            if heading:
                flush_paragraph(); flush_table()
                level = len(heading.group("hashes") or "") or len((heading.group("number") or "").split("."))
                title = (heading.group("title") or heading.group("number_title") or line).strip()
                headings[level - 1:] = [title]
                continue
            if _is_table_line(line):
                flush_paragraph()
                table.append((raw_line, line_start, position))
            else:
                flush_table()
                paragraph.append((raw_line, line_start, position))
        flush_paragraph(); flush_table()
    return blocks


def _is_table_line(line: str) -> bool:
    return line.startswith("|") and line.count("|") >= 2


def _table_blocks(text: str, page: int | None, start: int, end: int, headings: tuple[str, ...], extraction_method: str, token_limit: int) -> list[_Block]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return [_Block(text, page, start, end, headings, "table", extraction_method)]
    header = lines[:2] if re.fullmatch(r"\s*\|?\s*:?-{3,}.*", lines[1]) else lines[:1]
    rows = lines[len(header):]
    groups: list[list[str]] = []
    current = list(header)
    for row in rows:
        if len(current) > len(header) and count_tokens("\n".join(current + [row])) > token_limit:
            groups.append(current)
            current = list(header)
        current.append(row)
    if current:
        groups.append(current)
    return [_Block("\n".join(group), page, start, end, headings, "table", extraction_method) for group in groups]


def _fit_block(block: _Block, limit: int) -> list[_Block]:
    if count_tokens(block.text) <= limit or block.block_type == "table":
        return [block]
    pieces: list[str] = []
    for sentence in (part.strip() for part in _SENTENCE_PATTERN.split(block.text)):
        if not sentence:
            continue
        # A sentence past the whole budget has no boundary left to split on, so it
        # falls back to token slices. Without this it was emitted whole, which is
        # where chunks several times over the limit came from.
        pieces.extend(_token_slices(sentence, limit) if count_tokens(sentence) > limit else [sentence])
    fragments: list[_Block] = []
    current = ""
    for sentence in pieces:
        candidate = f"{current} {sentence}".strip()
        if current and count_tokens(candidate) > limit:
            fragments.append(_Block(current, block.page, block.start, block.end, block.heading_path, block.block_type, block.extraction_method))
            current = sentence
        else:
            current = candidate
    if current:
        fragments.append(_Block(current, block.page, block.start, block.end, block.heading_path, block.block_type, block.extraction_method))
    return fragments


def _token_slices(text: str, limit: int) -> list[str]:
    tokens = list(_TOKEN_PATTERN.finditer(text))
    if not tokens:
        return []
    slices: list[str] = []
    for index in range(0, len(tokens), limit):
        start = tokens[index].start()
        end = tokens[min(index + limit, len(tokens)) - 1].end()
        slices.append(text[start:end].strip())
    return slices


def _overlap_blocks(blocks: list[_Block], overlap_tokens: int) -> list[_Block]:
    """The trailing ``overlap_tokens`` of a flushed chunk, prefixing the next one.

    Overlap is measured in tokens, not whole blocks: a block longer than the
    remaining budget is carried as its trailing tokens only. Carrying such a
    block whole is what used to make the next chunk a superset of the one just
    emitted, and pushed it past ``chunk_tokens``.
    """
    if not overlap_tokens:
        return []
    result: list[_Block] = []
    total = 0
    for block in reversed(blocks):
        if block.block_type == "table":
            break
        size = count_tokens(block.text)
        if total + size > overlap_tokens:
            tail = _tail_tokens(block.text, overlap_tokens - total)
            if tail:
                result.insert(0, _trim_to_tail(block, tail))
            break
        result.insert(0, block)
        total += size
        if total >= overlap_tokens:
            break
    return result


def _tail_tokens(text: str, limit: int) -> str:
    """The trailing ``limit`` tokens of ``text``, cut on a token boundary."""
    if limit <= 0:
        return ""
    tokens = list(_TOKEN_PATTERN.finditer(text))
    if len(tokens) <= limit:
        return text
    return text[tokens[-limit].start():].strip()


def _trim_to_tail(block: _Block, tail: str) -> _Block:
    """``block`` reduced to its trailing ``tail``, keeping the block's own span.

    The span is deliberately left too wide. ``start``/``end`` index the raw page
    text, while ``text`` is the whitespace-joined paragraph, so the two are in
    different coordinate systems and no proportion between them is meaningful.
    A span that is too wide still contains the text it labels; a proportioned one
    pointed 14.5% of chunks at a different passage entirely.
    """
    return replace(block, text=tail)


def _make_chunk(blocks: list[_Block]) -> DocumentChunk:
    locations = tuple(ChunkLocation(block.page, block.start, block.end) for block in blocks)
    pages = [location.page for location in locations if location.page is not None]
    paths = {block.heading_path for block in blocks}
    types = {block.block_type for block in blocks}
    methods = {block.extraction_method for block in blocks}
    heading_path = blocks[-1].heading_path if len(paths) == 1 and blocks[-1].heading_path else None
    content = _join_blocks(blocks)
    return DocumentChunk(
        content=content,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        locations=locations,
        heading_path=heading_path,
        section_title=heading_path[-1] if heading_path else None,
        block_type=next(iter(types)) if len(types) == 1 else "mixed",
        extraction_method=next(iter(methods)) if len(methods) == 1 else "mixed",
        token_count=count_tokens(content),
    )


def _join_blocks(blocks: Iterable[_Block]) -> str:
    return "\n\n".join(block.text for block in blocks).strip()


def _block_type(text: str) -> str:
    if re.search(r"(?:\$[^$]+\$|\\\[|\\begin\{|[=∑∫√≤≥])", text):
        return "formula"
    return "paragraph"
