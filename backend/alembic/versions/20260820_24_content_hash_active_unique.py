"""Content-hash uniqueness only among live documents (T1).

The original full-table unique constraint reserved the hash of soft-deleted
documents forever: uploading the same content again hit an IntegrityError the
API surfaced as a 500, with no way out short of manual SQL. Deduplication
lookups always excluded deleted rows; this makes the database agree.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260820_24"
down_revision = "20260820_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("documents_content_hash_key", "documents", type_="unique")
    op.create_index(
        "uq_documents_content_hash_active",
        "documents",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("status != 'deleted'"),
    )


def downgrade() -> None:
    op.drop_index("uq_documents_content_hash_active", table_name="documents")
    # May fail if a deleted document's content was legitimately re-uploaded
    # while the partial index was in force — that data state is exactly what
    # the old constraint forbade, and keeping data beats keeping the downgrade.
    op.create_unique_constraint("documents_content_hash_key", "documents", ["content_hash"])
