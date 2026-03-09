"""Unique indexes on provider+provider_*_id to prevent duplicates; merge existing duplicates.

Revision ID: 022
Revises: 021_expiry_telegram_sent
Create Date: 2026-03-07

Why migration can take long:
- CREATE INDEX CONCURRENTLY does a full table scan per index and is intentionally slower
  than a blocking index build (to avoid locking writes). On large tables, each of the 4
  indexes can take tens of seconds to several minutes. Total 2–10+ minutes is normal.
- Data merge (UPDATE/DELETE) is done once per entity; index build is the main cost.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "022_unique_provider_ids"
down_revision: Union[str, None] = "021_expiry_telegram_sent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Session-level lock: only one process may run 022 at a time. Survives commit so we
    # hold it until all CONCURRENTLY indexes are done. Unlock at the end.
    conn.execute(text("SELECT pg_advisory_lock(922022)"))

    # 1) Players: merge duplicates (provider, provider_player_id), keep one id per pair.
    # Use one temp table so we scan players once instead of four times.
    # PostgreSQL has no MIN(uuid); use DISTINCT ON to pick one id per group.
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _022_player_keep (old_id uuid, keep_id uuid) ON COMMIT DROP
    """))
    conn.execute(text("""
        INSERT INTO _022_player_keep (old_id, keep_id)
        SELECT p.id AS old_id, k.keep_id
        FROM (
            SELECT DISTINCT ON (provider, provider_player_id) provider, provider_player_id, id AS keep_id
            FROM players
            WHERE provider IS NOT NULL AND provider_player_id IS NOT NULL
            ORDER BY provider, provider_player_id, id
        ) k
        JOIN players p ON p.provider = k.provider AND p.provider_player_id = k.provider_player_id
        WHERE p.id != k.keep_id
    """))
    conn.execute(text("""
        UPDATE matches m SET home_player_id = t.keep_id FROM _022_player_keep t WHERE m.home_player_id = t.old_id
    """))
    conn.execute(text("""
        UPDATE matches m SET away_player_id = t.keep_id FROM _022_player_keep t WHERE m.away_player_id = t.old_id
    """))
    conn.execute(text("""
        UPDATE match_results mr SET winner_id = t.keep_id FROM _022_player_keep t WHERE mr.winner_id = t.old_id
    """))
    conn.execute(text("DELETE FROM players p USING _022_player_keep t WHERE p.id = t.old_id"))
    conn.execute(text("DROP TABLE IF EXISTS _022_player_keep"))

    # 2) Leagues: merge duplicates (provider, provider_league_id), one temp table.
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _022_league_keep (old_id uuid, keep_id uuid) ON COMMIT DROP
    """))
    conn.execute(text("""
        INSERT INTO _022_league_keep (old_id, keep_id)
        SELECT l.id AS old_id, k.keep_id
        FROM (
            SELECT DISTINCT ON (provider, provider_league_id) provider, provider_league_id, id AS keep_id
            FROM leagues
            WHERE provider IS NOT NULL AND provider_league_id IS NOT NULL
            ORDER BY provider, provider_league_id, id
        ) k
        JOIN leagues l ON l.provider = k.provider AND l.provider_league_id = k.provider_league_id
        WHERE l.id != k.keep_id
    """))
    conn.execute(text("""
        UPDATE matches m SET league_id = t.keep_id FROM _022_league_keep t WHERE m.league_id = t.old_id
    """))
    conn.execute(text("DELETE FROM leagues l USING _022_league_keep t WHERE l.id = t.old_id"))
    conn.execute(text("DROP TABLE IF EXISTS _022_league_keep"))

    # 3–5) Create indexes with CONCURRENTLY in autocommit so we don't hold a long
    # transaction and block the app (avoids deadlock with backend/other migration).
    # CONCURRENTLY cannot run inside a transaction; IF NOT EXISTS makes retries safe.
    with op.get_context().autocommit_block():
        conn.execute(text("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_players_provider_provider_player_id
            ON players (provider, provider_player_id) WHERE provider_player_id IS NOT NULL
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_leagues_provider_provider_league_id
            ON leagues (provider, provider_league_id) WHERE provider_league_id IS NOT NULL
        """))
        conn.execute(text("ALTER TABLE matches DROP CONSTRAINT IF EXISTS uq_matches_provider_match_id"))
        conn.execute(text("DROP INDEX IF EXISTS ix_matches_provider_match_id"))
        conn.execute(text("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_matches_provider_provider_match_id
            ON matches (provider, provider_match_id)
        """))
        conn.execute(text("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_matches_provider_match_id
            ON matches (provider_match_id)
        """))
    conn.execute(text("SELECT pg_advisory_unlock(922022)"))


def downgrade() -> None:
    op.drop_index("ix_matches_provider_match_id", table_name="matches")
    op.drop_index("uq_matches_provider_provider_match_id", table_name="matches")
    op.create_index("ix_matches_provider_match_id", "matches", ["provider_match_id"], unique=True)
    op.create_constraint("uq_matches_provider_match_id", "matches", ["provider_match_id"], type_="unique")

    op.drop_index("uq_leagues_provider_provider_league_id", table_name="leagues")
    op.drop_index("uq_players_provider_provider_player_id", table_name="players")
