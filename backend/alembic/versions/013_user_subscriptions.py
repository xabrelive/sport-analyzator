"""Add user_subscriptions for paid access (TG analytics, signals; one sport / all)."""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "013_user_subscriptions"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_type", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("sport_key", sa.String(64), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"], unique=False)
    op.create_index("ix_user_subscriptions_access_type", "user_subscriptions", ["access_type"], unique=False)
    op.create_index("ix_user_subscriptions_valid_until", "user_subscriptions", ["valid_until"], unique=False)
    op.create_index("ix_user_subscriptions_sport_key", "user_subscriptions", ["sport_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_subscriptions_sport_key", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_valid_until", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_access_type", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_user_id", table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
