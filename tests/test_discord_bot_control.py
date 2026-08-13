from __future__ import annotations

import queue
import threading
from types import SimpleNamespace

import pytest
import tools.discord_bot_control as control_ui

from discord_bot.control import (
    BotControlError,
    BotProcessStatus,
    ControlResult,
    DiscordBotController,
    START_MESSAGE,
    STOP_MESSAGE,
    UPDATE_FINISHED_MESSAGE,
    UPDATE_STARTED_MESSAGE,
    read_env_file,
)


STOPPED = BotProcessStatus((), (), False, None)
RUNNING = BotProcessStatus((100,), (100, 101), True, True)
DUPLICATE = BotProcessStatus((100, 200), (100, 101, 200, 201), True, True)
DOCKER = BotProcessStatus((), (), False, None, docker_container_running=True)


def controller(tmp_path):
    instance = DiscordBotController(tmp_path, sleep=lambda _: None)
    instance.python_path.parent.mkdir(parents=True)
    instance.python_path.touch()
    return instance


def test_read_env_file_handles_comments_and_quotes_without_requiring_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "# local only",
                "DISCORD_TOKEN='secret-value'",
                'LOCAL_AGENT_BASE_URL=\"http://127.0.0.1:8000\"',
                "DISCORD_STATUS_CHANNEL_ID=123456",
            )
        ),
        encoding="utf-8",
    )

    values = read_env_file(env_file)

    assert values["DISCORD_TOKEN"] == "secret-value"
    assert values["LOCAL_AGENT_BASE_URL"] == "http://127.0.0.1:8000"
    assert values["DISCORD_STATUS_CHANNEL_ID"] == "123456"


def test_windows_controller_replaces_compose_backend_hostname(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "DISCORD_TOKEN=test-only",
                "LOCAL_AGENT_BASE_URL=http://api:8000",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DISCORD_CONTROL_BACKEND_URL", raising=False)

    environment = instance._runtime_environment()

    assert environment["LOCAL_AGENT_BASE_URL"] == "http://127.0.0.1:8000"
    assert environment["DISCORD_PERSISTENT_SESSIONS_ENABLED"] == "true"


@pytest.mark.parametrize("value", ["", "abc", "12 34", "1" * 65])
def test_status_channel_id_must_be_a_bounded_numeric_discord_id(tmp_path, value):
    with pytest.raises(BotControlError, match="channel ID"):
        controller(tmp_path).save_local_settings(value)


def test_start_sets_persistent_runtime_and_announces_only_after_gateway(
    tmp_path,
    monkeypatch,
):
    instance = controller(tmp_path)
    statuses = iter((STOPPED, RUNNING))
    events: list[object] = []
    environment = {
        "DISCORD_TOKEN": "not-logged",
        "LOCAL_AGENT_BASE_URL": "http://127.0.0.1:8000",
        "DISCORD_PERSISTENT_SESSIONS_ENABLED": "true",
    }
    process = SimpleNamespace(pid=100)

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(instance, "_runtime_environment", lambda: environment)
    monkeypatch.setattr(
        instance,
        "ensure_backend_control_ready",
        lambda: events.append("backend-ready") or False,
    )
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("cancelled-previous") or 0,
    )
    monkeypatch.setattr(
        instance,
        "validate_channel",
        lambda channel: events.append(("validate", channel)),
    )
    monkeypatch.setattr(
        instance,
        "_launch",
        lambda env: events.append(("launch", env.copy())) or process,
    )
    monkeypatch.setattr(
        instance,
        "_wait_for_gateway",
        lambda launched, log_offset: events.append(("gateway", launched.pid)) or True,
    )
    monkeypatch.setattr(
        instance,
        "announce",
        lambda channel, message: events.append(("announce", channel, message)),
    )
    monkeypatch.setattr(
        instance,
        "_write_state",
        lambda pid, channel: events.append(("state", pid, channel)),
    )
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.start("123")

    assert result.success is True
    assert result.announcement_sent is True
    assert events[0] == ("validate", "123")
    assert events[1] == "backend-ready"
    assert events[2] == "cancelled-previous"
    assert events[3][0] == "launch"
    assert events[3][1]["DISCORD_PERSISTENT_SESSIONS_ENABLED"] == "true"
    assert events[4] == ("gateway", 100)
    assert events[5] == ("announce", "123", START_MESSAGE)
    assert events[6] == ("state", 100, "123")


def test_start_refuses_duplicate_or_existing_bot_instance(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    monkeypatch.setattr(instance, "status", lambda: DUPLICATE)
    monkeypatch.setattr(
        instance,
        "_launch",
        lambda _: pytest.fail("a second bot must not be launched"),
    )

    result = instance.start("123")

    assert result.success is False
    assert result.process_status.duplicate_instances is True


def test_failed_startup_announcement_stops_new_process(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    statuses = iter((STOPPED,))
    events: list[str] = []
    process = SimpleNamespace(pid=100)

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(
        instance,
        "_runtime_environment",
        lambda: {
            "DISCORD_TOKEN": "not-logged",
            "LOCAL_AGENT_BASE_URL": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(
        instance,
        "ensure_backend_control_ready",
        lambda: False,
    )
    monkeypatch.setattr(instance, "cancel_open_backend_turns", lambda: 0)
    monkeypatch.setattr(instance, "validate_channel", lambda _: None)
    monkeypatch.setattr(instance, "_launch", lambda _: process)
    monkeypatch.setattr(instance, "_wait_for_gateway", lambda *_, **__: True)
    monkeypatch.setattr(
        instance,
        "announce",
        lambda *_: (_ for _ in ()).throw(BotControlError("no permission")),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_processes",
        lambda: events.append("terminated"),
    )
    monkeypatch.setattr(instance, "_clear_state", lambda: events.append("cleared"))
    monkeypatch.setattr(instance, "_log", lambda _: None)

    with pytest.raises(BotControlError, match="no permission"):
        instance.start("123")

    assert events == ["terminated", "cleared"]


def test_stop_announces_goodbye_before_terminating(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    statuses = iter((RUNNING, STOPPED))
    events: list[object] = []

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(
        instance,
        "announce",
        lambda channel, message: events.append(("announce", channel, message)),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_processes",
        lambda: events.append("terminated"),
    )
    monkeypatch.setattr(instance, "_clear_state", lambda: events.append("cleared"))
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("cancelled") or 2,
    )
    monkeypatch.setattr(instance, "ensure_backend_control_ready", lambda: False)
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.stop("123")

    assert result.success is True
    assert result.announcement_sent is True
    assert events == [
        "terminated",
        "cleared",
        "cancelled",
        ("announce", "123", STOP_MESSAGE),
    ]


def test_stop_still_stops_when_goodbye_delivery_fails(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    statuses = iter((RUNNING, STOPPED))
    events: list[str] = []

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(
        instance,
        "announce",
        lambda *_: (_ for _ in ()).throw(BotControlError("offline")),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_processes",
        lambda: events.append("terminated"),
    )
    monkeypatch.setattr(instance, "_clear_state", lambda: events.append("cleared"))
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("cancelled") or 1,
    )
    monkeypatch.setattr(instance, "ensure_backend_control_ready", lambda: False)
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.stop("123")

    assert result.success is True
    assert result.announcement_sent is False
    assert events == [
        "terminated",
        "cleared",
        "cancelled",
    ]
    assert "announcement failed" in result.message.lower()


def test_host_panel_refuses_to_stop_unmanaged_docker_bot(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    monkeypatch.setattr(instance, "status", lambda: DOCKER)
    monkeypatch.setattr(
        instance,
        "announce",
        lambda *_: pytest.fail("must not announce without stopping Docker"),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_processes",
        lambda: pytest.fail("must not terminate unrelated host processes"),
    )

    result = instance.stop("123")

    assert result.success is False
    assert "Docker" in result.message


def test_update_announces_before_and_after_restart(tmp_path, monkeypatch):
    instance = controller(tmp_path)
    events: list[object] = []
    restarted = ControlResult(
        "start",
        True,
        "ready",
        RUNNING,
        announcement_sent=True,
    )

    monkeypatch.setattr(instance, "status", lambda: RUNNING)
    monkeypatch.setattr(
        instance,
        "announce",
        lambda channel, message: events.append(("announce", channel, message)),
    )
    monkeypatch.setattr(
        instance,
        "_terminate_processes",
        lambda: events.append("terminated"),
    )
    monkeypatch.setattr(instance, "_clear_state", lambda: events.append("cleared"))
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("cancelled") or 3,
    )
    monkeypatch.setattr(
        instance,
        "_runtime_environment",
        lambda: {"DISCORD_TOKEN": "not-logged"},
    )
    monkeypatch.setattr(
        instance,
        "validate_channel",
        lambda channel: events.append(("validate", channel)),
    )
    monkeypatch.setattr(
        instance,
        "ensure_backend_control_ready",
        lambda force_reload: events.append(("backend-reload", force_reload)) or True,
    )
    monkeypatch.setattr(instance, "_log", lambda _: None)
    monkeypatch.setattr(
        instance,
        "start",
        lambda channel, announcement, cancel_previous_open: (
            events.append(
                ("start", channel, announcement, cancel_previous_open)
            )
            or restarted
        ),
    )

    result = instance.update("123")

    assert result.success is True
    assert events == [
        ("validate", "123"),
        ("announce", "123", UPDATE_STARTED_MESSAGE),
        "terminated",
        "cleared",
        ("backend-reload", True),
        "cancelled",
        ("start", "123", UPDATE_FINISHED_MESSAGE, False),
    ]


def test_stop_reports_failure_when_backend_cannot_terminally_cancel_turns(
    tmp_path,
    monkeypatch,
):
    instance = controller(tmp_path)
    statuses = iter((RUNNING, STOPPED))

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(instance, "announce", lambda *_: None)
    monkeypatch.setattr(instance, "_terminate_processes", lambda: None)
    monkeypatch.setattr(instance, "_clear_state", lambda: None)
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: (_ for _ in ()).throw(BotControlError("endpoint unavailable")),
    )
    monkeypatch.setattr(instance, "ensure_backend_control_ready", lambda: False)
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.stop("123")

    assert result.success is False
    assert result.process_status.running is False
    assert "not cancelled" in result.message


def test_start_self_heals_stale_backend_before_cancelling_and_launching(
    tmp_path,
    monkeypatch,
):
    instance = controller(tmp_path)
    statuses = iter((STOPPED, RUNNING))
    events: list[object] = []
    process = SimpleNamespace(pid=100)

    monkeypatch.setattr(instance, "status", lambda: next(statuses))
    monkeypatch.setattr(
        instance,
        "_runtime_environment",
        lambda: {"DISCORD_TOKEN": "not-logged"},
    )
    monkeypatch.setattr(instance, "validate_channel", lambda _: None)
    monkeypatch.setattr(
        instance,
        "ensure_backend_control_ready",
        lambda: events.append("backend-reloaded") or True,
    )
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("turns-cancelled") or 3,
    )
    monkeypatch.setattr(
        instance,
        "_launch",
        lambda _: events.append("bot-launched") or process,
    )
    monkeypatch.setattr(instance, "_wait_for_gateway", lambda *_, **__: True)
    monkeypatch.setattr(instance, "announce", lambda *_: None)
    monkeypatch.setattr(instance, "_write_state", lambda *_: None)
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.start("123")

    assert result.success is True
    assert events == ["backend-reloaded", "turns-cancelled", "bot-launched"]


def test_end_cancels_open_turns_even_when_bot_is_already_stopped(
    tmp_path,
    monkeypatch,
):
    instance = controller(tmp_path)
    events: list[object] = []

    monkeypatch.setattr(instance, "status", lambda: STOPPED)
    monkeypatch.setattr(instance, "_clear_state", lambda: events.append("cleared"))
    monkeypatch.setattr(
        instance,
        "ensure_backend_control_ready",
        lambda: events.append("backend-ready") or False,
    )
    monkeypatch.setattr(
        instance,
        "cancel_open_backend_turns",
        lambda: events.append("turns-cancelled") or 3,
    )
    monkeypatch.setattr(
        instance,
        "announce",
        lambda *_: pytest.fail("an already stopped bot must not announce goodbye"),
    )
    monkeypatch.setattr(instance, "_log", lambda _: None)

    result = instance.stop("123")

    assert result.success is True
    assert result.announcement_sent is False
    assert events == ["cleared", "backend-ready", "turns-cancelled"]
    assert "already stopped" in result.message


def test_backend_control_readiness_reloads_only_when_required(
    tmp_path,
    monkeypatch,
):
    instance = controller(tmp_path)
    reloads: list[str] = []
    monkeypatch.setattr(instance, "backend_healthy", lambda: True)
    monkeypatch.setattr(instance, "backend_control_route_ready", lambda: True)
    monkeypatch.setattr(
        instance,
        "reload_backend",
        lambda: reloads.append("reload") or 100,
    )

    assert instance.ensure_backend_control_ready() is False
    assert reloads == []

    monkeypatch.setattr(instance, "backend_control_route_ready", lambda: False)

    assert instance.ensure_backend_control_ready() is True
    assert reloads == ["reload"]


def test_window_close_always_requests_end_even_when_panel_was_busy(monkeypatch):
    events: list[object] = []

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    class FakeController:
        def request_abort(self):
            events.append("abort")

        def stop(self, channel):
            events.append(("stop", channel))
            return ControlResult("stop", True, "ended", STOPPED)

        def _log(self, message):
            events.append(("log", message))

        def _terminate_processes(self):
            events.append("force-terminate")

        def _clear_state(self):
            events.append("force-clear")

    panel = object.__new__(control_ui.DiscordBotControlPanel)
    panel.closing = False
    panel.busy = True
    panel.controller = FakeController()
    panel.operation_lock = threading.Lock()
    panel.events = queue.Queue()
    panel.channel_id = SimpleNamespace(get=lambda: "123")
    panel.window = SimpleNamespace(
        after=lambda milliseconds, callback: events.append(
            ("watchdog", milliseconds)
        )
    )
    panel.set_busy = lambda busy: events.append(("busy", busy))
    panel.append_activity = lambda message: events.append(("activity", message))
    panel.save_channel = lambda **_: True
    monkeypatch.setattr(control_ui.threading, "Thread", ImmediateThread)

    panel.on_close()

    assert panel.closing is True
    assert "abort" in events
    assert ("stop", "123") in events
    assert panel.events.get_nowait() == ("closed", None)
    assert ("watchdog", 45_000) in events
