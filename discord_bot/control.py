from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import httpx
import psutil


BOT_MODULE = "discord_bot.main"
BACKEND_MODULE = "uvicorn"
BACKEND_APP = "app.main:app"
BACKEND_CANCEL_ROUTE = "/api/discord/sessions/turns/cancel-open"
START_MESSAGE = "Ún tới chơi"
STOP_MESSAGE = "gút bai"
UPDATE_STARTED_MESSAGE = "Ún đang update"
UPDATE_FINISHED_MESSAGE = "Ún update xong"


class BotControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotProcessStatus:
    root_pids: tuple[int, ...]
    process_pids: tuple[int, ...]
    gateway_connected: bool
    persistent_sessions_enabled: bool | None
    docker_container_running: bool = False

    @property
    def running(self) -> bool:
        return bool(self.root_pids) or self.docker_container_running

    @property
    def duplicate_instances(self) -> bool:
        return len(self.root_pids) + int(self.docker_container_running) > 1


@dataclass(frozen=True)
class ControlResult:
    action: str
    success: bool
    message: str
    process_status: BotProcessStatus
    announcement_sent: bool = False


def read_env_file(path: Path) -> dict[str, str]:
    """Read the simple KEY=VALUE format used by the project without logging it."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _is_bot_command(command_line: list[str] | None) -> bool:
    if not command_line:
        return False
    for index, value in enumerate(command_line[:-1]):
        if value == "-m" and command_line[index + 1] == BOT_MODULE:
            return True
    return False


def _is_backend_command(command_line: list[str] | None) -> bool:
    if not command_line:
        return False
    has_module = any(
        value == "-m" and command_line[index + 1] == BACKEND_MODULE
        for index, value in enumerate(command_line[:-1])
    )
    return has_module and BACKEND_APP in command_line


def matching_bot_processes(repo_root: Path) -> list[psutil.Process]:
    expected_root = repo_root.resolve()
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (process.info.get("name") or "").lower() not in {
                "python.exe",
                "pythonw.exe",
                "python",
                "pythonw",
            }:
                continue
            if not _is_bot_command(process.info.get("cmdline")):
                continue
            try:
                process_root = Path(process.cwd()).resolve()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                process_root = expected_root
            if process_root == expected_root:
                matches.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return matches


def matching_backend_processes(repo_root: Path) -> list[psutil.Process]:
    expected_root = (repo_root / "backend").resolve()
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (process.info.get("name") or "").lower() not in {
                "python.exe",
                "pythonw.exe",
                "python",
                "pythonw",
            }:
                continue
            if not _is_backend_command(process.info.get("cmdline")):
                continue
            try:
                process_root = Path(process.cwd()).resolve()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
            if process_root == expected_root:
                matches.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return matches


def docker_bot_container_running() -> bool:
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.service=discord-bot",
                "--format",
                "{{.ID}}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def bot_process_status(repo_root: Path) -> BotProcessStatus:
    processes = matching_bot_processes(repo_root)
    by_pid = {process.pid: process for process in processes}
    roots: list[int] = []
    persistent_values: set[bool] = set()
    gateway_connected = False

    for process in processes:
        try:
            if process.ppid() not in by_pid:
                roots.append(process.pid)
            value = process.environ().get(
                "DISCORD_PERSISTENT_SESSIONS_ENABLED",
                "",
            ).strip().lower()
            if value:
                persistent_values.add(value in {"1", "true", "yes", "on"})
            for connection in process.net_connections(kind="tcp"):
                if (
                    connection.status == psutil.CONN_ESTABLISHED
                    and connection.raddr
                    and connection.raddr.port == 443
                ):
                    gateway_connected = True
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

    persistent: bool | None
    if persistent_values == {True}:
        persistent = True
    elif persistent_values == {False}:
        persistent = False
    else:
        persistent = None
    return BotProcessStatus(
        root_pids=tuple(sorted(roots)),
        process_pids=tuple(sorted(by_pid)),
        gateway_connected=gateway_connected,
        persistent_sessions_enabled=persistent,
        docker_container_running=docker_bot_container_running(),
    )


class DiscordBotController:
    def __init__(
        self,
        repo_root: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.env_path = self.repo_root / ".env"
        self.runtime_dir = self.repo_root / "data" / "discord_bot_control"
        self.settings_path = self.runtime_dir / "settings.json"
        self.state_path = self.runtime_dir / "state.json"
        self.stdout_path = self.runtime_dir / "bot.stdout.log"
        self.stderr_path = self.runtime_dir / "bot.stderr.log"
        self.backend_stdout_path = self.runtime_dir / "backend.stdout.log"
        self.backend_stderr_path = self.runtime_dir / "backend.stderr.log"
        self.control_log_path = self.runtime_dir / "control.log"
        self.python_path = self.repo_root / ".venv" / "Scripts" / "python.exe"
        self.backend_root = self.repo_root / "backend"
        self._abort_requested = threading.Event()
        self._sleep = sleep

    def _log(self, message: str) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        with self.control_log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {message}\n")

    def load_local_settings(self) -> dict[str, str]:
        if not self.settings_path.exists():
            return {}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            "status_channel_id": str(payload.get("status_channel_id", "")).strip(),
        }

    def save_local_settings(self, status_channel_id: str) -> None:
        channel_id = self._normalize_channel_id(status_channel_id)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps({"status_channel_id": channel_id}, indent=2),
            encoding="utf-8",
        )
        self._log("Saved status channel configuration.")

    def _runtime_environment(self) -> dict[str, str]:
        values = read_env_file(self.env_path)
        environment = os.environ.copy()
        environment.update(values)
        environment["DISCORD_PERSISTENT_SESSIONS_ENABLED"] = "true"
        # The control panel launches the bot directly on the Windows host.
        # The ordinary .env may contain the Compose-only hostname `api`, so it
        # must not leak into this host process.
        environment["LOCAL_AGENT_BASE_URL"] = environment.get(
            "DISCORD_CONTROL_BACKEND_URL",
            "http://127.0.0.1:8000",
        ).strip() or "http://127.0.0.1:8000"
        if not environment.get("DISCORD_TOKEN", "").strip():
            raise BotControlError("DISCORD_TOKEN is missing from the local runtime configuration.")
        return environment

    def _backend_base_url(self) -> str:
        values = os.environ.copy()
        values.update(read_env_file(self.env_path))
        return values.get(
            "DISCORD_CONTROL_BACKEND_URL",
            "http://127.0.0.1:8000",
        ).strip() or "http://127.0.0.1:8000"

    def configured_channel_id(self) -> str:
        local = self.load_local_settings().get("status_channel_id", "")
        if local:
            return local
        return read_env_file(self.env_path).get(
            "DISCORD_STATUS_CHANNEL_ID",
            "",
        ).strip()

    @staticmethod
    def _normalize_channel_id(channel_id: str) -> str:
        normalized = channel_id.strip()
        if not normalized or not normalized.isdecimal() or len(normalized) > 64:
            raise BotControlError("A valid numeric Discord status channel ID is required.")
        return normalized

    def status(self) -> BotProcessStatus:
        return bot_process_status(self.repo_root)

    def request_abort(self) -> None:
        """Ask an in-progress Start/Update operation to stop before launch."""
        self._abort_requested.set()

    def _reset_abort(self) -> None:
        self._abort_requested.clear()

    def _raise_if_abort_requested(self) -> None:
        if self._abort_requested.is_set():
            raise BotControlError("Operation cancelled because End/Close was requested.")

    def backend_healthy(self, base_url: str | None = None) -> bool:
        target = (
            base_url
            or self._backend_base_url()
        ).rstrip("/")
        try:
            response = httpx.get(f"{target}/health", timeout=5)
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    def backend_control_route_ready(self, base_url: str | None = None) -> bool:
        target = (base_url or self._backend_base_url()).rstrip("/")
        try:
            response = httpx.get(f"{target}/openapi.json", timeout=5)
            if response.status_code != 200:
                return False
            paths = response.json().get("paths", {})
            return (
                isinstance(paths, dict)
                and BACKEND_CANCEL_ROUTE in paths
                and "post" in paths[BACKEND_CANCEL_ROUTE]
            )
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return False

    def _discord_request(
        self,
        method: str,
        channel_id: str,
        *,
        message: str | None = None,
    ) -> httpx.Response:
        environment = self._runtime_environment()
        headers = {"Authorization": f"Bot {environment['DISCORD_TOKEN']}"}
        url = f"https://discord.com/api/v10/channels/{channel_id}"
        if message is not None:
            url += "/messages"
        with httpx.Client(headers=headers, timeout=10) as client:
            if method == "GET":
                return client.get(url)
            return client.post(
                url,
                json={
                    "content": message,
                    "allowed_mentions": {"parse": []},
                },
            )

    def validate_channel(self, channel_id: str) -> None:
        normalized = self._normalize_channel_id(channel_id)
        try:
            response = self._discord_request("GET", normalized)
        except httpx.HTTPError as error:
            raise BotControlError("Discord channel validation failed.") from error
        if response.status_code != 200:
            raise BotControlError(
                f"Discord channel validation returned HTTP {response.status_code}."
            )

    def announce(self, channel_id: str, message: str) -> None:
        normalized = self._normalize_channel_id(channel_id)
        try:
            response = self._discord_request(
                "POST",
                normalized,
                message=message,
            )
        except httpx.HTTPError as error:
            raise BotControlError("Discord status announcement failed.") from error
        if response.status_code not in {200, 201}:
            raise BotControlError(
                f"Discord status announcement returned HTTP {response.status_code}."
            )

    def cancel_open_backend_turns(self) -> int:
        target = self._backend_base_url().rstrip("/")
        try:
            response = httpx.post(
                f"{target}/api/discord/sessions/turns/cancel-open",
                json={},
                timeout=10,
            )
        except httpx.HTTPError as error:
            raise BotControlError(
                "Backend turn cancellation failed after the bot was stopped."
            ) from error
        if response.status_code != 200:
            raise BotControlError(
                "Backend turn cancellation returned "
                f"HTTP {response.status_code} after the bot was stopped."
            )
        try:
            cancelled = response.json().get("cancelled_turns")
        except ValueError as error:
            raise BotControlError(
                "Backend returned an invalid turn cancellation response."
            ) from error
        if not isinstance(cancelled, int) or cancelled < 0:
            raise BotControlError(
                "Backend returned an invalid cancelled-turn count."
            )
        return cancelled

    @staticmethod
    def _terminate_process_tree(processes: list[psutil.Process]) -> None:
        targets: dict[int, psutil.Process] = {}
        for process in processes:
            targets[process.pid] = process
            try:
                for child in process.children(recursive=True):
                    targets[child.pid] = child
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue

        def process_depth(process: psutil.Process) -> int:
            try:
                return len(process.parents()) if process.is_running() else 0
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                return 0

        ordered = sorted(targets.values(), key=process_depth, reverse=True)
        for process in ordered:
            try:
                process.terminate()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        _, alive = psutil.wait_procs(ordered, timeout=5)
        for process in alive:
            try:
                process.kill()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        if alive:
            psutil.wait_procs(alive, timeout=3)

    def _backend_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(read_env_file(self.env_path))
        environment.pop("POSTGRES_TEST_URL", None)
        if not environment.get("DATABASE_URL", "").strip():
            raise BotControlError(
                "DATABASE_URL is missing; backend reload was refused."
            )
        return environment

    def _port_8000_owned_by_unmanaged_process(self) -> bool:
        managed_pids = {
            process.pid
            for process in matching_backend_processes(self.repo_root)
        }
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return False
        for connection in connections:
            if (
                connection.status == psutil.CONN_LISTEN
                and connection.laddr
                and connection.laddr.port == 8000
                and connection.pid
                and connection.pid not in managed_pids
            ):
                return True
        return False

    def _launch_backend(self) -> subprocess.Popen[bytes]:
        if not self.python_path.exists():
            raise BotControlError(
                f"Virtual environment Python was not found at {self.python_path}."
            )
        if not self.backend_root.is_dir():
            raise BotControlError(
                f"Backend working directory was not found at {self.backend_root}."
            )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        stdout = self.backend_stdout_path.open("ab")
        stderr = self.backend_stderr_path.open("ab")
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        try:
            return subprocess.Popen(
                [
                    str(self.python_path),
                    "-m",
                    BACKEND_MODULE,
                    BACKEND_APP,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=self.backend_root,
                env=self._backend_environment(),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags,
            )
        finally:
            stdout.close()
            stderr.close()

    def reload_backend(self, *, timeout_seconds: int = 30) -> int:
        """Reload only the host Uvicorn API and verify the control contract."""
        backend_processes = matching_backend_processes(self.repo_root)
        if not backend_processes and self._port_8000_owned_by_unmanaged_process():
            raise BotControlError(
                "Port 8000 is owned by an unmanaged process; backend reload was refused."
            )
        if backend_processes:
            self._terminate_process_tree(backend_processes)
        self._raise_if_abort_requested()
        process = self._launch_backend()
        self._log(f"Reloaded backend launcher PID {process.pid}.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            self._raise_if_abort_requested()
            if process.poll() is not None:
                raise BotControlError(
                    "Backend exited before /health became ready. Check backend.stderr.log."
                )
            if self.backend_healthy() and self.backend_control_route_ready():
                self._log(
                    "Backend health is ready and the turn cancellation route is live."
                )
                return process.pid
            self._sleep(0.25)
        raise BotControlError(
            "Backend did not expose the required Discord control route within "
            f"{timeout_seconds} seconds."
        )

    def ensure_backend_control_ready(self, *, force_reload: bool = False) -> bool:
        """Return True when a backend reload was required."""
        if (
            not force_reload
            and self.backend_healthy()
            and self.backend_control_route_ready()
        ):
            return False
        self.reload_backend()
        return True

    def _launch(self, environment: dict[str, str]) -> subprocess.Popen[bytes]:
        if not self.python_path.exists():
            raise BotControlError(
                f"Virtual environment Python was not found at {self.python_path}."
            )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        stdout = self.stdout_path.open("ab")
        stderr = self.stderr_path.open("ab")
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        try:
            process = subprocess.Popen(
                [str(self.python_path), "-m", BOT_MODULE],
                cwd=self.repo_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags,
            )
        finally:
            stdout.close()
            stderr.close()
        return process

    def _wait_for_gateway(
        self,
        process: subprocess.Popen[bytes],
        *,
        log_offset: int,
        timeout_seconds: int = 30,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._abort_requested.is_set():
                return False
            if process.poll() is not None:
                return False
            if self.stderr_path.exists():
                with self.stderr_path.open("rb") as stream:
                    stream.seek(log_offset)
                    recent = stream.read().decode("utf-8", errors="replace")
                if "connected as" in recent and "connected to Gateway" in recent:
                    return True
                if "Traceback (most recent call last)" in recent:
                    return False
            self._sleep(0.25)
        return False

    def _write_state(self, launcher_pid: int, channel_id: str) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "launcher_pid": launcher_pid,
                    "started_at": datetime.now(UTC).isoformat(),
                    "persistent_sessions_enabled": True,
                    "status_channel_id": channel_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _clear_state(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    def _terminate_processes(self) -> None:
        self._terminate_process_tree(matching_bot_processes(self.repo_root))

    def start(
        self,
        channel_id: str,
        *,
        announcement: str = START_MESSAGE,
        cancel_previous_open: bool = True,
    ) -> ControlResult:
        self._reset_abort()
        normalized = self._normalize_channel_id(channel_id)
        before = self.status()
        if before.running:
            return ControlResult(
                "start",
                False,
                "Bot is already running; no second instance was started.",
                before,
            )
        environment = self._runtime_environment()
        self.validate_channel(normalized)
        self._raise_if_abort_requested()
        if self.ensure_backend_control_ready():
            self._log("Start refreshed the stale/unavailable backend runtime.")
        self._raise_if_abort_requested()
        if cancel_previous_open:
            cancelled_turns = self.cancel_open_backend_turns()
            self._log(
                f"Cancelled {cancelled_turns} open turn(s) left by an earlier bot run."
            )
        self._raise_if_abort_requested()
        log_offset = self.stderr_path.stat().st_size if self.stderr_path.exists() else 0
        process = self._launch(environment)
        self._log(f"Started bot launcher PID {process.pid}; persistent sessions enabled.")
        if not self._wait_for_gateway(process, log_offset=log_offset):
            self._terminate_processes()
            self._clear_state()
            raise BotControlError("Bot did not connect to the Discord Gateway within 30 seconds.")
        try:
            self.announce(normalized, announcement)
        except BotControlError:
            self._terminate_processes()
            self._clear_state()
            self._log("Startup announcement failed; stopped the newly launched bot.")
            raise
        self._write_state(process.pid, normalized)
        after = self.status()
        self._log(f"Bot ready; process PIDs={','.join(map(str, after.process_pids))}.")
        return ControlResult(
            "start",
            True,
            "Bot connected and the startup announcement was sent.",
            after,
            announcement_sent=True,
        )

    def stop(self, channel_id: str | None) -> ControlResult:
        self.request_abort()
        normalized = (
            self._normalize_channel_id(channel_id)
            if channel_id and channel_id.strip()
            else None
        )
        before = self.status()
        if before.docker_container_running:
            return ControlResult(
                "stop",
                False,
                "A Docker Discord bot is running; the host control panel did not stop it.",
                before,
            )
        was_running = before.running
        if was_running:
            # Stop the Gateway process first so no new Discord message can
            # enqueue while terminal cancellation is being applied.
            self._terminate_processes()
        self._clear_state()
        cancellation_error: BotControlError | None = None
        try:
            self._reset_abort()
            if self.ensure_backend_control_ready():
                self._log("End refreshed the backend before terminal cancellation.")
            cancelled_turns = self.cancel_open_backend_turns()
        except BotControlError as error:
            cancelled_turns = 0
            cancellation_error = error
        announcement_sent = False
        warning = ""
        if was_running and normalized is not None:
            try:
                self.announce(normalized, STOP_MESSAGE)
                announcement_sent = True
            except BotControlError as error:
                warning = f" Goodbye announcement failed: {error}"
        after = self.status()
        if cancellation_error is not None:
            self._log(
                f"Stopped bot, but turn cancellation failed: {cancellation_error}"
                + warning
            )
            return ControlResult(
                "stop",
                False,
                "Bot stopped, but open turns were not cancelled: "
                f"{cancellation_error}{warning}",
                after,
                announcement_sent=announcement_sent,
            )
        self._log(
            f"Stopped bot process tree; cancelled {cancelled_turns} open turn(s)."
            + warning
        )
        return ControlResult(
            "stop",
            not after.running,
            (
                f"Bot {'stopped' if was_running else 'was already stopped'}; "
                f"{cancelled_turns} open turn(s) cancelled."
                + warning
            ),
            after,
            announcement_sent=announcement_sent,
        )

    def update(self, channel_id: str) -> ControlResult:
        self._reset_abort()
        normalized = self._normalize_channel_id(channel_id)
        before = self.status()
        if before.docker_container_running:
            return ControlResult(
                "update",
                False,
                "A Docker Discord bot is running; stop it before using host Update/Restart.",
                before,
            )
        self._runtime_environment()
        self.validate_channel(normalized)
        if before.running:
            self.announce(normalized, UPDATE_STARTED_MESSAGE)
            self._log("Update/restart requested; update announcement sent.")
            self._terminate_processes()
        self._clear_state()
        self._raise_if_abort_requested()
        self.ensure_backend_control_ready(force_reload=True)
        self._raise_if_abort_requested()
        cancelled_turns = self.cancel_open_backend_turns()
        self._log(
            f"Cancelled {cancelled_turns} open turn(s) before update restart."
        )
        self._raise_if_abort_requested()
        try:
            result = self.start(
                normalized,
                announcement=UPDATE_FINISHED_MESSAGE,
                cancel_previous_open=False,
            )
        except Exception:
            self._log("Update/restart failed after the old bot was stopped.")
            raise
        return ControlResult(
            "update",
            result.success,
            "Backend source reloaded and the bot restarted.",
            result.process_status,
            announcement_sent=result.announcement_sent,
        )


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if sys.platform != "win32":
    # The controller UI and process lifecycle are intentionally Windows-only.
    # Keeping the core importable lets unit tests cover its policy everywhere.
    pass
