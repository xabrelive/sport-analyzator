"""Add paid_channel_sent_at to match_recommendations (1–3 в час, лучший прогноз)."""
import sqlalchemy as sa
from alembic import op

revision = "026_paid_channel_sent"
down_revision = "025_rec_cols_if_missing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_recommendations",
        sa.Column("paid_channel_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_recommendations", "paid_channel_sent_at")
