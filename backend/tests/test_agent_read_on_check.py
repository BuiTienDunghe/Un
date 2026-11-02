"""The read-on check: a turn that found the document, saw part of it and said the fact is not
there goes back once to read on. Off by default. No model, no GPU."""
from __future__ import annotations

import json

import pytest

from app.services.agent_service import (
    READ_ON_CHECK_STEP,
    READ_ON_GAVE_UP,
    READ_ON_RETRY,
    AgentService,
    _documents_left_unread,
)
from app.services.call_budget import agent_call_cap

GAVE_UP = "Trong các đoạn trích tôi chưa thấy số tiền. Bạn có muốn tôi đọc toàn văn không?"
FOUND = "Hội phí do ban chấp hành quyết định."


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments}],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(message) for message in messages])
        return "hết lượt", "fake"


class Retrieval:
    def __init__(self, hits=True):
        self.hits = hits

    def retrieve(self, query, top_k, document_id=None):
        if not self.hits:
            return []
        return [{"filename": "dieu_le.txt", "page": None, "content": "Đoạn đầu của điều lệ.", "score": 0.9, "chunk_id": "doc-1#0", "document_id": "doc-1", "chunk_index": 0}]


class Reader:
    def read_chunks(self, document_id, from_chunk, n):
        chunks = [{"chunk_index": i, "page_start": None, "page_end": None, "content": f"Đoạn {i}."} for i in range(from_chunk, min(from_chunk + n, 2))]
        return {"document_id": document_id, "filename": "dieu_le.txt", "total_chunks": 2, "chunks": chunks}


def run(rounds, check=True, retrieval=None):
    router = Router(rounds)
    agent = AgentService(router, retrieval or Retrieval(), None, document_reader=Reader(), read_on_check=check)
    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": "Hội phí bao nhiêu?"}])
    return answer, steps, router


SEARCH = call("search_documents", {"query": "hội phí"})


def test_it_is_off_by_default():
    answer, steps, router = run([SEARCH, final(GAVE_UP)], check=False)
    assert answer == GAVE_UP and len(router.prompts) == 2
    assert READ_ON_CHECK_STEP not in [s["kind"] for s in steps]


def test_stopping_at_the_excerpts_goes_back_once_and_the_rejected_answer_reaches_no_one():
    answer, steps, router = run([SEARCH, final(GAVE_UP), call("read_document", {"document_id": "doc-1", "from_chunk": 0, "n": 2}), final(FOUND)])
    assert answer == FOUND
    assert READ_ON_CHECK_STEP in [s["kind"] for s in steps]
    assert router.prompts[2][-1] == {"role": "system", "content": READ_ON_RETRY}
    check_step = next(s for s in steps if s["kind"] == READ_ON_CHECK_STEP)
    assert check_step["content"] is None


def test_it_goes_back_only_once():
    answer, steps, _ = run([SEARCH, final(GAVE_UP), final(GAVE_UP)])
    assert answer == GAVE_UP
    assert [s["kind"] for s in steps].count(READ_ON_CHECK_STEP) == 1


def test_a_document_read_to_its_end_may_truly_not_have_it():
    answer, steps, router = run([SEARCH, call("read_document", {"document_id": "doc-1", "from_chunk": 0, "n": 2}), final(GAVE_UP)])
    assert answer == GAVE_UP and len(router.prompts) == 3
    assert READ_ON_CHECK_STEP not in [s["kind"] for s in steps]


def test_a_search_that_found_nothing_has_nothing_to_read_on():
    answer, steps, _ = run([SEARCH, final(GAVE_UP)], retrieval=Retrieval(hits=False))
    assert answer == GAVE_UP
    assert READ_ON_CHECK_STEP not in [s["kind"] for s in steps]


def test_an_answer_that_found_it_is_left_alone():
    answer, steps, router = run([SEARCH, final(FOUND)])
    assert answer == FOUND and len(router.prompts) == 2
    assert READ_ON_CHECK_STEP not in [s["kind"] for s in steps]


def test_no_document_tool_called_is_the_lookup_checks_business():
    answer, steps, _ = run([final(GAVE_UP)])
    assert answer == GAVE_UP
    assert READ_ON_CHECK_STEP not in [s["kind"] for s in steps]


@pytest.mark.parametrize("text", [
    "trong các đoạn trích xuất hiện, tôi chưa thấy thông tin cụ thể",
    "các đoạn tìm được chưa nêu cụ thể số tiền thuê",
    "Bạn có muốn tôi đọc toàn văn",
    "tôi cần đọc thêm nội dung chi tiết",
    "Tài liệu không ghi thời hạn giao",
])
def test_what_counts_as_stopping(text):
    assert READ_ON_GAVE_UP.search(text)


@pytest.mark.parametrize("text", [FOUND, "Không khí trong xưởng phải thông thoáng.", "Đơn giá thấp nhất là 41.800 đồng."])
def test_what_does_not(text):
    assert not READ_ON_GAVE_UP.search(text)


def test_only_the_latest_read_of_a_document_counts():
    read = lambda following: {"role": "tool", "content": json.dumps({"document_id": "d", "next_from_chunk": following})}
    assert _documents_left_unread([read(None), read(3)], {"d"}) is True
    assert _documents_left_unread([read(3), read(None)], {"d"}) is False
    assert _documents_left_unread([{"role": "tool", "content": "không phải JSON"}], {"d"}) is True
    assert _documents_left_unread([], set()) is False


def test_the_cap_grows_by_one():
    assert agent_call_cap(3, read_on_check=True) == agent_call_cap(3) + 1
    assert agent_call_cap(3, True, True) == agent_call_cap(3) + 2
