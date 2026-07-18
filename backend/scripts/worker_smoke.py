"""Bounded worker startup probe; it never calls OCR, embedding, or Qdrant."""
from __future__ import annotations

import argparse
import json

from redis import Redis
from rq import Queue
from sqlalchemy import text

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine


def probe(role: str) -> dict[str, str]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    # Import validates that the RQ task path used by Docker is resolvable.
    import app.workers.tasks  # noqa: F401
    with create_postgres_engine(settings.database_url).connect() as connection:
        connection.execute(text("SELECT 1"))
    redis = Redis.from_url(settings.redis_url); redis.ping()
    queue_name = f"{settings.rq_queue_prefix}:{'ocr' if role == 'ocr' else 'index'}"
    Queue(queue_name, connection=redis)
    return {"role": role, "queue": queue_name, "postgres": "ok", "redis": "ok", "task_import": "ok"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--role", choices=("ocr", "index"), required=True)
    print(json.dumps(probe(parser.parse_args().role)))
