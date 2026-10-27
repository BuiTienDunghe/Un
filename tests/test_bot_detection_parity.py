"""The panel and the dashboard call the same processes "the host bot" (ticket 04).

Two detectors exist on purpose: discord_bot/control.py (the tkinter panel) and
backend/app/services/bot_control_service.py (the dashboard). The backend does not
import the bot — they only talk over HTTP — so the scan is written twice, and this
test is what keeps the two copies agreeing. Both read psutil.process_iter, so one
fake process table feeds both.
"""
from __future__ import annotations

from pathlib import Path

import psutil
import pytest

from app.services.bot_control_service import host_bot_pids
from discord_bot.control import matching_bot_processes


class FakeProcess:
    def __init__(self, pid: int, name: str | None, cmdline: list[str] | None, cwd: Path | Exception) -> None:
        self.pid = pid
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}
        self._cwd = cwd

    def cwd(self) -> str:
        if isinstance(self._cwd, Exception):
            raise self._cwd
        return str(self._cwd)


def table(repo: Path, elsewhere: Path) -> list[FakeProcess]:
    bot = ["python.exe", "-m", "discord_bot.main"]
    return [
        FakeProcess(1, "python.exe", bot, repo),                                     # the panel's bot
        FakeProcess(2, "pythonw.exe", bot, repo),                                    # windowless
        FakeProcess(3, "Python.EXE", bot, repo),                                     # name case
        FakeProcess(4, "python", ["python", "-X", "utf8", "-m", "discord_bot.main"], repo),  # flags before -m
        FakeProcess(5, "python.exe", bot, elsewhere),                                # another checkout
        FakeProcess(6, "python.exe", ["python.exe", "-m", "discord_bot.mainx"], repo),
        FakeProcess(7, "python.exe", ["python.exe", "discord_bot/main.py"], repo),   # not -m
        FakeProcess(8, "python.exe", ["python.exe", "-m"], repo),                    # -m last
        FakeProcess(9, "node.exe", bot, repo),                                       # not python
        FakeProcess(10, "python.exe", None, repo),                                   # no cmdline
        FakeProcess(11, None, bot, repo),                                            # no name
        FakeProcess(12, "python.exe", bot, psutil.AccessDenied(12)),                 # cwd unreadable: counts
        FakeProcess(13, "python.exe", bot, psutil.NoSuchProcess(13)),                # gone mid-scan: counts
        FakeProcess(14, "python.exe", ["python.exe", "-m", "uvicorn", "app.main:app"], repo),
    ]


@pytest.fixture
def processes(tmp_path, monkeypatch):
    repo, elsewhere = tmp_path / "repo", tmp_path / "copy"
    repo.mkdir()
    elsewhere.mkdir()
    fakes = table(repo, elsewhere)
    monkeypatch.setattr(psutil, "process_iter", lambda *args, **kwargs: iter(fakes))
    return repo


def test_both_detectors_pick_the_same_processes(processes):
    panel = sorted(process.pid for process in matching_bot_processes(processes))
    dashboard = sorted(host_bot_pids(processes))

    assert panel == dashboard
    # Pinned too, so a change that moves BOTH the same wrong way still fails here.
    assert dashboard == [1, 2, 3, 4, 12, 13]
