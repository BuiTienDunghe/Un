"""Create a portable PostgreSQL backup using host or Compose-container pg_dump."""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config.settings import get_settings

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/backups/postgres")
    parser.add_argument("--docker-service", help="Compose service containing pg_dump when host pg_dump is unavailable")
    args=parser.parse_args()
    url=get_settings().database_url
    if not url: raise RuntimeError("DATABASE_URL is required")
    parsed=urlparse(url.replace("postgresql+psycopg://", "postgresql://", 1))
    target=Path(args.output_dir); target.mkdir(parents=True, exist_ok=True)
    output=target / f"local-ai-{datetime.now().strftime('%Y%m%d-%H%M%S')}.dump"
    env=os.environ.copy()
    if parsed.password: env["PGPASSWORD"]=parsed.password
    if shutil.which("pg_dump"):
        command=["pg_dump", "--format=custom", "--file", str(output), "--host", parsed.hostname or "localhost", "--port", str(parsed.port or 5432), "--username", parsed.username or "postgres", parsed.path.lstrip("/")]
        subprocess.run(command, env=env, check=True)
    elif args.docker_service:
        # Stream a custom-format dump from the configured PostgreSQL container;
        # the database password is never put in the command or output.
        command=["docker", "compose", "exec", "-T", args.docker_service, "pg_dump", "--format=custom", "--username", parsed.username or "postgres", parsed.path.lstrip("/")]
        with output.open("wb") as handle:
            subprocess.run(command, stdout=handle, check=True)
    else:
        raise RuntimeError("pg_dump is unavailable on PATH; rerun with --docker-service <postgres-service>")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("pg_dump did not produce a non-empty backup")
    print(output)
if __name__=="__main__": main()
