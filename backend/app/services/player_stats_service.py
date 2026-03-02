"""Player stats computation (shared by players API and analytics)."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Match, MatchStatus
from app.schemas.player import PlayerStats


async def compute_player_stats(session: AsyncSession, player_id: UUID) -> PlayerStats | None:
    """Compute stats for a player from finished matches. Returns None if player not found."""
    from app.models import Player
    from app.models.match_result import MatchResult

    r = await session.execute(select(Player).where(Player.id == player_id))
    if r.scalar_one_or_none() is None:
        return None
    q = (
        select(Match)
        .where(Match.status == MatchStatus.FINISHED.value)
        .where((Match.home_player_id == player_id) | (Match.away_player_id == player_id))
        .options(selectinload(Match.result), selectinload(Match.scores))
    )
    matches = (await session.execute(q)).unique().scalars().all()
    total = len(matches)
    wins = sum(1 for m in matches if m.result and m.result.winner_id == player_id)
    losses = total - wins
    win_rate = (wins / total) if total else None

    wins_first_set = 0
    matches_with_first_set = 0
    wins_second_set = 0
    matches_with_second_set = 0
    total_sets_played = 0
    by_position: dict[int, list[bool]] = {}
    pattern_counts: dict[str, int] = {}

    for m in matches:
        scores = sorted(m.scores, key=lambda s: s.set_number) if m.scores else []
        is_home = m.home_player_id == player_id
        for i, s in enumerate(scores):
            set_num = i + 1
            my_won = (s.home_score > s.away_score) if is_home else (s.away_score > s.home_score)
            if set_num == 1:
                matches_with_first_set += 1
                if my_won:
                    wins_first_set += 1
            elif set_num == 2:
                matches_with_second_set += 1
                if my_won:
                    wins_second_set += 1
            if set_num not in by_position:
                by_position[set_num] = []
            by_position[set_num].append(my_won)
            total_sets_played += 1
        pattern = "".join(
            "W" if ((s.home_score > s.away_score) if is_home else (s.away_score > s.home_score)) else "L"
            for s in scores
        )
        if pattern:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

    win_first_set_pct = (wins_first_set / matches_with_first_set) if matches_with_first_set else None
    win_second_set_pct = (wins_second_set / matches_with_second_set) if matches_with_second_set else None
    avg_sets_per_match = (total_sets_played / total) if total else None

    set_win_pct_by_position = []
    for set_num in sorted(by_position.keys()):
        arr = by_position[set_num]
        set_win_pct_by_position.append({
            "set_number": set_num,
            "wins": sum(1 for x in arr if x),
            "total": len(arr),
            "pct": round(sum(1 for x in arr if x) / len(arr), 4) if arr else None,
        })

    total_patterns = sum(pattern_counts.values())
    set_patterns = [
        {"pattern": p, "count": c, "pct": round(c / total_patterns, 4) if total_patterns else None}
        for p, c in sorted(pattern_counts.items(), key=lambda x: -x[1])[:10]
    ]

    return PlayerStats(
        total_matches=total,
        wins=wins,
        losses=losses,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        wins_first_set=wins_first_set,
        matches_with_first_set=matches_with_first_set,
        win_first_set_pct=round(win_first_set_pct, 4) if win_first_set_pct is not None else None,
        wins_second_set=wins_second_set,
        matches_with_second_set=matches_with_second_set,
        win_second_set_pct=round(win_second_set_pct, 4) if win_second_set_pct is not None else None,
        total_sets_played=total_sets_played,
        avg_sets_per_match=round(avg_sets_per_match, 2) if avg_sets_per_match is not None else None,
        set_win_pct_by_position=set_win_pct_by_position,
        set_patterns=set_patterns,
    )
