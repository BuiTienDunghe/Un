"""Tier 3 condensation worker (memory_design.md §7).

Runs on the host beside the other workers, and is the ONLY place in the
system that sends member text to a third party — which is why it is gated on
two switches at once: DISCORD_CONDENSATION_ENABLED and a real GEMINI_API_KEY.
Missing either, it says so and exits instead of pretending to work.

Nothing here touches the answer path (invariant #7): the API only reads the
propositions this worker writes. Recovery is the batch row's status + lease,
not a signal handler — same operating model as the other workers.
"""
from __future__ import annotations

import argparse
import time

from app.config.settings import get_settings
from app.llm_clients.gemini_client import GeminiClient
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.discord_condensation_service import DiscordCondensationService


def build_service(settings) -> DiscordCondensationService | None:
    if not settings.discord_condensation_enabled:
        print(
            {"worker": "condensation", "status": "disabled",
             "reason": "DISCORD_CONDENSATION_ENABLED is not true"},
            flush=True,
        )
        return None
    if not settings.gemini_api_key:
        print(
            {"worker": "condensation", "status": "disabled",
             "reason": "GEMINI_API_KEY is not set"},
            flush=True,
        )
        return None
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")

    condenser_config = settings.load_models().get("condenser", {})
    factory = create_session_factory(create_postgres_engine(str(settings.database_url)))
    return DiscordCondensationService(
        factory,
        GeminiClient(
            settings.gemini_api_key,
            settings.gemini_chat_timeout_seconds,
            settings.gemini_retry_count,
        ),
        model=str(condenser_config.get("name", "gemini-2.5-flash")),
        temperature=float(condenser_config.get("temperature", 0.2)),
        max_tokens=int(condenser_config.get("max_tokens", 4096)),
        min_batch=settings.discord_condensation_min_batch,
        max_batch=settings.discord_condensation_max_batch,
        silence_gap_minutes=settings.discord_condensation_silence_gap_minutes,
        worker_id="condensation-worker",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    arguments = parser.parse_args()

    settings = get_settings()
    service = build_service(settings)
    if service is None:
        return 0

    interval = max(60, settings.discord_condensation_interval_minutes * 60)
    print(
        {"worker": "condensation", "status": "started",
         "model": service.model, "min_batch": service.min_batch,
         "interval_seconds": interval},
        flush=True,
    )
    while True:
        try:
            outcomes = service.run_once()
            done = [item for item in outcomes if item.status == "completed"]
            print(
                {
                    "worker": "condensation",
                    "batches": len(done),
                    "propositions": sum(item.proposition_count for item in done),
                    "other": [
                        f"{item.status}:{item.reason}"
                        for item in outcomes
                        if item.status not in {"completed", "skipped"}
                    ],
                },
                flush=True,
            )
        except Exception as error:  # a bad cycle must never kill the worker
            print(
                {"worker": "condensation", "error": f"{type(error).__name__}: {error}"},
                flush=True,
            )
            if arguments.once:
                return 1
        if arguments.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
