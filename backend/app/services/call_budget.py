"""How many times one turn may call the generation model (ticket 43, README.en rule 5).

The rule promises a fixed inference budget: the default answer path makes one call, and
three exceptions add at most one each. Until now nothing held it; a fourth call added to
rag_service or agent_service would have shipped silently. A fourth exception exists, off by
default (ticket 45): a pasted text too long for the window is read in parts, one call each,
under a budget of its own (long_input_call_cap) so the agent's cap stays what it was. A fifth, off in code and on
in models.yaml by the owner's decision on rule 5 (agent.lookup_check, harness-fix round): a turn that called no tool and gave
up ("tôi không có thông tin") is sent back once to look, which adds one call to the agent's cap (agent_call_cap). The entry point of a turn opens
a budget with its cap, ModelRouter counts every chat / chat_tools / stream_chat made while
it is open, and a turn that goes past its cap is logged and kept in OVERRUNS. Nothing is
blocked: the caps are worked out by hand, so a miscount must show up as a red test and a
warning, not as a user's turn that stops half way. The test (test_call_budget) drives each
path to its worst case and fails when OVERRUNS is not empty, or when a cap is loose.

A ContextVar for deadline.py's reason: the router is reached through wrappers and test
doubles that would all have to grow a parameter to carry one number. With no budget open
(indexing, the Discord pre-turn condensation) the router counts nothing. The agent eval
calls AgentService.run, so its turns are counted like any other.

Only generation calls count. Embeddings, OCR and vision are not part of the rule, and a
client's own transport retry of one request is below the router.
"""
from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_LOG = logging.getLogger(__name__)

# Plain chat: the answer. A RAG turn: the follow-up rewrite, then the answer.
CHAT_CALL_CAP = 1
RAG_CALL_CAP = 2


def agent_call_cap(max_steps: int, lookup_check: bool = False, read_on_check: bool = False, read_rest: bool = False, promise_check: bool = False) -> int:
    """`max_steps` tool rounds, plus one round for each of the two retries (figures the turn
    never saw; a tool call that would not parse), plus the forced answer when the rounds run out.
    The lookup check (off by default, harness-fix round) is one more retry, so one more call;
    so is the read-on check (off by default, 02/11) and the round that answers from what the
    code read (off by default, 03/11). The promise check (wherever a tool carries one, 03/11)
    adds two: the structured call for the owed tool's arguments, and the round that answers
    from its result (or, without structured output, the retry and nothing more)."""
    return max_steps + 3 + sum(1 for check in (lookup_check, read_on_check, read_rest) if check) + (2 if promise_check else 0)


def long_input_call_cap(parts: int) -> int:
    """Reading a paste in parts (ticket 45, README.en rule 5's fourth exception): one call per
    part read, and `parts` is bounded by long_input.LONG_INPUT_MAX_PARTS. Its calls are counted
    in a budget nested inside the agent's, so they never eat into agent_call_cap."""
    return parts


def read_rest_call_cap(parts: int) -> int:
    """The code reading the rest of a document (README.en rule 5's sixth exception): one call per
    part, `parts` bounded by document_reading.READ_REST_MAX_PARTS, nested like long_input's."""
    return parts


@dataclass
class TurnCalls:
    turn: str
    cap: int
    used: int = 0


_CURRENT: ContextVar[TurnCalls | None] = ContextVar("llm_turn_calls", default=None)

# (turn, cap, calls made so far) of every turn that went past its cap, newest last. Bounded:
# it is read by the test and by someone looking, not a log of record.
OVERRUNS: deque[tuple[str, int, int]] = deque(maxlen=50)


@contextmanager
def turn_call_budget(turn: str, cap: int) -> Iterator[TurnCalls]:
    """Count the generation calls made inside this block against `cap`. A budget opened
    inside another takes the calls made inside it, so each entry point answers for its own."""
    calls = TurnCalls(turn, cap)
    token = _CURRENT.set(calls)
    try:
        yield calls
    finally:
        _CURRENT.reset(token)


def count_generation_call() -> None:
    """Called by ModelRouter before every generation call. Does nothing outside a budget."""
    calls = _CURRENT.get()
    if calls is None:
        return
    calls.used += 1
    if calls.used > calls.cap:
        OVERRUNS.append((calls.turn, calls.cap, calls.used))
        _LOG.warning("%s turn made generation call %d, over its cap of %d", calls.turn, calls.used, calls.cap)
