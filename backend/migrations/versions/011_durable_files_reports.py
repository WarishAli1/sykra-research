import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "011_durable_files_reports"
down_revision = "010_diagram_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("uploaded_files", sa.Column("mime_type", sa.String(120), nullable=False, server_default="application/pdf"))
    op.add_column("uploaded_files", sa.Column("source", sa.String(16), nullable=False, server_default="chat"))
    op.add_column("uploaded_files", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("uploaded_files", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="Report"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("plan", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("references", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reports_session_updated", "reports", ["session_id", "updated_at"])
    op.create_table(
        "report_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_report_sections_report_position", "report_sections", ["report_id", "position"])
    op.create_table(
        "report_conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_report_conversation_messages_report_id", "report_conversation_messages", ["report_id"])


def downgrade():
    op.drop_index("ix_report_conversation_messages_report_id", table_name="report_conversation_messages")
    op.drop_table("report_conversation_messages")
    op.drop_index("ix_report_sections_report_position", table_name="report_sections")
    op.drop_table("report_sections")
    op.drop_index("ix_reports_session_updated", table_name="reports")
    op.drop_table("reports")
    op.drop_column("uploaded_files", "metadata")
    op.drop_column("uploaded_files", "extracted_text")
    op.drop_column("uploaded_files", "source")
    op.drop_column("uploaded_files", "mime_type")
