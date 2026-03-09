"""Add live_odds_fixed_at and disappeared retry fields for resilient pipeline."""
import sqlalchemy as sa
from alembic import op

revision = "017_live_odds_fixed"
down_revision = "016_match_result_fetch_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("live_odds_fixed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("next_disappeared_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("disappeared_retry_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("matches", "disappeared_retry_count")
    op.drop_column("matches", "next_disappeared_retry_at")
    op.drop_column("matches", "live_odds_fixed_at")
