"""BetsAPI collector — table tennis: списки событий + детали (event/view) + коэффициенты (v4 prematch).

Запросы к API (лимит 3600/час ≈ 1 запрос/сек):
- Списки (v3): upcoming, inplay, ended — 3 запроса.
- Детали (v1): event/view — до 10 id за запрос, только для upcoming+inplay (не для ended).
- Коэффициенты (v4): bet365/prematch — только по событиям с bet365_id (из view); для inplay и upcoming без line-кф.

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
BETSAPI_BASE_V4 = "https://api.b365api.com/v4"
EVENT_VIEW_BATCH_SIZE = 10


logger = logging.getLogger(__name__)


class BetsApiRateLimitError(Exception):
    """Сигнализирует о том, что BetsAPI вернуло 429 Too Many Requests."""

    pass


class BetsapiEndedRequestError(Exception):
    """Ошибка запроса GET /v3/events/ended (HTTP или success=false). Не трактовать как «пустая страница»."""

    pass


def _parse_v4_prematch_odds(v4_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Парсит ответ GET /v4/bet365/prematch в формат [ { name, markets: [ { name, outcomes } ] } ] для normalizer.
    Поддерживает структуры: results.markets[].{name,outcomes}, MG/MA/PA (сокращения BetsAPI)."""
    if not isinstance(v4_data, dict):
        return []
    results = v4_data.get("results") or v4_data
    if isinstance(results, dict) and "markets" in results:
        markets_raw = results.get("markets")
    else:
        markets_raw = results.get("markets") if isinstance(results, dict) else None
    if not isinstance(markets_raw, list) or not markets_raw:
        return []
    markets_out: list[dict[str, Any]] = []
    for m in markets_raw:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or m.get("id") or m.get("market") or "winner")
        outcomes_raw = m.get("outcomes") or m.get("choices") or m.get("participants") or []
        if isinstance(outcomes_raw, dict):
            outcomes_raw = list(outcomes_raw.values())
        outcomes = []
        for o in outcomes_raw if isinstance(outcomes_raw, list) else []:
            if not isinstance(o, dict):
                continue
            name = o.get("name") or o.get("NA") or o.get("selection") or o.get("id")
            price = o.get("price") or o.get("odd") or o.get("OD")
            if name is None or price is None:
                continue
            try:
                float(price)
            except (TypeError, ValueError):
                continue
            outcomes.append({"name": str(name).lower() if isinstance(name, str) else str(name), "price": str(price)})
        if outcomes:
            markets_out.append({"name": m_name, "outcomes": outcomes})
    if markets_out:
        return [{"name": "b365", "markets": markets_out}]
    return []


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

        # ——— Event odds: v4 bet365/prematch только по событиям с bet365_id ———
        if fetch_event_odds and ids_for_odds:
            skipped_no_bet365 = 0
            skipped_v4_empty = 0
            async with httpx.AsyncClient(timeout=60.0) as client3:
                for eid in ids_for_odds:
                    if eid not in events_by_id:
                        continue
                    ev = events_by_id[eid]
                    # bet365_id может прийти в списке (upcoming/inplay) или в event/view
                    bet365_id = (ev.get("bet365_id") or "").strip()
                    if not bet365_id:
                        skipped_no_bet365 += 1
                        continue
                    try:
                        rp = await client3.get(
                            f"{BETSAPI_BASE_V4}/bet365/prematch",
                            params={"token": token, "FI": bet365_id},
                        )
                        await asyncio.sleep(rate_limit_seconds)
                        if not rp.is_success:
                            continue
                        prematch = rp.json()
                        bookmakers = _parse_v4_prematch_odds(prematch)
                        if bookmakers:
                            events_by_id[eid]["bookmakers"] = bookmakers
                        else:
                            skipped_v4_empty += 1
                    except Exception:
                        continue
            if skipped_no_bet365 or skipped_v4_empty:
                logger.info(
                    "BetsAPI odds: requested %s, skipped no bet365_id=%s, v4 prematch empty=%s",
                    len(ids_for_odds),
                    skipped_no_bet365,
                    skipped_v4_empty,
                )

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
