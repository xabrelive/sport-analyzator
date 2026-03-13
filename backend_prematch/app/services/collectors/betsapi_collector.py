"""BetsAPI collector — table tennis: списки событий + детали (event/view) + коэффициенты (event/odds).

Запросы к API (лимит 3600/час ≈ 1 запрос/сек):
- Списки (v3): upcoming, inplay, ended — 3 запроса.
- Детали (v1): event/view — до 10 id за запрос, только для upcoming+inplay (не для ended).
- Коэффициенты (v2): event/odds — для всех inplay + для upcoming только если ещё нет в БД (один раз).

По завершённым матчам view и odds не запрашиваем.
"""
import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.services.collectors.base import BaseCollector

TABLE_TENNIS_SPORT_ID = 92

BETSAPI_BASE_URLS = [
    "https://api.b365api.com/v3",
    "https://api.betsapi.com/v3",
]
BETSAPI_BASE_V1 = "https://api.b365api.com/v1"
BETSAPI_BASE_V2 = "https://api.b365api.com/v2"
EVENT_VIEW_BATCH_SIZE = 10


logger = logging.getLogger(__name__)


class BetsApiRateLimitError(Exception):
    """Сигнализирует о том, что BetsAPI вернуло 429 Too Many Requests."""

    pass


class BetsapiEndedRequestError(Exception):
    """Ошибка запроса GET /v3/events/ended (HTTP или success=false). Не трактовать как «пустая страница»."""

    pass


def _parse_line_value(raw: Any) -> float | None:
    """Извлекает числовое значение линии из API (handicap/total/line). Поддерживает строки с запятой и unicode минус."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        s = raw.strip().replace(",", ".").replace("\u2212", "-")  # unicode minus
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _normalize_odds_response(odds_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Преобразует ответ event/odds в формат для normalizer: все снимки по каждому рынку, line_value для гандикапа/тотала."""
    results = odds_data.get("results") or {}
    if not isinstance(results, dict):
        return []

    # Формат v2: results.odds либо results[event_id].odds (при одном event_id в запросе)
    odds_by_market = results.get("odds")
    if not isinstance(odds_by_market, dict) and results:
        first_key = next(iter(results), None)
        if first_key is not None:
            block = results.get(first_key)
            if isinstance(block, dict):
                odds_by_market = block.get("odds")

    if isinstance(odds_by_market, dict) and odds_by_market:
        markets_out: list[dict[str, Any]] = []
        for market_id, snapshots in odds_by_market.items():
            if not isinstance(snapshots, list) or not snapshots:
                continue
            market_id_str = str(market_id)
            # Over/Under: 92_3 = тотал сетов; 92_4–92_6 = тотал очков (матч, 1-й, 2-й сет); 92_12–92_16 = тотал очков (3–7-й сет)
            is_ou = market_id_str in ("92_3", "92_4", "92_5", "92_6", "92_12", "92_13", "92_14", "92_15", "92_16")
            snap_list: list[dict[str, Any]] = []
            for snap in snapshots:
                if not isinstance(snap, dict):
                    continue
                home_od = snap.get("home_od") or snap.get("home_odd")
                away_od = snap.get("away_od") or snap.get("away_odd")
                add_time = snap.get("add_time")
                # Линия гандикапа/тотала: API может отдавать handicap, total, line или handicap_line, total_line, spread, point
                line_val = None
                for key in ("handicap", "total", "line", "handicap_line", "total_line", "spread", "point", "line_value"):
                    line_val = _parse_line_value(snap.get(key))
                    if line_val is not None:
                        break
                if home_od is None or away_od is None:
                    continue
                try:
                    h = str(home_od).strip()
                    a = str(away_od).strip()
                except Exception:
                    continue
                if h == "-" or a == "-":
                    continue
                try:
                    float(h)
                    float(a)
                except ValueError:
                    continue
                if is_ou:
                    outcomes = [
                        {"name": "over", "price": h, "line_value": line_val},
                        {"name": "under", "price": a, "line_value": line_val},
                    ]
                else:
                    outcomes = [
                        {"name": "home", "price": h, "line_value": line_val},
                        {"name": "away", "price": a, "line_value": line_val},
                    ]
                snap_list.append({
                    "snapshot_time": int(add_time) if add_time is not None else None,
                    "line_value": line_val,
                    "score_at_snapshot": snap.get("ss"),
                    "outcomes": outcomes,
                })
            if not snap_list:
                continue
            markets_out.append({
                "name": market_id_str,
                "snapshots": snap_list,
            })
        if markets_out:
            return [{"name": "b365", "markets": markets_out}]

    # Классический формат: results[event_id].bookmakers / .odds (один снимок на рынок)
    out: list[dict[str, Any]] = []
    for _eid, event_block in results.items():
        if not isinstance(event_block, dict):
            continue
        bookmakers_raw = event_block.get("bookmakers") or event_block.get("odds") or []
        if isinstance(bookmakers_raw, dict):
            bookmakers_raw = list(bookmakers_raw.values())
        for bm in bookmakers_raw if isinstance(bookmakers_raw, list) else []:
            if not isinstance(bm, dict):
                continue
            bm_name = bm.get("name") or bm.get("bookmaker") or "unknown"
            markets_raw = bm.get("markets") or bm.get("odds") or []
            if isinstance(markets_raw, dict):
                markets_raw = list(markets_raw.values())
            markets = []
            for m in markets_raw if isinstance(markets_raw, list) else []:
                if not isinstance(m, dict):
                    continue
                m_name = m.get("name") or m.get("market") or "winner"
                outcomes_raw = m.get("outcomes") or m.get("odds") or m.get("choices") or []
                if isinstance(outcomes_raw, dict):
                    outcomes_raw = list(outcomes_raw.values())
                outcomes = [{"name": o.get("name") or o.get("selection"), "price": o.get("price") or o.get("odd")} for o in (outcomes_raw if isinstance(outcomes_raw, list) else []) if isinstance(o, dict)]
                if outcomes:
                    markets.append({"name": m_name, "outcomes": outcomes})
            if markets:
                out.append({"name": bm_name, "markets": markets})
        break
    return out


class BetsApiCollector(BaseCollector):
    # По умолчанию основной хост из документации (https://api.b365api.com/)
    BASE_URL = "https://api.b365api.com/v3"

    async def fetch(
        self,
        sport_id: int | None = None,
        include_upcoming: bool = True,
        include_inplay: bool = True,
        include_ended: bool = True,
        fetch_event_view: bool = True,
        fetch_event_odds: bool = True,
        *,
        upcoming_ids_with_odds: set[str] | None = None,
        events_from_lists: list[dict[str, Any]] | None = None,
        event_ids_for_view: list[str] | None = None,
        event_ids_for_odds: list[str] | None = None,
        page_size_ended: int = 100,
        rate_limit_seconds: float = 1.0,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not settings.betsapi_token:
            return []
        upcoming_ids_with_odds = upcoming_ids_with_odds or set()
        sid = sport_id if sport_id is not None else getattr(
            settings, "betsapi_table_tennis_sport_id", TABLE_TENNIS_SPORT_ID
        )
        token = settings.betsapi_token
        events_by_id: dict[str, dict[str, Any]] = {}
        params: dict[str, Any] = {"sport_id": sid, "token": token}
        base = self.BASE_URL

        # Режим "только списки" или "полный цикл со списками"
        if events_from_lists is None:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if include_upcoming:
                    # Пагинация: загружаем все страницы upcoming, чтобы получить матчи и через 1–2–3+ часа.
                    # Если какая‑то страница долго не отвечает или даёт timeout, не роняем весь цикл линии —
                    # используем уже собранные страницы как усечённый список.
                    page = 1
                    max_upcoming_pages = 50  # разумный лимит, чтобы не упереться в лимит API
                    while page <= max_upcoming_pages:
                        try:
                            r = await client.get(
                                f"{base}/events/upcoming",
                                params={**params, "page": page},
                            )
                        except httpx.ReadTimeout:
                            logger.warning(
                                "BetsAPI events/upcoming: timeout on page=%s sport_id=%s, total_so_far=%s. "
                                "Stopping pagination and using collected events.",
                                page,
                                sid,
                                len(events_by_id),
                            )
                            break
                        if r.status_code == 429:
                            logger.warning(
                                "BetsAPI rate limit (429) on events/upcoming for sport_id=%s", sid
                            )
                            raise BetsApiRateLimitError("events/upcoming 429 Too Many Requests")
                        if not r.is_success and r.status_code == 403:
                            for alt in BETSAPI_BASE_URLS:
                                if alt == base:
                                    continue
                                r = await client.get(f"{alt}/events/upcoming", params={**params, "page": page})
                                if r.is_success:
                                    base = alt
                                    break
                                await asyncio.sleep(rate_limit_seconds)
                        if not r.is_success:
                            logger.warning(
                                "BetsAPI events/upcoming: HTTP %s body=%s",
                                r.status_code,
                                (r.text or "")[:200],
                            )
                            break
                        try:
                            data = r.json() or {}
                        except Exception:
                            data = {}
                        results_raw = data.get("results") or data.get("events") or data.get("data")
                        if isinstance(results_raw, list):
                            res_list = results_raw
                        elif isinstance(results_raw, dict):
                            res_list = []
                            for eid, ev in results_raw.items():
                                if isinstance(ev, dict):
                                    if ev.get("id") is None:
                                        ev = dict(ev)
                                        ev["id"] = eid
                                    res_list.append(ev)
                        else:
                            res_list = []
                        api_ok = data.get("success") in (True, 1, "1")
                        if not api_ok:
                            top_keys = list(data.keys())[:15] if isinstance(data, dict) else []
                            logger.warning(
                                "BetsAPI events/upcoming: success=%s results_type=%s count=%s message=%s keys=%s",
                                data.get("success"),
                                type(results_raw).__name__ if results_raw is not None else "NoneType",
                                len(res_list),
                                data.get("message") or data.get("error") or "",
                                top_keys,
                            )
                            break
                        if not res_list:
                            break
                        for e in res_list:
                            if isinstance(e, dict):
                                e["_source"] = "upcoming"
                                eid_key = str(e.get("id"))
                                if eid_key:
                                    events_by_id[eid_key] = e
                        logger.info(
                            "BetsAPI events/upcoming: page=%s sport_id=%s count=%s total_so_far=%s",
                            page,
                            sid,
                            len(res_list),
                            len(events_by_id),
                        )
                        # Следующая страница только если получили полную страницу (обычно 50)
                        pager = data.get("pager")
                        per_page = 50
                        if isinstance(pager, dict) and pager.get("per_page") is not None:
                            try:
                                per_page = int(pager["per_page"]) or 50
                            except (TypeError, ValueError):
                                pass
                        if len(res_list) < per_page:
                            break
                        page += 1
                        await asyncio.sleep(rate_limit_seconds)

                if include_inplay:
                    r2 = await client.get(f"{base}/events/inplay", params=params)
                    if r2.status_code == 429:
                        logger.warning(
                            "BetsAPI rate limit (429) on events/inplay for sport_id=%s", sid
                        )
                        raise BetsApiRateLimitError("events/inplay 429 Too Many Requests")
                    if r2.is_success:
                        data2 = r2.json()
                        if data2.get("success") and isinstance(data2.get("results"), list):
                            for e in data2["results"]:
                                e["_source"] = "inplay"
                                events_by_id[str(e.get("id"))] = e
                    await asyncio.sleep(rate_limit_seconds)

                if include_ended:
                    r3 = await client.get(
                        f"{base}/events/ended",
                        params={**params, "page": 1},
                    )
                    if r3.is_success:
                        data3 = r3.json()
                        if data3.get("success") and isinstance(data3.get("results"), list):
                            for e in data3["results"]:
                                e["_source"] = "ended"
                                events_by_id[str(e.get("id"))] = e
                    await asyncio.sleep(rate_limit_seconds)
        else:
            for e in events_from_lists:
                if isinstance(e, dict) and e.get("id") is not None:
                    events_by_id[str(e.get("id"))] = dict(e)

        event_ids = list(events_by_id.keys())
        if not event_ids:
            return list(events_by_id.values())

        # Кому запрашивать view: только не завершённые (upcoming + inplay)
        if event_ids_for_view is not None:
            ids_for_view = [eid for eid in event_ids_for_view if eid in events_by_id]
        else:
            ids_for_view = [
                eid for eid in event_ids
                if events_by_id.get(eid, {}).get("_source") != "ended"
            ]
        # Кому запрашивать odds: все inplay + upcoming только если ещё нет в БД
        if event_ids_for_odds is not None:
            ids_for_odds = [eid for eid in event_ids_for_odds if eid in events_by_id]
        else:
            inplay_ids = [
                eid for eid in event_ids
                if events_by_id.get(eid, {}).get("_source") == "inplay"
            ]
            upcoming_ids = [
                eid for eid in event_ids
                if events_by_id.get(eid, {}).get("_source") == "upcoming"
            ]
            ids_for_odds = inplay_ids + [
                eid for eid in upcoming_ids if eid not in upcoming_ids_with_odds
            ]

        # ——— Event view: только для upcoming + inplay ———
        if fetch_event_view and ids_for_view:
            async with httpx.AsyncClient(timeout=60.0) as client2:
                for i in range(0, len(ids_for_view), EVENT_VIEW_BATCH_SIZE):
                    chunk = ids_for_view[i : i + EVENT_VIEW_BATCH_SIZE]
                    view_params = {"token": token, "event_id": ",".join(chunk)}
                    try:
                        rv = await client2.get(f"{BETSAPI_BASE_V1}/event/view", params=view_params)
                        await asyncio.sleep(rate_limit_seconds)
                        if not rv.is_success:
                            continue
                        view_data = rv.json()
                        view_results = view_data.get("results") or {}
                        if isinstance(view_results, dict):
                            for eid, detail in view_results.items():
                                eid_str = str(eid)
                                if isinstance(detail, dict) and eid_str in events_by_id:
                                    for k, v in detail.items():
                                        if events_by_id[eid_str].get(k) is None:
                                            events_by_id[eid_str][k] = v
                    except Exception:
                        continue

        # ——— Event odds: все inplay + upcoming без сохранённых коэффициентов ———
        # Запрашиваем все доступные рынки для НТ (1–25): 92_1–92_3 стандартные; 92_4+ — тоталы/форы по сетам 1–7, инд. тоталы (по тарифу BetsAPI)
        odds_market_param = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25"
        if fetch_event_odds and ids_for_odds:
            async with httpx.AsyncClient(timeout=60.0) as client3:
                for eid in ids_for_odds:
                    try:
                        ro = await client3.get(
                            f"{BETSAPI_BASE_V2}/event/odds",
                            params={"token": token, "event_id": eid, "odds_market": odds_market_param},
                        )
                        await asyncio.sleep(rate_limit_seconds)
                        if not ro.is_success:
                            continue
                        data = ro.json()
                        bookmakers = _normalize_odds_response(data)
                        if bookmakers and eid in events_by_id:
                            events_by_id[eid]["bookmakers"] = bookmakers
                            results = data.get("results")
                            if isinstance(results, dict) and results.get("stats") is not None:
                                events_by_id[eid]["odds_stats"] = results["stats"]
                    except Exception:
                        continue

        return list(events_by_id.values())

    async def fetch_ended_by_day(
        self,
        day_yyyymmdd: str,
        page: int = 1,
        sport_id: int | None = None,
        *,
        rate_limit_seconds: float = 1.0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """GET /v3/events/ended по дню и странице. day_yyyymmdd = YYYYMMDD (min 20160901)."""
        if not settings.betsapi_token:
            return [], None
        sid = sport_id if sport_id is not None else getattr(
            settings, "betsapi_table_tennis_sport_id", TABLE_TENNIS_SPORT_ID
        )
        params: dict[str, Any] = {
            "sport_id": sid,
            "token": settings.betsapi_token,
            "day": day_yyyymmdd,
            "page": page,
        }
        base = self.BASE_URL
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(f"{base}/events/ended", params=params)
            await asyncio.sleep(rate_limit_seconds)
            if not r.is_success:
                if r.status_code == 429:
                    raise BetsApiRateLimitError(f"BetsAPI 429: {r.text[:200]}")
                raise BetsapiEndedRequestError(f"BetsAPI events/ended HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if not data.get("success"):
                raise BetsapiEndedRequestError(f"BetsAPI events/ended success=false: {str(data.get('error', data))[:200]}")
            results = data.get("results")
            if not isinstance(results, list):
                raise BetsapiEndedRequestError(f"BetsAPI events/ended results not list: {type(results).__name__}")
            for e in results:
                e["_source"] = "ended"
            return results, data.get("pager")
