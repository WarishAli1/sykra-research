from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006_sessions_and_google_profile"
down_revision = "005_message_status"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column("users", sa.Column("image", sa.String(length=2048), nullable=True))
    op.add_column("research_sessions", sa.Column("name", sa.String(length=200), nullable=True))
    op.execute("UPDATE research_sessions SET name = 'My Session' WHERE name IS NULL")
    op.alter_column("research_sessions", "name", nullable=False, server_default="My Session")

    op.add_column("chats", sa.Column("session_id", uuid, nullable=True))
    op.create_foreign_key("fk_chats_session_id", "chats", "research_sessions", ["session_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_chats_session_id", "chats", ["session_id"])

    op.add_column("library_papers", sa.Column("session_id", uuid, nullable=True))
    op.create_foreign_key("fk_library_papers_session_id", "library_papers", "research_sessions", ["session_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_library_papers_session_id", "library_papers", ["session_id"])

    # Preserve pre-session data by placing each user's existing records in one owned session.
    op.execute("""
        INSERT INTO research_sessions (id, external_id, user_id, name)
        SELECT gen_random_uuid(), 'default-' || u.id::text, u.id, 'My Session'
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM research_sessions rs WHERE rs.user_id = u.id
        )
    """)
    op.execute("""
        UPDATE chats c
        SET session_id = rs.id
        FROM research_sessions rs
        WHERE c.session_id IS NULL AND rs.user_id = c.user_id
    """)
    op.execute("""
        UPDATE library_papers p
        SET session_id = rs.id
        FROM research_sessions rs
        WHERE p.session_id IS NULL AND rs.user_id = p.user_id
    """)


def downgrade():
    op.drop_index("ix_library_papers_session_id", table_name="library_papers")
    op.drop_constraint("fk_library_papers_session_id", "library_papers", type_="foreignkey")
    op.drop_column("library_papers", "session_id")
    op.drop_index("ix_chats_session_id", table_name="chats")
    op.drop_constraint("fk_chats_session_id", "chats", type_="foreignkey")
    op.drop_column("chats", "session_id")
    op.drop_column("research_sessions", "name")
    op.drop_column("users", "image")
