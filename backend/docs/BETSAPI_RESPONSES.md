# BetsAPI — что приходит в каждом запросе

Скрипт проверки: из корня проекта:
```bash
PYTHONPATH=backend python3 backend/scripts/inspect_betsapi_responses.py
```
Требуется `.env` с `BETSAPI_TOKEN`.

---

## 1) GET /v3/events/upcoming

- **Верхний уровень:** `success`, `pager`, `results`
- **results:** список событий (до 50).
- **Элемент:** `id`, `sport_id`, `time` (unix), `time_status` (`"0"` = не начат), `league` (id, name, cc), `home` / `away` (id, name, image_id, cc), `ss` (счёт по сетам, часто null в линии).

---

## 2) GET /v3/events/inplay

- **Верхний уровень:** `success`, `pager`, `results`
- **results:** список событий в лайве (и недавно завершённых).
- **Элемент:** те же поля, что и в upcoming, плюс:
  - **`time_status`** — статус матча:
    - **`"0"`** — не начат (линия) — в inplay обычно не приходит, такие только в upcoming
    - **`"1"`** — в игре (лайв)
    - **`"3"`** или **`"100"`** — завершён
  - **`status`** — иногда есть отдельно: `"ended"`, `"closed"`, `"finished"` для завершённых
  - `ss` (счёт), `scores` (dict по сетам), `bet365_id`

Итого: **лайв/завершён/линия** определяются по **`time_status`** (и при необходимости по `status`). Линия приходит только в **upcoming**; в **inplay** — только лайв (`time_status=1`) и только что завершённые (`time_status=3` или `100`).

---

## 3) GET /v1/event/view?event_id=id1,id2,...

- **Верхний уровень:** `success`, `results`
- **results:** либо **list** (при одном event_id), либо **dict** (event_id → объект).
- **Объект события:** как в списках + `timeline`, `extra` (bestofsets, stadium_data и т.д.), `confirmed_at`. Дополняет поля из списка (ss, score, timer и т.д.).

---

## 4) GET /v2/event/odds?event_id=id

- **Верхний уровень:** `success`, `results`
- **results:** `{ "stats": {...}, "odds": {...} }`
- **results.stats:** служебное (matching_dir, odds_update по рынкам).
- **results.odds:** объект **рынок → список снимков**:
  - ключи для наст. тенниса: `92_1`, `92_2`, `92_3` (рынки);
  - значение — **list** элементов вида:
    - `id`, `home_od`, `away_od`, `ss` (счёт в момент котировки), `add_time` (unix).

Формат v2 для table tennis **не** в виде bookmakers/markets/outcomes: это история котировок по рынкам (home_od/away_od во времени). Текущий коллектор ожидает формат с `bookmakers`; для v2 по НТ нужно отдельно маппить `results.odds` → наш формат (например, последний снимок по каждому рынку как один «букмекер» или писать все снимки с phase=live).

---

## Итог для нашего кода

| Запрос            | Что используем |
|-------------------|----------------|
| upcoming          | id, time, time_status, league, home, away, ss |
| inplay            | то же + ss, scores, time_status=1 |
| event/view        | доп. поля (ss, extra, timer) для мержа в событие |
| event/odds (v2 НТ)| results.odds = рынки 92_1/92_2/92_3, списки {id, home_od, away_od, ss, add_time} — нужен маппинг в OddsSnapshot |
