"""Runs the API and the background workers from one window (ticket 38).

Every line a service prints appears here with its name in front, and is kept in
data/logs/services/<name>_<date>.log for 30 days, so a service that dies leaves a reason behind.
A service that dies is started again and said out loud; after 5 quick failures in a row it is left
down and said louder. Closing this window stops them all: they share a Windows job that dies with it.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs" / "services"
KEEP_DAYS = 30
STOP_EVENT_NAME = "Local\\LocalAICoreSupervisorStop"
QUICK_FAILURE_SECONDS = 60
MAX_QUICK_FAILURES = 5
CONSOLE_BACKLOG = 5000
RESET, RED = "\033[0m", "\033[91m"
COLOURS = ("\033[96m", "\033[92m", "\033[93m", "\033[95m", "\033[94m", "\033[36m", "\033[32m", "\033[33m")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$", re.I)
URL_PASSWORD = re.compile(r"(://[^/\s:@]+:)[^/\s@]+(@)")
# A query string can carry what someone typed, and this file outlives the console.
ACCESS_QUERY = re.compile(r'("[A-Z]+ [^?" ]+)\?[^" ]*')


@dataclass(frozen=True)
class Service:
    name: str
    command: tuple[str, ...]
    cwd: Path
    # The .env line that turns it on: a name and what its value must start with ("" = any value).
    needs: tuple[str, str] | None = None


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            name, separator, value = line.partition("=")
            if separator and not line.lstrip().startswith("#"):
                values[name.strip()] = value.strip().strip("\"'")
    return values


def services(python: str = sys.executable) -> list[Service]:
    backend = ROOT / "backend"

    def worker(name: str, module: str, *arguments: str, needs: tuple[str, str] | None = None) -> Service:
        return Service(name, (python, "-m", module, *arguments), backend, needs)

    return [
        Service("api", (python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"), backend),
        worker("backup", "scripts.backup_worker", "--loop"),
        # Without it, deleted documents stay in status 'deleting' forever: the API only marks them.
        worker("cleanup", "scripts.cleanup_worker", "--loop"),
        worker("outbox", "scripts.outbox_dispatcher", needs=("DISCORD_MEMORY_INGESTION_ENABLED", "true")),
        worker("memory", "scripts.memory_worker", needs=("DISCORD_MEMORY_INGESTION_ENABLED", "true")),
        # The only component that sends member text to a third party: its own flag, and the worker
        # itself refuses to run without a real GEMINI_API_KEY and says which one is missing.
        worker("condenser", "scripts.condensation_worker", "--loop", needs=("DISCORD_CONDENSATION_ENABLED", "true")),
        Service("decided", ("cmd", "/c", str(ROOT / "run-decided.bat")), ROOT, ("DECIDED_URL", "")),
        worker("decided-worker", "scripts.decided_worker", needs=("DECIDED_URL", "")),
    ]


def enabled(all_services: list[Service], env: dict[str, str]) -> list[Service]:
    def wanted(service: Service) -> bool:
        if service.needs is None:
            return True
        value = env.get(service.needs[0], "")
        return bool(value) and value.startswith(service.needs[1])

    return [service for service in all_services if wanted(service)]


class Redactor:
    """Masks every secret named in .env, since the API's own filter only guards the API's own file."""

    def __init__(self, env: dict[str, str]) -> None:
        self.secrets = [(name, value) for name, value in env.items() if SECRET_NAME.search(name) and len(value) >= 8]

    def __call__(self, line: str) -> str:
        for name, value in self.secrets:
            if value in line:
                line = line.replace(value, f"<{name}:REDACTED>")
        return ACCESS_QUERY.sub(r"\1?<hidden>", URL_PASSWORD.sub(r"\1<hidden>\2", line))


class DailyLog:
    def __init__(self, name: str, directory: Path = LOG_DIR, today: Callable[[], date] = date.today) -> None:
        self.name, self.directory, self.today = name, directory, today
        self.opened: date | None = None
        self.file = None

    def write(self, line: str) -> None:
        now = self.today()
        if now != self.opened:
            if self.file:
                self.file.close()
            self.directory.mkdir(parents=True, exist_ok=True)
            self.file = open(self.directory / f"{self.name}_{now:%Y-%m-%d}.log", "a", encoding="utf-8")
            self.opened = now
            prune(self.directory, now)
        self.file.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        self.file.flush()


def prune(directory: Path, today: date, keep_days: int = KEEP_DAYS) -> None:
    oldest = today - timedelta(days=keep_days)
    for path in directory.glob("*_*.log"):
        try:
            stamp = date.fromisoformat(path.stem.rsplit("_", 1)[1])
        except ValueError:
            continue
        if stamp < oldest:
            path.unlink(missing_ok=True)


def backoff(failures: int) -> int:
    return min(5 * 2 ** max(failures - 1, 0), 300)


class Supervisor:
    def __init__(self, to_run: list[Service], redact: Callable[[str], str], log_dir: Path = LOG_DIR) -> None:
        self.to_run = to_run
        self.redact = redact
        self.log_dir = log_dir
        self.stopping = threading.Event()
        # A window being selected in stops accepting text, and a service must not wait for that.
        self.console: queue.Queue = queue.Queue(CONSOLE_BACKLOG)
        self.colours = {service.name: COLOURS[index % len(COLOURS)] for index, service in enumerate(to_run)}
        self.width = max((len(service.name) for service in to_run), default=0)
        self.down: list[str] = []

    def say(self, name: str, line: str, log: DailyLog | None = None, alarm: bool = False) -> None:
        clean = self.redact(line.rstrip().replace("\x00", ""))
        if not clean:
            return
        if log:
            log.write(clean)
        colour = RED if alarm else self.colours.get(name, "")
        try:
            self.console.put_nowait(f"{colour}{name:<{self.width}}{RESET} | {clean}")
        except queue.Full:
            pass  # The file above already has it.

    def _print_console(self) -> None:
        while True:
            try:
                print(self.console.get(), flush=True)
            except (OSError, ValueError):
                return

    def _run_once(self, service: Service, log: DailyLog) -> int:
        child = subprocess.Popen(
            service.command, cwd=service.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"},
        )
        for raw in child.stdout:
            self.say(service.name, raw.decode("utf-8", errors="replace"), log)
        return child.wait()

    def keep_running(self, service: Service) -> None:
        log = DailyLog(service.name, self.log_dir)
        failures = 0
        while not self.stopping.is_set():
            self.say(service.name, "[started]", log)
            began = time.monotonic()
            try:
                code = self._run_once(service, log)
            except OSError as error:
                code = f"could not start: {error}"
            if self.stopping.is_set():
                return
            if code == 0:
                # Workers exit cleanly when a setting tells them there is nothing to do.
                self.say(service.name, "[finished, not restarting]", log)
                return
            failures = failures + 1 if time.monotonic() - began < QUICK_FAILURE_SECONDS else 1
            if failures >= MAX_QUICK_FAILURES:
                self.down.append(service.name)
                self.say(service.name, f"[DOWN: {failures} quick failures in a row, last {code}. Not trying again. See {log.directory / service.name}_*.log]", log, alarm=True)
                return
            wait = backoff(failures)
            self.say(service.name, f"[died: {code}. Starting again in {wait} s]", log, alarm=True)
            self.stopping.wait(wait)

    def run(self, wait_for_stop: Callable[[], None]) -> None:
        threading.Thread(target=self._print_console, daemon=True).start()
        self.console.put(f"Starting {len(self.to_run)} services. Logs: {self.log_dir}. Close this window, or run stop-local-ai-core.bat, to stop everything.")
        for service in self.to_run:
            threading.Thread(target=self.keep_running, args=(service,), daemon=True).start()
        wait_for_stop()
        self.stopping.set()


# ── Windows: the job that takes everything down with this process, and the stop signal ──
def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    return kernel32


class _BasicLimits(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("per_process", "per_job")] + [
        ("flags", ctypes.c_uint32), ("working_min", ctypes.c_size_t), ("working_max", ctypes.c_size_t),
        ("active_processes", ctypes.c_uint32), ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32), ("scheduling", ctypes.c_uint32),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


def join_kill_on_close_job() -> None:
    """Everything this process starts from now on dies when this process does, however it ends."""
    job_object_extended_limit_information, kill_on_job_close = 9, 0x2000
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.basic.flags = kill_on_job_close
    if not job or not kernel32.SetInformationJobObject(job, job_object_extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits)) \
            or not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise OSError(f"Could not create the job that stops the services together (error {ctypes.get_last_error()}).")


def is_running() -> bool:
    kernel32 = _kernel32()
    handle = kernel32.OpenEventW(0x1F0003, False, STOP_EVENT_NAME)
    if handle:
        kernel32.CloseHandle(handle)
    return bool(handle)


def request_stop(wait_seconds: float = 15.0) -> bool:
    """True once no supervisor is left running."""
    kernel32 = _kernel32()
    handle = kernel32.OpenEventW(0x1F0003, False, STOP_EVENT_NAME)
    if not handle:
        return True
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--running", action="store_true", help="exit 0 if a supervisor is running, 1 if not")
    parser.add_argument("--stop", action="store_true", help="stop the running supervisor and everything under it")
    arguments = parser.parse_args()
    if arguments.running:
        return 0 if is_running() else 1
    if arguments.stop:
        return 0 if request_stop() else 1
    if is_running():
        print("Already running in another window.")
        return 0

    kernel32 = _kernel32()
    os.system("")  # Turns on colours in a classic console.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stop_event = kernel32.CreateEventW(None, True, False, STOP_EVENT_NAME)
    join_kill_on_close_job()
    env = read_env(ROOT / ".env")

    def wait_for_stop() -> None:
        try:
            # Short waits: a wait that never returns would swallow Ctrl+C.
            while kernel32.WaitForSingleObject(stop_event, 500) != 0:
                pass
        except KeyboardInterrupt:
            pass

    Supervisor(enabled(services(), env), Redactor(env)).run(wait_for_stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
