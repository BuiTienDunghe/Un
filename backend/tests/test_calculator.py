"""Ticket 34: exact arithmetic that can run nothing but arithmetic."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.agent_service import AgentService
from app.services.calculator import CalculationError, calculate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0.1 + 0.2", "0.3"),
        ("14500000 * 1.075", "15587500"),
        ("1250000 * 0.15", "187500"),
        ("(7 + 3) / 4", "2.5"),
        ("10 / 3", "3.333333333333"),
        ("2 ** 10", "1024"),
        ("-5 + 2", "-3"),
        ("17 // 5", "3"),
        ("17 % 5", "2"),
    ],
)
def test_the_sums_come_out_exact(expression, expected) -> None:
    assert calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('calc')", "open('x')", "(1).__class__", "abc", "[1, 2]", "'a' * 3", "True + 1",
        "lambda: 1", "1 if 1 else 2", "1 / 0", "9 ** 9 ** 9", "10 ** 1000", "", "1" * 300, "1.250.000", "((((", "2 ** (10 ** 9)",
    ],
)
def test_anything_else_is_refused_with_a_reason(expression) -> None:
    with pytest.raises(CalculationError):
        calculate(expression)


def agent() -> AgentService:
    return AgentService(SimpleNamespace(models={"general": {"name": "m"}}), SimpleNamespace(), SimpleNamespace())


def test_the_tool_returns_the_result_or_tells_the_model_what_to_fix() -> None:
    assert json.loads(agent()._execute_tool("calculate", {"expression": "2 + 2"}, None))["result"] == "4"
    bad = json.loads(agent()._execute_tool("calculate", {"expression": "abc"}, None))
    assert bad["code"] == "BAD_ARGUMENTS" and "số" in bad["error"]
    assert json.loads(agent()._execute_tool("calculate", {}, None))["code"] == "BAD_ARGUMENTS"
