"""Add confidence_pct and free_channel_sent_at to match_recommendations."""
import sqlalchemy as sa
from alembic import op

revision = "024_rec_confidence_free"
down_revision = "023_match_sport_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_recommendations",
        sa.Column("confidence_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "match_recommendations",
        sa.Column("free_channel_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_recommendations", "free_channel_sent_at")
    op.drop_column("match_recommendations", "confidence_pct")
