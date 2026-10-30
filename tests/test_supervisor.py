"""The one window (ticket 38): what it starts, what it keeps out of its files, and when it gives up."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from datetime import date
from pathlib import Path

import pytest

from tools import supervisor
from tools.supervisor import DailyLog, Redactor, Service, Supervisor, backoff, enabled, prune, read_env, services

REPO = Path(__file__).resolve().parent.parent


def names(env: dict[str, str]) -> list[str]:
    return [service.name for service in enabled(services("python"), env)]


def script(tmp_path: Path, body: str) -> tuple[str, ...]:
    path = tmp_path / "service.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return (sys.executable, "-u", str(path))


def run_until(sup: Supervisor, done, timeout: float = 30.0) -> None:
    def wait_for_stop() -> None:
        deadline = time.monotonic() + timeout
        while not done() and time.monotonic() < deadline:
            time.sleep(0.05)

    sup.run(wait_for_stop)


def test_flags_decide_what_starts_like_the_launcher_did() -> None:
    assert names({}) == ["api", "backup", "cleanup"]
    assert "condenser" in names({"DISCORD_CONDENSATION_ENABLED": "true"})
    assert "condenser" not in names({"DISCORD_CONDENSATION_ENABLED": "false"})
    assert {"outbox", "memory"} <= set(names({"DISCORD_MEMORY_INGESTION_ENABLED": "true"}))
    assert {"decided", "decided-worker"} <= set(names({"DECIDED_URL": "http://127.0.0.1:8377"}))
    assert "decided" not in names({"DECIDED_URL": ""})


def test_env_file_reader_skips_comments_and_quotes(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('# A=1\nB=2\nC="three"\nnoise\n', encoding="utf-8")
    assert read_env(path) == {"B": "2", "C": "three"}
    assert read_env(tmp_path / "absent") == {}


def test_secrets_never_reach_a_line() -> None:
    redact = Redactor({"ANTHROPIC_API_KEY": "sk-long-secret-value", "DISCORD_TOKEN": "abc.def.ghi", "SHORT_KEY": "off", "DECIDED_URL": "http://x"})
    assert "sk-long-secret-value" not in redact("failed with sk-long-secret-value in it")
    assert "abc.def.ghi" not in redact("token abc.def.ghi")
    assert redact("the word off stays") == "the word off stays"
    assert "hunter2" not in redact("cannot reach postgresql://user:hunter2@localhost:5432/db")
    assert redact('127.0.0.1:1 - "GET /search?q=private+words HTTP/1.1" 200') == '127.0.0.1:1 - "GET /search?<hidden> HTTP/1.1" 200'


def test_a_new_day_opens_a_new_file_and_old_files_go(tmp_path: Path) -> None:
    (tmp_path / "api_2026-01-01.log").write_text("old", encoding="utf-8")
    (tmp_path / "api_notadate.log").write_text("keep", encoding="utf-8")
    days = [date(2026, 10, 30), date(2026, 10, 31)]
    log = DailyLog("api", tmp_path, today=lambda: days[0])
    log.write("one")
    days.pop(0)
    log.write("two")
    log.file.close()
    assert "one" in (tmp_path / "api_2026-10-30.log").read_text(encoding="utf-8")
    assert "two" in (tmp_path / "api_2026-10-31.log").read_text(encoding="utf-8")
    assert not (tmp_path / "api_2026-01-01.log").exists()
    assert (tmp_path / "api_notadate.log").exists()


def test_prune_keeps_what_is_inside_the_window(tmp_path: Path) -> None:
    kept = tmp_path / "api_2026-10-01.log"
    kept.write_text("x", encoding="utf-8")
    prune(tmp_path, date(2026, 10, 31))
    assert kept.exists()


def test_backoff_grows_and_stops_growing() -> None:
    assert [backoff(n) for n in (1, 2, 3)] == [5, 10, 20]
    assert backoff(50) == 300


def test_a_clean_exit_is_not_restarted(tmp_path: Path) -> None:
    command = script(tmp_path, "print('nothing to do')")
    sup = Supervisor([Service("w", command, tmp_path)], lambda line: line, tmp_path)
    run_until(sup, lambda: any("not restarting" in p.read_text(encoding="utf-8") for p in tmp_path.glob("w_*.log")))
    text = next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8")
    assert "nothing to do" in text and text.count("[started]") == 1


def test_a_dying_service_restarts_and_gives_up_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "backoff", lambda failures: 0)
    monkeypatch.setattr(supervisor, "MAX_QUICK_FAILURES", 3)
    command = script(tmp_path, "import sys; print('why it died'); sys.exit(7)")
    sup = Supervisor([Service("w", command, tmp_path)], lambda line: line, tmp_path)
    run_until(sup, lambda: sup.down == ["w"])
    text = next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8")
    assert text.count("[started]") == 3 and text.count("why it died") == 3
    assert "DOWN" in text and "last 7" in text


def test_unstartable_command_is_reported_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "backoff", lambda failures: 0)
    monkeypatch.setattr(supervisor, "MAX_QUICK_FAILURES", 2)
    sup = Supervisor([Service("w", (str(tmp_path / "no-such-program.exe"),), tmp_path)], lambda line: line, tmp_path)
    run_until(sup, lambda: sup.down == ["w"])
    assert "could not start" in next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8")


def test_lines_are_redacted_before_the_file(tmp_path: Path) -> None:
    command = script(tmp_path, "print('key sk-long-secret-value end')")
    sup = Supervisor([Service("w", command, tmp_path)], Redactor({"A_KEY": "sk-long-secret-value"}), tmp_path)
    run_until(sup, lambda: any("not restarting" in p.read_text(encoding="utf-8") for p in tmp_path.glob("w_*.log")))
    assert "sk-long-secret-value" not in next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8")


def test_a_full_console_never_holds_a_service_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting text in a window stops it reading; the file must keep every line anyway."""
    monkeypatch.setattr(supervisor, "CONSOLE_BACKLOG", 2)
    sup = Supervisor([], lambda line: line, tmp_path)
    log = DailyLog("w", tmp_path)
    for index in range(50):
        sup.say("w", f"line {index}", log)
    log.file.close()
    assert sup.console.qsize() == 2
    assert len(next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8").splitlines()) == 50


@pytest.mark.skipif(sys.platform != "win32", reason="the job and the stop signal are Windows objects")
def test_stop_signal_takes_the_children_down_with_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real thing, in a process of its own: stop, and no service is left behind.
    Under its own signal name: this suite must never stop the stack running on the same machine."""
    event = f"Local\\LocalAICoreSupervisorTest{os.getpid()}"
    monkeypatch.setattr(supervisor, "STOP_EVENT_NAME", event)
    pid_file = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    child.write_text(f"import os, time, pathlib\npathlib.Path(r'{pid_file}').write_text(str(os.getpid()))\ntime.sleep(120)\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from tools import supervisor as s
        s.STOP_EVENT_NAME = r'{event}'
        s.LOG_DIR = Path(r'{tmp_path}')
        s.ROOT = Path(r'{tmp_path}')
        s.services = lambda: [s.Service('child', (sys.executable, '-u', r'{child}'), Path(r'{tmp_path}'))]
        s.enabled = lambda found, env: found
        sys.argv = ['supervisor']
        raise SystemExit(s.main())
    """), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    process = subprocess.Popen([sys.executable, str(runner)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        pid = int(pid_file.read_text())
        assert supervisor.is_running()
        assert supervisor.request_stop()
        process.wait(timeout=15)
        time.sleep(0.5)
        listed = subprocess.run(["tasklist", "/fi", f"pid eq {pid}", "/nh"], capture_output=True, text=True).stdout
        assert str(pid) not in listed
        assert not supervisor.is_running()
    finally:
        process.kill()


def test_launcher_and_stop_go_through_the_supervisor() -> None:
    launcher = (REPO / "run-local-ai-core.bat").read_text(encoding="utf-8")
    assert launcher.index("--ollama-pull-list") < launcher.index("-m tools.supervisor")
    assert "windowtitle" not in launcher and "uvicorn app.main" not in launcher
    assert "tools.supervisor --stop" in (REPO / "stop-local-ai-core.bat").read_text(encoding="utf-8")
    decided = (REPO / "run-decided.bat").read_text(encoding="utf-8").lower()
    assert "\ntitle " not in decided and "windowtitle" not in decided


def test_every_start_reads_the_pick_and_an_empty_one_clears_the_pin(tmp_path: Path) -> None:
    choice = tmp_path / "model_choice.env"
    choice.write_text("MODEL_VERSION_GENERAL=\nMODEL_VERSION_OCR=ocr-v1\n", encoding="utf-8")
    env = supervisor.service_env({"MODEL_VERSION_GENERAL": "general-haiku-v1", "KEEP": "1"}, choice)
    assert "MODEL_VERSION_GENERAL" not in env
    assert env["MODEL_VERSION_OCR"] == "ocr-v1" and env["KEEP"] == "1" and env["LOCAL_AI_SUPERVISED"] == "1"
    assert supervisor.service_env({"A": "1"}, tmp_path / "absent")["A"] == "1"


def test_leaving_to_apply_a_pick_is_a_restart_not_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "MAX_QUICK_FAILURES", 1)
    flag = tmp_path / "ran"
    command = script(tmp_path, f"""
        import pathlib, sys
        flag = pathlib.Path(r'{flag}')
        if flag.exists():
            sys.exit(0)
        flag.write_text('x')
        sys.exit({supervisor.RESTART_EXIT_CODE})
    """)
    sup = Supervisor([Service("w", command, tmp_path)], lambda line: line, tmp_path)
    run_until(sup, lambda: any("not restarting" in p.read_text(encoding="utf-8") for p in tmp_path.glob("w_*.log")))
    text = next(tmp_path.glob("w_*.log")).read_text(encoding="utf-8")
    assert text.count("[started]") == 2 and "restarting on the model" in text and sup.down == []
