"""Add result_fetch_attempts and last_result_fetch_at to matches for backfill."""
import sqlalchemy as sa
from alembic import op

revision = "016_match_result_fetch_attempts"
down_revision = "015_recommendation_odds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("result_fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "matches",
        sa.Column("last_result_fetch_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "last_result_fetch_at")
    op.drop_column("matches", "result_fetch_attempts")
