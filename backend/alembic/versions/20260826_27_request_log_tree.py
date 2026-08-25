"""request_logs: a join key, token counts, and the prompt's hash (D4-lite).

Before this, request_logs was seven columns with one integer for the whole
request and NO link to anything: the only way to connect "this question took
16 s" to "this question was X" was a timestamp 19 ms apart, and 19% of the
question rows in production were already orphaned that way (conversation
deleted, messages cascaded, measurement left dangling).

message_id deliberately has NO foreign key. agent_traces has FKs with
ondelete=CASCADE and the consequence is measured: its sequence is at 20 and
the table is at 0 — every trace was deleted with the conversation it
explained. Telemetry must outlive the thing it measures; a dangling id still
says "there was an answer", and the 7-day retention bounds it anyway.

tokens_in/tokens_out are Ollama's own prompt_eval_count/eval_count, which the
client used to parse and throw away. prompt_hash is the sha256 of the
ASSEMBLED system prompt (after injection-defense wrapping) — the only
mechanism that answers "did the prompt change on Tuesday?" and the only kind
of check that catches a version label sitting on the wrong text.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260826_27"
down_revision = "20260825_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.add_column("request_logs", sa.Column("tokens_in", sa.Integer(), nullable=True))
    op.add_column("request_logs", sa.Column("tokens_out", sa.Integer(), nullable=True))
    op.add_column("request_logs", sa.Column("prompt_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_request_logs_message_id", "request_logs", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_request_logs_message_id", table_name="request_logs")
    op.drop_column("request_logs", "prompt_hash")
    op.drop_column("request_logs", "tokens_out")
    op.drop_column("request_logs", "tokens_in")
    op.drop_column("request_logs", "message_id")
