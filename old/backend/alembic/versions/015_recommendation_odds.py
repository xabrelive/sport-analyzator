"""Add odds_at_recommendation to match_recommendations."""
import sqlalchemy as sa
from alembic import op

revision = "015_recommendation_odds"
down_revision = "014_match_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_recommendations",
        sa.Column("odds_at_recommendation", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_recommendations", "odds_at_recommendation")
