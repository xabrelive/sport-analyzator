"""Add is_admin and trial_until to users."""
import sqlalchemy as sa
from alembic import op

revision = "027_user_admin_trial"
down_revision = "026_paid_channel_sent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("trial_until", sa.Date(), nullable=True))
    op.create_index("ix_users_trial_until", "users", ["trial_until"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_trial_until", table_name="users")
    op.drop_column("users", "trial_until")
    op.drop_column("users", "is_admin")
