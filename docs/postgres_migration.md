# PostgreSQL setup

The runtime is PostgreSQL-only since 2026-07-19. The steps of that move from SQLite, and its tools, were removed on 2026-10-30: see `.scratch/ARCHIVE.md` for the tag that holds them.

## Start the local PostgreSQL container

1. Set a non-placeholder `POSTGRES_PASSWORD` and matching `DATABASE_URL` in
   the local `.env` file.  Do not commit `.env`.
2. Start only the opt-in PostgreSQL profile:

   ```powershell
   docker compose --profile postgres up -d postgres
   ```

3. Apply the schema:

   ```powershell
   $env:DATABASE_URL = 'postgresql+psycopg://local_ai:YOUR_PASSWORD@127.0.0.1:5432/local_ai_core'
   .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
   ```

`alembic upgrade head --sql` can be used without `DATABASE_URL` to inspect the
PostgreSQL DDL; it does not contact a server.
