"""read_document: the agent reads past a search's 400-character excerpt (ticket 20 #1).

A search hands each chunk a handle (document_id + chunk_index) and its whole length; in the
same turn read_document opens that document and returns chunks whole, as many as fit its
own cap, with next_from_chunk where the reading goes on. A document the turn's searches did
not show cannot be opened, and that refusal reads the same as an unknown id. No stack: the
backends are fakes and the model is scripted.
"""
from __future__ import annotations

import json

from app.services.agent_service import (
    BAD_ARGUMENTS,
    NOT_READABLE,
    READ_CHUNK_MAX_CHARS,
    TOOL_UNAVAILABLE_HERE,
    AgentService,
)

DOC = "doc_0f9c3a43b649406b9220bbc27dd39562"


def chunk_text(index: int, length: int = 1680) -> str:
    head = f"Đoạn {index}: "
    return head + "x" * (length - len(head))


class Documents:
    """Five chunks of DOC, the last two on page 3; OTHER has no pages."""

    def __init__(self, length: int = 1680):
        pages = [(1, 1), (1, 2), (2, 2), (3, 3), (3, 3)]
        self.chunks = {
            DOC: [{"chunk_index": i, "page_start": start, "page_end": end, "content": chunk_text(i, length)} for i, (start, end) in enumerate(pages)],
            "doc_other": [{"chunk_index": 0, "page_start": None, "page_end": None, "content": "không chia trang"}],
        }
        self.calls: list[tuple] = []

    def _slice(self, document_id, chunks):
        return {"document_id": document_id, "filename": f"{document_id}.pdf", "total_chunks": len(self.chunks[document_id]), "chunks": chunks}

    def read_chunks(self, document_id, from_chunk, n):
        self.calls.append(("read", document_id, from_chunk, n))
        if document_id not in self.chunks:
            return None
        return self._slice(document_id, [c for c in self.chunks[document_id] if c["chunk_index"] >= from_chunk][:n])

    def chunks_on_page(self, document_id, page, n):
        self.calls.append(("page", document_id, page, n))
        if document_id not in self.chunks:
            return None
        covers = [c for c in self.chunks[document_id] if c["page_start"] is not None and c["page_start"] <= page <= (c["page_end"] or c["page_start"])]
        return self._slice(document_id, covers[:n])


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        found = [{"document_id": DOC, "chunk_index": 1, "filename": "quy_che.pdf", "page": 1, "content": chunk_text(1), "score": 0.9}]
        # A hand-written eval fixture carries no document: no handle to read it by.
        found.append({"filename": "viet_tay.txt", "page": None, "content": "ngắn", "score": 0.5})
        return found[:top_k]


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        return "hết lượt", "fake"


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def agent(documents=None, router=None, read_limit=6000) -> AgentService:
    return AgentService(router, Retrieval(), None, document_reader=documents, read_result_max_chars=read_limit)


def read(service: AgentService, arguments: dict, readable=(DOC, "doc_other")) -> tuple[dict, str | None]:
    text, code, _ = service._run_tool("read_document", arguments, {"readable_documents": set(readable)})
    return json.loads(text), code


def test_a_search_gives_each_readable_chunk_a_handle_and_its_whole_length():
    context = {"readable_documents": set()}
    items = json.loads(agent()._run_tool("search_documents", {"query": "nghỉ phép"}, context)[0])

    assert items[0]["document_id"] == DOC and items[0]["chunk_index"] == 1
    assert len(items[0]["excerpt"]) == 400 and items[0]["chars"] == 1680, "the excerpt says it stopped short"
    assert "document_id" not in items[1] and items[1]["chars"] == 4
    assert context["readable_documents"] == {DOC}, "the turn may now open what it was shown"


def test_one_turn_searches_then_reads_the_chunk_whole():
    documents = Documents()
    router = Router([
        call("search_documents", {"query": "nghỉ phép"}),
        call("read_document", {"document_id": DOC, "from_chunk": 1, "n": 1}),
        {"content": "Đã đọc.", "tool_calls": [], "raw_tool_calls": []},
    ])
    answer, _, steps = agent(documents, router).run([{"role": "user", "content": "Quy chế nói gì?"}])

    assert answer == "Đã đọc."
    result = [step for step in steps if step["kind"] == "tool_result"][1]
    assert result["error_code"] is None
    payload = json.loads(result["content"])
    assert payload["chunks"][0]["content"] == chunk_text(1), "whole, not the 400-character excerpt"
    assert payload["next_from_chunk"] == 2 and payload["total_chunks"] == 5


def test_a_document_the_turn_was_not_shown_reads_like_an_unknown_id():
    service = agent(Documents())
    unshown, code = read(service, {"document_id": DOC}, readable=())
    unknown, unknown_code = read(service, {"document_id": "doc_khong_co"}, readable=("doc_khong_co",))

    assert code == unknown_code == BAD_ARGUMENTS
    assert unshown["error"] == unknown["error"] == NOT_READABLE, "no oracle for which ids exist"
    assert service.document_reader.calls == [("read", "doc_khong_co", 0, 2)], "an unshown id never reaches the store"


def test_without_a_reader_the_tool_says_it_is_not_available_here():
    payload, code = read(agent(None), {"document_id": DOC})
    assert code == TOOL_UNAVAILABLE_HERE and "search_documents" in payload["error"]


def test_chunks_fit_the_read_cap_whole_and_point_at_the_first_one_left_out():
    service = agent(Documents(length=READ_CHUNK_MAX_CHARS))
    text, _, _ = service._run_tool("read_document", {"document_id": DOC, "from_chunk": 0, "n": 3}, {"readable_documents": {DOC}})
    payload = json.loads(text)

    assert len(text) <= 6000
    assert [c["chunk_index"] for c in payload["chunks"]] == [0, 1], "two 2 400-character chunks fit 6 000, three do not"
    assert all(len(c["content"]) == READ_CHUNK_MAX_CHARS and not c["content"].endswith("…") for c in payload["chunks"])
    assert payload["next_from_chunk"] == 2


def test_reading_past_the_end_is_a_result_not_an_error():
    payload, code = read(agent(Documents()), {"document_id": DOC, "from_chunk": 9})
    assert code is None and payload == {"result": "đã hết tài liệu", "total_chunks": 5}

    last, _ = read(agent(Documents()), {"document_id": DOC, "from_chunk": 4, "n": 3})
    assert [c["chunk_index"] for c in last["chunks"]] == [4] and last["next_from_chunk"] is None


def test_a_page_wins_over_from_chunk_and_a_pageless_document_says_so():
    documents = Documents()
    payload, _ = read(agent(documents), {"document_id": DOC, "page": 3, "from_chunk": 0, "n": 3})
    assert [c["chunk_index"] for c in payload["chunks"]] == [3, 4]
    assert documents.calls[-1] == ("page", DOC, 3, 3)

    pageless, code = read(agent(Documents()), {"document_id": "doc_other", "page": 2})
    assert code is None and "from_chunk" in pageless["result"]


def test_counts_from_the_model_are_clamped_and_unreadable_ones_fall_back():
    documents = Documents()
    service = agent(documents)
    read(service, {"document_id": DOC, "from_chunk": -4, "n": 10})
    read(service, {"document_id": DOC, "from_chunk": "hai", "n": "ba"})
    assert documents.calls == [("read", DOC, 0, 3), ("read", DOC, 0, 2)]


def test_the_callers_context_is_copied_and_may_allow_a_document_outright():
    # The hook #3 uses for a long paste stored as a temporary document.
    context = {"guild_id": None, "readable_documents": {DOC}}
    router = Router([call("read_document", {"document_id": DOC}), {"content": "xong", "tool_calls": [], "raw_tool_calls": []}])
    _, _, steps = agent(Documents(), router).run([{"role": "user", "content": "đọc giúp"}], context)

    assert [s for s in steps if s["kind"] == "tool_result"][0]["error_code"] is None
    assert context == {"guild_id": None, "readable_documents": {DOC}}, "the caller's dict is not written to"


def test_one_chunk_over_a_small_cap_is_shortened_rather_than_cut_mid_json():
    text, _, _ = agent(Documents(length=READ_CHUNK_MAX_CHARS), read_limit=1000)._run_tool(
        "read_document", {"document_id": DOC, "n": 2}, {"readable_documents": {DOC}})
    payload = json.loads(text)  # valid JSON
    assert len(text) <= 1000 and len(payload["chunks"]) == 1 and payload["chunks"][0]["content"].endswith("…")
    assert payload["next_from_chunk"] == 1


def test_the_model_is_shown_read_document_right_after_search_documents():
    schemas = agent().registry.schemas()
    names = [tool["function"]["name"] for tool in schemas]
    assert names[:2] == ["search_documents", "read_document"]
    assert schemas[1]["function"]["parameters"]["required"] == ["document_id"]
