from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.discord_memory_recovery_service import (
    DiscordMemoryRecoveryService,
)


settings = get_settings()
if not settings.database_url:
    raise SystemExit("DATABASE_URL is required")
parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument("--dry-run", action="store_true")
mode.add_argument("--execute", action="store_true")
arguments = parser.parse_args()
service = DiscordMemoryRecoveryService(
    create_session_factory(create_postgres_engine(settings.database_url))
)
print(
    {
        "mode": "dry-run" if arguments.dry_run else "execute",
        "stale_memory_jobs": service.recover_stale(
            dry_run=arguments.dry_run
        ),
    }
)
