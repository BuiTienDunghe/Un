"""What the decided model suggests for each heard message, and what a person said about it.

Holds no message text: the text is read from the ledger each time, so an edit or a Discord delete
there applies here too. Additive only: one new table.

Revision ID: 20261030_36
Revises: 20261027_35
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261030_36"
down_revision = "20261027_35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_message_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("discord_message_id", sa.Text(), nullable=False),
        sa.Column("guild_id", sa.Text(), nullable=False),
        sa.Column("suggested_label", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("stable", sa.Boolean(), nullable=False),
        sa.Column("probs", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("final_label", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('pending','approved','rejected','skipped')", name="ck_discord_message_labels_status"),
        sa.UniqueConstraint("discord_message_id", name="uq_discord_message_labels_message"),
    )
    op.create_index("ix_discord_message_labels_guild_status", "discord_message_labels", ["guild_id", "status", "final_label"])


def downgrade() -> None:
    op.drop_index("ix_discord_message_labels_guild_status", table_name="discord_message_labels")
    op.drop_table("discord_message_labels")
