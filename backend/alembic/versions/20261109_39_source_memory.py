"""Canonical source memory and audience invalidation barrier."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "20261109_39"
down_revision = "20261102_38"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("source_memory_states",
        sa.Column("tenant", sa.String(160), primary_key=True),
        sa.Column("audience", sa.String(200), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("barrier_at", sa.DateTime(timezone=True)))
    op.create_table("source_memories",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("tenant", sa.String(160), nullable=False),
        sa.Column("audience", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("tokens", postgresql.TSVECTOR(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("memory_type", sa.String(64), nullable=False, server_default="source_note"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'retracted')", name="ck_source_memory_status"),
        sa.CheckConstraint("revision > 0", name="ck_source_memory_revision"))
    op.create_index("ix_source_memory_audience", "source_memories", ["tenant", "audience", "status"])
    op.create_index("ix_source_memory_tokens", "source_memories", ["tokens"], postgresql_using="gin")
    # Existing model-written history is not an automatic v2 evidence migration.
    # Seed a one-time barrier for tenants already present at activation.
    op.execute("""INSERT INTO source_memory_states (tenant, audience, epoch, barrier_at)
        SELECT tenant, '__history__', 1, clock_timestamp() FROM (
            SELECT DISTINCT 'discord:' || guild_id AS tenant FROM discord_conversation_sessions
            UNION SELECT DISTINCT 'discord:' || guild_id FROM discord_channel_messages
            UNION SELECT DISTINCT 'web:' || COALESCE(user_id::text, 'local') FROM conversations
        ) existing ON CONFLICT DO NOTHING""")


def downgrade():
    op.drop_table("source_memories")
    op.drop_table("source_memory_states")
