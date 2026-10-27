"""Agent trace summaries: the content-free skeleton of each agent step (ticket 16).

One row per step of agent_traces, minus every argument, result and answer, so it
can outlive the conversation that agent_traces still cascades with. No foreign key
on purpose: telemetry outlives its subject, as request_logs.message_id already does.
Additive only: one new table, nothing backfilled (agent_traces held 0 rows).

Revision ID: 20261027_35
Revises: 20261011_34
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261027_35"
down_revision = "20261011_34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_trace_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("arguments_shape", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_trace_summaries_conversation_created", "agent_trace_summaries", ["conversation_id", "created_at"])
    op.create_index("ix_agent_trace_summaries_message_id", "agent_trace_summaries", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_trace_summaries_message_id", table_name="agent_trace_summaries")
    op.drop_index("ix_agent_trace_summaries_conversation_created", table_name="agent_trace_summaries")
    op.drop_table("agent_trace_summaries")
