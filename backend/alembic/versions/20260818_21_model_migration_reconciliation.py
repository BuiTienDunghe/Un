"""Reconcile the SQLAlchemy models with the migrated schema (P0-6).

`alembic check` reported 31 differences. They were not one problem but two, and
they are fixed in opposite directions:

* 14 of them are the database genuinely missing something the models declare -
  they are created here.
* 17 of them are model declarations that lied about a database that has been
  correct since 20260717_01 - those are fixed in `app/postgres/models.py`, with
  no DDL at all.

Two deliberate omissions, so the next reader does not re-open the question:

* `ix_documents_cleanup_status` and `ix_jobs_status_available` exist in the
  database but on no model. Autogenerate wants to drop them. Migrations here are
  additive only, and dropping a live index is a production change that buys
  nothing, so they are declared on the models instead.
* Plain `CREATE INDEX`, not `CONCURRENTLY`. `alembic/env.py` runs every
  migration inside one transaction and PostgreSQL rejects `CREATE INDEX
  CONCURRENTLY` there (SQLSTATE 25001). These tables are small on a personal
  installation, so a brief lock beats splitting the migration into
  autocommit blocks that cannot be rolled back as a unit.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260818_21"
down_revision = "20260818_20"
branch_labels = None
depends_on = None

# Every entry is either an unindexed child of an ON DELETE CASCADE foreign key
# (deleting one document would otherwise sequential-scan each child table) or a
# column that real application queries filter on.
INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_document_chunks_document_id", "document_chunks", ["document_id"]),
    ("ix_document_pages_document_id", "document_pages", ["document_id"]),
    ("ix_document_pages_version_id", "document_pages", ["version_id"]),
    ("ix_document_versions_document_id", "document_versions", ["document_id"]),
    ("ix_document_versions_status", "document_versions", ["status"]),
    ("ix_ingestion_runs_document_id", "ingestion_runs", ["document_id"]),
    ("ix_ingestion_runs_status", "ingestion_runs", ["status"]),
    ("ix_ingestion_runs_version_id", "ingestion_runs", ["version_id"]),
    ("ix_jobs_document_id", "jobs", ["document_id"]),
    ("ix_jobs_ingestion_run_id", "jobs", ["ingestion_run_id"]),
    ("ix_jobs_job_type", "jobs", ["job_type"]),
    ("ix_jobs_version_id", "jobs", ["version_id"]),
    ("ix_outbox_events_status", "outbox_events", ["status"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)
    # The outbox dedup key must never be NULL: PostgreSQL treats NULLs as
    # distinct inside a unique index, so a NULL key silently defeats the
    # deduplication the outbox depends on. Every writer already supplies one;
    # the backfill only covers rows predating that guarantee.
    op.execute("UPDATE outbox_events SET idempotency_key = 'legacy:' || id WHERE idempotency_key IS NULL")
    op.alter_column("outbox_events", "idempotency_key", existing_type=sa.String(length=255), nullable=False)


def downgrade() -> None:
    op.alter_column("outbox_events", "idempotency_key", existing_type=sa.String(length=255), nullable=True)
    # Backfilled 'legacy:' keys stay: a downgrade restores schema, it does not
    # destroy data it cannot tell apart from a real key.
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
