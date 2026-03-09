"""Add user is_blocked and last_login_at."""
import sqlalchemy as sa
from alembic import op

revision = "032_user_blocked_last_login"
down_revision = "031_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "is_blocked")
