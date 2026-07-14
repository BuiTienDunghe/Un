from __future__ import annotations

from pathlib import Path
from time import perf_counter
from collections.abc import Iterator

from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter


class CodeService:
    def __init__(self, router: ModelRouter, logging_service: LoggingService) -> None:
        self.router = router
        self.logging_service = logging_service
        self.system_prompt = (Path(__file__).parents[1] / "prompts" / "code_system.md").read_text(encoding="utf-8")

    def respond(self, message: str, code_context: str | None, repo_context: str | None) -> tuple[str, str, int]:
        parts = [message]
        if code_context:
            parts.append(f"\n\nCode or traceback:\n{code_context}")
        if repo_context:
            parts.append(f"\n\nRepository context:\n{repo_context}")
        started = perf_counter()
        answer, model_used = self.router.chat(
            "code", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": "".join(parts)}]
        )
        latency_ms = int((perf_counter() - started) * 1000)
        self.logging_service.log_request("/code/chat", model_used, latency_ms, "ok")
        return answer, model_used, latency_ms

    def stream_response(self, message: str, code_context: str | None, repo_context: str | None) -> tuple[Iterator[str], str]:
        parts = [message]
        if code_context:
            parts.append(f"\n\nCode or traceback:\n{code_context}")
        if repo_context:
            parts.append(f"\n\nRepository context:\n{repo_context}")
        tokens, model_used = self.router.stream_chat("code", [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": "".join(parts)}])

        def generate() -> Iterator[str]:
            started = perf_counter()
            completed = False
            try:
                for token in tokens:
                    yield token
                completed = True
            finally:
                if completed:
                    self.logging_service.log_request("/code/chat", model_used, int((perf_counter() - started) * 1000), "ok")

        return generate(), model_used
