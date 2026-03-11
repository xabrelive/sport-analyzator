"""Add USD pricing and refresh subscription tariffs.

Revision ID: 025
Revises: 024
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "billing_products",
        sa.Column("price_usd", sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text("0")),
    )

    op.execute(
        """
        UPDATE billing_products
        SET
          price_rub = v.price_rub,
          price_usd = v.price_usd
        FROM (
          VALUES
            ('analytics_1d',  399.00,   5.00),
            ('analytics_7d', 2650.00,  33.21),
            ('analytics_30d',7990.00, 100.13),
            ('vip_1d',        270.00,   3.38),
            ('vip_7d',       1590.00,  19.92),
            ('vip_30d',      4670.00,  58.52)
        ) AS v(code, price_rub, price_usd)
        WHERE billing_products.code = v.code
        """
    )

    op.alter_column("billing_products", "price_usd", server_default=None)


def downgrade() -> None:
    op.execute(
        """
        UPDATE billing_products
        SET
          price_rub = v.price_rub
        FROM (
          VALUES
            ('analytics_1d',  299.00),
            ('analytics_7d', 1990.00),
            ('analytics_30d',5990.00),
            ('vip_1d',        199.00),
            ('vip_7d',       1190.00),
            ('vip_30d',      3490.00)
        ) AS v(code, price_rub)
        WHERE billing_products.code = v.code
        """
    )
    op.drop_column("billing_products", "price_usd")

