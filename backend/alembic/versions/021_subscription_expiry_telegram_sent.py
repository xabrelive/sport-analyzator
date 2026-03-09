"""Add expiry_telegram_sent_at to user_subscriptions (notify once when subscription expires)."""
import sqlalchemy as sa
from alembic import op

revision = "021_expiry_telegram_sent"
down_revision = "020_telegram_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_subscriptions",
        sa.Column("expiry_telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_subscriptions", "expiry_telegram_sent_at")
