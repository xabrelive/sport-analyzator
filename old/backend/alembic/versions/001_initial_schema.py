"""Initial schema: leagues, players, matches, match_scores, odds_snapshots, match_results.

Revision ID: 001
Revises:
Create Date: 2025-02-28

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
        "leagues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("provider_league_id", sa.String(100), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leagues_name", "leagues", ["name"], unique=False)
    op.create_index("ix_leagues_provider_league_id", "leagues", ["provider_league_id"], unique=False)

    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider_player_id", sa.String(100), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_players_name", "players", ["name"], unique=False)
    op.create_index("ix_players_provider_player_id", "players", ["provider_player_id"], unique=False)

    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_match_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("league_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("home_player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("away_player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["home_player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["away_player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_match_id", name="uq_matches_provider_match_id"),
    )
    op.create_index("ix_matches_provider_match_id", "matches", ["provider_match_id"], unique=True)
    op.create_index("ix_matches_league_id", "matches", ["league_id"], unique=False)
    op.create_index("ix_matches_status", "matches", ["status"], unique=False)
    op.create_index("ix_matches_start_time", "matches", ["start_time"], unique=False)

    op.create_table(
        "match_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_scores_match_id", "match_scores", ["match_id"], unique=False)

    op.create_table(
        "odds_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bookmaker", sa.String(100), nullable=False),
        sa.Column("market", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(255), nullable=False),
        sa.Column("odds", sa.Numeric(10, 2), nullable=False),
        sa.Column("implied_probability", sa.Numeric(8, 6), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_odds_snapshots_match_id", "odds_snapshots", ["match_id"], unique=False)
    op.create_index("ix_odds_snapshots_bookmaker", "odds_snapshots", ["bookmaker"], unique=False)

    op.create_table(
        "match_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("final_score", sa.String(50), nullable=False),
        sa.Column("winner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["winner_id"], ["players.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_match_results_match_id"),
    )
    op.create_index("ix_match_results_match_id", "match_results", ["match_id"], unique=True)


def downgrade() -> None:
    op.drop_table("match_results")
    op.drop_table("odds_snapshots")
    op.drop_table("match_scores")
    op.drop_table("matches")
    op.drop_table("players")
    op.drop_table("leagues")
