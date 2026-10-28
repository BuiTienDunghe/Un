"""A long paste becomes a document the agent opens, not text the model carries (ticket 20 #3).

A user message longer than PASTE_THRESHOLD stays whole as the message it is — in
`messages`, deleted with its conversation, never in the document library (option S1). The
model is handed a slip instead: the paste's length, its chunk count, its id, its first and
last SLIP_EDGE_CHARS characters (a question sits at either end; doc-39's is at the end),
and how to open it. read_document reads a paste only from the running turn's
tool_context["pastes"], chunked on the fly by the chunker uploaded documents use. Nothing
is indexed, so no GPU is needed, and a paste opens only in the conversation that holds it
(ticket 20 #1, A2). The same text always gets the same id, so a later turn of the same
conversation reads it again. search_documents ranks the same chunks by the words they share
with the query (search_pastes), on the fly too.

Plain chat has no tool to open a slip: there PASTE_THRESHOLD stays the limit, and a paste
already in the history becomes a one-line note.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from hashlib import sha256
from typing import Any

from app.utils.chunking import chunk_pages

PASTE_THRESHOLD = 10_000  # the old /chat limit: anything up to it travels exactly as before
PASTE_MAX = 100_000  # tool mode's limit (ticket 20 #3, owner's choice via the coordinator)
SLIP_EDGE_CHARS = 600
# The chunker's own defaults, which are models.yaml's rag.chunk_tokens / chunk_overlap_tokens:
# a paste reads in chunks the size of an uploaded document's (median ~1 700 characters).
CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS = 480, 80
# Okapi BM25's usual constants.
BM25_K1, BM25_B = 1.2, 0.75
_WORD = re.compile(r"\w+")


def is_paste(message: dict[str, Any]) -> bool:
    return message.get("role") == "user" and len(str(message.get("content") or "")) > PASTE_THRESHOLD


def paste_id(text: str) -> str:
    return "paste_" + sha256(text.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=8)
def _chunks(text: str) -> tuple[str, ...]:
    return tuple(chunk.content for chunk in chunk_pages([(None, text, "native")], CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS))


def slip(text: str) -> str:
    """What the model reads in place of the paste.

    Ticket 20 #3-B: on #3's slip ("lưu thành tài liệu tạm") doc-39 called search_documents,
    said it had searched the text, and asked the user whether to read on. So this slip never
    calls the paste a document (read_document's document_id parameter aside), says
    search_documents cannot see it, and gives the exact call to make: read_document's own
    description says its id comes from search_documents, and only the slip can say otherwise.
    What the paste is comes first; what to do comes after the tail, next to the question the
    user asked last, because doc-39 quoted the tail and passed over the line above the head.

    Ticket 20 #3-C (owner's choice B): on #3-B's slip the model's first read asked n = the
    chunk count the slip stated (8, 15, 10) on 4 of 5 paste tasks, over the cap of 3, and
    doc-42 read three times with its answer already in the tail
    (kept/agent-eval-v0.5-paste-slip-b/). So the slip says what n read_document accepts and
    that reading on is another call, no longer states the chunk count, and says to answer at
    once when the two edges are enough. Later reads asked n = total_chunks - from_chunk on
    4 of 5, a count the read result itself carries; only the cap sentence speaks to those.

    Ticket 20 #3-D, 3' (owner's choice): reading on from chunk 0, three at a time, cannot
    reach an answer past the third read, so search_documents now finds a paste's chunks
    (search_pastes) and the slip says so in place of "search_documents không tìm thấy nó":
    a search hands back the chunk_index to read straight away. The rest of #3-C's slip
    stands, "không cần search_documents trước" included: reading from chunk 0 still needs
    no search, which is what read_document's own description would otherwise suggest.
    """
    document_id = paste_id(text)
    head, tail = text[:SLIP_EDGE_CHARS].rstrip(), text[-SLIP_EDGE_CHARS:].lstrip()
    # read_document's most chunks a call (agent_service.READ_MAX_CHUNKS, which this module
    # cannot import, agent_service importing it); a test keeps the two equal.
    most = 3
    return (
        f"[Người dùng dán vào tin nhắn này một văn bản dài {len(text)} ký tự. Bạn chỉ thấy phần đầu và "
        f"phần cuối; phần giữa chưa hiện ra.]\n\nĐẦU VĂN BẢN:\n{head}\n\n[… phần giữa chưa thấy …]\n\n"
        f"CUỐI VĂN BẢN:\n{tail}\n\n"
        f"[Văn bản dán nằm trong tin nhắn, không phải tệp đã tải lên. search_documents tìm được trong nó và "
        f"trả chunk_index để đọc thẳng đoạn đó bằng read_document. "
        f"Nếu phần đầu và phần cuối đã đủ để trả lời thì trả lời luôn, không đọc thêm. "
        f"Nếu câu hỏi cần phần chưa thấy, hãy tự đọc trước khi trả lời hay hỏi lại người dùng: gọi thẳng "
        f'read_document(document_id="{document_id}", from_chunk=0, n={most}), không cần search_documents trước. '
        f"read_document chỉ nhận n từ 1 đến {most}, tức mỗi lần đọc tối đa {most} đoạn, và văn bản không có "
        f"trang; muốn đọc tiếp thì gọi lại với from_chunk bằng next_from_chunk trong kết quả, tới khi thấy "
        f"điều cần tìm hoặc next_from_chunk là null.]"
    )


def note(text: str) -> str:
    """What plain chat keeps of a paste in the history: it has no tool to open a slip."""
    return f"[Người dùng đã dán một văn bản dài {len(text)} ký tự; chỉ đọc được ở chế độ công cụ.]"


def take_pastes(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The agent's view: every paste replaced by its slip, and the pastes by id."""
    pastes: dict[str, str] = {}
    shown: list[dict[str, Any]] = []
    for message in messages:
        if is_paste(message):
            text = str(message["content"])
            pastes[paste_id(text)] = text
            shown.append({**message, "content": slip(text)})
        else:
            shown.append(message)
    return shown, pastes


def shorten_pastes(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plain chat's view of a history: every paste replaced by its note."""
    return [{**message, "content": note(str(message["content"]))} if is_paste(message) else message for message in messages]


def search_text(message: str) -> str:
    """What memory search embeds for a message: the message, or a paste's two edges."""
    if len(message) <= PASTE_THRESHOLD:
        return message
    return message[:SLIP_EDGE_CHARS] + "\n" + message[-SLIP_EDGE_CHARS:]


def read_paste(document_id: str, text: str, from_chunk: int, n: int, page: int = 0) -> dict[str, object]:
    """read_document's view of a paste, shaped like a DocumentReader slice. A paste has
    no pages, so reading by page finds nothing."""
    chunks = _chunks(text)
    picked = [] if page else list(enumerate(chunks))[max(0, from_chunk): max(0, from_chunk) + max(1, n)]
    return {
        "document_id": document_id,
        "filename": f"đoạn dán ({len(text)} ký tự)",
        "total_chunks": len(chunks),
        "chunks": [{"chunk_index": index, "page_start": None, "page_end": None, "content": content} for index, content in picked],
    }


def _terms(text: str) -> list[str]:
    # NFC first: a paste copied from macOS can arrive decomposed, and \w+ would cut its
    # vowels at the combining mark, so no word of it would match a composed query.
    return _WORD.findall(unicodedata.normalize("NFC", text).lower())


def search_pastes(pastes: dict[str, str], query: str, top_k: int) -> list[dict[str, object]]:
    """search_documents' view of this turn's pastes (ticket 20 #3-D, 3'): their chunks by
    BM25 against the query, best first, at most top_k, shaped like retrieval chunks.

    Plain Python, no model and no GPU: Vietnamese syllables split on \\w+, no word
    segmentation. A word in half the chunks or more weighs nothing (Robertson's IDF,
    clamped at zero, where Lucene's log(1 + …) stays positive), and a chunk scoring zero is
    left out. `pastes` holds every paste of the conversation, not only the last message's,
    so a chunk sharing only "là" or "của" with a question about the library must not sit
    above the library's results."""
    wanted = set(_terms(query))
    rows = [
        (document_id, len(text), index, content, Counter(_terms(content)))
        for document_id, text in pastes.items()
        for index, content in enumerate(_chunks(text))
    ]
    if not wanted or not rows:
        return []
    count = len(rows)
    average = sum(sum(terms.values()) for *_, terms in rows) / count or 1.0
    weight = {}
    for word in wanted:
        holding = sum(1 for *_, terms in rows if word in terms)
        weight[word] = max(0.0, math.log((count - holding + 0.5) / (holding + 0.5)))
    ranked = []
    for order, (document_id, length, index, content, terms) in enumerate(rows):
        size = sum(terms.values())
        score = sum(
            weight[word] * terms[word] * (BM25_K1 + 1) / (terms[word] + BM25_K1 * (1 - BM25_B + BM25_B * size / average))
            for word in wanted
            if terms[word]
        )
        if score > 0:
            ranked.append((-score, order, document_id, length, index, content))
    ranked.sort()
    return [
        # The name read_paste gives the same paste.
        {"document_id": document_id, "filename": f"đoạn dán ({length} ký tự)", "chunk_index": index, "content": content}
        for _, _, document_id, length, index, content in ranked[: max(1, top_k)]
    ]
