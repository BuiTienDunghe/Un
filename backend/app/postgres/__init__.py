"""PostgreSQL persistence layer — the application's sole runtime database.

`models.py` declares the schema (kept in lockstep with Alembic by the CI
`alembic check` gate), `repositories.py` holds per-unit-of-work data access for
the document/job pipeline, and `database.py` builds engines/session factories.
"""
