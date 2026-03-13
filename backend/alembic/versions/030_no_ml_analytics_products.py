"""Add billing products for no-ML analytics subscription."""
from alembic import op


revision = "030_no_ml_analytics_products"
down_revision = "029_forecast_early_scan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO billing_products (id, code, name, service_key, duration_days, price_rub, price_usd, enabled, sort_order)
        VALUES
          ('8e5d2c4e-3f41-4f6c-9a26-6f6a0e9f1001', 'analytics_no_ml_1d',  'Аналитика без ML · 1 день',  'analytics_no_ml', 1, 149, 1.99, true, 11),
          ('8e5d2c4e-3f41-4f6c-9a26-6f6a0e9f1002', 'analytics_no_ml_7d',  'Аналитика без ML · 7 дней',  'analytics_no_ml', 7,  890, 9.99, true, 21),
          ('8e5d2c4e-3f41-4f6c-9a26-6f6a0e9f1003', 'analytics_no_ml_30d', 'Аналитика без ML · 30 дней', 'analytics_no_ml', 30, 2990, 29.99, true, 31)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM billing_products
        WHERE code IN ('analytics_no_ml_1d', 'analytics_no_ml_7d', 'analytics_no_ml_30d')
        """
    )

