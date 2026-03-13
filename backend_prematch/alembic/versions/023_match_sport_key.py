"""Add sport_key to matches for subscription-scoped signal delivery."""
import sqlalchemy as sa
from alembic import op

revision = "023_match_sport_key"
down_revision = "022_unique_provider_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("sport_key", sa.String(64), nullable=True),
    )
    op.execute("UPDATE matches SET sport_key = 'table_tennis' WHERE sport_key IS NULL")
    op.create_index(
        "ix_matches_sport_key",
        "matches",
        ["sport_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_matches_sport_key", table_name="matches")
    op.drop_column("matches", "sport_key")
