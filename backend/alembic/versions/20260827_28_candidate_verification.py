"""discord_memory_candidates: the 1-vs-1 verifier's verdict (job 4).

memory_design.md §13.2 E1. The deterministic guard measurably cannot judge
whether a proposed fact FOLLOWS from its source — it accepted 'Dũng dùng
Postgres' against a source saying the opposite (§9.1, reproduced by
execution). The verifier records a 3-state verdict per candidate:

  entailment    → eligible for autonomous apply, when the threshold returns
  contradiction → human review, with the supersession pre-filled — never
                  auto-superseded on a model verdict alone
  unknown       → human review

verification_method records how the verdict was reached (e.g.
"nli-1v1:qwen3.5:9b"), so a later model or prompt change is distinguishable
from old verdicts. NULL means the verifier has not run — every pre-existing
row keeps meaning exactly what it meant. Additive only; downgrade drops the
two columns and their CHECK.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260827_28"
down_revision = "20260826_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discord_memory_candidates",
        sa.Column("verification_method", sa.Text(), nullable=True),
    )
    op.add_column(
        "discord_memory_candidates",
        sa.Column("verification_result", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_discord_memory_candidates_verification_result",
        "discord_memory_candidates",
        "verification_result IS NULL OR verification_result IN "
        "('entailment', 'contradiction', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discord_memory_candidates_verification_result",
        "discord_memory_candidates",
        type_="check",
    )
    op.drop_column("discord_memory_candidates", "verification_result")
    op.drop_column("discord_memory_candidates", "verification_method")
