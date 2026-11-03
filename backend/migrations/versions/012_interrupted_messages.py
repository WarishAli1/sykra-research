from alembic import op


revision = "012_interrupted_messages"
down_revision = "011_durable_files_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_messages_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IN ('streaming', 'generating', 'complete', 'stopped', 'failed', 'interrupted')",
    )


def downgrade():
    op.drop_constraint("ck_messages_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IN ('streaming', 'complete', 'stopped', 'failed')",
    )
