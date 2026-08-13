from __future__ import annotations
import time
import argparse
from loguru import logger
from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.job_queue_service import JobQueueService
from app.services.outbox_dispatcher_service import OutboxDispatcherService

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
    dispatcher = OutboxDispatcherService(
        create_session_factory(create_postgres_engine(settings.database_url)),
        JobQueueService(
            settings.redis_url,
            settings.rq_queue_prefix,
            memory_queue_name=settings.discord_memory_queue_name,
        ),
        settings.job_max_attempts,
    )
    while True:
        count = dispatcher.dispatch_pending()
        logger.info("outbox dispatcher published {} event(s)", count)
        if args.once: break
        time.sleep(1)
