"""Scheduled Telegram posts for promo/stats by schedule."""
import sqlalchemy as sa
from alembic import op

revision = "036_scheduled_telegram_posts"
down_revision = "035_telegram_result_sent_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_telegram_posts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("template_type", sa.String(64), nullable=True),
        sa.Column("body", sa.String(8000), nullable=True),
        sa.Column("send_at_time_msk", sa.String(5), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_telegram_posts_target", "scheduled_telegram_posts", ["target"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scheduled_telegram_posts_target", table_name="scheduled_telegram_posts")
    op.drop_table("scheduled_telegram_posts")
