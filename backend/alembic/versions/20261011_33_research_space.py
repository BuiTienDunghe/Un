"""Không gian Nghiên cứu: dự án, cụm, paper, highlight, kết nối.

Một paper là một Document sẵn có (bảng ``documents``) cộng một dòng
``research_papers`` trỏ tới nó — tải lên, OCR, chunk, trích dẫn dùng lại
pipeline tài liệu; không có pipeline thứ hai. Xoá paper hay dự án không xoá
Document. Additive only: năm bảng mới, không sửa bảng cũ.

Revision ID: 20261011_33
Revises: 20260828_32
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID


revision = "20261011_33"
down_revision = "20260828_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("insights", JSONB(), nullable=True),
        sa.Column("insights_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_projects_owner_user_id", "research_projects", ["owner_user_id"])
    op.create_index("ix_research_projects_updated_at", "research_projects", ["updated_at"])

    op.create_table(
        "research_clusters",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("color_index", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("color_index BETWEEN 1 AND 5", name="ck_research_clusters_color_index"),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_clusters_project_id", "research_clusters", ["project_id"])

    op.create_table(
        "research_papers",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("short_name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("venue", sa.String(length=255), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("arxiv_id", sa.String(length=32), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("cluster_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("note_md", sa.Text(), nullable=True),
        sa.Column("tags", JSONB(), nullable=False),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("summary_model", sa.String(length=255), nullable=True),
        sa.Column("summary_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outline", JSONB(), nullable=True),
        sa.Column("metadata_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('unread','reading','read')", name="ck_research_papers_status"),
        sa.CheckConstraint("stars BETWEEN 0 AND 5", name="ck_research_papers_stars"),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["research_clusters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "document_id", name="uq_research_papers_project_document"),
    )
    op.create_index("ix_research_papers_project_id", "research_papers", ["project_id"])
    op.create_index("ix_research_papers_document_id", "research_papers", ["document_id"])
    op.create_index("ix_research_papers_cluster_id", "research_papers", ["cluster_id"])

    op.create_table(
        "research_annotations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("paper_id", sa.String(length=128), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("rects", JSONB(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["research_papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_annotations_paper_id", "research_annotations", ["paper_id"])

    op.create_table(
        "research_edges",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("a_paper_id", sa.String(length=128), nullable=False),
        sa.Column("b_paper_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("explain", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_src", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('builds','competes','backbone')", name="ck_research_edges_type"),
        sa.CheckConstraint("source IN ('manual','ai')", name="ck_research_edges_source"),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["a_paper_id"], ["research_papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["b_paper_id"], ["research_papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_edges_project_id", "research_edges", ["project_id"])
    op.create_index("ix_research_edges_a_paper_id", "research_edges", ["a_paper_id"])
    op.create_index("ix_research_edges_b_paper_id", "research_edges", ["b_paper_id"])


def downgrade() -> None:
    for table in ("research_edges", "research_annotations", "research_papers", "research_clusters", "research_projects"):
        op.drop_table(table)
