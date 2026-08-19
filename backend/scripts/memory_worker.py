"""Windows-host RQ consumer for the Discord memory-extraction queue.

The compose `worker-memory` service runs the same queue inside Docker, but the
one-click launcher does not build images; this entrypoint lets the default
install consume `{prefix}:{memory_queue}` with the project venv. SimpleWorker
is deliberate: RQ's default Worker forks, which Windows cannot do — the test
suite's RQ integration tests run SimpleWorker on this host for the same reason.
"""
from __future__ import annotations

import argparse

from redis import Redis
from rq import Queue, SimpleWorker

# Imported eagerly so a broken task path fails at startup, not per-job.
from app.config.settings import get_settings
from app.workers import memory_tasks  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord memory extraction worker (host)")
    parser.add_argument("--burst", action="store_true", help="Drain the queue once and exit (acceptance/testing)")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    redis = Redis.from_url(settings.redis_url)
    queue_name = f"{settings.rq_queue_prefix}:{settings.discord_memory_queue_name}"
    print(f"memory worker listening on {queue_name}", flush=True)
    worker = SimpleWorker([Queue(queue_name, connection=redis)], connection=redis)
    worker.work(burst=args.burst, with_scheduler=True, logging_level="INFO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
