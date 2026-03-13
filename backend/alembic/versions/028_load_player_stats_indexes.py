"""Composite indexes for load_player_stats (status+home_id, status+away_id).

Ускоряет запросы статистики игроков в карточке матча и калькуляторе.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "028_load_player_stats_indexes"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_tt_line_events_status_home_id",
        "table_tennis_line_events",
        ["status", "home_id"],
        unique=False,
    )
    op.create_index(
        "ix_tt_line_events_status_away_id",
        "table_tennis_line_events",
        ["status", "away_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tt_line_events_status_away_id", table_name="table_tennis_line_events")
    op.drop_index("ix_tt_line_events_status_home_id", table_name="table_tennis_line_events")
