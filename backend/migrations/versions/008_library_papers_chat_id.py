from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "008_library_papers_chat_id"
down_revision = "007_chat_pins_and_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column("library_papers", sa.Column("chat_id", uuid, nullable=True))
    op.create_foreign_key("fk_library_papers_chat_id", "library_papers", "chats", ["chat_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_library_papers_chat_id", "library_papers", ["chat_id"])

    # Optional backfill: attach each existing paper to the oldest chat in its session.
    op.execute("""
        UPDATE library_papers p
        SET chat_id = (
            SELECT c.id FROM chats c
            WHERE c.session_id = p.session_id AND c.deleted_at IS NULL
            ORDER BY c.created_at ASC LIMIT 1
        )
        WHERE p.chat_id IS NULL AND p.session_id IS NOT NULL
    """)


def downgrade():
    op.drop_index("ix_library_papers_chat_id", table_name="library_papers")
    op.drop_constraint("fk_library_papers_chat_id", "library_papers", type_="foreignkey")
    op.drop_column("library_papers", "chat_id")