"""Feature builder for table tennis forecast V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.table_tennis_line_event import (
    LINE_EVENT_STATUS_FINISHED,
    TableTennisLineEvent,
)
from app.models.table_tennis_match_feature import TableTennisMatchFeature
from app.models.table_tennis_player_daily_feature import TableTennisPlayerDailyFeature


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_sets_score(value: str | None) -> tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


@dataclass
class FeatureSnapshot:
    event_id: str
    home_id: str
    away_id: str
    league_id: str
    features: dict
    data_quality_score: float


async def rebuild_player_daily_features_once(session: AsyncSession) -> int:
    """Rebuild 7d fatigue/workload aggregates for active players."""
    now = _utc_now()
    since = now - timedelta(days=8)
    rows = (
        await session.execute(
            select(TableTennisLineEvent).where(
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                    TableTennisLineEvent.starts_at >= since,
                )
            )
        )
    ).scalars().all()

    by_player_day: dict[tuple[str, date], list[datetime]] = {}
    for ev in rows:
        day = ev.starts_at.date()
        by_player_day.setdefault((ev.home_id, day), []).append(ev.starts_at)
        by_player_day.setdefault((ev.away_id, day), []).append(ev.starts_at)

    if not by_player_day:
        return 0

    player_ids = {pid for (pid, _day) in by_player_day.keys()}
    await session.execute(
        delete(TableTennisPlayerDailyFeature).where(
            and_(
                TableTennisPlayerDailyFeature.player_id.in_(player_ids),
                TableTennisPlayerDailyFeature.day >= since.date(),
            )
        )
    )

    inserts = 0
    for (player_id, day), times in by_player_day.items():
        d1 = len(times)
        d2 = sum(
            len(by_player_day.get((player_id, day - timedelta(days=delta)), []))
            for delta in range(0, 2)
        )
        d7 = sum(
            len(by_player_day.get((player_id, day - timedelta(days=delta)), []))
            for delta in range(0, 7)
        )
        ordered = sorted(times)
        rest_values: list[float] = []
        for i in range(1, len(ordered)):
            rest_values.append((ordered[i] - ordered[i - 1]).total_seconds() / 60.0)
        avg_rest = (sum(rest_values) / len(rest_values)) if rest_values else None
        fatigue_score = min(100.0, d1 * 12.0 + d2 * 5.0 + d7 * 2.0)

        session.add(
            TableTennisPlayerDailyFeature(
                player_id=player_id,
                day=day,
                matches_1d=d1,
                matches_2d=d2,
                matches_7d=d7,
                avg_rest_minutes_48h=avg_rest,
                fatigue_score=fatigue_score,
            )
        )
        inserts += 1

    await session.commit()
    return inserts


async def build_match_feature_snapshot(
    session: AsyncSession,
    event: TableTennisLineEvent,
) -> FeatureSnapshot:
    """Build pre-match feature snapshot for one event."""
    now = _utc_now()
    history_since = now - timedelta(days=90)

    def _player_history_stmt(player_id: str):
        return select(TableTennisLineEvent).where(
            and_(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                or_(
                    TableTennisLineEvent.home_id == player_id,
                    TableTennisLineEvent.away_id == player_id,
                ),
                TableTennisLineEvent.starts_at >= history_since,
            )
        )

    home_history = (await session.execute(_player_history_stmt(event.home_id))).scalars().all()
    away_history = (await session.execute(_player_history_stmt(event.away_id))).scalars().all()

    def _win_rate(player_id: str, rows: list[TableTennisLineEvent]) -> float:
        total = 0
        wins = 0
        for row in rows:
            hs, as_ = _parse_sets_score(row.live_sets_score)
            if hs is None or as_ is None or hs == as_:
                continue
            total += 1
            home_win = hs > as_
            if (row.home_id == player_id and home_win) or (row.away_id == player_id and not home_win):
                wins += 1
        return wins / total if total else 0.5

    home_wr = _win_rate(event.home_id, home_history)
    away_wr = _win_rate(event.away_id, away_history)

    h2h_rows = (
        await session.execute(
            select(TableTennisLineEvent).where(
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                    or_(
                        and_(
                            TableTennisLineEvent.home_id == event.home_id,
                            TableTennisLineEvent.away_id == event.away_id,
                        ),
                        and_(
                            TableTennisLineEvent.home_id == event.away_id,
                            TableTennisLineEvent.away_id == event.home_id,
                        ),
                    ),
                )
            )
        )
    ).scalars().all()

    h2h_total = 0
    h2h_home_wins = 0
    for row in h2h_rows:
        hs, as_ = _parse_sets_score(row.live_sets_score)
        if hs is None or as_ is None or hs == as_:
            continue
        h2h_total += 1
        if row.home_id == event.home_id:
            if hs > as_:
                h2h_home_wins += 1
        elif as_ > hs:
            h2h_home_wins += 1
    h2h_home_wr = (h2h_home_wins / h2h_total) if h2h_total else 0.5

    player_day = event.starts_at.date()
    home_fatigue = (
        await session.execute(
            select(TableTennisPlayerDailyFeature.fatigue_score).where(
                and_(
                    TableTennisPlayerDailyFeature.player_id == event.home_id,
                    TableTennisPlayerDailyFeature.day <= player_day,
                )
            ).order_by(TableTennisPlayerDailyFeature.day.desc()).limit(1)
        )
    ).scalar_one_or_none()
    away_fatigue = (
        await session.execute(
            select(TableTennisPlayerDailyFeature.fatigue_score).where(
                and_(
                    TableTennisPlayerDailyFeature.player_id == event.away_id,
                    TableTennisPlayerDailyFeature.day <= player_day,
                )
            ).order_by(TableTennisPlayerDailyFeature.day.desc()).limit(1)
        )
    ).scalar_one_or_none()

    odds_1 = float(event.odds_1 or 0)
    odds_2 = float(event.odds_2 or 0)
    implied_home = (1.0 / odds_1) if odds_1 > 1e-9 else 0.5
    implied_away = (1.0 / odds_2) if odds_2 > 1e-9 else 0.5
    normalizer = implied_home + implied_away
    if normalizer > 1e-9:
        implied_home /= normalizer
        implied_away /= normalizer

    home_matches = len(home_history)
    away_matches = len(away_history)
    data_quality = min(1.0, (home_matches + away_matches + h2h_total) / 60.0)

    features = {
        "home_form_wr_90d": home_wr,
        "away_form_wr_90d": away_wr,
        "form_delta": home_wr - away_wr,
        "h2h_home_wr": h2h_home_wr,
        "h2h_count": h2h_total,
        "home_fatigue": float(home_fatigue or 0.0),
        "away_fatigue": float(away_fatigue or 0.0),
        "fatigue_delta": float((away_fatigue or 0.0) - (home_fatigue or 0.0)),
        "implied_home": implied_home,
        "implied_away": implied_away,
        "home_samples": home_matches,
        "away_samples": away_matches,
    }
    return FeatureSnapshot(
        event_id=event.id,
        home_id=event.home_id,
        away_id=event.away_id,
        league_id=event.league_id,
        features=features,
        data_quality_score=round(data_quality, 4),
    )


async def upsert_match_feature(session: AsyncSession, snapshot: FeatureSnapshot, model_run_id: int | None = None) -> TableTennisMatchFeature:
    existing = (
        await session.execute(
            select(TableTennisMatchFeature)
            .where(TableTennisMatchFeature.event_id == snapshot.event_id)
            .order_by(TableTennisMatchFeature.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        existing.model_run_id = model_run_id
        existing.home_id = snapshot.home_id
        existing.away_id = snapshot.away_id
        existing.league_id = snapshot.league_id
        existing.features_json = snapshot.features
        existing.data_quality_score = snapshot.data_quality_score
        return existing

    row = TableTennisMatchFeature(
        event_id=snapshot.event_id,
        model_run_id=model_run_id,
        home_id=snapshot.home_id,
        away_id=snapshot.away_id,
        league_id=snapshot.league_id,
        features_json=snapshot.features,
        data_quality_score=snapshot.data_quality_score,
    )
    session.add(row)
    return row
