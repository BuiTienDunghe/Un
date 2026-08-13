"""allow an explicit pre-filter Discord memory receipt

Revision ID: 20260728_17
Revises: 20260728_16
"""

from alembic import op
import sqlalchemy as sa

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_FILTER_DECISIONS_V1,
    DISCORD_MEMORY_FILTER_DECISIONS_V2,
)


revision = "20260728_17"
down_revision = "20260728_16"
branch_labels = None
depends_on = None


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_filter_decision",
        "discord_memory_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_filter_decision",
        "discord_memory_candidates",
        f"filter_decision IN ({_quoted(DISCORD_MEMORY_FILTER_DECISIONS_V2)})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_filter_decision",
        "discord_memory_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_filter_decision",
        "discord_memory_candidates",
        f"filter_decision IN ({_quoted(DISCORD_MEMORY_FILTER_DECISIONS_V1)})",
    )

