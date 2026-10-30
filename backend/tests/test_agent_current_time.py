"""Ticket 32: the agent reads the clock through a tool, in Vietnam's time."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import app.services.agent_service as agent_service
from app.services.agent_service import AgentService, core_tools


def agent() -> AgentService:
    router = SimpleNamespace(models={"general": {"name": "m"}})
    return AgentService(router, SimpleNamespace(), SimpleNamespace())


def test_the_tool_says_the_date_the_weekday_and_the_time_in_vietnam(monkeypatch) -> None:
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            # 18:30 UTC on Friday 30/10/2026 is already 01:30 on Saturday in Vietnam.
            return datetime(2026, 10, 30, 18, 30, 5, tzinfo=agent_service.timezone.utc).astimezone(tz)

    monkeypatch.setattr(agent_service, "datetime", Fixed)
    payload = json.loads(agent()._execute_tool("current_time", {}, None))
    assert payload["date"] == "31/10/2026"
    assert payload["weekday"] == "Thứ Bảy"
    assert payload["time"] == "01:30"
    assert payload["iso"] == "2026-10-31T01:30:05+07:00"


def test_the_guide_names_the_tool_so_the_model_knows_to_use_it() -> None:
    assert "current_time" in agent_service.AGENT_GUIDE
    assert core_tools().get("current_time").label == "Đang xem giờ…"
