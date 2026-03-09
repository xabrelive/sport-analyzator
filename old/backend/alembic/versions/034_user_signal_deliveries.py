"""User signal deliveries: лог отправки сигналов в личку пользователю (TG/email)."""
import sqlalchemy as sa
from alembic import op

revision = "034_user_signal_deliveries"
down_revision = "033_subscription_grant_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_signal_deliveries",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_recommendation_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sent_via", sa.String(20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_recommendation_id"], ["match_recommendations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_signal_deliveries_user_id", "user_signal_deliveries", ["user_id"], unique=False)
    op.create_index("ix_user_signal_deliveries_match_recommendation_id", "user_signal_deliveries", ["match_recommendation_id"], unique=False)
    op.create_index("ix_user_signal_deliveries_sent_at", "user_signal_deliveries", ["sent_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_signal_deliveries_sent_at", table_name="user_signal_deliveries")
    op.drop_index("ix_user_signal_deliveries_match_recommendation_id", table_name="user_signal_deliveries")
    op.drop_index("ix_user_signal_deliveries_user_id", table_name="user_signal_deliveries")
    op.drop_table("user_signal_deliveries")
