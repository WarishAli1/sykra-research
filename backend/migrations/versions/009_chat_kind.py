from alembic import op
import sqlalchemy as sa


revision = "009_chat_kind"
down_revision = "008_library_papers_chat_id"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chats",
        sa.Column("kind", sa.String(16), nullable=False, server_default="chat"),
    )
    op.create_index("ix_chats_kind", "chats", ["kind"])

    op.execute("""
        UPDATE chats
        SET kind = 'report'
        WHERE id IN (
            SELECT chat_id FROM messages
            WHERE citations ? 'report_artifact'
        )
    """)


def downgrade():
    op.drop_index("ix_chats_kind", table_name="chats")
    op.drop_column("chats", "kind")