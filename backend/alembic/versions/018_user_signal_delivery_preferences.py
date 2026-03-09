"""Add user preferences for signal delivery: Telegram and/or email."""
import sqlalchemy as sa
from alembic import op

revision = "018_signal_delivery_prefs"
down_revision = "017_live_odds_fixed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("signal_via_telegram", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "users",
        sa.Column("signal_via_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("users", "signal_via_email")
    op.drop_column("users", "signal_via_telegram")
