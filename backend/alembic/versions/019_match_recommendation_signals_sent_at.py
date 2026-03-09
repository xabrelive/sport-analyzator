"""Add signals_sent_at to match_recommendations for batching signal delivery."""
import sqlalchemy as sa
from alembic import op

revision = "019_signals_sent_at"
down_revision = "018_signal_delivery_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_recommendations",
        sa.Column("signals_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_recommendations", "signals_sent_at")
