"""memory vocabulary v2: personal_fact filter reason

Three production statements died at the filter gate as no_durable_fact because
the closed vocabulary had no birthday key ("tôi thích trà sữa" 25/08 guild 1;
both birthdays of 27/08 guild 2 turn 12 — memory_design.md §13). The rule
filter v2 emits reason "personal_fact" for first-person birthday statements;
this revision widens the candidates CHECK to accept it.

Additive only: existing rows all satisfy the wider constraint. Downgrade
restores the V1 list — safe as long as no personal_fact rows exist yet, which
is exactly the pre-upgrade state it returns to.

Revision ID: 20260828_29
Revises: 20260827_28
"""

from alembic import op

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_FILTER_REASON_CODES_V1,
    DISCORD_MEMORY_FILTER_REASON_CODES_V2,
)


revision = "20260828_29"
down_revision = "20260827_28"
branch_labels = None
depends_on = None


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        "filter_reason_code IN "
        f"({_quoted(DISCORD_MEMORY_FILTER_REASON_CODES_V2)})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        type_="check",
    )
    # Rows the V1 constraint cannot accept are remapped to exactly the
    # classification those messages had in the V1 era (they died as
    # no_durable_fact) — otherwise the CHECK recreation below fails the
    # moment one personal_fact row exists (review finding 28/08).
    op.execute(
        "UPDATE discord_memory_candidates "
        "SET filter_decision = 'no_op', filter_reason_code = 'no_durable_fact', "
        "validation_status = 'not_required', decision = 'no_op' "
        "WHERE filter_reason_code = 'personal_fact'"
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_filter_reason_code",
        "discord_memory_candidates",
        "filter_reason_code IN "
        f"({_quoted(DISCORD_MEMORY_FILTER_REASON_CODES_V1)})",
    )
