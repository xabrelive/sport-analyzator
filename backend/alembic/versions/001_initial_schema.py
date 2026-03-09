"""Initial schema: users, verification_codes.

Revision ID: 001
Revises:
Create Date: 2025-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_username", sa.String(128), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "verification_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("contact", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_codes_type", "verification_codes", ["type"])
    op.create_index("ix_verification_codes_contact", "verification_codes", ["contact"])
    op.create_index("ix_verification_codes_code_hash", "verification_codes", ["code_hash"])
    op.create_index("ix_verification_codes_expires_at", "verification_codes", ["expires_at"])
    op.create_index("ix_verification_codes_user_id", "verification_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_verification_codes_user_id", table_name="verification_codes")
    op.drop_index("ix_verification_codes_expires_at", table_name="verification_codes")
    op.drop_index("ix_verification_codes_code_hash", table_name="verification_codes")
    op.drop_index("ix_verification_codes_contact", table_name="verification_codes")
    op.drop_index("ix_verification_codes_type", table_name="verification_codes")
    op.drop_table("verification_codes")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
