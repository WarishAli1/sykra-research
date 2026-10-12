from alembic import op
import sqlalchemy as sa


revision = "007_chat_pins_and_cleanup"
down_revision = "006_sessions_and_google_profile"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chats", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_chats_pinned_at", "chats", ["pinned_at"])
    op.execute("""
        DELETE FROM chats c
        WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.chat_id = c.id)
    """)


def downgrade():
    op.drop_index("ix_chats_pinned_at", table_name="chats")
    op.drop_column("chats", "pinned_at")
