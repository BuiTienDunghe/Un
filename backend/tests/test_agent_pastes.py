"""A long paste becomes a document the agent reads, not text the model carries (ticket 20 #3).

A message longer than PASTE_THRESHOLD stays whole in the conversation; the model gets a slip
with its two edges and an id, and read_document opens it from the turn's own pastes. Plain
chat keeps the old limit (422 INPUT_TOO_LONG) and sees a paste in its history as a one-line
note, the stream path included. No database, no model: stores and models are fakes.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.chat as chat_router
from app.security.api_key import require_api_key
from app.services.agent_service import ANSWER_CHECK_STEP, BAD_ARGUMENTS, NOT_READABLE, READ_MAX_CHUNKS, SEARCH_EXCERPT_CHARS, AgentService
from app.services.chat_service import ChatService
from app.services.pastes import (
    PASTE_MAX,
    PASTE_THRESHOLD,
    SLIP_EDGE_CHARS,
    _chunks,
    is_paste,
    note,
    paste_id,
    read_paste,
    search_pastes,
    search_text,
    shorten_pastes,
    slip,
    take_pastes,
)

QUESTION = "Theo biên bản trên, hạn nộp hồ sơ là ngày nào?"
SECRET = "Hạn nộp hồ sơ dự thầu là ngày 14/11, chị Thu Hà phụ trách."


def paste(middle: str = SECRET, length: int = 12_000) -> str:
    filler = "Mục họp thường lệ, không có gì đáng chú ý trong đoạn này. " * (length // 60)
    half = len(filler) // 2
    return "Mình dán biên bản dưới đây.\n\n" + filler[:half] + "\n\n" + middle + "\n\n" + filler[half:] + "\n\n" + QUESTION


PASTED = paste()


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds=(), reply: str = "ok"):
        self.rounds, self.reply = list(rounds), reply
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(m) for m in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(m) for m in messages])
        return self.reply, "fake"

    def stream_chat(self, role, messages):
        self.prompts.append([dict(m) for m in messages])
        return iter([self.reply]), "fake"


class Reader:
    """A document store that has never heard of any paste."""

    def __init__(self):
        self.asked: list[str] = []

    def read_chunks(self, document_id, from_chunk, n):
        self.asked.append(document_id)
        return None

    def chunks_on_page(self, document_id, page, n):
        self.asked.append(document_id)
        return None


def agent(rounds, reader=None) -> tuple[AgentService, Router]:
    router = Router(rounds)
    return AgentService(router, None, None, document_reader=reader), router


def test_a_paste_is_whatever_runs_past_the_old_limit_and_keeps_one_id():
    assert not is_paste({"role": "user", "content": "x" * PASTE_THRESHOLD})
    assert is_paste({"role": "user", "content": "x" * (PASTE_THRESHOLD + 1)})
    assert not is_paste({"role": "assistant", "content": "x" * (PASTE_THRESHOLD + 1)}), "only what the user pasted"
    assert paste_id(PASTED) == paste_id(str(PASTED)) and paste_id(PASTED).startswith("paste_")


def test_the_slip_carries_both_edges_and_how_to_open_it_and_not_the_middle():
    text = slip(PASTED)
    assert paste_id(PASTED) in text and "read_document" in text and str(len(PASTED)) in text
    assert PASTED[:SLIP_EDGE_CHARS].rstrip() in text and QUESTION in text, "the question at the end survives"
    assert SECRET not in text and len(text) < 2 * SLIP_EDGE_CHARS + 900


def framing(text: str) -> tuple[str, str]:
    """The slip's own words before the head and after the tail, without the user's text."""
    head, tail = text[:SLIP_EDGE_CHARS].rstrip(), text[-SLIP_EDGE_CHARS:].lstrip()
    shown = slip(text)
    return shown[: shown.index(head)], shown[shown.index(tail) + len(tail):]


def test_the_slip_never_calls_the_paste_a_document_and_says_search_finds_its_chunks():
    # #3-B: on "lưu thành tài liệu tạm" doc-39 searched the library and asked the user
    # whether to read on (kept/agent-eval-v0.3-pastes/REPORT.md). #3-D, 3': search now
    # finds the paste, and the slip says it hands back the chunk to read.
    before, after = framing(PASTED)
    assert "tài liệu" not in before + after
    assert "không tìm thấy" not in after and "search_documents tìm được trong nó" in after
    assert "trả chunk_index để đọc thẳng đoạn đó bằng read_document" in after and "hỏi lại người dùng" in after


def test_the_slip_gives_the_exact_call_after_the_question_the_user_asked():
    before, after = framing(PASTED)
    pid = paste_id(PASTED)
    assert f'read_document(document_id="{pid}", from_chunk=0, n={READ_MAX_CHUNKS})' in after, "n is the most a call reads"
    assert "from_chunk bằng next_from_chunk" in after and "next_from_chunk là null" in after
    assert "read_document" not in before, "what to do comes after the tail, not above the head"


def test_the_slip_states_the_cap_and_not_the_chunk_count():
    # #3-C: on #3-B's "Văn bản có N đoạn" the first read asked n = N on 4 of 5 paste tasks,
    # over the cap (kept/agent-eval-v0.5-paste-slip-b/REPORT.md).
    before, after = framing(PASTED)
    total = len(_chunks(PASTED))
    assert f"{total} đoạn" not in before + after and "từ 0 đến" not in before + after
    assert f"chỉ nhận n từ 1 đến {READ_MAX_CHUNKS}" in after and f"tối đa {READ_MAX_CHUNKS} đoạn" in after
    assert "gọi lại với from_chunk" in after, "reading on is another call, not a bigger n"


def test_the_slip_says_to_answer_at_once_when_the_edges_are_enough_before_how_to_read():
    # #3-C: doc-42 read three times with its answer already in the tail.
    _, after = framing(PASTED)
    enough = after.index("đã đủ để trả lời thì trả lời luôn")
    assert enough < after.index("read_document(")


def test_only_a_message_past_the_threshold_becomes_a_slip():
    at_limit = {"role": "user", "content": "x" * PASTE_THRESHOLD}
    assert take_pastes([at_limit]) == ([at_limit], {})
    over = {"role": "user", "content": "x" * (PASTE_THRESHOLD + 1)}
    shown, pastes = take_pastes([over])
    assert shown == [{**over, "content": slip(over["content"])}] and list(pastes) == [paste_id(over["content"])]

    service, router = agent([final("ok")])
    service.run([at_limit])
    assert "read_document(document_id=" not in json.dumps(router.prompts, ensure_ascii=False), "a short message travels as it was"


def test_a_paste_reads_in_chunks_and_has_no_pages():
    read = read_paste(paste_id(PASTED), PASTED, 0, 50)
    assert read["total_chunks"] == len(read["chunks"]) > 2
    assert "".join(c["content"] for c in read["chunks"]).count("14/11") >= 1
    assert read_paste(paste_id(PASTED), PASTED, 0, 3, page=2)["chunks"] == []
    assert read_paste(paste_id(PASTED), PASTED, 999, 2)["chunks"] == []


def test_plain_chat_keeps_a_note_and_memory_search_reads_only_the_edges():
    history = [{"role": "user", "content": PASTED}, {"role": "assistant", "content": "Đã đọc."}]
    assert shorten_pastes(history) == [{"role": "user", "content": note(PASTED)}, history[1]]
    assert len(search_text(PASTED)) <= 2 * SLIP_EDGE_CHARS + 1 and search_text("ngắn") == "ngắn"


def test_the_agent_sees_the_slip_and_reads_the_middle_through_read_document():
    pid = paste_id(PASTED)
    middle = next(c["chunk_index"] for c in read_paste(pid, PASTED, 0, 50)["chunks"] if "14/11" in c["content"])
    service, router = agent([call("read_document", {"document_id": pid, "from_chunk": middle, "n": 1}), final("Hạn 14/11, chị Thu Hà phụ trách.")])
    answer, _, steps = service.run([{"role": "user", "content": PASTED}])

    first_prompt = json.dumps(router.prompts[0], ensure_ascii=False)
    assert SECRET not in first_prompt and pid in first_prompt, "the model carries the slip, not the paste"
    result = [s for s in steps if s["kind"] == "tool_result"][0]
    assert result["error_code"] is None
    read = json.loads(result["content"])
    assert read["document_id"] == pid and any("14/11" in c["content"] for c in read["chunks"])
    assert answer == "Hạn 14/11, chị Thu Hà phụ trách." and [s["kind"] for s in steps][-1] == "final", "read first: no retry"


def test_a_paste_from_an_earlier_turn_opens_again_under_the_same_id():
    pid = paste_id(PASTED)
    history = [{"role": "user", "content": PASTED}, {"role": "assistant", "content": "Đã lưu biên bản."}]
    service, router = agent([call("read_document", {"document_id": pid, "n": 1}), final("xong")])
    _, _, steps = service.run([*history, {"role": "user", "content": "Ai phụ trách hồ sơ?"}])
    assert [s for s in steps if s["kind"] == "tool_result"][0]["error_code"] is None
    assert SECRET not in json.dumps(router.prompts, ensure_ascii=False)


def test_only_this_turns_own_pastes_open_never_a_callers_or_the_stores():
    # The caller cannot hand the turn a paste: run() takes pastes from the messages alone,
    # and an id it did not take there goes to the document store, which refuses it.
    reader = Reader()
    planted = {"pastes": {"paste_planted": "nội dung cài vào"}, "readable_documents": {"paste_planted"}}
    service, _ = agent([call("read_document", {"document_id": "paste_planted"}), final("xong")], reader)
    _, _, steps = service.run([{"role": "user", "content": "đọc giúp"}], planted)

    result = [s for s in steps if s["kind"] == "tool_result"][0]
    assert result["error_code"] == BAD_ARGUMENTS and json.loads(result["content"])["error"] == NOT_READABLE
    assert "nội dung cài vào" not in json.dumps(steps, ensure_ascii=False) and reader.asked == ["paste_planted"]


def test_a_paste_read_by_page_says_it_has_no_pages():
    service, _ = agent([call("read_document", {"document_id": paste_id(PASTED), "page": 2}), final("xong")])
    _, _, steps = service.run([{"role": "user", "content": PASTED}])
    payload = json.loads([s for s in steps if s["kind"] == "tool_result"][0]["content"])
    assert "from_chunk" in payload["result"]


def test_a_figure_only_in_the_unread_middle_sends_the_agent_back_to_read_it():
    # #2's check sees the slip, not the paste: quoting the middle without opening it is a
    # figure from nowhere, and the retry is the agent's chance to read first.
    pid = paste_id(PASTED)
    service, router = agent([final("Hạn là ngày 14/11."), call("read_document", {"document_id": pid, "n": 3}), final("Hạn 14/11.")])
    _, _, steps = service.run([{"role": "user", "content": PASTED}])
    assert [s["kind"] for s in steps][:2] == [ANSWER_CHECK_STEP, "tool_call"]


class Library:
    """A document library that records what it was asked."""

    def __init__(self, chunks=()):
        self.chunks, self.asked = list(chunks), []

    def retrieve(self, query, top_k, document_id=None):
        self.asked.append((query, top_k, document_id))
        return [dict(chunk) for chunk in self.chunks[:top_k]]


SHELF = [
    {"filename": "so-tay.pdf", "page": 3, "document_id": "doc-1", "chunk_index": 5, "content": "Quy trình bảo hành thiết bị. " * 20, "score": 0.81234},
    {"filename": "ghi-chu.txt", "page": None, "content": "Một đoạn không có tài liệu phía sau.", "score": 0.4},
]


def searched(library, messages, query, top_k=4):
    """The search result the agent's model reads, parsed, after one search_documents call."""
    service = AgentService(Router([call("search_documents", {"query": query, "top_k": top_k}), final("xong")]), library, None)
    _, _, steps = service.run(messages)
    result = [s for s in steps if s["kind"] == "tool_result"][0]
    assert result["error_code"] is None
    return json.loads(result["content"])


def middle_index(text: str = PASTED) -> int:
    return next(i for i, chunk in enumerate(_chunks(text)) if "14/11" in chunk)


def test_search_finds_the_pasted_chunk_holding_the_querys_words_first():
    found = search_pastes({paste_id(PASTED): PASTED}, "hạn nộp hồ sơ dự thầu, ai phụ trách", 4)
    assert found[0]["chunk_index"] == middle_index() and SECRET in found[0]["content"]
    assert len({row["chunk_index"] for row in found}) == len(found) <= 4, "each chunk once, at most top_k"


def test_a_pasted_result_carries_the_paste_id_and_chunk_and_opens_with_read_document():
    pid, middle = paste_id(PASTED), middle_index()
    library = Library()
    items = searched(library, [{"role": "user", "content": PASTED}], "hạn nộp hồ sơ dự thầu")
    first = items[0]
    # The excerpt is the chunk's head, as the library's is; here the matching sentence lies
    # past it, which is what the read sentence is for.
    assert first["document_id"] == pid and first["chunk_index"] == middle
    assert first["excerpt"] == _chunks(PASTED)[middle][: SEARCH_EXCERPT_CHARS - 1] + "…" and "14/11" not in first["excerpt"]
    assert first["filename"] == read_paste(pid, PASTED, 0, 1)["filename"] and first["chars"] == len(_chunks(PASTED)[middle])
    assert first["read"] == f'đọc trọn đoạn này bằng read_document(document_id="{pid}", from_chunk={middle})'
    assert "score" not in first and "page" not in first, "a BM25 score is not on the library's scale; a paste has no pages"
    assert library.asked == [("hạn nộp hồ sơ dự thầu", 4, None)], "the library is still asked, once, as before"

    service, _ = agent([call("read_document", {"document_id": first["document_id"], "from_chunk": first["chunk_index"], "n": 1}), final("Hạn 14/11.")])
    _, _, steps = service.run([{"role": "user", "content": PASTED}])
    read = [s for s in steps if s["kind"] == "tool_result"][0]
    assert read["error_code"] is None and SECRET in json.loads(read["content"])["chunks"][0]["content"]


def test_pasted_results_come_before_the_librarys_and_not_found_needs_both_empty():
    pid = paste_id(PASTED)
    items = searched(Library(SHELF), [{"role": "user", "content": PASTED}], "hạn nộp hồ sơ dự thầu bảo hành thiết bị")
    sources = [item.get("document_id") for item in items]
    assert sources[0] == pid and sources[-2:] == ["doc-1", None], "the paste first, then the library in its own order"

    nothing = searched(Library(), [{"role": "user", "content": PASTED}], "lịch bảo dưỡng máy phát điện")
    assert nothing == {"result": "không tìm thấy đoạn tài liệu nào phù hợp"}


def test_without_a_paste_search_documents_answers_exactly_as_before():
    library = Library(SHELF)
    items = searched(library, [{"role": "user", "content": "bảo hành thiết bị thế nào?"}], "quy trình bảo hành", top_k=12)
    # Built the way search_documents built it before #3-D: the library's chunks alone.
    assert items == [
        {"filename": "so-tay.pdf", "page": 3, "document_id": "doc-1", "chunk_index": 5,
         "excerpt": SHELF[0]["content"][: SEARCH_EXCERPT_CHARS - 1] + "…", "chars": len(SHELF[0]["content"]), "score": 0.812},
        {"filename": "ghi-chu.txt", "page": None, "excerpt": SHELF[1]["content"], "chars": len(SHELF[1]["content"]), "score": 0.4},
    ]
    assert library.asked == [("quy trình bảo hành", 8, None)]
    assert searched(Library(), [{"role": "user", "content": "có gì không?"}], "bất kỳ") == {"result": "không tìm thấy đoạn tài liệu nào phù hợp"}


def test_a_paste_earlier_in_the_conversation_does_not_crowd_a_library_question():
    # `pastes` holds every paste of the conversation. A question about the library shares
    # only words that sit in half the paste's chunks or more (here the filler, in every
    # chunk), which weigh nothing: the result is the library's alone.
    history = [{"role": "user", "content": PASTED}, {"role": "assistant", "content": "Đã đọc."}]
    question = {"role": "user", "content": "Quy trình bảo hành trong sổ tay thế nào?"}
    query = "quy trình bảo hành thiết bị trong đoạn họp thường lệ"
    assert search_pastes({paste_id(PASTED): PASTED}, "mục họp thường lệ, không có gì đáng chú ý", 4) == []
    assert searched(Library(SHELF), [*history, question], query) == searched(Library(SHELF), [question], query)


def test_a_decomposed_paste_still_matches_a_composed_query():
    import unicodedata

    text = unicodedata.normalize("NFD", PASTED)
    assert text != PASTED
    found = search_pastes({paste_id(text): text}, "hạn nộp hồ sơ dự thầu", 1)
    assert found and "14/11" in found[0]["content"]


def client(chat_service) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router.router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.state.chat_service = chat_service
    return TestClient(app)


class ChatServiceStub:
    def __init__(self):
        self.messages: list[str] = []

    def respond(self, message, conversation_id, use_memory, system_prompt, use_tools, user_id=None):
        self.messages.append(message)
        return "ok", "fake", "conv-1", 1, None


def test_plain_chat_refuses_a_paste_with_input_too_long_and_tool_mode_takes_it(monkeypatch):
    monkeypatch.setattr(chat_router, "resolve_identity", lambda request: type("I", (), {"is_user": False, "user_id": None})())
    stub = ChatServiceStub()
    api = client(stub)

    refused = api.post("/chat", json={"message": PASTED})
    assert refused.status_code == 422 and refused.json()["detail"]["error_code"] == "INPUT_TOO_LONG"
    assert api.post("/chat", json={"message": "x" * PASTE_THRESHOLD}).status_code == 200, "the old limit still fits"
    assert api.post("/chat", json={"message": PASTED, "use_tools": True}).status_code == 200
    assert api.post("/chat", json={"message": "x" * (PASTE_MAX + 1), "use_tools": True}).status_code == 422
    assert stub.messages == ["x" * PASTE_THRESHOLD, PASTED], "the paste reaches the service whole"


class Store:
    def __init__(self, history):
        self.history, self.added = history, []

    def conversation_exists(self, conversation_id):
        return True

    def get_messages(self, conversation_id, limit):
        return [dict(m) for m in self.history]

    def add_message(self, conversation_id, role, content, model_used=None):
        self.added.append((role, content))
        return len(self.added)


class Log:
    def log_request(self, *args, **kwargs):
        pass


def test_the_stream_path_and_plain_chat_see_a_pasted_history_as_a_note():
    history = [{"role": "user", "content": PASTED}, {"role": "assistant", "content": "Đã lưu."}]
    router = Router()
    service = ChatService(Store(history), router, Log(), history_limit=40)

    tokens, _, _ = service.stream_response("Ai phụ trách?", "conv-1")
    assert list(tokens) == ["ok"]
    service.respond("Ai phụ trách?", "conv-1")

    for prompt in router.prompts:
        text = json.dumps(prompt, ensure_ascii=False)
        assert SECRET not in text and note(PASTED) in text
    assert service.store.added[0] == ("user", "Ai phụ trách?")
