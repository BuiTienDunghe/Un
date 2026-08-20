"""Trace table for agent-mode answers (P2-2).

Each row is one step of the agent loop — a tool call, its result, or the final
synthesis — linked to the assistant message it produced so an operator can
replay why the agent answered the way it did.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260819_22"
down_revision = "20260818_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("arguments", JSONB(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_traces_message_id", "agent_traces", ["message_id"])
    op.create_index(
        "ix_agent_traces_conversation_created",
        "agent_traces",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_traces_conversation_created", table_name="agent_traces")
    op.drop_index("ix_agent_traces_message_id", table_name="agent_traces")
    op.drop_table("agent_traces")
