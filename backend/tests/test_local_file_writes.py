"""Laptop agent, batch 2: write_file, move_file, delete_file, each waiting for the owner. No database, no model.

Off by default. On, only the owner's web turn sees the tools; a call ends the turn on an approval card, nothing
changes until the owner approves, what was approved is what runs, and every change can be undone for 3 days.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.services import local_file_writes, local_files
from app.services.agent_service import AgentService, core_tools
from app.services.approvals import STOP_AWAITING_APPROVAL, ApprovalError
from app.services.local_files import LOCAL_FILES_KEY, Refused

OWNER = {LOCAL_FILES_KEY: True}


class Router:
    def __init__(self, rounds):
        self.rounds, self.tools_seen = list(rounds), []

    def chat_tools(self, role, messages, tools):
        self.tools_seen.append([tool["function"]["name"] for tool in tools])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        return "đã trả lời", "fake"


def calls(name: str, arguments: dict) -> dict:
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments}],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


def answer(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


@pytest.fixture()
def place(tmp_path: Path) -> SimpleNamespace:
    docs = tmp_path / "Documents"
    (docs / "cu").mkdir(parents=True)
    (docs / "ghi chu.md").write_text("bản cũ", encoding="utf-8")
    (docs / "bao-cao.pdf").write_bytes(b"%PDF-1.4 fake")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "hoa-don.txt").write_text("500.000 đồng", encoding="utf-8")
    return SimpleNamespace(root=tmp_path, docs=docs, downloads=downloads, backup=tmp_path / "backup", setting=f"{docs};{downloads}")


def build(place, *rounds: dict) -> tuple[AgentService, local_file_writes.LocalApprovals, list]:
    registry = core_tools()
    roots = local_files.register(registry, place.setting)
    agent = AgentService(Router(rounds), None, None, registry=registry)
    notes: list = []
    gate = local_file_writes.register(agent, roots, place.backup, record_message=lambda cid, text: notes.append((cid, text)))
    return agent, gate, notes


def ask(gate, tool: str, arguments: dict, context: dict | None = None) -> str:
    return gate.request(tool, arguments, {**OWNER, "conversation_id": "c1", **(context or {})}).approval_id


# ── off by default, and invisible outside the owner's turn ───────────────────


def test_it_is_off_unless_its_own_flag_is_set_on_top_of_reading() -> None:
    assert Settings.model_fields["agent_local_files_write_enabled"].default is False
    assert Settings.model_fields["agent_local_files_backup_dir"].default == ""
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "if roots and settings.agent_local_files_write_enabled:" in source


def test_a_turn_not_marked_sees_only_the_core_tools(place) -> None:
    agent, gate, _ = build(place)
    assert agent.approvals is gate
    assert agent._offered_schemas() == core_tools().schemas()
    assert agent._offered_schemas({"guild_id": "1", "turn_id": "t"}) == core_tools().schemas()


def test_the_owners_turn_sees_reading_then_writing_after_read_document(place) -> None:
    agent, _, _ = build(place, answer("xong"))
    agent.run([{"role": "user", "content": "chào"}], tool_context=dict(OWNER))
    names = list(core_tools().names())
    # One order for the three, so they follow read_file by name.
    assert agent.router.tools_seen[0] == [*names[:2], "list_files", "read_file", "delete_file", "move_file", "write_file", *names[2:]]


def test_a_write_call_from_elsewhere_is_refused_and_any_other_call_goes_to_the_previous_gate(place) -> None:
    _, gate, _ = build(place)
    seen = []
    gate.fallback = SimpleNamespace(request=lambda name, arguments, context: seen.append(name) or "kept")
    with pytest.raises(ApprovalError) as refused:
        gate.request("write_file", {"path": "Documents/a.txt", "content": "x"}, {"guild_id": "1"})
    assert refused.value.code == "APPROVAL_UNAVAILABLE" and seen == []
    assert gate.request("remind", {}, {"guild_id": "1"}) == "kept" and seen == ["remind"]
    gate.fallback = None
    with pytest.raises(ApprovalError) as nobody:
        gate.request("remind", {}, {"guild_id": "1"})
    assert nobody.value.code == "APPROVAL_UNAVAILABLE"


def test_a_backup_folder_inside_an_allowed_folder_adds_nothing(place) -> None:
    registry = core_tools()
    roots = local_files.register(registry, place.setting)
    agent = AgentService(Router([]), None, None, registry=registry)
    assert local_file_writes.register(agent, roots, place.docs / "backup") is None
    assert "write_file" not in agent.registry.names() and agent.approvals is None


# ── the turn stops at the card; nothing changes before the owner says yes ─────


def test_a_write_call_ends_the_turn_on_a_card_and_writes_nothing(place) -> None:
    agent, gate, _ = build(place, calls("write_file", {"path": "Documents/moi.md", "content": "# Mới"}))
    reply, _, steps = agent.run([{"role": "user", "content": "tạo tệp moi.md"}], tool_context=dict(OWNER))
    final = steps[-1]
    assert final["stop_reason"] == STOP_AWAITING_APPROVAL and final["approval_id"]
    assert "Documents/moi.md" in reply and "Duyệt" in reply
    assert not (place.docs / "moi.md").exists()
    card = gate.get(final["approval_id"])
    assert card["status"] == "pending" and card["plan"]["content"] == "# Mới" and card["seconds_left"] > 0


def test_a_wrong_call_goes_back_to_the_model_and_nobody_is_asked(place) -> None:
    agent, gate, _ = build(
        place, calls("write_file", {"path": "outside/x.txt", "content": "x"}), answer("Thư mục đó không được phép."),
    )
    reply, _, steps = agent.run([{"role": "user", "content": "ghi x"}], tool_context=dict(OWNER))
    assert reply == "Thư mục đó không được phép."
    assert next(step for step in steps if step["kind"] == "tool_result")["error_code"] == "BAD_ARGUMENTS"
    assert gate._pending == {}


@pytest.mark.parametrize(("tool", "arguments"), [
    ("write_file", {"path": "Documents/.env", "content": "x"}),
    ("write_file", {"path": "Documents/.an/x.txt", "content": "x"}),
    ("write_file", {"path": "Documents/moi.docx", "content": "x"}),
    ("write_file", {"path": "Documents/chua-co/x.txt", "content": "x"}),
    ("write_file", {"path": "Documents/CON.txt", "content": "x"}),
    ("write_file", {"path": "Documents/bao-cao.pdf", "content": "x"}),
    ("write_file", {"path": "Documents/x.txt", "content": 5}),
    ("write_file", {"path": "x.txt", "content": "x"}),
    ("write_file", {"path": "Documents/bao cao?.md", "content": "x"}),
    ("write_file", {"path": "Documents/a<b>.md", "content": "x"}),
    ("write_file", {"path": "Documents/tab\there.md", "content": "x"}),
    ("write_file", {"path": "Documents/cham-cuoi.md.", "content": "x"}),
    ("write_file", {"path": "Documents/dai.md", "content": "x" * 50_001}),
    ("move_file", {"path": "Documents/ghi chu.md", "to": "Downloads/hoa-don.txt"}),
    ("move_file", {"path": "Documents/cu", "to": "Downloads"}),
    ("move_file", {"path": "Documents/ghi chu.md", "to": "Documents/ghi chu.md"}),
    ("delete_file", {"path": "Documents/cu"}),
    ("delete_file", {"path": "Documents/khong-co.txt"}),
])
def test_what_the_rules_forbid_is_refused_before_anyone_is_asked(place, tool, arguments) -> None:
    _, gate, _ = build(place)
    with pytest.raises(ApprovalError):
        ask(gate, tool, arguments)
    assert gate._pending == {}


def test_the_tool_never_runs_without_an_approved_plan(place) -> None:
    agent, _, _ = build(place)
    arguments = {"path": "Documents/moi.md", "content": "x"}
    assert json.loads(agent._execute_tool("write_file", arguments, dict(OWNER)))["code"] == "APPROVAL_REQUIRED"
    text, code, _ = agent.run_approved("write_file", arguments, dict(OWNER))
    assert code == "TOOL_UNAVAILABLE_HERE" and not (place.docs / "moi.md").exists()


def test_the_same_call_twice_is_one_card_and_five_is_the_most(place) -> None:
    _, gate, _ = build(place)
    first = ask(gate, "write_file", {"path": "Documents/a.md", "content": "x"})
    assert ask(gate, "write_file", {"path": "Documents/a.md", "content": "x"}) == first
    for number in range(4):
        ask(gate, "write_file", {"path": f"Documents/b{number}.md", "content": "x"})
    with pytest.raises(ApprovalError) as refused:
        ask(gate, "write_file", {"path": "Documents/c.md", "content": "x"})
    assert refused.value.code == "TOO_MANY_PENDING"


# ── approve, deny, expire ────────────────────────────────────────────────────


def test_approving_writes_once_and_notes_it_in_the_conversation(place) -> None:
    _, gate, notes = build(place)
    approval = ask(gate, "write_file", {"path": "Documents/moi.md", "content": "# Mới\n"})
    done = gate.decide(approval, True)
    assert done["status"] == "done" and done["result"]["change_id"]
    assert (place.docs / "moi.md").read_text(encoding="utf-8") == "# Mới\n"
    assert notes == [("c1", "Đã làm sau khi bạn duyệt: Tạo tệp mới Documents/moi.md (6 ký tự).")]
    with pytest.raises(ApprovalError) as again:
        gate.decide(approval, True)
    assert again.value.code == "APPROVAL_NOT_PENDING"


def test_two_clicks_at_the_same_moment_run_it_once(place) -> None:
    import threading

    _, gate, _ = build(place)
    approval = ask(gate, "write_file", {"path": "Documents/mot-lan.md", "content": "x"})
    ran: list = []
    original = gate.run_approved
    gate.run_approved = lambda *args: ran.append(1) or original(*args)
    start = threading.Barrier(8)
    outcomes: list = []

    def click() -> None:
        start.wait()
        try:
            outcomes.append(gate.decide(approval, True)["status"])
        except ApprovalError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=click) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert ran == [1] and outcomes.count("done") == 1 and outcomes.count("APPROVAL_NOT_PENDING") == 7


def test_denying_or_letting_it_expire_changes_nothing_and_a_denial_is_noted(place) -> None:
    _, gate, notes = build(place)
    denied = ask(gate, "delete_file", {"path": "Downloads/hoa-don.txt"})
    assert gate.decide(denied, False)["status"] == "denied"
    late = ask(gate, "write_file", {"path": "Documents/ghi chu.md", "content": "mới"})
    gate.clock = lambda: 10**12
    with pytest.raises(ApprovalError) as expired:
        gate.decide(late, True)
    assert expired.value.code == "APPROVAL_EXPIRED"
    assert (place.downloads / "hoa-don.txt").exists() and (place.docs / "ghi chu.md").read_text(encoding="utf-8") == "bản cũ"
    assert notes == [("c1", "Bạn đã từ chối: Xoá tệp Downloads/hoa-don.txt (giữ 3 ngày để hoàn tác). Chưa làm gì.")]


def test_if_the_file_changed_after_the_card_was_shown_nothing_runs_and_that_is_noted(place) -> None:
    _, gate, notes = build(place)
    approval = ask(gate, "write_file", {"path": "Documents/moi.md", "content": "của trợ lý"})
    (place.docs / "moi.md").write_text("người dùng vừa tạo", encoding="utf-8")
    result = gate.decide(approval, True)
    assert result["status"] == "failed" and "đã thay đổi" in result["result"]["error"]
    assert (place.docs / "moi.md").read_text(encoding="utf-8") == "người dùng vừa tạo"
    assert notes and notes[0][1].startswith("Chưa làm được: Tạo tệp mới Documents/moi.md")


def test_a_runnable_file_or_a_changed_extension_carries_a_warning(place) -> None:
    _, gate, _ = build(place)
    script = gate.get(ask(gate, "write_file", {"path": "Documents/chay.bat", "content": "echo hi"}))
    assert ".bat" in script["plan"]["warning"]
    renamed = gate.get(ask(gate, "move_file", {"path": "Documents/ghi chu.md", "to": "Documents/ghi chu.cmd"}))
    assert ".md sang .cmd" in renamed["plan"]["warning"] and "chạy được" in renamed["plan"]["warning"]
    plain = gate.get(ask(gate, "write_file", {"path": "Documents/thuong.md", "content": "x"}))
    assert "warning" not in plain["plan"]


def test_an_unknown_card_id_is_not_found(place) -> None:
    _, gate, _ = build(place)
    for bad in ("../x", "0" * 32):
        with pytest.raises(ApprovalError) as missing:
            gate.get(bad)
        assert missing.value.code == "APPROVAL_NOT_FOUND"


# ── every change can be undone, and an undo loses nothing either ─────────────


def run(gate, tool: str, arguments: dict) -> str:
    result = gate.decide(ask(gate, tool, arguments), True)
    assert result["status"] == "done", result
    return result["result"]["change_id"]


def kept(place) -> Path:
    (change,) = list(place.backup.iterdir())
    return change / "kept"


def test_an_overwrite_keeps_the_old_text_and_undo_puts_it_back(place) -> None:
    _, gate, _ = build(place)
    change = run(gate, "write_file", {"path": "Documents/ghi chu.md", "content": "bản mới"})
    assert (place.docs / "ghi chu.md").read_text(encoding="utf-8") == "bản mới"
    assert (kept(place) / "ghi chu.md").read_text(encoding="utf-8") == "bản cũ"
    assert "trở về bản trước" in gate.writes.undo(change)
    assert (place.docs / "ghi chu.md").read_text(encoding="utf-8") == "bản cũ"
    assert (kept(place) / "undone-ghi chu.md").read_text(encoding="utf-8") == "bản mới"
    with pytest.raises(Refused):
        gate.writes.undo(change)


def test_undoing_a_new_file_removes_it_but_keeps_a_copy(place) -> None:
    _, gate, _ = build(place)
    change = run(gate, "write_file", {"path": "Downloads/moi.txt", "content": "x"})
    gate.writes.undo(change)
    assert not (place.downloads / "moi.txt").exists()
    assert (kept(place) / "undone-moi.txt").read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("created", [True, False])
def test_undo_refuses_a_file_changed_by_hand_since_the_assistant_wrote_it(place, created) -> None:
    _, gate, _ = build(place)
    path = "Documents/moi.md" if created else "Documents/ghi chu.md"
    change = run(gate, "write_file", {"path": path, "content": "của trợ lý"})
    target = place.docs / path.split("/", 1)[1]
    target.write_text("người dùng sửa tiếp", encoding="utf-8")
    with pytest.raises(Refused) as refused:
        gate.writes.undo(change)
    assert "đã bị sửa sau khi trợ lý ghi" in refused.value.message
    assert target.read_text(encoding="utf-8") == "người dùng sửa tiếp"
    # Removed by hand instead: an overwrite comes back, a created file has nothing left to remove.
    target.unlink()
    gate.writes.undo(change)
    assert target.exists() is (not created)


@pytest.mark.parametrize("name", ["change.json", "Change.JSON"])
def test_a_file_named_like_the_change_record_is_kept_and_undone_whole(place, name) -> None:
    (place.docs / name).write_text('{"cua": "nguoi dung"}', encoding="utf-8")
    _, gate, _ = build(place)
    change = run(gate, "delete_file", {"path": f"Documents/{name}"})
    assert (kept(place) / name).read_text(encoding="utf-8") == '{"cua": "nguoi dung"}'
    gate.writes.undo(change)
    assert (place.docs / name).read_text(encoding="utf-8") == '{"cua": "nguoi dung"}'
    overwrite = run(gate, "write_file", {"path": f"Documents/{name}", "content": "{}"})
    gate.writes.undo(overwrite)
    assert (place.docs / name).read_text(encoding="utf-8") == '{"cua": "nguoi dung"}'


def test_a_move_into_a_folder_keeps_the_name_and_undo_moves_it_back(place) -> None:
    _, gate, _ = build(place)
    change = run(gate, "move_file", {"path": "Downloads/hoa-don.txt", "to": "Documents/cu"})
    assert (place.docs / "cu" / "hoa-don.txt").exists() and not (place.downloads / "hoa-don.txt").exists()
    gate.writes.undo(change)
    assert (place.downloads / "hoa-don.txt").read_text(encoding="utf-8") == "500.000 đồng"


def test_a_rename_works_for_any_kind_of_file(place) -> None:
    _, gate, _ = build(place)
    run(gate, "move_file", {"path": "Documents/bao-cao.pdf", "to": "Documents/cu/bao-cao-q3.pdf"})
    assert (place.docs / "cu" / "bao-cao-q3.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_a_delete_is_a_move_into_the_backup_and_undo_brings_it_back(place) -> None:
    _, gate, _ = build(place)
    change = run(gate, "delete_file", {"path": "Documents/bao-cao.pdf"})
    assert not (place.docs / "bao-cao.pdf").exists()
    gate.writes.undo(change)
    assert (place.docs / "bao-cao.pdf").read_bytes() == b"%PDF-1.4 fake"


@pytest.mark.parametrize("tool", ["delete_file", "move_file"])
def test_undoing_a_delete_or_a_move_does_not_overwrite_a_file_that_took_the_place(place, tool) -> None:
    _, gate, _ = build(place)
    arguments = {"path": "Downloads/hoa-don.txt"} | ({"to": "Documents/cu"} if tool == "move_file" else {})
    change = run(gate, tool, arguments)
    (place.downloads / "hoa-don.txt").write_text("tệp mới của người dùng", encoding="utf-8")
    with pytest.raises(Refused):
        gate.writes.undo(change)
    assert (place.downloads / "hoa-don.txt").read_text(encoding="utf-8") == "tệp mới của người dùng"


def test_changes_older_than_three_days_are_removed(place) -> None:
    now = [datetime(2026, 11, 12, tzinfo=UTC)]
    backups = local_file_writes.Backups(place.backup, clock=lambda: now[0])
    change_id, folder = backups.open({"tool": "delete_file", "path": "Documents/x", "state": "done"})
    now[0] += timedelta(days=2)
    assert backups.prune() == 0 and folder.exists()
    now[0] += timedelta(days=1, minutes=1)
    assert backups.prune() == 1 and not folder.exists()
    with pytest.raises(Refused):
        backups.find(change_id)


def test_what_an_undo_kept_lasts_three_days_from_the_undo(place) -> None:
    now = [datetime(2026, 11, 12, tzinfo=UTC)]
    _, gate, _ = build(place)
    gate.writes.backups.clock = lambda: now[0]
    change = run(gate, "write_file", {"path": "Documents/ghi chu.md", "content": "bản mới"})
    now[0] += timedelta(days=2, hours=23)
    gate.writes.undo(change)
    now[0] += timedelta(days=1)
    assert gate.writes.backups.prune() == 0 and (kept(place) / "undone-ghi chu.md").exists()
    now[0] += timedelta(days=2, minutes=1)
    assert gate.writes.backups.prune() == 1


def test_a_read_only_kept_file_is_still_removed_on_time(place) -> None:
    import os
    import stat as stat_module

    now = [datetime(2026, 11, 12, tzinfo=UTC)]
    _, gate, _ = build(place)
    gate.writes.backups.clock = lambda: now[0]
    run(gate, "delete_file", {"path": "Downloads/hoa-don.txt"})
    os.chmod(kept(place) / "hoa-don.txt", stat_module.S_IREAD)
    now[0] += timedelta(days=4)
    assert gate.writes.backups.prune() == 1 and list(place.backup.iterdir()) == []


def test_a_broken_change_record_is_a_refusal_not_a_crash(place) -> None:
    _, gate, _ = build(place)
    change = run(gate, "delete_file", {"path": "Downloads/hoa-don.txt"})
    (next(place.backup.iterdir()) / "change.json").write_text("{không phải json", encoding="utf-8")
    with pytest.raises(Refused) as refused:
        gate.writes.undo(change)
    assert "hỏng" in refused.value.message


# ── the conversation is told, and only on the owner's turn ───────────────────


class Store:
    def __init__(self) -> None:
        self.traces: list = []

    def conversation_exists(self, conversation_id):
        return True

    def get_messages(self, conversation_id, limit):
        return []

    def add_message(self, conversation_id, role, content, model_used=None, sources=None):
        return 7

    def add_agent_traces(self, conversation_id, message_id, steps, source="web"):
        self.traces.append(steps)


class Logging:
    def log_request(self, *args, **kwargs):
        pass


def test_the_owners_turn_carries_its_conversation_id_and_no_other_turn_does() -> None:
    from app.services.chat_service import ChatService

    seen: list = []
    chat = ChatService(Store(), router=None, logging_service=Logging(), history_limit=10)
    chat.agent_service = SimpleNamespace(run=lambda messages, tool_context=None, on_step=None: seen.append(tool_context) or ("ok", "m", []))
    chat.respond("ghi tệp", "c1", use_tools=True, tool_context=dict(OWNER))
    chat.respond("ghi tệp", "c1", use_tools=True)
    assert seen[0]["conversation_id"] == "c1"
    assert "conversation_id" not in (seen[1] or {})


# ── the card's routes ────────────────────────────────────────────────────────


def test_the_card_routes_answer_the_owner_only(place) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import local_files as route

    _, gate, _ = build(place)
    approval = ask(gate, "write_file", {"path": "Documents/moi.md", "content": "x"})
    app = FastAPI()
    app.state.settings = SimpleNamespace(agent_local_files_enabled=True, local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.local_file_approvals = gate
    app.include_router(route.router)
    here = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    elsewhere = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.168.1.20", 50000))

    def code(response) -> str:
        # A bare FastAPI app wraps HTTPException's detail; main.py's handler flattens it.
        return response.json()["detail"]["error_code"]

    assert elsewhere.get(f"/local-files/approvals/{approval}").status_code == 403
    assert here.get(f"/local-files/approvals/{approval}").json()["status"] == "pending"
    done = here.post(f"/local-files/approvals/{approval}", json={"approve": True}).json()
    assert done["status"] == "done" and (place.docs / "moi.md").exists()
    assert code(here.post(f"/local-files/approvals/{approval}", json={"approve": True})) == "APPROVAL_NOT_PENDING"
    undone = here.post(f"/local-files/changes/{done['result']['change_id']}/undo").json()
    assert undone["undone"] is True and not (place.docs / "moi.md").exists()
    assert code(here.post(f"/local-files/changes/{done['result']['change_id']}/undo")) == "UNDO_REFUSED"
    assert here.get("/local-files/approvals/" + "0" * 32).status_code == 404

    app.state.local_file_approvals = None
    assert code(here.get(f"/local-files/approvals/{approval}")) == "LOCAL_FILES_WRITE_DISABLED"


def test_a_reopened_conversation_gets_its_cards_back(place) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import local_files as route

    _, gate, _ = build(place)
    done = run(gate, "delete_file", {"path": "Downloads/hoa-don.txt"})
    waiting = ask(gate, "write_file", {"path": "Documents/moi.md", "content": "x"})
    ask(gate, "write_file", {"path": "Documents/khac.md", "content": "x"}, {"conversation_id": "c2"})
    app = FastAPI()
    app.state.settings = SimpleNamespace(agent_local_files_enabled=True, local_ai_auth_enabled=False, local_ai_api_key="")
    app.state.local_file_approvals = gate
    app.include_router(route.router)
    here = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    cards = here.get("/local-files/conversations/c1/cards").json()
    assert [item["id"] for item in cards["approvals"]] == [waiting]
    assert [(item["id"], item["state"], item["undoable"]) for item in cards["changes"]] == [(done, "done", True)]
    gate.writes.undo(done)
    assert here.get("/local-files/conversations/c1/cards").json()["changes"][0]["state"] == "undone"
    assert here.get("/local-files/conversations/c3/cards").json() == {"approvals": [], "changes": []}


@pytest.mark.parametrize(("auth", "role", "origin", "allowed"), [
    (True, "admin", None, True),
    (True, "member", None, False),
    (False, None, "http://evil.example", False),
])
def test_the_card_routes_follow_the_owner_rule(place, monkeypatch, auth, role, origin, allowed) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import chat as chat_route
    from app.routers import local_files as route
    from app.security.auth import ANONYMOUS, Identity

    _, gate, _ = build(place)
    approval = ask(gate, "write_file", {"path": "Documents/moi.md", "content": "x"})
    identity = Identity("user", user_id="1", username="u", role=role) if role else ANONYMOUS
    monkeypatch.setattr(chat_route, "resolve_identity", lambda request: identity)
    app = FastAPI()
    app.state.settings = SimpleNamespace(agent_local_files_enabled=True, local_ai_auth_enabled=auth, local_ai_api_key="")
    app.state.local_file_approvals = gate
    app.include_router(route.router)
    # The key layer is tested elsewhere; this is about who counts as the owner once past it.
    from app.security.api_key import require_api_key

    app.dependency_overrides[require_api_key] = lambda: None
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    headers = {"origin": origin} if origin else {}
    response = client.post(f"/local-files/approvals/{approval}", json={"approve": True}, headers=headers)
    assert (response.status_code == 200) is allowed
    assert (place.docs / "moi.md").exists() is allowed
