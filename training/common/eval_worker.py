"""One RQ worker for an eval stack, in a form Windows can actually run.

The `rq worker` CLI forks per job. Windows has no fork, so it exits without a
word — which is why the product runs its OCR and index workers inside Linux
containers and the launcher never starts them on the host. SimpleWorker runs the
job in its own process instead, which is fine here: this worker exists to index
a fixed corpus once, not to survive a poisoned job in production.

    python -m training.common.eval_worker index
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"ocr", "index"}:
        print("usage: python -m training.common.drill_worker {ocr|index}")
        return 2
    queue_name = sys.argv[1]

    from redis import Redis
    from rq import Queue, SimpleWorker

    from app.config.settings import get_settings

    settings = get_settings()
    prefix = getattr(settings, "rq_queue_prefix", "local-ai:lab")
    connection = Redis.from_url(str(settings.redis_url))
    queue = Queue(f"{prefix}:{queue_name}", connection=connection)
    worker = SimpleWorker([queue], connection=connection)
    print(f"drill worker {queue_name}: queue={queue.name} db={str(settings.database_url).rsplit('/', 1)[-1]}", flush=True)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
