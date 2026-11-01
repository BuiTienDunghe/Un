"""Ticket 46: the bot's half of approvals — Duyệt / Từ chối buttons and /approvals.

Off by default and silent when off; only the member the call belongs to can press; a second press runs
nothing; a button dies with its deadline; the call is shown whole and cannot ping. No Discord, no backend.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import httpx

from discord_bot import approvals as module
from discord_bot.api_client import (
    BackendApproval, BackendApprovalDecision, BackendResponseError, BackendUnavailableError, LocalAgentClient, LocalAgentSettings,
)
from discord_bot.approvals import ApprovalView, fenced, format_approval, format_decision, offer_buttons, seconds_left
from discord_bot.main import DiscordConversationGateway, DiscordSettings, PreparedDiscordAnswer, answer_mention, create_bot

HOME, OTHER = "111", "222"
ME, YOU = "900", "901"
TURN = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ID = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
NOTICE = "Mình cần bạn duyệt trước khi làm việc này.\nCông cụ: send_note\nMã duyệt: bbbbbbbb\n"


def run(coroutine):
    return asyncio.run(coroutine)


def approval(arguments: str = '{"text": "Họp lúc 9h"}', *, requester: str = ME, minutes: float = 10, turn: str | None = TURN) -> BackendApproval:
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return BackendApproval(ID, ID[:8], HOME, "55", requester, "send_note", arguments, expires.isoformat(), turn)


class FakeApi:
    def __init__(self, waiting: list[BackendApproval] | None = None) -> None:
        self.waiting = waiting or []
        self.listed: list[tuple[str, str]] = []
        self.decided: list[tuple[str, str, str, bool]] = []
        self.error: Exception | None = None
        self.decision = BackendApprovalDecision("done", "send_note", '{"sent": "Họp lúc 9h"}')
        # Holds the first decision open, as a tool that takes a while would; a later one is never held.
        self.gate: asyncio.Event | None = None

    async def list_approvals(self, guild_id, author_id):
        self.listed.append((guild_id, author_id))
        return list(self.waiting)

    async def decide_approval(self, approval_id, guild_id, actor_id, *, approve):
        self.decided.append((approval_id, guild_id, actor_id, approve))
        if self.gate is not None and len(self.decided) == 1:
            await self.gate.wait()
        if self.error:
            raise self.error
        return BackendApprovalDecision("done" if approve else "denied", "send_note", self.decision.text if approve else None)


class Response:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []
        self.edited: list[object] = []
        self.deferred = False

    async def send_message(self, text, ephemeral=False, **_):
        self.sent.append((text, ephemeral))

    async def edit_message(self, **kwargs):
        assert kwargs["allowed_mentions"].everyone is False  # restated on every edit, as progress_message.py does
        self.edited.append(kwargs.get("view"))

    async def defer(self, thinking=False, ephemeral=False):
        self.deferred = True


class Followup:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, content, ephemeral=False, **kwargs):
        self.sent.append({"content": content, "ephemeral": ephemeral, **kwargs})
        return SimpleNamespace(edit=self.sent_message_edit)

    async def sent_message_edit(self, **kwargs):
        return None


def click(user: str = ME) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=int(user)), response=Response(), followup=Followup(), guild_id=int(HOME))


async def press(view: ApprovalView, button, interaction) -> None:
    """What discord.py does on a click: the check first, the callback only if it passes."""
    if await view.interaction_check(interaction):
        await button.callback(interaction)


class Message:
    def __init__(self) -> None:
        self.edits: list[dict] = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self


# ---- how a waiting call is shown ----

def test_the_call_is_shown_whole_in_a_block_it_cannot_leave_and_cannot_ping() -> None:
    nasty = '{"text": "@everyone <@123> ``` xin chào ````"}'
    text = format_approval(approval(nasty))
    assert nasty in text  # whole, character for character
    fence = text.split("\n")[1]
    assert set(fence) == {"`"} and len(fence) > 4  # longer than any run of backticks inside
    assert text.count(fence) == 2  # opened once, closed once
    assert fenced("a") == "```\na\n```"


def test_a_decision_is_worded_by_what_happened_and_shows_the_result_clipped() -> None:
    assert "từ chối" in format_decision(BackendApprovalDecision("denied", "send_note"))
    done = format_decision(BackendApprovalDecision("done", "send_note", "x" * 5000))
    assert "Đã chạy `send_note`" in done and len(done) < 1700
    failed = format_decision(BackendApprovalDecision("failed", "send_note", None, "TOOL_FAILED"))
    assert "không thành công" in failed and "TOOL_FAILED" in failed


# ---- who can press, and how often ----

def test_somebody_else_pressing_is_told_so_privately_and_nothing_is_sent_or_switched_off() -> None:
    async def scenario():
        api = FakeApi()
        view = ApprovalView(api, approval(), timeout=600)
        stranger = click(YOU)
        await press(view, view.approve, stranger)
        await press(view, view.deny, stranger)
        return api, view, stranger

    api, view, stranger = run(scenario())
    assert api.decided == []
    assert stranger.response.sent == [(module.NOT_YOURS, True), (module.NOT_YOURS, True)]
    assert stranger.response.edited == [] and not any(item.disabled for item in view.children)


def test_the_member_presses_yes_and_the_backend_is_asked_once_as_that_member() -> None:
    async def scenario():
        api = FakeApi()
        view = ApprovalView(api, approval(), timeout=600)
        mine = click(ME)
        await press(view, view.approve, mine)
        return api, view, mine

    api, view, mine = run(scenario())
    assert api.decided == [(ID, HOME, ME, True)]
    assert all(item.disabled for item in view.children) and mine.response.edited == [view]
    (sent,) = mine.followup.sent
    assert "Đã chạy `send_note`" in sent["content"] and sent["allowed_mentions"].everyone is False
    assert sent["allowed_mentions"].users is False and sent["allowed_mentions"].roles is False


def test_no_sends_a_denial_and_runs_nothing_else() -> None:
    async def scenario():
        api = FakeApi()
        view = ApprovalView(api, approval(), timeout=600)
        mine = click(ME)
        await press(view, view.deny, mine)
        return api, mine

    api, mine = run(scenario())
    assert api.decided == [(ID, HOME, ME, False)] and "từ chối" in mine.followup.sent[0]["content"]


def test_pressing_twice_asks_the_backend_once_even_while_the_first_is_still_waiting() -> None:
    async def scenario():
        api = FakeApi()
        api.gate = asyncio.Event()
        view = ApprovalView(api, approval(), timeout=600)
        first, second, third = click(ME), click(ME), click(ME)
        slow = asyncio.create_task(press(view, view.approve, first))
        await asyncio.sleep(0)
        await press(view, view.approve, second)  # yes again, while the tool is still running
        await press(view, view.deny, third)  # and a no
        api.gate.set()
        await slow
        return api, first, second, third

    api, first, second, third = run(scenario())
    assert api.decided == [(ID, HOME, ME, True)]
    assert second.response.sent == [(module.ALREADY_PRESSED, True)] and third.response.sent == [(module.ALREADY_PRESSED, True)]


def test_a_refusal_from_the_backend_is_shown_privately_and_the_buttons_stay_off() -> None:
    async def scenario():
        api = FakeApi()
        api.error = BackendResponseError("Việc này đã quá hạn duyệt nên bị huỷ, không chạy.")
        view = ApprovalView(api, approval(), timeout=600)
        mine = click(ME)
        await press(view, view.approve, mine)
        again = click(ME)
        await press(view, view.approve, again)
        return api, view, mine, again

    api, view, mine, again = run(scenario())
    (sent,) = mine.followup.sent
    assert sent["ephemeral"] is True and "quá hạn" in sent["content"] and "/approvals" in sent["content"]
    assert all(item.disabled for item in view.children) and len(api.decided) == 1


# ---- the deadline ----

def test_the_buttons_live_as_long_as_the_call_does_and_switch_off_with_it() -> None:
    now = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
    waiting = approval(minutes=0)
    waiting = BackendApproval(**{**waiting.__dict__, "expires_at": (now + timedelta(minutes=10)).isoformat()})
    assert seconds_left(waiting, now) == 600 and seconds_left(waiting, now + timedelta(minutes=11)) == 0
    assert seconds_left(BackendApproval(**{**waiting.__dict__, "expires_at": "not a date"})) == 0

    async def scenario():
        view = ApprovalView(FakeApi(), approval(), timeout=seconds_left(waiting, now))
        view.message = Message()
        timeout = view.timeout
        await view.on_timeout()
        return timeout, view

    timeout, view = run(scenario())
    assert timeout == 600
    assert all(item.disabled for item in view.children)
    (edit,) = view.message.edits
    assert edit["view"] is view and edit["allowed_mentions"].everyone is False


def test_a_button_pressed_before_the_timeout_is_not_edited_again_by_it() -> None:
    async def scenario():
        view = ApprovalView(FakeApi(), approval(), timeout=600)
        view.message = Message()
        await press(view, view.deny, click(ME))
        await view.on_timeout()
        return view

    assert run(scenario()).message.edits == []


# ---- putting the buttons on the answer ----

def test_buttons_go_on_the_answer_that_asks_and_only_for_the_turn_that_asked() -> None:
    async def scenario(waiting, answer):
        api, message = FakeApi(waiting), Message()
        await offer_buttons(api, message, guild_id=HOME, author_id=ME, turn_id=TURN, answer=answer)
        return api, message

    api, message = run(scenario([approval()], NOTICE))
    assert api.listed == [(HOME, ME)]
    (edit,) = message.edits
    assert isinstance(edit["view"], ApprovalView) and edit["allowed_mentions"].everyone is False

    api, message = run(scenario([approval(turn="cccccccc-3333-4333-8333-cccccccccccc")], NOTICE))
    assert message.edits == []  # somebody else's turn, or an older one: not this answer's call


def test_an_ordinary_answer_costs_no_request_at_all() -> None:
    async def scenario():
        api, message = FakeApi([approval()]), Message()
        await offer_buttons(api, message, guild_id=HOME, author_id=ME, turn_id=TURN, answer="Chào bạn, hôm nay trời đẹp.")
        await offer_buttons(api, message, guild_id=HOME, author_id=ME, turn_id=None, answer=NOTICE)
        return api, message

    api, message = run(scenario())
    assert api.listed == [] and message.edits == []


def test_a_backend_that_fails_does_not_break_the_answer_that_is_already_out() -> None:
    async def scenario():
        class Down(FakeApi):
            async def list_approvals(self, guild_id, author_id):
                raise BackendUnavailableError("down")

        class Broken(Message):
            async def edit(self, **kwargs):
                raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "missing access")

        await offer_buttons(Down(), Message(), guild_id=HOME, author_id=ME, turn_id=TURN, answer=NOTICE)
        await offer_buttons(FakeApi([approval()]), Broken(), guild_id=HOME, author_id=ME, turn_id=TURN, answer=NOTICE)

    run(scenario())  # no exception


# ---- off by default ----

def test_off_there_is_no_command_and_the_bot_never_calls_an_approvals_gate(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.delenv("DISCORD_APPROVALS_ENABLED", raising=False)
    assert DiscordSettings.from_env().approvals_enabled is False
    api = FakeApi([approval()])
    bot = create_bot(api, "system", 0, docs_guild_allowlist=frozenset({HOME}))
    assert bot.tree.get_command("approvals") is None
    gateway = DiscordConversationGateway(api, "system", 0, True)
    assert gateway.approvals_enabled is False
    prepared = PreparedDiscordAnswer(NOTICE, TURN, "token")
    run(gateway.offer_approvals(prepared, [Message()], SimpleNamespace(id=int(HOME)), int(ME)))
    assert api.listed == [] and api.decided == []
    monkeypatch.setenv("DISCORD_APPROVALS_ENABLED", "true")
    assert DiscordSettings.from_env().approvals_enabled is True


def test_on_the_gateway_asks_only_in_a_server_and_only_with_something_to_attach_to() -> None:
    async def scenario():
        api = FakeApi([approval()])
        gateway = DiscordConversationGateway(api, "system", 0, True, approvals_enabled=True)
        prepared = PreparedDiscordAnswer(NOTICE, TURN, "token")
        await gateway.offer_approvals(prepared, [Message()], None, int(ME))  # a direct message
        await gateway.offer_approvals(prepared, [], SimpleNamespace(id=int(HOME)), int(ME))  # nothing was sent
        asked_before = list(api.listed)
        message = Message()
        await gateway.offer_approvals(prepared, [Message(), message], SimpleNamespace(id=int(HOME)), int(ME))
        return asked_before, api, message

    asked_before, api, message = run(scenario())
    assert asked_before == [] and api.listed == [(HOME, ME)]
    assert len(message.edits) == 1  # the last chunk carries the buttons


def mention_turn(api: FakeApi, *, enabled: bool):
    """A whole @mention turn through answer_mention, with the backend's reply to it scripted."""
    class Typing:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    reply = Message()
    completed = []

    class Progress:
        async def replace(self, content):
            return None

        async def fail(self, text):
            raise AssertionError(text)

        async def discard(self):
            raise AssertionError("discarded")

    async def prepare(*args, **kwargs):
        return PreparedDiscordAnswer(NOTICE, TURN, "token")

    async def delivered(prepared, ids):
        completed.append(ids)

    async def send_reply(content, mention_author=False):
        reply.content = content
        return reply

    gateway = DiscordConversationGateway(api, "system", 0, True, approvals_enabled=enabled)
    gateway.prepare, gateway.delivered = prepare, delivered
    message = SimpleNamespace(
        id=5, content="gửi ghi chú", author=SimpleNamespace(id=int(ME), display_name="Me"), guild=SimpleNamespace(id=int(HOME)),
        channel=SimpleNamespace(typing=Typing), reference=None, reply=send_reply,
    )
    reply.id = 77
    run(answer_mention(gateway, message, "gửi ghi chú", Progress()))
    return reply, completed


def test_through_a_whole_turn_the_buttons_appear_only_when_switched_on() -> None:
    api = FakeApi([approval()])
    reply, completed = mention_turn(api, enabled=True)
    assert api.listed == [(HOME, ME)] and completed == [["77"]]
    assert isinstance(reply.edits[0]["view"], ApprovalView)

    api = FakeApi([approval()])
    reply, completed = mention_turn(api, enabled=False)
    assert api.listed == [] and api.decided == [] and reply.edits == [] and completed == [["77"]]


# ---- /approvals ----

def approvals_command(api: FakeApi, *, guild: str | None = HOME, user: str = ME, allowlist=frozenset({HOME})):
    bot = create_bot(api, "system", 0, docs_guild_allowlist=allowlist, approvals_enabled=True)
    call = SimpleNamespace(
        guild_id=None if guild is None else int(guild), user=SimpleNamespace(id=int(user)), response=Response(), followup=Followup(),
    )

    async def scenario():
        await bot.tree.get_command("approvals").callback(call)

    run(scenario())
    return call


def test_the_command_lists_what_is_waiting_for_the_asker_with_buttons_only_they_see() -> None:
    api = FakeApi([approval('{"text": "một"}'), approval('{"text": "hai"}')])
    call = approvals_command(api)
    assert api.listed == [(HOME, ME)] and call.response.deferred
    assert len(call.followup.sent) == 2
    for sent in call.followup.sent:
        assert sent["ephemeral"] is True and isinstance(sent["view"], ApprovalView) and sent["allowed_mentions"].everyone is False
    assert '{"text": "một"}' in call.followup.sent[0]["content"]


def test_the_command_says_so_when_nothing_is_waiting_and_refuses_outside_the_list() -> None:
    api = FakeApi()
    assert "không có việc nào" in approvals_command(api).followup.sent[0]["content"]
    outside = approvals_command(FakeApi(), guild=OTHER)
    assert outside.response.sent == [("Lệnh này chưa bật ở server này.", True)]
    direct = approvals_command(FakeApi(), guild=None, allowlist=None)
    assert direct.response.sent == [("Lệnh này chỉ dùng trong server.", True)]


def test_the_command_shows_the_backends_refusal_privately() -> None:
    class Off(FakeApi):
        async def list_approvals(self, guild_id, author_id):
            raise BackendResponseError("Xin duyệt đang tắt.")

    call = approvals_command(Off())
    assert call.followup.sent == [{"content": "Xin duyệt đang tắt.", "ephemeral": True}]


# ---- the HTTP client ----

def client_for(handler) -> LocalAgentClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend")
    return LocalAgentClient(LocalAgentSettings("http://backend", api_key="k"), http)


ROW = {
    "id": ID, "short_id": ID[:8], "guild_id": HOME, "channel_id": "55", "requester_id": ME, "tool_name": "send_note",
    "arguments": '{"text": "Họp lúc 9h"}', "expires_at": "2026-11-02T03:10:00+00:00", "status": "pending", "source_turn_id": TURN,
}


def test_the_list_is_asked_with_the_member_and_a_malformed_row_is_dropped() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, params=dict(request.url.params), key=request.headers.get("X-API-Key"))
        return httpx.Response(200, json=[ROW, {"id": "broken"}, "junk", {**ROW, "source_turn_id": None}])

    first, second = run(client_for(handler).list_approvals(HOME, ME))
    assert seen == {"path": "/api/discord/approvals", "params": {"guild_id": HOME, "author_id": ME}, "key": "k"}
    assert first.source_turn_id == TURN and first.arguments == '{"text": "Họp lúc 9h"}' and second.source_turn_id is None


def test_a_decision_goes_to_the_right_path_as_the_member_and_its_answer_is_checked() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/deny"):
            return httpx.Response(200, json={"status": "denied", "tool_name": "send_note", "text": None, "code": None})
        if request.url.path.endswith("/approve") and len(seen) > 2:
            return httpx.Response(200, json={"status": 5})
        return httpx.Response(200, json={"status": "done", "tool_name": "send_note", "text": "{}", "code": None})

    client = client_for(handler)
    assert run(client.decide_approval(ID, HOME, ME, approve=True)) == BackendApprovalDecision("done", "send_note", "{}", None)
    assert run(client.decide_approval(ID, HOME, ME, approve=False)).status == "denied"
    assert seen == [(f"/api/discord/approvals/{ID}/approve", {"guild_id": HOME, "actor_id": ME}), (f"/api/discord/approvals/{ID}/deny", {"guild_id": HOME, "actor_id": ME})]
    try:
        run(client.decide_approval(ID, HOME, ME, approve=True))
    except BackendResponseError as error:
        assert "invalid approval decision" in str(error)
    else:
        raise AssertionError("an answer that is not a decision must not be taken for one")


def test_a_refusal_carries_the_backends_own_words() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": True, "error_code": "APPROVAL_NOT_YOURS", "message": "Chỉ người nhờ việc này mới duyệt hoặc từ chối được."})

    try:
        run(client_for(handler).decide_approval(ID, HOME, YOU, approve=True))
    except BackendResponseError as error:
        assert str(error) == "Chỉ người nhờ việc này mới duyệt hoặc từ chối được."
    else:
        raise AssertionError("a 403 must raise")
