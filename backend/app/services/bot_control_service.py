"""Start/stop/status for the Discord bot from the dashboard (P3-2).

The dashboard drives the `discord-bot` service under `docker compose --profile
discord`, the same container run-discord-bot.bat starts. The tkinter control
panel (tools/discord_bot_control.py) starts a different kind of bot: a
`python -m discord_bot.main` process straight on the host. Both are real, so the
status reports either, and start refuses while the host one runs — two bots on
one token answer every message twice.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import psutil

BOT_MODULE = "discord_bot.main"
PYTHON_NAMES = frozenset({"python.exe", "pythonw.exe", "python", "pythonw"})


class BotControlError(RuntimeError):
    pass


class BotTokenMissingError(BotControlError):
    pass


class BotRunningOnHostError(BotControlError):
    pass


def host_bot_pids(repo_root: Path) -> list[int]:
    """PIDs of `python -m discord_bot.main` processes started from repo_root: the panel's bot.

    The same verdict as matching_bot_processes in discord_bot/control.py, written here
    rather than imported because the backend and the bot only ever talk over HTTP.
    tests/test_bot_detection_parity.py holds the two to the same answer on the same
    processes, including the panel's leniency: a process whose cwd cannot be read counts.
    """
    expected = repo_root.resolve()
    pids: list[int] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (process.info.get("name") or "").lower() not in PYTHON_NAMES:
                continue
            cmdline = process.info.get("cmdline") or []
            if not any(value == "-m" and following == BOT_MODULE for value, following in zip(cmdline, cmdline[1:])):
                continue
            try:
                root = Path(process.cwd()).resolve()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                root = expected
            if root == expected:
                pids.append(process.pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return pids


class BotControlService:
    def __init__(self, compose_dir: Path, service: str = "discord-bot", env_path: Path | None = None) -> None:
        self.compose_dir = compose_dir
        self.service = service
        self.env_path = env_path or compose_dir / ".env"

    def _compose(self, *args: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", "compose", "--profile", "discord", *args],
            cwd=self.compose_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _container_status(self) -> dict[str, object]:
        try:
            result = self._compose("ps", self.service, "--format", "json")
        except FileNotFoundError:
            return {"state": "unknown", "detail": "docker không có trên máy"}
        except subprocess.TimeoutExpired:
            return {"state": "unknown", "detail": "docker không phản hồi"}
        if result.returncode != 0:
            return {"state": "unknown", "detail": (result.stderr or "").strip()[:200] or "lỗi docker compose"}
        text = (result.stdout or "").strip()
        if not text:
            return {"state": "stopped", "detail": None}
        try:
            # `compose ps --format json` emits one JSON object per line.
            first = json.loads(text.splitlines()[0])
        except ValueError:
            return {"state": "unknown", "detail": "không đọc được trạng thái compose"}
        state = str(first.get("State", "")).lower()
        return {"state": "running" if state == "running" else "stopped", "detail": state or None}

    def status(self) -> dict[str, object]:
        """`state` keeps its three values (the web UI compares them); `runner` says
        which kind is up when it is: "host", "docker", or "host+docker" — the
        duplicate this service exists to prevent."""
        container = self._container_status()
        if not host_bot_pids(self.compose_dir):
            if container["state"] == "running":
                return {**container, "runner": "docker", "detail": "running (docker)"}
            return container
        if container["state"] == "running":
            return {"state": "running", "runner": "host+docker", "detail": "running (host + docker): hai bot cùng chạy"}
        return {"state": "running", "runner": "host", "detail": "running (host)"}

    def has_token(self) -> bool:
        """Same precheck run-discord-bot.bat does: a non-empty DISCORD_TOKEN."""
        try:
            content = self.env_path.read_text(encoding="utf-8")
        except OSError:
            return False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("DISCORD_TOKEN=") and stripped.split("=", 1)[1].strip():
                return True
        return False

    def start(self) -> dict[str, object]:
        if not self.has_token():
            raise BotTokenMissingError("DISCORD_TOKEN trống hoặc thiếu trong .env")
        if host_bot_pids(self.compose_dir):
            raise BotRunningOnHostError("Bot đang chạy trên máy (bật từ bảng điều khiển); tắt nó ở đó trước khi bật bản Docker")
        try:
            result = self._compose("up", "-d", self.service, timeout=180.0)
        except FileNotFoundError as error:
            raise BotControlError("docker không có trên máy") from error
        except subprocess.TimeoutExpired as error:
            raise BotControlError("khởi động bot quá thời gian chờ (build image lần đầu có thể lâu — thử lại)") from error
        if result.returncode != 0:
            raise BotControlError((result.stderr or "").strip()[:300] or "docker compose up thất bại")
        return self.status()

    def stop(self) -> dict[str, object]:
        # The panel refuses to stop the Docker bot; this refuses the mirror case. With
        # only the host bot up there is nothing here to stop, and "stopped" would lie.
        if host_bot_pids(self.compose_dir) and self._container_status()["state"] != "running":
            raise BotRunningOnHostError("Bot đang chạy trên máy (bật từ bảng điều khiển); tắt nó ở đó")
        try:
            result = self._compose("stop", self.service, timeout=60.0)
        except FileNotFoundError as error:
            raise BotControlError("docker không có trên máy") from error
        except subprocess.TimeoutExpired as error:
            raise BotControlError("dừng bot quá thời gian chờ") from error
        if result.returncode != 0:
            raise BotControlError((result.stderr or "").strip()[:300] or "docker compose stop thất bại")
        return self.status()
