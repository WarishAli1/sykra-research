from alembic import op


revision = "005_message_status"
down_revision = "004_email_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IN ('streaming', 'complete', 'stopped', 'failed')",
    )


def downgrade():
    op.drop_constraint("ck_messages_status", "messages", type_="check")
