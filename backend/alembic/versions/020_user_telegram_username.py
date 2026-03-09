"""Add telegram_username to users for display in profile."""
import sqlalchemy as sa
from alembic import op

revision = "020_telegram_username"
down_revision = "019_signals_sent_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("telegram_username", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "telegram_username")
