"""phase 3b cancellation and job hardening"""
from alembic import op
import sqlalchemy as sa
revision="20260717_04"; down_revision="20260717_03"; branch_labels=None; depends_on=None
def upgrade():
    op.add_column("ingestion_runs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
def downgrade(): op.drop_column("ingestion_runs", "cancel_requested")
