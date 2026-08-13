"""persist Discord bot response delivery correlation

Revision ID: 20260728_15
Revises: 20260726_14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_15"
down_revision = "20260726_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A response can be split into multiple Discord messages. A child table
    # preserves every returned message ID and its delivery order without
    # changing or backfilling legacy turns.
    op.create_table(
        "discord_turn_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("discord_message_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_discord_turn_deliveries_chunk_index",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["discord_session_turns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "chunk_index",
            name="uq_discord_turn_delivery_chunk",
        ),
        sa.UniqueConstraint(
            "discord_message_id",
            name="uq_discord_turn_delivery_message",
        ),
    )


def downgrade() -> None:
    op.drop_table("discord_turn_deliveries")
