"""Add telegram_result_sent_at to user_signal_deliveries for batch result DM."""
import sqlalchemy as sa
from alembic import op

revision = "035_telegram_result_sent_at"
down_revision = "034_user_signal_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_signal_deliveries",
        sa.Column("telegram_result_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_signal_deliveries", "telegram_result_sent_at")
