"""Không gian Nghiên cứu: luồng chat lưu được (``research_threads``).

Một luồng là một dòng trỏ tới một ``conversations`` sẵn có — tin nhắn và trích
dẫn vẫn do rag_service lưu ở đó. ``paper_id`` NULL = luồng của cả dự án;
``conversation_id`` NULL cho tới tin đầu tiên. Additive only: một bảng mới.

Revision ID: 20261011_34
Revises: 20261011_33
"""

import sqlalchemy as sa
from alembic import op


revision = "20261011_34"
down_revision = "20261011_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_threads",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("paper_id", sa.String(length=128), nullable=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["research_papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_threads_project_id", "research_threads", ["project_id"])
    op.create_index("ix_research_threads_paper_id", "research_threads", ["paper_id"])
    op.create_index("ix_research_threads_conversation_id", "research_threads", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("research_threads")
