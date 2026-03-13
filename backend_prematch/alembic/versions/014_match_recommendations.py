"""Add match_recommendations table (stored pre-match rec from line/live, one per match)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "014_match_recommendations"
down_revision = "013_user_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if insp.has_table("match_recommendations"):
        return
    op.create_table(
        "match_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_text", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_match_recommendations_match_id"),
    )
    op.create_index("ix_match_recommendations_match_id", "match_recommendations", ["match_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_match_recommendations_match_id", table_name="match_recommendations")
    op.drop_table("match_recommendations")
