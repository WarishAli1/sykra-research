from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "010_diagram_documents"
down_revision = "009_chat_kind"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "diagram_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="Untitled flowchart"),
        sa.Column("document", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_diagram_documents_session_id", "diagram_documents", ["session_id"])
    op.create_index("ix_diagram_documents_user_id", "diagram_documents", ["user_id"])
    op.create_index("ix_diagram_documents_session_updated", "diagram_documents", ["session_id", "updated_at"])


def downgrade():
    op.drop_index("ix_diagram_documents_session_updated", table_name="diagram_documents")
    op.drop_index("ix_diagram_documents_user_id", table_name="diagram_documents")
    op.drop_index("ix_diagram_documents_session_id", table_name="diagram_documents")
    op.drop_table("diagram_documents")
