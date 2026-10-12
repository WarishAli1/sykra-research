from alembic import op

revision = "002_user_indexes"
down_revision = "001_auth_and_chats"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_chats_user_id", "chats", ["user_id"])
    op.create_index("ix_chats_deleted_at", "chats", ["deleted_at"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_library_papers_user_id", "library_papers", ["user_id"])


def downgrade():
    op.drop_index("ix_library_papers_user_id", table_name="library_papers")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_chats_deleted_at", table_name="chats")
    op.drop_index("ix_chats_user_id", table_name="chats")
