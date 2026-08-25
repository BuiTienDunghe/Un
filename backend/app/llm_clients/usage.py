"""Per-call token usage, handed from the LLM client to whoever logs the request.

Ollama reports prompt_eval_count/eval_count in the same response body the
client already parses; until D4-lite the client kept message.content and threw
the rest away, so "was the 16 s prompt-eval or generation?" was unanswerable.

A ContextVar rather than a return-value change on purpose: router.chat() is a
2-tuple at seven call sites across three provider clients, and widening it
would touch all of them to serve one telemetry column. A ContextVar is scoped
per thread/task, so concurrent requests cannot read each other's numbers —
the failure a plain attribute on the client would invite.

Providers that report nothing (Gemini/DeepSeek today) simply never call
record_usage, and the columns stay NULL — absence is visible, not faked.
"""
from __future__ import annotations

from contextvars import ContextVar

_LAST_USAGE: ContextVar[dict[str, int] | None] = ContextVar("llm_last_usage", default=None)


def record_usage(prompt_tokens: int | None, completion_tokens: int | None) -> None:
    _LAST_USAGE.set({
        "tokens_in": int(prompt_tokens) if prompt_tokens is not None else None,
        "tokens_out": int(completion_tokens) if completion_tokens is not None else None,
    })


def consume_usage() -> dict[str, int | None]:
    """Read and clear the last call's usage. Clearing matters: without it a
    follow-up call that fails to report would silently inherit the previous
    call's numbers."""
    value = _LAST_USAGE.get()
    _LAST_USAGE.set(None)
    return value or {"tokens_in": None, "tokens_out": None}
