"""Stage 1: early scan (6-12h) — временное хранение, не публикуем."""
from alembic import op
import sqlalchemy as sa


revision = "029_forecast_early_scan"
down_revision = "028_load_player_stats_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_tennis_forecast_early_scan",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), sa.ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("minutes_to_match", sa.Integer(), nullable=True),
        sa.Column("p_match", sa.Float(), nullable=True),
        sa.Column("has_value", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tt_forecast_early_scan_event_id", "table_tennis_forecast_early_scan", ["event_id"])
    op.create_index("ix_tt_forecast_early_scan_created_at", "table_tennis_forecast_early_scan", ["created_at"])


def downgrade() -> None:
    op.drop_table("table_tennis_forecast_early_scan")
