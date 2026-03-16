"""Add user notification timezone offset setting."""
from alembic import op
import sqlalchemy as sa


revision = "031_user_tz_offset"
down_revision = "030_no_ml_analytics_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_tz_offset_minutes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("users", "notification_tz_offset_minutes", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "notification_tz_offset_minutes")

