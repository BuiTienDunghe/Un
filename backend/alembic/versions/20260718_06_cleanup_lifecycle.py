"""cleanup lifecycle
Revision ID: 20260718_06
Revises: 20260718_05
"""
from alembic import op
import sqlalchemy as sa
revision="20260718_06"; down_revision="20260718_05"; branch_labels=None; depends_on=None
def upgrade():
 op.add_column("documents",sa.Column("deleted_requested_at",sa.DateTime(timezone=True),nullable=True)); op.add_column("documents",sa.Column("deleted_at",sa.DateTime(timezone=True),nullable=True)); op.create_index("ix_documents_cleanup_status", "documents", ["status","deleted_requested_at"])
def downgrade():
 op.drop_index("ix_documents_cleanup_status",table_name="documents"); op.drop_column("documents","deleted_at"); op.drop_column("documents","deleted_requested_at")
