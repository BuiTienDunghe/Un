"""Tools that wait for a person before they run (ticket 46): what the agent loop needs to know.

A tool is declared with `requires_approval=True` (AgentTool). The loop then never runs it by
itself: it asks the gate it was given to keep the call (name and arguments, exactly as the model
wrote them), ends the turn with the gate's fixed reply, and goes no further. Running the call is
the gate's business, later, when the person it belongs to approves; nothing in the core decides
who that is. With no gate the tool is neither offered to the model nor run.

This file holds only the vocabulary the loop and a gate share, so the core imports nothing from
the package that implements the gate (app.discord.approvals).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# The final step's stop_reason when the turn ended on a call that waits for a person.
STOP_AWAITING_APPROVAL = "awaiting_approval"
# On the trace's tool_result step of that call: the tool has not run.
APPROVAL_PENDING = "APPROVAL_PENDING"
# Reached the model as a tool error: the tool is declared but nobody can approve it here.
APPROVAL_UNAVAILABLE = "APPROVAL_UNAVAILABLE"
# A tool that requires approval reached the code that runs tools without going through approval.
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class ApprovalError(Exception):
    """A refusal with a code. `message` is for whoever reads it: the model (as a tool error) or the person."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApprovalNotice:
    """A call that was kept. `reply` is the turn's answer, written by code, never by the model."""

    approval_id: str
    reply: str


class ApprovalGate(Protocol):
    def request(self, tool_name: str, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ApprovalNotice:
        """Keep the call and say how it will be approved. ApprovalError when it cannot be kept
        (nobody to approve it, too many waiting, switched off): the tool has not run either way."""
        ...
