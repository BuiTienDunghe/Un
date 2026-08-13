"""bound deterministic Discord memory filter vocabulary

Revision ID: 20260728_18
Revises: 20260728_17
"""

from alembic import op

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2,
    DISCORD_MEMORY_FILTER_DECISIONS_V2,
    DISCORD_MEMORY_FILTER_DECISIONS_V3,
    DISCORD_MEMORY_FILTER_REASON_CODES_V1,
    DISCORD_MEMORY_VALIDATION_STATUSES_V1,
)


revision = "20260728_18"
down_revision = "20260728_17"
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
        f"filter_decision IN ({_quoted(DISCORD_MEMORY_FILTER_DECISIONS_V3)})",
    )
    op.drop_constraint(
        "ck_discord_memory_candidates_validation_status",
        "discord_memory_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_validation_status",
        "discord_memory_candidates",
        "validation_status IN "
        f"({_quoted(DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2)})",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        "filter_reason_code IN "
        f"({_quoted(DISCORD_MEMORY_FILTER_REASON_CODES_V1)})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_discord_memory_candidates_validation_status",
        "discord_memory_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_validation_status",
        "discord_memory_candidates",
        f"validation_status IN ({_quoted(DISCORD_MEMORY_VALIDATION_STATUSES_V1)})",
    )
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

