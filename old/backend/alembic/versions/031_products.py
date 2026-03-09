"""Products table: услуги (подписка на аналитику, на приватный канал)."""
import sqlalchemy as sa
from alembic import op

revision = "031_products"
down_revision = "030_payment_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_key", "products", ["key"], unique=True)

    # Дефолтные услуги
    op.execute(
        sa.text("""
            INSERT INTO products (id, key, name, enabled, sort_order)
            VALUES
                (gen_random_uuid(), 'tg_analytics', 'Подписка на аналитику', true, 0),
                (gen_random_uuid(), 'signals', 'Подписка на приватный канал', true, 1)
        """)
    )


def downgrade() -> None:
    op.drop_index("ix_products_key", table_name="products")
    op.drop_table("products")
