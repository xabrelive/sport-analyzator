"""Store Telegram message_id for channel forecasts and result reply timestamp."""
import sqlalchemy as sa
from alembic import op

revision = "029_rec_telegram_msg_id"
down_revision = "028_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_recommendations",
        sa.Column("free_channel_telegram_message_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "match_recommendations",
        sa.Column("paid_channel_telegram_message_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "match_recommendations",
        sa.Column("free_result_replied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "match_recommendations",
        sa.Column("paid_result_replied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_recommendations", "paid_result_replied_at")
    op.drop_column("match_recommendations", "free_result_replied_at")
    op.drop_column("match_recommendations", "paid_channel_telegram_message_id")
    op.drop_column("match_recommendations", "free_channel_telegram_message_id")
