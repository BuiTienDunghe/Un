"""Reading the rest: a turn that found the document and said the fact is not there has the code
read what is left, one note per part, and answers from the notes. Off by default. No model, no GPU."""
from __future__ import annotations

import pytest

from app.llm_clients.deadline import ModelCallTimeoutError
from app.services.agent_service import AgentService
from app.services.call_budget import OVERRUNS, agent_call_cap
from app.services.document_reading import DOCUMENT_PART_STEP, READ_REST_STEP
from app.services.injection_defense import InjectionDefense
from scripts.agent_eval_grader import grade

GAVE_UP = "Trong các đoạn trích tôi chưa thấy số tiền. Bạn có muốn tôi đọc toàn văn không?"
FOUND = "Hội phí là 340.000 đồng."
NOTE = "Hội phí 340.000 đồng."


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments}],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


class Router:
    """`rounds` for the loop's calls; a note call (router.chat with options) answers `note`."""

    def __init__(self, rounds, note=NOTE, on_note=None, forced=()):
        self.rounds = list(rounds)
        self.forced = list(forced)
        self.note = note
        self.on_note = on_note
        self.prompts: list[list[dict]] = []
        self.note_prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages, options=None):
        if options is None:
            self.prompts.append([dict(message) for message in messages])
            reply = self.forced.pop(0) if self.forced else "hết lượt"
            return (reply() if callable(reply) else reply), "fake"
        self.note_prompts.append([dict(message) for message in messages])
        if self.on_note:
            self.on_note()
        return self.note, "fake"


class Retrieval:
    def __init__(self, documents=("doc-1",)):
        self.documents = documents

    def retrieve(self, query, top_k, document_id=None):
        return [
            {"filename": f"{doc}.txt", "page": None, "content": "Đoạn đầu.", "score": 0.9, "chunk_id": f"{doc}#0", "document_id": doc, "chunk_index": 0}
            for doc in self.documents
        ]


class Reader:
    """`sizes` chunks per document, each `chars` long; `missing` documents read as gone."""

    def __init__(self, sizes=None, chars=100, missing=()):
        self.sizes = sizes or {"doc-1": 4}
        self.chars = chars
        self.missing = missing
        self.asked: list[tuple[str, int]] = []

    def read_chunks(self, document_id, from_chunk, n):
        self.asked.append((document_id, from_chunk))
        if document_id in self.missing:
            return None
        total = self.sizes.get(document_id, 0)
        chunks = [
            {"chunk_index": i, "page_start": None, "page_end": None, "content": f"[{document_id} đoạn {i}]" + "x" * self.chars}
            for i in range(from_chunk, min(from_chunk + n, total))
        ]
        return {"document_id": document_id, "filename": f"{document_id}.txt", "total_chunks": total, "chunks": chunks}


SEARCH = call("search_documents", {"query": "hội phí"})
READ_FIRST = call("read_document", {"document_id": "doc-1", "from_chunk": 0, "n": 2})
QUESTION = "Hội phí bao nhiêu?"


def run(rounds, reader=None, retrieval=None, enabled=True, router=None, **kwargs):
    router = router or Router(rounds)
    agent = AgentService(router, retrieval or Retrieval(), None, document_reader=reader or Reader(), read_rest=enabled, **kwargs)
    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": QUESTION}])
    return answer, steps, router


def kinds(steps):
    return [step["kind"] for step in steps]


def test_it_is_off_by_default():
    answer, steps, router = run([SEARCH, final(GAVE_UP)], enabled=False)
    assert answer == GAVE_UP and not router.note_prompts
    assert READ_REST_STEP not in kinds(steps)


def test_giving_up_has_the_code_read_all_of_it_and_the_model_answers_from_the_notes():
    reader = Reader()
    answer, steps, router = run([SEARCH, final(GAVE_UP), final(FOUND)], reader=reader)
    assert answer == FOUND
    # Every chunk went into the note call, the part that held the answer included.
    part = router.note_prompts[0][-1]["content"]
    assert all(f"[doc-1 đoạn {i}]" in part for i in range(4))
    assert QUESTION in part
    last = router.prompts[-1]
    assert NOTE in last[-1]["content"] and QUESTION in last[-1]["content"]
    assert last[-1]["role"] == "user", "a document's notes never reach the model as a system message"
    assert kinds(steps).count(DOCUMENT_PART_STEP) == 1
    assert READ_REST_STEP in kinds(steps)


def test_the_rejected_answer_reaches_no_one():
    _, steps, router = run([SEARCH, final(GAVE_UP), final(FOUND)])
    assert GAVE_UP not in [message.get("content") for message in router.prompts[-1]]
    assert next(step for step in steps if step["kind"] == READ_REST_STEP)["content"] is None


def test_the_read_is_in_the_trace_as_a_read_and_says_the_code_made_it():
    _, steps, _ = run([SEARCH, final(GAVE_UP), final(FOUND)])
    reads = [step for step in steps if step["kind"] == "tool_call" and step["tool_name"] == "read_document"]
    assert len(reads) == 1
    assert reads[0]["by_code"] is True and reads[0]["arguments"]["document_id"] == "doc-1"


def test_the_grader_counts_the_codes_read_but_does_not_mark_its_arguments():
    schemas = {"read_document": {"properties": {"n": {"type": "integer", "minimum": 1, "maximum": 3}}}}
    steps = [{"kind": "tool_call", "tool_name": "read_document", "by_code": True, "arguments": {"n": 12}}, {"kind": "final"}]
    checks = {check["check"]: check["passed"] for check in grade({"tools_required": ["read_document"]}, steps, "x", schemas)["checks"]}
    assert checks["tools_required"] is True and checks["args_valid"] is True


def test_out_of_rounds_with_documents_half_read_the_code_reads_the_rest():
    router = Router([SEARCH, READ_FIRST, READ_FIRST], forced=[GAVE_UP, FOUND])
    answer, steps, _ = run([], reader=Reader(sizes={"doc-1": 6}), router=router)
    assert answer == FOUND
    assert len(router.note_prompts) == 1 and "[doc-1 đoạn 3]" in router.note_prompts[0][-1]["content"]
    assert READ_REST_STEP in kinds(steps)
    assert GAVE_UP not in [message.get("content") for message in router.prompts[-1]]


def test_a_forced_answer_that_found_it_is_left_alone():
    router = Router([SEARCH, READ_FIRST, READ_FIRST], forced=["Hội phí do ban chấp hành quyết định."])
    answer, steps, _ = run([], reader=Reader(sizes={"doc-1": 6}), router=router)
    assert answer == "Hội phí do ban chấp hành quyết định." and not router.note_prompts
    assert READ_REST_STEP not in kinds(steps)


def test_when_the_second_forced_answer_runs_out_of_time_the_first_stands():
    def timed_out():
        raise ModelCallTimeoutError("late")
    router = Router([SEARCH, READ_FIRST, READ_FIRST], forced=[GAVE_UP, timed_out])
    answer, _, _ = run([], reader=Reader(sizes={"doc-1": 6}), router=router)
    assert answer == GAVE_UP


def test_it_happens_once():
    answer, steps, router = run([SEARCH, final(GAVE_UP), final(GAVE_UP)])
    assert answer == GAVE_UP
    assert kinds(steps).count(READ_REST_STEP) == 1 and len(router.note_prompts) == 1


def test_a_document_read_to_its_end_may_truly_not_have_it():
    reader = Reader(sizes={"doc-1": 2})
    answer, steps, router = run([SEARCH, call("read_document", {"document_id": "doc-1", "from_chunk": 0, "n": 2}), final(GAVE_UP)], reader=reader)
    assert answer == GAVE_UP and not router.note_prompts
    assert READ_REST_STEP not in kinds(steps)


def test_it_starts_where_the_model_stopped_reading():
    reader = Reader(sizes={"doc-1": 5})
    _, _, router = run([SEARCH, call("read_document", {"document_id": "doc-1", "from_chunk": 0, "n": 2}), final(GAVE_UP), final(FOUND)], reader=reader)
    part = router.note_prompts[0][-1]["content"]
    assert "[doc-1 đoạn 1]" not in part and "[doc-1 đoạn 2]" in part and "[doc-1 đoạn 4]" in part


def test_no_tool_called_is_the_lookup_checks_business():
    answer, steps, router = run([final(GAVE_UP)])
    assert answer == GAVE_UP and not router.note_prompts


def test_an_answer_that_found_it_is_left_alone():
    answer, _, router = run([SEARCH, final("Hội phí do ban chấp hành quyết định.")])
    assert answer == "Hội phí do ban chấp hành quyết định." and not router.note_prompts


def test_documents_go_in_the_order_the_search_showed_them():
    reader = Reader(sizes={"b": 1, "a": 1, "c": 1})
    _, _, router = run([SEARCH, final(GAVE_UP), final(FOUND)], reader=reader, retrieval=Retrieval(("b", "a", "c")))
    assert ["[b đoạn 0]" in p[-1]["content"] for p in router.note_prompts] == [True, False, False]
    assert "[c đoạn 0]" in router.note_prompts[2][-1]["content"]


def test_a_read_that_began_in_the_middle_leaves_the_beginning_for_the_code():
    reader = Reader(sizes={"doc-1": 5})
    _, _, router = run([SEARCH, call("read_document", {"document_id": "doc-1", "from_chunk": 3, "n": 2}), final(GAVE_UP), final(FOUND)], reader=reader)
    part = router.note_prompts[0][-1]["content"]
    assert "[doc-1 đoạn 0]" in part and "[doc-1 đoạn 2]" in part and "[doc-1 đoạn 3]" not in part


def test_a_document_that_cannot_be_read_is_skipped_and_said():
    reader = Reader(sizes={"b": 1}, missing=("a",))
    answer, _, _ = run([SEARCH, final(GAVE_UP), final(FOUND)], reader=reader, retrieval=Retrieval(("a", "b")))
    assert answer.startswith(FOUND)
    assert "a.txt" in answer.split("Lưu ý", 1)[1]


def test_past_the_part_limit_the_answer_says_what_was_not_read(monkeypatch):
    monkeypatch.setattr("app.services.document_reading.READ_REST_MAX_PARTS", 2)
    documents = {f"d{i}": 1 for i in range(4)}
    answer, steps, router = run([SEARCH, final(GAVE_UP), final(FOUND)], reader=Reader(sizes=documents), retrieval=Retrieval(tuple(documents)))
    assert len(router.note_prompts) == 2 and kinds(steps).count(DOCUMENT_PART_STEP) == 2
    assert answer.startswith(FOUND) and "Lưu ý" in answer and "d2.txt" in answer and "d3.txt" in answer
    assert "d0.txt" not in answer


def test_out_of_time_the_reading_stops_and_the_answer_says_so():
    clock = {"now": 0.0}
    router = Router([SEARCH, final(GAVE_UP), final(FOUND)], on_note=lambda: clock.__setitem__("now", clock["now"] + 40.0))
    documents = {f"d{i}": 1 for i in range(4)}
    answer, _, router = run([], reader=Reader(sizes=documents), retrieval=Retrieval(tuple(documents)), router=router, clock=lambda: clock["now"])
    # 90 seconds less the 20 reserved: the first takes 40, and a second of the same would end past the edge.
    assert len(router.note_prompts) == 1
    assert "Lưu ý" in answer and "d1.txt" in answer


def test_with_no_room_for_notes_nothing_is_spent():
    answer, steps, router = run([SEARCH, final(GAVE_UP)], inline_max_tokens=1_300)
    assert answer == GAVE_UP and not router.note_prompts
    assert READ_REST_STEP not in kinds(steps)


def test_a_part_and_its_note_wear_the_data_markers_with_the_defense_on():
    defense = InjectionDefense(enabled=True)
    _, _, router = run([SEARCH, final(GAVE_UP), final(FOUND)], defense=defense)
    assert defense.wrap_tool_result("x").split("\n")[0] in router.note_prompts[0][-1]["content"]
    assert defense.wrap_tool_result(NOTE) in router.prompts[-1][-1]["content"]


def test_a_figure_only_the_notes_hold_passes_the_answer_check():
    _, steps, router = run([SEARCH, final(GAVE_UP), final(FOUND)])
    assert len(router.prompts) == 3, "340.000 came from a note: no retry for an unseen figure"
    assert not next(step for step in steps if step["kind"] == "final").get("error_code")


def test_the_calls_stay_within_their_caps():
    OVERRUNS.clear()
    documents = {f"d{i}": 1 for i in range(8)}
    run([SEARCH, final(GAVE_UP), final(FOUND)], reader=Reader(sizes=documents), retrieval=Retrieval(tuple(documents)))
    assert not OVERRUNS


def test_the_cap_grows_by_one():
    assert agent_call_cap(3, read_rest=True) == agent_call_cap(3) + 1


@pytest.mark.parametrize("flags", [{"read_on_check": True}])
def test_with_both_on_the_code_reads_and_the_model_is_not_also_sent_back(flags):
    _, steps, router = run([SEARCH, final(GAVE_UP), final(GAVE_UP)], **flags)
    assert kinds(steps).count(READ_REST_STEP) == 1
    assert "read_on_check" not in kinds(steps)


def test_a_store_that_fails_while_reading_the_rest_costs_the_extra_not_the_turn():
    class Broken(Reader):
        def read_chunks(self, document_id, from_chunk, n):
            if from_chunk == 0 and n > 3:  # the code's own read; the model's read_document asks n <= 3
                raise RuntimeError("database down")
            return super().read_chunks(document_id, from_chunk, n)
    answer, steps, _ = run([SEARCH, final(GAVE_UP)], reader=Broken())
    assert answer == GAVE_UP and READ_REST_STEP not in kinds(steps)


def test_a_second_forced_answer_that_fails_leaves_the_first():
    def down():
        raise RuntimeError("ollama 500")
    router = Router([SEARCH, READ_FIRST, READ_FIRST], forced=[GAVE_UP, down])
    answer, _, _ = run([], reader=Reader(sizes={"doc-1": 6}), router=router)
    assert answer == GAVE_UP
