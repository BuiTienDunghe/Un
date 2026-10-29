"""Ticket 20 #4, D2: one "⏳" reply that follows the turn's steps and becomes the answer."""
from __future__ import annotations

import asyncio
import contextlib
from time import monotonic
from types import SimpleNamespace

import discord
import httpx
import pytest

from discord_bot.api_client import (
    BackendDiscordSession,
    BackendDiscordTurn,
    BackendDiscordTurnExecution,
    BackendResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
    LocalAgentClient,
    LocalAgentSettings,
)
from discord_bot.main import DiscordConversationGateway, answer_mention
from discord_bot.progress_message import PREFIX, WORKING_LABEL, ProgressMessage


THINKING = "Đang suy nghĩ…"
SEARCHING = "Đang tra tài liệu…"
WRITING = "Đang viết câu trả lời…"


def http_error(kind: type[discord.HTTPException], status: int) -> discord.HTTPException:
    return kind(SimpleNamespace(status=status, reason="test"), "test")


async def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        if monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


class Discord:
    """The Discord side: every message the bot posted, and every write, in order."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, int, str | None, float]] = []
        self.messages: dict[int, FakeMessage] = {}
        self._next_id = 1000

    def new_message(self, content: str) -> "FakeMessage":
        self._next_id += 1
        message = FakeMessage(self, self._next_id, content)
        self.messages[message.id] = message
        return message

    def log(self, kind: str, message_id: int, content: str | None) -> None:
        self.writes.append((kind, message_id, content, monotonic()))

    def kinds(self) -> list[str]:
        return [write[0] for write in self.writes]


class FakeMessage:
    def __init__(self, discord_side: Discord, message_id: int, content: str) -> None:
        self.discord_side, self.id, self.content = discord_side, message_id, content
        self.deleted = False
        self.edit_attempts = 0
        self.edit_errors: list[Exception] = []

    async def edit(self, *, content, allowed_mentions):
        # Today's first chunk is reply(..., mention_author=False): an edit restates it.
        assert allowed_mentions.replied_user is False
        self.edit_attempts += 1
        if self.edit_errors:
            raise self.edit_errors.pop(0)
        self.content = content
        self.discord_side.log("edit", self.id, content)
        # discord.py returns a new object for the same message.
        return SimpleNamespace(id=self.id, edit=self.edit, delete=self.delete)

    async def delete(self):
        self.deleted = True
        self.discord_side.log("delete", self.id, None)


class FakeChannel:
    def __init__(self, discord_side: Discord) -> None:
        self.discord_side = discord_side
        self.id = 20
        self.type = discord.ChannelType.text

    async def send(self, content):
        message = self.discord_side.new_message(content)
        self.discord_side.log("send", message.id, content)
        return message

    def typing(self):
        return contextlib.nullcontext()


class FakeSource:
    """The asker's message."""

    def __init__(self, discord_side: Discord) -> None:
        self.discord_side = discord_side
        self.id = 500
        self.reference = None
        self.guild = SimpleNamespace(id=10, name="Guild", member_count=0, members=[])
        self.channel = FakeChannel(discord_side)
        self.author = SimpleNamespace(id=30, display_name="Dũng")
        self.reply_errors: list[Exception] = []

    async def reply(self, content, *, mention_author):
        assert mention_author is False
        if self.reply_errors:
            raise self.reply_errors.pop(0)
        message = self.discord_side.new_message(content)
        self.discord_side.log("reply", message.id, content)
        return message


def running(answer: str, turn_id: str = "turn") -> BackendDiscordTurnExecution:
    return BackendDiscordTurnExecution(turn_id, "session", 1, "running", answer, "model", "token", None)


def state(status: str, turn_id: str = "turn", replacement: str | None = None) -> BackendDiscordTurnExecution:
    return BackendDiscordTurnExecution(turn_id, "session", 1, status, None, None, None, replacement)


class FakeBackend:
    """Execute returns `executions` in order; before each, it awaits the matching entry of
    `gates` (a predicate on the Discord side), which is how a turn is made long. Progress
    polls return `labels` in order, then the last one again."""

    def __init__(self, executions, *, gates=None, labels=(), discord_side: Discord | None = None) -> None:
        self.executions = list(executions)
        self.gates = list(gates or [])
        self.labels = list(labels)
        self.calls: list[tuple] = []
        self.progress_polls: list[str] = []
        self.completion_failures = 0

    async def resolve_discord_session(self, guild_id, channel_id, thread_id=None):
        return BackendDiscordSession("session", "conversation", False, "active")

    async def enqueue_discord_turn(self, session_id, message_id, message, **_):
        return BackendDiscordTurn("turn", session_id, 1, "queued", True)

    async def execute_discord_turn(self, turn_id):
        self.calls.append(("execute", turn_id))
        gate = self.gates.pop(0) if self.gates else None
        if gate is not None:
            await wait_until(gate)
        outcome = self.executions.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def get_discord_turn_progress(self, turn_id):
        self.progress_polls.append(turn_id)
        label = self.labels.pop(0) if len(self.labels) > 1 else (self.labels[0] if self.labels else None)
        if isinstance(label, Exception):
            raise label
        return SimpleNamespace(turn_id=turn_id, running=label is not None, label=label)

    async def complete_discord_turn(self, turn_id, token, response_message_ids):
        self.calls.append(("complete", turn_id, token, tuple(response_message_ids)))
        if self.completion_failures:
            self.completion_failures -= 1
            raise BackendTimeoutError("completion response was lost")
        return "completed"

    async def fail_discord_turn(self, turn_id, token, error, *, retryable):
        self.calls.append(("fail", turn_id, token, error, retryable))
        return "queued" if retryable else "failed"

    def completions(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "complete"]


EDIT_INTERVAL = 0.05


def quick(source, **overrides) -> ProgressMessage:
    # Production's 2 s / 1.5 s / 1.5 s, scaled down: polls as often as edits may happen, so
    # every label a poll sees gets its own edit.
    timings = {"first_post_seconds": 0.05, "poll_seconds": 0.05, "edit_interval_seconds": EDIT_INTERVAL, **overrides}
    return ProgressMessage(source, **timings)


def run(backend: FakeBackend, source: FakeSource, progress: ProgressMessage, question: str = "câu hỏi") -> None:
    gateway = DiscordConversationGateway(backend, "prompt", 0, True, poll_budget_seconds=10)
    asyncio.run(answer_mention(gateway, source, question, progress))


def progress_posted(discord_side: Discord):
    return lambda: "reply" in discord_side.kinds()


def shows(discord_side: Discord, text: str):
    return lambda: any(message.content == text for message in discord_side.messages.values())


def test_short_turn_sends_the_answer_and_never_posts_progress():
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([running("trả lời nhanh")], labels=[THINKING])

    run(backend, source, quick(source, first_post_seconds=1.0))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [("reply", "trả lời nhanh")]
    # The watcher still slept when the answer came: it never asked for progress either.
    assert backend.progress_polls == []
    reply_id = discord_side.writes[0][1]
    assert backend.completions() == [("complete", "turn", "token", (str(reply_id),))]


def test_long_turn_posts_once_follows_each_new_label_then_becomes_the_answer():
    discord_side = Discord()
    source = FakeSource(discord_side)
    labels = [
        THINKING, THINKING,
        SEARCHING,
        None,  # between two events: the last label stays
        BackendUnavailableError("poll failed"),  # a failed poll changes nothing
        WRITING,
    ]
    backend = FakeBackend(
        [running("câu trả lời")],
        gates=[shows(discord_side, PREFIX + WRITING)],
        labels=labels,
    )

    run(backend, source, quick(source))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + THINKING),
        ("edit", PREFIX + SEARCHING),
        ("edit", PREFIX + WRITING),
        ("edit", "câu trả lời"),
    ]
    assert len({message_id for _, message_id, _, _ in discord_side.writes}) == 1
    times = [at for *_, at in discord_side.writes]
    assert all(later - earlier >= EDIT_INTERVAL for earlier, later in zip(times, times[1:]))
    progress_id = discord_side.writes[0][1]
    assert backend.completions() == [("complete", "turn", "token", (str(progress_id),))]
    assert set(backend.progress_polls) == {"turn"}


def test_long_turn_without_steps_shows_the_working_text():
    # A plain-chat turn, or one queued behind another, reports no label.
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([running("xong")], gates=[progress_posted(discord_side)], labels=[None])

    run(backend, source, quick(source))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + WORKING_LABEL),
        ("edit", "xong"),
    ]


def test_long_answer_edits_the_first_chunk_in_and_sends_the_rest():
    discord_side = Discord()
    source = FakeSource(discord_side)
    answer = ("dòng trả lời dài\n" * 300).strip()
    backend = FakeBackend([running(answer)], gates=[progress_posted(discord_side)], labels=[THINKING])

    run(backend, source, quick(source))

    kinds = discord_side.kinds()
    assert kinds[0] == "reply" and kinds[1] == "edit" and set(kinds[2:]) == {"send"} and len(kinds) >= 4
    assert all(len(content) <= 2_000 for _, _, content, _ in discord_side.writes)
    edited = discord_side.writes[1]
    assert edited[1] == discord_side.writes[0][1]
    delivered = [edited[2]] + [content for kind, _, content, _ in discord_side.writes if kind == "send"]
    assert "\n".join(delivered).split() == answer.split()
    ids = tuple(str(message_id) for kind, message_id, _, _ in discord_side.writes if kind != "reply")
    assert backend.completions() == [("complete", "turn", "token", ids)]


@pytest.mark.parametrize(
    ("outcome", "text"),
    [
        (state("failed"), "Discord turn ended with status failed."),
        (state("cancelled"), "Discord turn ended with status cancelled."),
        (BackendTimeoutError("Discord turn execution timed out. Please try again later."),
         "Discord turn execution timed out. Please try again later."),
    ],
)
def test_failed_turn_turns_the_progress_message_into_todays_error_text(outcome, text):
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([outcome], gates=[progress_posted(discord_side)], labels=[THINKING])

    run(backend, source, quick(source))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + THINKING),
        ("edit", text),
    ]
    assert backend.completions() == []


def test_failed_short_turn_replies_with_the_error_as_today():
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([state("failed")])

    run(backend, source, quick(source, first_post_seconds=1.0))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", "Discord turn ended with status failed."),
    ]


def test_turn_with_nothing_to_send_removes_the_progress_message():
    # "completed": an earlier delivery already answered this turn, and today sends nothing.
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([state("completed")], gates=[progress_posted(discord_side)], labels=[THINKING])

    run(backend, source, quick(source))

    assert discord_side.kinds() == ["reply", "delete"]


def test_unexpected_error_removes_the_progress_message_and_still_raises():
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend([RuntimeError("bug")], gates=[progress_posted(discord_side)], labels=[THINKING])

    with pytest.raises(RuntimeError, match="bug"):
        run(backend, source, quick(source))

    assert discord_side.kinds() == ["reply", "delete"]


def test_progress_message_deleted_by_a_user_answer_goes_out_as_a_new_reply():
    discord_side = Discord()
    source = FakeSource(discord_side)

    def deleted_then_posted():
        if "reply" not in discord_side.kinds():
            return False
        next(iter(discord_side.messages.values())).edit_errors.append(http_error(discord.NotFound, 404))
        return True

    backend = FakeBackend([running("câu trả lời")], gates=[deleted_then_posted], labels=[THINKING])

    run(backend, source, quick(source))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + THINKING),
        ("reply", "câu trả lời"),
    ]
    answer_id = discord_side.writes[1][1]
    assert backend.completions() == [("complete", "turn", "token", (str(answer_id),))]


@pytest.mark.parametrize("error", [http_error(discord.Forbidden, 403), http_error(discord.HTTPException, 500)])
def test_progress_message_that_cannot_be_edited_is_removed_and_the_answer_replied(error):
    discord_side = Discord()
    source = FakeSource(discord_side)

    def broken_then_posted():
        if "reply" not in discord_side.kinds():
            return False
        next(iter(discord_side.messages.values())).edit_errors.append(error)
        return True

    backend = FakeBackend([running("câu trả lời")], gates=[broken_then_posted], labels=[THINKING])

    run(backend, source, quick(source))

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + THINKING),
        ("delete", None),
        ("reply", "câu trả lời"),
    ]


def test_progress_message_deleted_midway_is_never_posted_again():
    discord_side = Discord()
    source = FakeSource(discord_side)
    armed: list[FakeMessage] = []

    def deleted_then_edit_tried():
        # The progress message vanishes right after its post; the turn ends once the
        # watcher has tried to show SEARCHING on it, and then for a while longer.
        if not armed and "reply" in discord_side.kinds():
            armed.append(next(iter(discord_side.messages.values())))
            armed[0].edit_errors.append(http_error(discord.NotFound, 404))
        return bool(armed) and armed[0].edit_attempts >= 1 and len(backend.progress_polls) >= 2

    backend = FakeBackend(
        [running("câu trả lời")],
        gates=[deleted_then_edit_tried],
        labels=[THINKING, SEARCHING],
    )

    async def scenario():
        gateway = DiscordConversationGateway(backend, "prompt", 0, True, poll_budget_seconds=10)
        progress = quick(source)
        original = backend.execute_discord_turn

        async def execute_then_linger(turn_id):
            outcome = await original(turn_id)
            # Several poll intervals: a watcher still alive would poll and post again.
            await asyncio.sleep(0.2)
            return outcome

        backend.execute_discord_turn = execute_then_linger
        await answer_mention(gateway, source, "câu hỏi", progress)

    asyncio.run(scenario())

    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [
        ("reply", PREFIX + THINKING),
        ("reply", "câu trả lời"),
    ]
    assert len(backend.progress_polls) == 2


def test_progress_that_cannot_be_posted_leaves_todays_delivery():
    discord_side = Discord()
    source = FakeSource(discord_side)
    source.reply_errors.append(http_error(discord.Forbidden, 403))
    backend = FakeBackend([running("câu trả lời")], gates=[lambda: not source.reply_errors], labels=[THINKING])

    async def scenario():
        gateway = DiscordConversationGateway(backend, "prompt", 0, True, poll_budget_seconds=10)
        original = backend.execute_discord_turn

        async def execute_then_linger(turn_id):
            outcome = await original(turn_id)
            await asyncio.sleep(0.2)
            return outcome

        backend.execute_discord_turn = execute_then_linger
        await answer_mention(gateway, source, "câu hỏi", quick(source))

    asyncio.run(scenario())

    # The post failed once and was never tried again; the answer replied as today.
    assert [(kind, content) for kind, _, content, _ in discord_side.writes] == [("reply", "câu trả lời")]
    assert len(backend.progress_polls) == 1


def test_retried_and_requeued_turn_keeps_one_progress_message_and_one_answer():
    discord_side = Discord()
    source = FakeSource(discord_side)
    backend = FakeBackend(
        [
            # A retryable backend failure put the turn back in the queue...
            state("queued"),
            # ...then its conversation was gone and it moved to a replacement turn...
            state("requeued", replacement="turn-2"),
            # ...which answers.
            running("câu trả lời", turn_id="turn-2"),
        ],
        gates=[progress_posted(discord_side), None, lambda: "turn-2" in backend.progress_polls],
        labels=[THINKING],
    )
    backend.completion_failures = 2

    run(backend, source, quick(source))

    assert discord_side.kinds() == ["reply", "edit"]
    assert discord_side.writes[1][2] == "câu trả lời"
    assert [call[1] for call in backend.calls if call[0] == "execute"] == ["turn", "turn", "turn-2"]
    # The progress message is the answer, so its id is the delivery the backend records;
    # completion is retried with it and nothing is sent to Discord again.
    progress_id = str(discord_side.writes[0][1])
    assert backend.completions() == [("complete", "turn-2", "token", (progress_id,))] * 3


def test_stop_waits_for_a_post_in_flight_and_nothing_writes_after_it():
    async def scenario():
        discord_side = Discord()
        source = FakeSource(discord_side)
        released = asyncio.Event()
        original_reply = source.reply

        async def slow_reply(content, *, mention_author):
            await released.wait()
            return await original_reply(content, mention_author=mention_author)

        source.reply = slow_reply
        progress = quick(source, first_post_seconds=0.0)

        async def label(_turn_id):
            return THINKING

        progress.watch("turn", label)
        await asyncio.sleep(0.05)
        stopping = asyncio.create_task(progress.stop())
        await asyncio.sleep(0.02)
        assert not stopping.done()
        released.set()
        await stopping
        posted = len(discord_side.writes)
        await asyncio.sleep(0.1)
        # The post finished and kept its message; the watcher wrote nothing after stop().
        assert posted == 1 and len(discord_side.writes) == 1
        assert progress.message is not None

    asyncio.run(scenario())


def test_client_reads_the_progress_endpoint_with_a_short_timeout():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["timeout"] = request.url.path, request.extensions["timeout"]
        seen["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={"turn_id": "turn-1", "running": True, "label": SEARCHING, "kind": "tool_call", "round": 1, "events": 3})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend", timeout=45) as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend", api_key="secret-key"), http)
            return await client.get_discord_turn_progress("turn-1")

    progress = asyncio.run(scenario())
    assert seen["path"] == "/api/discord/sessions/turns/turn-1/progress"
    assert seen["key"] == "secret-key"
    assert seen["timeout"]["read"] == 5.0
    assert progress.running is True and progress.label == SEARCHING


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (httpx.Response(200, json={"turn_id": "turn-1", "running": False, "label": SEARCHING}), None),
        (httpx.Response(500, json={}), BackendUnavailableError),
        (httpx.Response(200, json={"running": "yes"}), BackendResponseError),
    ],
)
def test_client_progress_label_only_while_running_and_errors_are_typed(response, outcome):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), base_url="http://backend") as http:
            client = LocalAgentClient(LocalAgentSettings("http://backend"), http)
            return await client.get_discord_turn_progress("turn-1")

    if outcome is None:
        progress = asyncio.run(scenario())
        assert progress.running is False and progress.label is None
    else:
        with pytest.raises(outcome):
            asyncio.run(scenario())
