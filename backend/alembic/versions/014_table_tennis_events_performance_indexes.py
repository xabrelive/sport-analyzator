"""Performance indexes for table tennis events queries.

Revision ID: 014
Revises: 013
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Основные выборки line/live: status + starts_at (+ сортировка по starts_at).
    op.create_index(
        "ix_tt_line_events_status_starts_at",
        "table_tennis_line_events",
        ["status", "starts_at"],
    )

    # Live выборка: status='live' + is_stale + проверка свежести по времени.
    op.create_index(
        "ix_tt_line_events_status_is_stale_starts_at",
        "table_tennis_line_events",
        ["status", "is_stale", "starts_at"],
    )
    op.create_index(
        "ix_tt_line_events_status_is_stale_last_score_changed_at",
        "table_tennis_line_events",
        ["status", "is_stale", "last_score_changed_at"],
    )

    # Finished-блок "Недавно завершены".
    op.create_index(
        "ix_tt_line_events_status_finished_at",
        "table_tennis_line_events",
        ["status", "finished_at"],
    )

    # Результат-чек воркера (2h/3h): фильтр по result_status + result_checked_* + starts_at.
    op.create_index(
        "ix_tt_line_events_result_status_checked_1h_starts_at",
        "table_tennis_line_events",
        ["result_status", "result_checked_1h_at", "starts_at"],
    )
    op.create_index(
        "ix_tt_line_events_result_status_checked_3h_starts_at",
        "table_tennis_line_events",
        ["result_status", "result_checked_3h_at", "starts_at"],
    )

    # Карточка игрока: быстрый поиск матчей игрока + сортировка по времени.
    op.create_index(
        "ix_tt_line_events_home_id_starts_at",
        "table_tennis_line_events",
        ["home_id", "starts_at"],
    )
    op.create_index(
        "ix_tt_line_events_away_id_starts_at",
        "table_tennis_line_events",
        ["away_id", "starts_at"],
    )

    # Частый запрос коэффициентов по будущим scheduled матчам без кф.
    op.create_index(
        "ix_tt_line_events_odds_missing_scheduled_future",
        "table_tennis_line_events",
        ["status", "result_status", "starts_at"],
        postgresql_where=sa.text("(odds_1 IS NULL OR odds_2 IS NULL)"),
    )


def downgrade() -> None:
    op.drop_index("ix_tt_line_events_odds_missing_scheduled_future", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_away_id_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_home_id_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_result_status_checked_3h_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_result_status_checked_1h_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_status_finished_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_status_is_stale_last_score_changed_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_status_is_stale_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_status_starts_at", table_name="table_tennis_line_events")

