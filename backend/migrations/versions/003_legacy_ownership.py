from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "003_legacy_ownership"
down_revision = "002_user_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_research_sessions_external_id", "research_sessions", ["external_id"])
    op.create_index("ix_research_sessions_user_id", "research_sessions", ["user_id"])
    op.create_index(
        "ix_research_sessions_user_updated",
        "research_sessions",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "uploaded_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index("ix_uploaded_files_session_id", "uploaded_files", ["session_id"])
    op.create_index("ix_uploaded_files_user_id", "uploaded_files", ["user_id"])
    op.create_index(
        "ix_uploaded_files_user_session",
        "uploaded_files",
        ["user_id", "session_id"],
    )


def downgrade():
    op.drop_index("ix_uploaded_files_user_session", table_name="uploaded_files")
    op.drop_index("ix_uploaded_files_user_id", table_name="uploaded_files")
    op.drop_index("ix_uploaded_files_session_id", table_name="uploaded_files")
    op.drop_table("uploaded_files")
    op.drop_index("ix_research_sessions_user_updated", table_name="research_sessions")
    op.drop_index("ix_research_sessions_user_id", table_name="research_sessions")
    op.drop_index("ix_research_sessions_external_id", table_name="research_sessions")
    op.drop_table("research_sessions")
