"""Add table tennis forecast V2 schema.

Revision ID: 020
Revises: 019
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "table_tennis_model_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tt_model_runs_model_name", "table_tennis_model_runs", ["model_name"])
    op.create_index("ix_tt_model_runs_model_version", "table_tennis_model_runs", ["model_version"])
    op.create_index("ix_tt_model_runs_is_active", "table_tennis_model_runs", ["is_active"])
    op.create_index("ix_tt_model_runs_created_at", "table_tennis_model_runs", ["created_at"])

    op.create_table(
        "table_tennis_player_daily_features",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("player_name", sa.String(length=255), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("matches_1d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matches_2d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matches_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_rest_minutes_48h", sa.Float(), nullable=True),
        sa.Column("fatigue_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("player_id", "day", name="uq_tt_player_daily_features_player_day"),
    )
    op.create_index("ix_tt_player_daily_features_player_id", "table_tennis_player_daily_features", ["player_id"])
    op.create_index("ix_tt_player_daily_features_day", "table_tennis_player_daily_features", ["day"])
    op.create_index("ix_tt_player_daily_features_fatigue", "table_tennis_player_daily_features", ["fatigue_score"])

    op.create_table(
        "table_tennis_match_features",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=64), sa.ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("table_tennis_model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("home_id", sa.String(length=64), nullable=True),
        sa.Column("away_id", sa.String(length=64), nullable=True),
        sa.Column("league_id", sa.String(length=64), nullable=True),
        sa.Column("data_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tt_match_features_event_id", "table_tennis_match_features", ["event_id"])
    op.create_index("ix_tt_match_features_created_at", "table_tennis_match_features", ["created_at"])
    op.create_index("ix_tt_match_features_model_run_id", "table_tennis_match_features", ["model_run_id"])
    op.create_index("ix_tt_match_features_quality", "table_tennis_match_features", ["data_quality_score"])

    op.create_table(
        "table_tennis_forecasts_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=64), sa.ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("table_tennis_model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="paid"),
        sa.Column("market", sa.String(length=32), nullable=False, server_default="match"),
        sa.Column("pick_side", sa.String(length=16), nullable=False),
        sa.Column("forecast_text", sa.String(length=300), nullable=False),
        sa.Column("probability_pct", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("edge_pct", sa.Float(), nullable=True),
        sa.Column("odds_used", sa.Numeric(10, 3), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("final_status", sa.String(length=32), nullable=True),
        sa.Column("final_sets_score", sa.String(length=32), nullable=True),
        sa.Column("explanation_summary", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", "channel", "market", name="uq_tt_forecasts_v2_event_channel_market"),
    )
    op.create_index("ix_tt_forecasts_v2_event_id", "table_tennis_forecasts_v2", ["event_id"])
    op.create_index("ix_tt_forecasts_v2_channel", "table_tennis_forecasts_v2", ["channel"])
    op.create_index("ix_tt_forecasts_v2_market", "table_tennis_forecasts_v2", ["market"])
    op.create_index("ix_tt_forecasts_v2_status", "table_tennis_forecasts_v2", ["status"])
    op.create_index("ix_tt_forecasts_v2_edge", "table_tennis_forecasts_v2", ["edge_pct"])
    op.create_index("ix_tt_forecasts_v2_odds", "table_tennis_forecasts_v2", ["odds_used"])
    op.create_index("ix_tt_forecasts_v2_created_at", "table_tennis_forecasts_v2", ["created_at"])
    op.create_index("ix_tt_forecasts_v2_resolved_at", "table_tennis_forecasts_v2", ["resolved_at"])

    op.create_table(
        "table_tennis_forecast_explanations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("forecast_v2_id", sa.Integer(), sa.ForeignKey("table_tennis_forecasts_v2.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factor_key", sa.String(length=64), nullable=False),
        sa.Column("factor_label", sa.String(length=255), nullable=False),
        sa.Column("factor_value", sa.String(length=255), nullable=True),
        sa.Column("contribution", sa.Float(), nullable=False, server_default="0"),
        sa.Column("direction", sa.String(length=16), nullable=False, server_default="neutral"),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_tt_forecast_explanations_forecast_id", "table_tennis_forecast_explanations", ["forecast_v2_id"])
    op.create_index("ix_tt_forecast_explanations_factor_key", "table_tennis_forecast_explanations", ["factor_key"])


def downgrade() -> None:
    op.drop_index("ix_tt_forecast_explanations_factor_key", table_name="table_tennis_forecast_explanations")
    op.drop_index("ix_tt_forecast_explanations_forecast_id", table_name="table_tennis_forecast_explanations")
    op.drop_table("table_tennis_forecast_explanations")

    op.drop_index("ix_tt_forecasts_v2_resolved_at", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_created_at", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_odds", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_edge", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_status", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_market", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_channel", table_name="table_tennis_forecasts_v2")
    op.drop_index("ix_tt_forecasts_v2_event_id", table_name="table_tennis_forecasts_v2")
    op.drop_table("table_tennis_forecasts_v2")

    op.drop_index("ix_tt_match_features_quality", table_name="table_tennis_match_features")
    op.drop_index("ix_tt_match_features_model_run_id", table_name="table_tennis_match_features")
    op.drop_index("ix_tt_match_features_created_at", table_name="table_tennis_match_features")
    op.drop_index("ix_tt_match_features_event_id", table_name="table_tennis_match_features")
    op.drop_table("table_tennis_match_features")

    op.drop_index("ix_tt_player_daily_features_fatigue", table_name="table_tennis_player_daily_features")
    op.drop_index("ix_tt_player_daily_features_day", table_name="table_tennis_player_daily_features")
    op.drop_index("ix_tt_player_daily_features_player_id", table_name="table_tennis_player_daily_features")
    op.drop_table("table_tennis_player_daily_features")

    op.drop_index("ix_tt_model_runs_created_at", table_name="table_tennis_model_runs")
    op.drop_index("ix_tt_model_runs_is_active", table_name="table_tennis_model_runs")
    op.drop_index("ix_tt_model_runs_model_version", table_name="table_tennis_model_runs")
    op.drop_index("ix_tt_model_runs_model_name", table_name="table_tennis_model_runs")
    op.drop_table("table_tennis_model_runs")
