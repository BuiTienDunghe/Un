"""The 1-vs-1 verifier — job 4's model half (memory_design.md §13.2 E1).

The deterministic guard answers "is the quote real and do the words match";
it measurably CANNOT answer "does the fact FOLLOW from the source" — it
accepted 'Dũng dùng Postgres' against a source saying the opposite (§9.1).
This adapter asks the local model exactly that one question, one candidate
versus one source, and returns a 3-state verdict:

  entailment    → eligible for autonomous apply, when the threshold returns
  contradiction → human review with the supersession pre-filled — a model
                  verdict NEVER supersedes anything on its own
  unknown       → human review

Fail-safe by construction: any transport error, timeout, or unparseable
answer is "unknown" — the candidate simply waits for a human, which is
today's behaviour. The verifier can make the pipeline more autonomous,
never less safe.

Budget (measured, §13.1): ~16 candidates/day × one extra ~60s call = well
inside the night window; 1-vs-1 saturates at ~3,400 msg/day, 11× the
committed target. Runs in the background worker only — invariant #7's
default answer path is untouched.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.postgres.discord_memory_constants import DISCORD_MEMORY_VERIFICATION_RESULTS_V1

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "verify-v1"

_SYSTEM_PROMPT = (
    "Bạn là bộ kiểm chứng suy luận. Cho một NGUỒN (tin nhắn gốc) và một MỆNH ĐỀ "
    "(sự việc được đề xuất ghi nhớ), trả lời đúng MỘT từ:\n"
    "- ENTAILMENT: mệnh đề suy ra trực tiếp từ nguồn.\n"
    "- CONTRADICTION: nguồn phủ nhận hoặc nói ngược với mệnh đề.\n"
    "- UNKNOWN: nguồn không đủ căn cứ để khẳng định hay phủ nhận.\n"
    "Chỉ trả lời một từ, viết hoa, không giải thích."
)


@dataclass(frozen=True, slots=True)
class DiscordMemoryVerdict:
    result: str  # one of DISCORD_MEMORY_VERIFICATION_RESULTS_V1
    method: str  # e.g. "nli-1v1:qwen3.5:9b/verify-v1"
    raw_answer: str
    latency_ms: int


class DiscordMemoryVerifierAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        model: str = "qwen3.5:9b",
        num_ctx: int = 2048,
        temperature: float = 0.0,
        timeout_seconds: float = 90.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.client = client

    @property
    def method(self) -> str:
        return f"nli-1v1:{self.model}/{_PROMPT_VERSION}"

    def verify(self, *, canonical_fact: str, source_text: str) -> DiscordMemoryVerdict:
        started = time.perf_counter()
        raw = ""
        try:
            post = self.client.post if self.client is not None else httpx.post
            response = post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"NGUỒN: {source_text}\n"
                                f"MỆNH ĐỀ: {canonical_fact}\n"
                                "Trả lời một từ:"
                            ),
                        },
                    ],
                    "options": {
                        "num_ctx": self.num_ctx,
                        "temperature": self.temperature,
                        "num_predict": 8,
                    },
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw = str(
                (response.json().get("message") or {}).get("content") or ""
            ).strip()
        except Exception:
            logger.exception("memory verifier transport failed; verdict=unknown")
        latency_ms = int((time.perf_counter() - started) * 1000)
        return DiscordMemoryVerdict(
            result=self._parse(raw),
            method=self.method,
            raw_answer=raw[:200],
            latency_ms=latency_ms,
        )

    @staticmethod
    def _parse(raw: str) -> str:
        answer = raw.strip().lower()
        for label in DISCORD_MEMORY_VERIFICATION_RESULTS_V1:
            if answer.startswith(label):
                return label
        # Anything else — empty, prose, refusal — waits for a human.
        return "unknown"
