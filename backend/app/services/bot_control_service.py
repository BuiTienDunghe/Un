"""Start/stop/status for the Discord bot from the dashboard (P3-2).

The bot has always run as the `discord-bot` service under
`docker compose --profile discord` (see run-discord-bot.bat). This service
drives that same mechanism, so the dashboard button and the .bat are two doors
to one process — status can never disagree with reality because reality IS
`docker compose ps`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class BotControlError(RuntimeError):
    pass


class BotTokenMissingError(BotControlError):
    pass


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

    def status(self) -> dict[str, object]:
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
        try:
            result = self._compose("stop", self.service, timeout=60.0)
        except FileNotFoundError as error:
            raise BotControlError("docker không có trên máy") from error
        except subprocess.TimeoutExpired as error:
            raise BotControlError("dừng bot quá thời gian chờ") from error
        if result.returncode != 0:
            raise BotControlError((result.stderr or "").strip()[:300] or "docker compose stop thất bại")
        return self.status()
