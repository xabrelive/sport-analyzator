"""Add indexes for faster lookups: matches.provider, match_results.finished_at, leagues/players.provider.

Revision ID: 012
Revises: 011
Create Date: 2025-03-01

"""
from typing import Sequence, Union

from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_matches_provider", "matches", ["provider"], unique=False)
    op.create_index("ix_match_results_finished_at", "match_results", ["finished_at"], unique=False)
    op.create_index("ix_leagues_provider", "leagues", ["provider"], unique=False)
    op.create_index("ix_players_provider", "players", ["provider"], unique=False)
    op.create_index("ix_matches_provider_status", "matches", ["provider", "status"], unique=False)
    op.create_index("ix_matches_start_time_status", "matches", ["start_time", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matches_start_time_status", table_name="matches")
    op.drop_index("ix_matches_provider_status", table_name="matches")
    op.drop_index("ix_players_provider", table_name="players")
    op.drop_index("ix_leagues_provider", table_name="leagues")
    op.drop_index("ix_match_results_finished_at", table_name="match_results")
    op.drop_index("ix_matches_provider", table_name="matches")
