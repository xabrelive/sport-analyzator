"""Subscription grant log: история выдачи подписок через админку с комментарием."""
import sqlalchemy as sa
from alembic import op

revision = "033_subscription_grant_log"
down_revision = "032_user_blocked_last_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_grant_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("access_type", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("sport_key", sa.String(64), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_grant_logs_user_id", "subscription_grant_logs", ["user_id"], unique=False)
    op.create_index("ix_subscription_grant_logs_granted_by_user_id", "subscription_grant_logs", ["granted_by_user_id"], unique=False)
    op.create_index("ix_subscription_grant_logs_created_at", "subscription_grant_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_subscription_grant_logs_created_at", table_name="subscription_grant_logs")
    op.drop_index("ix_subscription_grant_logs_granted_by_user_id", table_name="subscription_grant_logs")
    op.drop_index("ix_subscription_grant_logs_user_id", table_name="subscription_grant_logs")
    op.drop_table("subscription_grant_logs")
