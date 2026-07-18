"""transactional outbox fields

Revision ID: 20260718_05
Revises: 20260717_04
"""
from alembic import op
import sqlalchemy as sa

revision = "20260718_05"
down_revision = "20260717_04"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("outbox_events", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.add_column("outbox_events", sa.Column("job_id", sa.String(128), nullable=True))
    op.add_column("outbox_events", sa.Column("redis_job_id", sa.String(128), nullable=True))
    op.create_unique_constraint("uq_outbox_events_idempotency_key", "outbox_events", ["idempotency_key"])
    op.create_index("ix_outbox_events_job_id", "outbox_events", ["job_id"])

def downgrade():
    op.drop_index("ix_outbox_events_job_id", table_name="outbox_events")
    op.drop_constraint("uq_outbox_events_idempotency_key", "outbox_events", type_="unique")
    op.drop_column("outbox_events", "redis_job_id")
    op.drop_column("outbox_events", "job_id")
    op.drop_column("outbox_events", "idempotency_key")
