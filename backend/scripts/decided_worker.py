"""Sends heard messages to the local decided service and records its suggestions (ticket 36).
Off unless DECIDED_URL is set. The service being down is normal, since it shares the GPU and may be
closed: the worker waits and tries again, and a message is simply labelled later.
"""
from __future__ import annotations

import argparse
import time

import httpx

from app.config.settings import get_settings
from app.discord.message_labels import MIN_TEXT_CHARS, MessageLabelService
from app.postgres.database import create_postgres_engine, create_session_factory

IDLE_SECONDS = 30
# The first message after an idle spell waits for the weights to load.
REQUEST_TIMEOUT_SECONDS = 180.0


def run_once(service: MessageLabelService, url: str, client: httpx.Client) -> int:
    done = 0
    for message_id, guild_id, text in service.unlabelled():
        if len(text.strip()) < MIN_TEXT_CHARS:
            service.record(message_id, guild_id, {"label": "ignore", "confidence": 1.0, "stable": True, "probs": {}, "model": "too-short"})
            continue
        response = client.post(f"{url.rstrip('/')}/classify", json={"text": text})
        response.raise_for_status()
        service.record(message_id, guild_id, response.json())
        done += 1
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    settings = get_settings()
    if not settings.decided_url:
        print({"worker": "decided", "status": "disabled", "reason": "DECIDED_URL is not set"}, flush=True)
        return 0
    service = MessageLabelService(create_session_factory(create_postgres_engine(str(settings.database_url))))
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        while True:
            try:
                done = run_once(service, settings.decided_url, client)
                print({"worker": "decided", "labelled": done}, flush=True)
            except httpx.HTTPError as error:
                print({"worker": "decided", "status": "waiting", "reason": type(error).__name__}, flush=True)
                done = 0
            if arguments.once:
                return 0
            if not done:
                time.sleep(IDLE_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
