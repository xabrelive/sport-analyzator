"""Add composite index on odds_snapshots (match_id, market) for fast live/overview odds queries."""
from alembic import op

revision = "037_odds_snapshots_mkt_ix"
down_revision = "036_scheduled_telegram_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_odds_snapshots_match_id_market",
        "odds_snapshots",
        ["match_id", "market"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_odds_snapshots_match_id_market", table_name="odds_snapshots", if_exists=True)
