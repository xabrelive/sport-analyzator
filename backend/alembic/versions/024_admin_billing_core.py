"""Add admin billing core tables.

Revision ID: 024
Revises: 023
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("service_key", sa.String(length=32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_rub", sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_billing_products_code"), "billing_products", ["code"], unique=True)
    op.create_index(op.f("ix_billing_products_service_key"), "billing_products", ["service_key"], unique=False)

    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("method_type", sa.String(length=32), nullable=False, server_default=sa.text("'custom'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_key", sa.String(length=32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'admin'")),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_subscriptions_user_id"), "user_subscriptions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_subscriptions_service_key"), "user_subscriptions", ["service_key"], unique=False)
    op.create_index(op.f("ix_user_subscriptions_valid_until"), "user_subscriptions", ["valid_until"], unique=False)

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("amount_rub", sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("payment_method_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_methods.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_invoices_user_id"), "invoices", ["user_id"], unique=False)
    op.create_index(op.f("ix_invoices_status"), "invoices", ["status"], unique=False)
    op.create_index(op.f("ix_invoices_payment_method_id"), "invoices", ["payment_method_id"], unique=False)

    op.execute(
        """
        INSERT INTO billing_products (id, code, name, service_key, duration_days, price_rub, enabled, sort_order)
        VALUES
          ('b6f1164e-d749-4b18-b1e6-f349ea52cc3f', 'analytics_1d', 'Подписка на аналитику · 1 день', 'analytics', 1, 299, true, 10),
          ('f6572f89-c97b-486b-a310-e88f6582694c', 'analytics_7d', 'Подписка на аналитику · 7 дней', 'analytics', 7, 1990, true, 20),
          ('d50f4c6f-f3ef-4568-a7ff-e5a4d1c7cff8', 'analytics_30d', 'Подписка на аналитику · 30 дней', 'analytics', 30, 5990, true, 30),
          ('3f9786ed-49e9-4f64-a8d3-b1d8d16fef16', 'vip_1d', 'Подписка на VIP канал · 1 день', 'vip_channel', 1, 199, true, 40),
          ('4f2fca56-8181-4ff8-b64e-8c84f33f9fd8', 'vip_7d', 'Подписка на VIP канал · 7 дней', 'vip_channel', 7, 1190, true, 50),
          ('f396cb20-6303-43dc-b40c-c856f5b45867', 'vip_30d', 'Подписка на VIP канал · 30 дней', 'vip_channel', 30, 3490, true, 60)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invoices_payment_method_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_status"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_user_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(op.f("ix_user_subscriptions_valid_until"), table_name="user_subscriptions")
    op.drop_index(op.f("ix_user_subscriptions_service_key"), table_name="user_subscriptions")
    op.drop_index(op.f("ix_user_subscriptions_user_id"), table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
    op.drop_table("payment_methods")
    op.drop_index(op.f("ix_billing_products_service_key"), table_name="billing_products")
    op.drop_index(op.f("ix_billing_products_code"), table_name="billing_products")
    op.drop_table("billing_products")
