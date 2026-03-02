"""Normalizer: raw payload -> internal models, write to DB."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Match, MatchResult, MatchScore, MatchStatus, OddsSnapshot, Player

# В архиве нет времени окончания; используем время начала + 20 мин как приближение
ARCHIVE_FINISHED_AT_OFFSET_MINUTES = 20
# Матчи до 01.01.2026 при совпадении provider_match_id заменяем данными из архива
ARCHIVE_REPLACE_CUTOFF = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Окно поиска «того же» матча по игрокам и времени (линия могла прийти с одним id, лайв — с другим).
# Узкое окно (30 мин): одни и те же игроки могут играть два разных матча в течение 2 часов — не склеиваем.
MATCH_SAME_EVENT_WINDOW_MINUTES = 30


def _is_event_ended(event: dict[str, Any]) -> bool:
    """BetsAPI: time_status 3=Ended, 100=Ended; или status/result."""
    if not isinstance(event, dict):
        return False
    ts = event.get("time_status")
    if ts is not None and ts in (3, 100, "3", "100"):
        return True
    if str(event.get("status") or "").lower() in ("ended", "closed", "finished"):
        return True
    return False


def _parse_ss(ss: str | None) -> list[tuple[int, int]]:
    """Parse BetsAPI ss/score: '2-1 (11:9 9:11 11:7)', '11:9 9:11 11:7', '11-9 9-11', etc. -> [(11,9), (9,11), (11,7)]."""
    if not ss or not isinstance(ss, str):
        return []
    s = ss.strip()
    # Вариант 1: скобки с парами — "2-1 (11:9 9:11 11:7)" или "(11:9 9:11)"
    inside = re.search(r"\(([^)]+)\)", s)
    if inside:
        s = inside.group(1)
    # Разбиваем по пробелам/запятым и парсим каждую часть как "a:b" или "a-b"
    parts = re.split(r"[\s,;]+", s)
    result: list[tuple[int, int]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if ":" in p:
            tok = p.split(":", 1)
        elif "-" in p:
            tok = p.split("-", 1)
        else:
            continue
        if len(tok) != 2:
            continue
        try:
            a, b = int(tok[0].strip()), int(tok[1].strip())
            # разумный диапазон очков в сете (НТ: до 11 или до 21)
            if 0 <= a <= 30 and 0 <= b <= 30:
                result.append((a, b))
        except ValueError:
            continue
    return result


def _event_sets_scores(event: dict[str, Any]) -> list[tuple[int, int]]:
    """Счёт по сетам из события: сначала из scores (inplay list), иначе из ss."""
    scores = event.get("scores")
    if isinstance(scores, dict) and scores:
        result: list[tuple[int, int]] = []
        for key in sorted(scores.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            s = scores.get(key)
            if isinstance(s, dict):
                h, a = s.get("home"), s.get("away")
                try:
                    result.append((int(h), int(a)))
                except (TypeError, ValueError):
                    pass
        if result:
            return result
    ss = event.get("ss") or (event.get("scores") if isinstance(event.get("scores"), str) else None)
    return _parse_ss(ss)


def _add_odds_snapshot(
    session: AsyncSession,
    match_id: UUID,
    bookmaker: str,
    market_name: str,
    out: dict[str, Any],
    phase: str | None,
    snapshot_time: int | float | None,
    market_line: float | Decimal | None,
    score_at_snapshot: str | None = None,
) -> None:
    """Добавляет одну запись OddsSnapshot (outcome из букмекера/рынка)."""
    name = out.get("name") or out.get("selection")
    price = out.get("price") or out.get("odd")
    if name is None or price is None:
        return
    try:
        odds_val = Decimal(str(price))
    except Exception:
        return
    implied = (Decimal("1") / odds_val) if odds_val else None
    line_val = out.get("line_value") if out.get("line_value") is not None else market_line
    if line_val is not None:
        try:
            line_val = Decimal(str(line_val))
        except Exception:
            line_val = None
    st_val = snapshot_time
    if st_val is not None and isinstance(st_val, (int, float)):
        try:
            st_val = datetime.fromtimestamp(int(st_val), tz=timezone.utc)
        except (ValueError, OSError):
            st_val = None
    session.add(
        OddsSnapshot(
            match_id=match_id,
            bookmaker=bookmaker,
            market=market_name,
            selection=str(name),
            odds=odds_val,
            implied_probability=round(implied, 6) if implied else None,
            line_value=line_val,
            snapshot_time=st_val,
            phase=phase,
            score_at_snapshot=score_at_snapshot[:100] if score_at_snapshot else None,
        )
    )


class Normalizer:
    """Map provider payloads to internal League/Player/Match/MatchScore/MatchResult/OddsSnapshot and persist."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def normalize_betsapi_response(
        self, events: list[dict[str, Any]], current_event_ids: set[str] | None = None
    ) -> list[UUID]:
        """
        BetsAPI events: id, time (unix), home, away, league?, ss?, score?, odds?.

        current_event_ids: если задано, матчи со status=LIVE и provider_match_id не из этого
        множества помечаются как FINISHED (исчезли из inplay/upcoming — завершены).
        """
        seen_ids: set[str] = set()
        match_ids: list[UUID] = []
        # Матчи из текущего батча (игроки + время) — чтобы не помечать как отменённые, если тот же матч пришёл под другим id
        seen_players_time: list[tuple[UUID, UUID, datetime]] = []
        provider = "betsapi"

        for event in events:
            if not isinstance(event, dict):
                continue
            eid = event.get("id")
            if not eid:
                continue
            eid_str = str(eid)
            source = event.get("_source", "")

            home_obj = event.get("home") or {}
            away_obj = event.get("away") or {}
            if isinstance(home_obj, dict):
                home_name = home_obj.get("name") or home_obj.get("title") or "Home"
                home_pid = home_obj.get("id") if isinstance(home_obj.get("id"), (str, int)) else None
                home_image_id = home_obj.get("image_id")
                home_cc = home_obj.get("cc")
            else:
                home_name = str(home_obj) if home_obj else "Home"
                home_pid = home_image_id = home_cc = None
            if isinstance(away_obj, dict):
                away_name = away_obj.get("name") or away_obj.get("title") or "Away"
                away_pid = away_obj.get("id") if isinstance(away_obj.get("id"), (str, int)) else None
                away_image_id = away_obj.get("image_id")
                away_cc = away_obj.get("cc")
            else:
                away_name = str(away_obj) if away_obj else "Away"
                away_pid = away_image_id = away_cc = None

            time_val = event.get("time")
            if time_val is not None:
                if isinstance(time_val, str) and time_val.isdigit():
                    time_val = int(time_val)
                st = datetime.fromtimestamp(int(time_val), tz=timezone.utc) if time_val else None
            else:
                st = None
            if st is None:
                continue

            league_id = None
            league_obj = event.get("league")
            if isinstance(league_obj, dict) and (league_obj.get("id") or league_obj.get("name")):
                league_id = await self._get_or_create_league(
                    provider=provider,
                    provider_league_id=str(league_obj.get("id", "")),
                    name=league_obj.get("name") or "Unknown",
                    country=league_obj.get("cc") or league_obj.get("country"),
                )

            if source == "ended":
                existing_match = (
                    await self.session.execute(
                        select(Match).where(
                            Match.provider == provider,
                            Match.provider_match_id == eid_str,
                        )
                    )
                ).scalars().first()
                if existing_match is not None:
                    match = existing_match
                else:
                    home_player = await self._get_or_create_player(home_name, provider, str(home_pid) if home_pid is not None else None)
                    away_player = await self._get_or_create_player(away_name, provider, str(away_pid) if away_pid is not None else None)
                    if home_player and away_player:
                        candidate = await self._find_scheduled_match_by_players_and_time(
                            provider, home_player.id, away_player.id, st, MATCH_SAME_EVENT_WINDOW_MINUTES
                        )
                        if candidate is not None:
                            candidate.provider_match_id = eid_str
                            if league_id is not None:
                                candidate.league_id = league_id
                            await self.session.flush()
                            match = candidate
                        else:
                            match = await self._get_or_create_match(
                                provider=provider,
                                provider_match_id=eid_str,
                                home_name=home_name,
                                away_name=away_name,
                                start_time=st.isoformat(),
                                league_id=league_id,
                                home_provider_id=str(home_pid) if home_pid is not None else None,
                                away_provider_id=str(away_pid) if away_pid is not None else None,
                            )
                    else:
                        match = await self._get_or_create_match(
                            provider=provider,
                            provider_match_id=eid_str,
                            home_name=home_name,
                            away_name=away_name,
                            start_time=st.isoformat(),
                            league_id=league_id,
                            home_provider_id=str(home_pid) if home_pid is not None else None,
                            away_provider_id=str(away_pid) if away_pid is not None else None,
                        )
            elif source == "inplay":
                existing_match = (
                    await self.session.execute(
                        select(Match).where(
                            Match.provider == provider,
                            Match.provider_match_id == eid_str,
                        )
                    )
                ).scalars().first()
                if existing_match is not None:
                    match = existing_match
                else:
                    home_player = await self._get_or_create_player(home_name, provider, str(home_pid) if home_pid is not None else None)
                    away_player = await self._get_or_create_player(away_name, provider, str(away_pid) if away_pid is not None else None)
                    if home_player and away_player:
                        # Линия под одним id, лайв под другим — в узком окне (30 мин) считаем одним матчем
                        candidate = await self._find_scheduled_match_by_players_and_time(
                            provider, home_player.id, away_player.id, st, MATCH_SAME_EVENT_WINDOW_MINUTES, include_live=True
                        )
                        if candidate is not None:
                            candidate.provider_match_id = eid_str
                            if league_id is not None:
                                candidate.league_id = league_id
                            await self.session.flush()
                            match = candidate
                        else:
                            match = await self._get_or_create_match(
                                provider=provider,
                                provider_match_id=eid_str,
                                home_name=home_name,
                                away_name=away_name,
                                start_time=st.isoformat(),
                                league_id=league_id,
                                home_provider_id=str(home_pid) if home_pid is not None else None,
                                away_provider_id=str(away_pid) if away_pid is not None else None,
                            )
                    else:
                        match = await self._get_or_create_match(
                            provider=provider,
                            provider_match_id=eid_str,
                            home_name=home_name,
                            away_name=away_name,
                            start_time=st.isoformat(),
                            league_id=league_id,
                            home_provider_id=str(home_pid) if home_pid is not None else None,
                            away_provider_id=str(away_pid) if away_pid is not None else None,
                        )
            else:
                match = await self._get_or_create_match(
                    provider=provider,
                    provider_match_id=eid_str,
                    home_name=home_name,
                    away_name=away_name,
                    start_time=st.isoformat(),
                    league_id=league_id,
                    home_provider_id=str(home_pid) if home_pid is not None else None,
                    away_provider_id=str(away_pid) if away_pid is not None else None,
                )
            if not match:
                continue
            match_ids.append(match.id)
            seen_players_time.append((match.home_player_id, match.away_player_id, match.start_time))
            seen_ids.add(eid_str)

            # Игроки: image_id, country
            await self._update_players_from_event(match, home_image_id=home_image_id, home_country=home_cc, away_image_id=away_image_id, away_country=away_cc)

            # Обновляем поля из event/view (extra.bestofsets → sets_to_win, timeline, timer, confirmed_at, bet365_id, started_at, finished_at)
            await self._update_match_from_event(match, event)

            if source == "inplay":
                is_ended = _is_event_ended(event)
                await self.session.execute(
                    update(Match).where(Match.id == match.id).values(
                        status=MatchStatus.FINISHED.value if is_ended else MatchStatus.LIVE.value
                    )
                )
                ss = event.get("ss") or (event.get("scores") if isinstance(event.get("scores"), str) else None)
                sets_scores = _event_sets_scores(event)
                if sets_scores:
                    await self.session.execute(delete(MatchScore).where(MatchScore.match_id == match.id))
                    for set_num, (h, a) in enumerate(sets_scores, start=1):
                        self.session.add(
                            MatchScore(
                                match_id=match.id,
                                set_number=set_num,
                                home_score=h,
                                away_score=a,
                            )
                        )
                if is_ended:
                    existing_result = (
                        await self.session.execute(select(MatchResult).where(MatchResult.match_id == match.id))
                    ).scalars().first()
                    if not existing_result:
                        score_str = event.get("score") or ss or "0-0"
                        home_sets = sum(1 for h, a in sets_scores if h > a)
                        away_sets = sum(1 for h, a in sets_scores if a > h)
                        winner_id = None
                        if home_sets > away_sets:
                            winner_id = match.home_player_id
                        elif away_sets > home_sets:
                            winner_id = match.away_player_id
                        finished_at = datetime.now(timezone.utc)
                        self.session.add(
                            MatchResult(
                                match_id=match.id,
                                final_score=score_str[:50],
                                winner_id=winner_id,
                                finished_at=finished_at,
                            )
                        )
            elif source == "ended":
                ss = event.get("ss") or (event.get("scores") if isinstance(event.get("scores"), str) else None)
                score_str = event.get("score") or ss or "0-0"
                sets_scores = _event_sets_scores(event)
                match_start = match.start_time
                if match_start and getattr(match_start, "tzinfo", None) is None:
                    match_start = match_start.replace(tzinfo=timezone.utc)
                replace_with_archive = match_start is not None and match_start < ARCHIVE_REPLACE_CUTOFF
                # В архиве нет даты завершения — берём дату начала + 20 мин
                finished_at_approx = st + timedelta(minutes=ARCHIVE_FINISHED_AT_OFFSET_MINUTES)

                if replace_with_archive:
                    await self.session.execute(
                        update(Match).where(Match.id == match.id).values(
                            start_time=st,
                            league_id=league_id,
                            status=MatchStatus.FINISHED.value,
                            started_at=st,
                            finished_at=finished_at_approx,
                        )
                    )
                else:
                    await self.session.execute(
                        update(Match).where(Match.id == match.id).values(
                            status=MatchStatus.FINISHED.value,
                            started_at=st,
                            finished_at=finished_at_approx,
                        )
                    )

                if sets_scores:
                    await self.session.execute(delete(MatchScore).where(MatchScore.match_id == match.id))
                    for set_num, (h, a) in enumerate(sets_scores, start=1):
                        self.session.add(
                            MatchScore(
                                match_id=match.id,
                                set_number=set_num,
                                home_score=h,
                                away_score=a,
                            )
                        )

                if replace_with_archive:
                    await self.session.execute(delete(MatchResult).where(MatchResult.match_id == match.id))
                existing_result = (
                    await self.session.execute(select(MatchResult).where(MatchResult.match_id == match.id))
                ).scalars().first()
                if not existing_result:
                    home_sets = sum(1 for h, a in sets_scores if h > a)
                    away_sets = sum(1 for h, a in sets_scores if a > h)
                    winner_id = None
                    if home_sets > away_sets:
                        winner_id = match.home_player_id
                    elif away_sets > home_sets:
                        winner_id = match.away_player_id
                    self.session.add(
                        MatchResult(
                            match_id=match.id,
                            final_score=score_str[:50],
                            winner_id=winner_id,
                            finished_at=finished_at_approx,
                        )
                    )
                    await self.session.flush()

            odds_data = event.get("odds") or event.get("bookmakers")
            if match and odds_data and isinstance(odds_data, list):
                phase = "line" if source == "upcoming" else "live" if source == "inplay" else None
                for bm in odds_data:
                    if not isinstance(bm, dict):
                        continue
                    bm_key = bm.get("name") or bm.get("key") or "unknown"
                    for m in bm.get("markets") or bm.get("odds") or []:
                        if not isinstance(m, dict):
                            continue
                        market_name = m.get("name") or "winner"
                        snapshots = m.get("snapshots")
                        if isinstance(snapshots, list) and snapshots:
                            for snap in snapshots:
                                if not isinstance(snap, dict):
                                    continue
                                snapshot_time = snap.get("snapshot_time")
                                market_line = snap.get("line_value")
                                score_at_snapshot = snap.get("score_at_snapshot") or snap.get("ss")
                                if isinstance(score_at_snapshot, str):
                                    score_at_snapshot = score_at_snapshot.strip() or None
                                else:
                                    score_at_snapshot = None
                                outcomes_list = snap.get("outcomes") or []
                                for out in outcomes_list:
                                    if not isinstance(out, dict):
                                        continue
                                    _add_odds_snapshot(
                                        self.session, match.id, bm_key, market_name,
                                        out, phase, snapshot_time, market_line,
                                        score_at_snapshot=score_at_snapshot,
                                    )
                        else:
                            outcomes_list = m.get("outcomes") or m.get("choices") or []
                            snapshot_time = m.get("snapshot_time")
                            market_line = m.get("line_value")
                            for out in outcomes_list:
                                if not isinstance(out, dict):
                                    continue
                                _add_odds_snapshot(
                                    self.session, match.id, bm_key, market_name,
                                    out, phase, snapshot_time, market_line,
                                )
                if event.get("odds_stats") is not None:
                    await self.session.execute(
                        update(Match).where(Match.id == match.id).values(odds_stats=event["odds_stats"])
                    )

        if current_event_ids is not None and len(current_event_ids) > 0:
            # Матчи, которые исчезли из inplay (их provider_match_id нет в текущей выборке)
            disappeared = await self.session.execute(
                select(Match.id).where(
                    Match.provider == "betsapi",
                    Match.status == MatchStatus.LIVE.value,
                    ~Match.provider_match_id.in_(current_event_ids),
                )
            )
            disappeared_ids = [r[0] for r in disappeared.all()]
            if disappeared_ids:
                # Есть ли счёт по сетам: если да — завершаем с результатом, если нет — возможно отменён (но не всегда)
                scores_count = (
                    await self.session.execute(
                        select(MatchScore.match_id, MatchScore.set_number).where(
                            MatchScore.match_id.in_(disappeared_ids)
                        )
                    )
                ).all()
                has_scores_ids = {r[0] for r in scores_count}
                to_finish = [mid for mid in disappeared_ids if mid in has_scores_ids]
                # Без счёта: не помечаем отменённым, если в этом же батче есть матч с теми же игроками и временем (тот же матч под другим id)
                no_scores_ids = [mid for mid in disappeared_ids if mid not in has_scores_ids]
                # Никогда не помечаем отменённым матч, у которого уже есть результат (сохраняем «угадано» в статистике)
                has_result = set()
                if no_scores_ids:
                    res_r = await self.session.execute(
                        select(MatchResult.match_id).where(MatchResult.match_id.in_(no_scores_ids))
                    )
                    has_result = {r[0] for r in res_r.all()}
                no_scores_ids = [mid for mid in no_scores_ids if mid not in has_result]
                skip_cancel: set[UUID] = set()
                if no_scores_ids and seen_players_time:
                    disappeared_matches = (
                        await self.session.execute(
                            select(Match.id, Match.home_player_id, Match.away_player_id, Match.start_time).where(
                                Match.id.in_(no_scores_ids)
                            )
                        )
                    ).all()
                    delta_sec = MATCH_SAME_EVENT_WINDOW_MINUTES * 60
                    for mid, h, a, t in disappeared_matches:
                        if h is None or a is None or t is None:
                            continue
                        t_naive = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
                        for sh, sa, st in seen_players_time:
                            st_naive = st.replace(tzinfo=timezone.utc) if st.tzinfo is None else st
                            if sh == h and sa == a and abs((t_naive - st_naive).total_seconds()) <= delta_sec:
                                skip_cancel.add(mid)
                                break
                to_cancel = [mid for mid in no_scores_ids if mid not in skip_cancel]
                if to_finish:
                    await self.session.execute(
                        update(Match).where(Match.id.in_(to_finish)).values(status=MatchStatus.FINISHED.value)
                    )
                    await self._create_result_from_scores_for_matches(to_finish)
                if to_cancel:
                    await self.session.execute(
                        update(Match).where(Match.id.in_(to_cancel)).values(status=MatchStatus.CANCELLED.value)
                    )

        # Дополнительно: матчи уже в статусе FINISHED без MatchResult, но с MatchScore — подтягиваем результат (подстраховка и бэкфилл)
        await self._create_result_from_scores_for_finished_without_result()

        await self.session.commit()
        return list(dict.fromkeys(match_ids))

    async def _create_result_from_scores_for_matches(self, match_ids: list[UUID]) -> None:
        """Для матчей без MatchResult создаёт запись результата из MatchScore (счёт по сетам). Вызывается при пометке LIVE→FINISHED из-за исчезновения из inplay."""
        if not match_ids:
            return
        existing_result = await self.session.execute(
            select(MatchResult.match_id).where(MatchResult.match_id.in_(match_ids))
        )
        has_result = {r[0] for r in existing_result.all()}
        need_result = [mid for mid in match_ids if mid not in has_result]
        if not need_result:
            return
        matches = (
            await self.session.execute(
                select(Match).where(
                    Match.id.in_(need_result),
                )
            )
        ).scalars().all()
        match_by_id = {m.id: m for m in matches}
        scores_rows = (
            await self.session.execute(
                select(MatchScore.match_id, MatchScore.set_number, MatchScore.home_score, MatchScore.away_score)
                .where(MatchScore.match_id.in_(need_result))
                .order_by(MatchScore.match_id, MatchScore.set_number)
            )
        ).all()
        scores_by_match: dict[UUID, list[tuple[int, int]]] = {}
        for mid, set_num, h, a in scores_rows:
            scores_by_match.setdefault(mid, []).append((h, a))
        now = datetime.now(timezone.utc)
        for mid in need_result:
            match = match_by_id.get(mid)
            if not match or not match.home_player_id or not match.away_player_id:
                continue
            sets_scores = scores_by_match.get(mid)
            if not sets_scores:
                continue
            home_sets = sum(1 for h, a in sets_scores if h > a)
            away_sets = sum(1 for h, a in sets_scores if a > h)
            score_parts = [f"{h}:{a}" for h, a in sets_scores]
            score_str = " ".join(score_parts)[:50]
            winner_id = None
            if home_sets > away_sets:
                winner_id = match.home_player_id
            elif away_sets > home_sets:
                winner_id = match.away_player_id
            self.session.add(
                MatchResult(
                    match_id=mid,
                    final_score=score_str,
                    winner_id=winner_id,
                    finished_at=now,
                )
            )

    async def _create_result_from_scores_for_finished_without_result(self) -> None:
        """Находит матчи со статусом FINISHED без MatchResult, но с хотя бы одним MatchScore, и создаёт для них MatchResult (бэкфилл и подстраховка)."""
        from sqlalchemy import exists
        has_score = select(MatchScore.match_id).where(MatchScore.match_id == Match.id).limit(1)
        r = await self.session.execute(
            select(Match.id).where(
                Match.status == MatchStatus.FINISHED.value,
                ~Match.id.in_(select(MatchResult.match_id)),
                exists(has_score),
            )
        )
        ids = [row[0] for row in r.all()]
        if ids:
            await self._create_result_from_scores_for_matches(ids)

    async def _update_match_from_event(self, match: Match, event: dict[str, Any]) -> None:
        """Обновляет Match полями из event/view: extra.bestofsets → sets_to_win, timeline, extra, timer, confirmed_at, bet365_id, started_at, finished_at."""
        vals: dict[str, Any] = {}
        extra = event.get("extra")
        if isinstance(extra, dict):
            bestof = extra.get("bestofsets")
            if bestof is not None:
                try:
                    n = int(bestof)
                    if n in (3, 5, 7):
                        vals["sets_to_win"] = (n + 1) // 2  # 3→2 (BO3), 5→3 (BO5), 7→4 (BO7)
                except (TypeError, ValueError):
                    pass
            vals["extra"] = extra
        if event.get("timeline") is not None:
            vals["timeline"] = event["timeline"]
        if event.get("timer") is not None:
            vals["current_timer"] = str(event["timer"])
        if event.get("confirmed_at") is not None:
            ca = event["confirmed_at"]
            if isinstance(ca, (int, float)):
                vals["confirmed_at"] = datetime.fromtimestamp(int(ca), tz=timezone.utc)
            elif isinstance(ca, str):
                try:
                    vals["confirmed_at"] = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                except ValueError:
                    pass
        if event.get("bet365_id") is not None:
            vals["bet365_id"] = str(event["bet365_id"])
        source = event.get("_source", "")
        sets_scores = _event_sets_scores(event)
        if source == "inplay" and sets_scores and match.started_at is None:
            vals["started_at"] = datetime.now(timezone.utc)
        if _is_event_ended(event) and match.finished_at is None and source != "ended":
            vals["finished_at"] = datetime.now(timezone.utc)
        if source == "ended":
            t = event.get("time")
            if t is not None:
                try:
                    dt = datetime.fromtimestamp(int(t), tz=timezone.utc)
                    vals["started_at"] = dt
                    vals["finished_at"] = dt + timedelta(minutes=ARCHIVE_FINISHED_AT_OFFSET_MINUTES)
                except (TypeError, ValueError):
                    pass
        if vals:
            await self.session.execute(update(Match).where(Match.id == match.id).values(**vals))

    async def _update_players_from_event(
        self,
        match: Match,
        *,
        home_image_id: str | None = None,
        home_country: str | None = None,
        away_image_id: str | None = None,
        away_country: str | None = None,
    ) -> None:
        """Обновляет Player: image_id и country из event (home/away)."""
        if home_image_id is not None or home_country is not None:
            v = {}
            if home_image_id is not None:
                v["image_id"] = str(home_image_id)[:100]
            if home_country is not None:
                v["country"] = str(home_country)[:100]
            if v:
                await self.session.execute(
                    update(Player).where(Player.id == match.home_player_id).values(**v)
                )
        if away_image_id is not None or away_country is not None:
            v = {}
            if away_image_id is not None:
                v["image_id"] = str(away_image_id)[:100]
            if away_country is not None:
                v["country"] = str(away_country)[:100]
            if v:
                await self.session.execute(
                    update(Player).where(Player.id == match.away_player_id).values(**v)
                )

    async def _get_or_create_league(
        self,
        provider: str,
        provider_league_id: str,
        name: str,
        country: str | None = None,
    ) -> UUID | None:
        if not name:
            return None
        if not provider_league_id:
            provider_league_id = name
        existing = await self.session.execute(
            select(League).where(
                League.provider == provider,
                League.provider_league_id == provider_league_id,
            )
        )
        league = existing.scalar_one_or_none()
        if league:
            return league.id
        league = League(
            name=name,
            country=country,
            provider_league_id=provider_league_id,
            provider=provider,
        )
        self.session.add(league)
        await self.session.flush()
        return league.id

    async def _get_or_create_match(
        self,
        provider: str,
        provider_match_id: str,
        home_name: str,
        away_name: str,
        start_time: str | None,
        league_id: UUID | None = None,
        home_provider_id: str | None = None,
        away_provider_id: str | None = None,
    ) -> Match | None:
        from datetime import datetime

        home_player = await self._get_or_create_player(
            home_name, provider, home_provider_id
        )
        away_player = await self._get_or_create_player(
            away_name, provider, away_provider_id
        )
        if not home_player or not away_player:
            return None

        st = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else None
        if not st:
            return None

        existing = await self.session.execute(
            select(Match).where(
                Match.provider == provider,
                Match.provider_match_id == provider_match_id,
            )
        )
        match = existing.scalar_one_or_none()
        if match:
            if league_id is not None:
                match.league_id = league_id
            return match

        match = Match(
            provider_match_id=provider_match_id,
            provider=provider,
            league_id=league_id,
            home_player_id=home_player.id,
            away_player_id=away_player.id,
            start_time=st,
            status=MatchStatus.SCHEDULED.value,
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def _find_scheduled_match_by_players_and_time(
        self,
        provider: str,
        home_player_id: UUID,
        away_player_id: UUID,
        start_time: datetime,
        window_minutes: int = 30,
        *,
        include_live: bool = False,
    ) -> Match | None:
        """Ищет матч с теми же игроками и start_time в окне ±window_minutes минут.
        Узкое окно (30 мин по умолчанию): одни и те же игроки могут играть два разных матча в течение 2 часов."""
        statuses = [MatchStatus.SCHEDULED.value, MatchStatus.CANCELLED.value, MatchStatus.POSTPONED.value]
        if include_live:
            statuses.append(MatchStatus.LIVE.value)
        delta = timedelta(minutes=window_minutes)
        lo = start_time - delta
        hi = start_time + delta
        r = await self.session.execute(
            select(Match).where(
                Match.provider == provider,
                Match.status.in_(statuses),
                Match.home_player_id == home_player_id,
                Match.away_player_id == away_player_id,
                Match.start_time >= lo,
                Match.start_time <= hi,
            ).limit(1)
        )
        return r.scalars().first()

    async def _get_or_create_player(
        self,
        name: str,
        provider: str,
        provider_player_id: str | None,
    ) -> Player | None:
        if provider_player_id:
            existing = await self.session.execute(
                select(Player).where(
                    Player.provider == provider,
                    Player.provider_player_id == provider_player_id,
                )
            )
            p = existing.scalar_one_or_none()
            if p:
                if p.name != name:
                    p.name = name
                return p
        else:
            existing = await self.session.execute(
                select(Player).where(
                    Player.provider == provider,
                    Player.name == name,
                )
            )
            p = existing.scalar_one_or_none()
            if p:
                return p
        p = Player(name=name, provider=provider, provider_player_id=provider_player_id)
        self.session.add(p)
        await self.session.flush()
        return p
