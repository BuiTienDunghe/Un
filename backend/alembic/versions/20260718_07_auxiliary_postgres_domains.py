"""auxiliary PostgreSQL domains for SQLite cutover Phase 2

Revision ID: 20260718_07
Revises: 20260718_06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260718_07"
down_revision = "20260718_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("conversations", sa.Column("id", sa.String(length=128), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.create_table("messages", sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), sa.Column("conversation_id", sa.String(length=128), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(length=32), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("model_used", sa.String(length=255)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table("memories", sa.Column("id", sa.String(length=128), primary_key=True), sa.Column("content", sa.Text(), nullable=False), sa.Column("memory_type", sa.String(length=64), nullable=False), sa.Column("importance", sa.Float(), nullable=False), sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_table("request_logs", sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), sa.Column("endpoint", sa.Text(), nullable=False), sa.Column("model_used", sa.String(length=255)), sa.Column("latency_ms", sa.Integer(), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.Column("error_code", sa.String(length=64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_request_logs_created_at", "request_logs", ["created_at"])
    op.create_table("ocr_runs", sa.Column("id", sa.String(length=128), primary_key=True), sa.Column("filename", sa.Text(), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.Column("model", sa.String(length=255), nullable=False), sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_ocr_runs_updated_at", "ocr_runs", ["updated_at"])
    op.create_table("ocr_cache", sa.Column("id", sa.String(length=128), primary_key=True), sa.Column("input_hash", sa.String(length=64), nullable=False), sa.Column("engine", sa.String(length=64), nullable=False), sa.Column("model_name", sa.String(length=255), nullable=False), sa.Column("model_revision", sa.String(length=255), nullable=False), sa.Column("config_fingerprint", sa.String(length=64), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("input_hash", "engine", "model_name", "model_revision", "config_fingerprint", name="uq_ocr_cache_key"))
    op.create_table("embedding_cache", sa.Column("id", sa.String(length=128), primary_key=True), sa.Column("content_hash", sa.String(length=64), nullable=False), sa.Column("model_name", sa.String(length=255), nullable=False), sa.Column("model_revision", sa.String(length=255), nullable=False), sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("config_fingerprint", sa.String(length=64), nullable=False), sa.Column("normalization_fingerprint", sa.String(length=64), nullable=False), sa.Column("vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("content_hash", "model_name", "model_revision", "dimensions", "config_fingerprint", "normalization_fingerprint", name="uq_embedding_cache_key"))


def downgrade() -> None:
    op.drop_table("embedding_cache")
    op.drop_table("ocr_cache")
    op.drop_index("ix_ocr_runs_updated_at", table_name="ocr_runs")
    op.drop_table("ocr_runs")
    op.drop_index("ix_request_logs_created_at", table_name="request_logs")
    op.drop_table("request_logs")
    op.drop_table("memories")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_table("conversations")
