"""phase 3 durable RQ job metadata

Revision ID: 20260717_03
Revises: 20260717_02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_03"
down_revision = "20260717_02"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.add_column("jobs", sa.Column("redis_job_id", sa.String(128), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(64), nullable=True))
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_unique_constraint("uq_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.create_unique_constraint("uq_jobs_redis_job_id", "jobs", ["redis_job_id"])
    op.create_index("ix_jobs_status_available", "jobs", ["status", "available_at"])

def downgrade() -> None:
    op.drop_index("ix_jobs_status_available", table_name="jobs")
    op.drop_constraint("uq_jobs_redis_job_id", "jobs", type_="unique")
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    for column in ("updated_at", "lease_expires_at", "heartbeat_at", "error_code", "redis_job_id", "idempotency_key"):
        op.drop_column("jobs", column)
