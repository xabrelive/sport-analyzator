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
- **Объект события:** как в списках + `timeline`, `extra` (bestofsets, stadium_data и т.д.), `confirmed_at`, **`bet365_id`**. Дополняет поля из списка (ss, score, timer и т.д.).

**bet365_id** нужен для запроса коэффициентов: без него v4 prematch не вызвать.

---

## 4) GET /v4/bet365/prematch?FI=bet365_id

- **Параметр:** `FI` = bet365_id из ответа event/view.
- **Верхний уровень:** `success`, `results`
- **results:** объект с полем **`markets`** — список рынков.
- **Рынок:** `name` или `id` (напр. 1_1, 92_1), **`outcomes`** или `choices` — список исходов с полями `name`/`NA`, `price`/`OD`.

Мы используем только этот запрос для коэффициентов (линия и один раз на старте лайва). Запросы v2/event/odds отключены.

---

## Итог для нашего кода

| Запрос            | Что используем |
|-------------------|----------------|
| upcoming          | id, time, time_status, league, home, away, ss |
| inplay            | то же + ss, scores, time_status=1 |
| event/view        | доп. поля (ss, extra, timer, **bet365_id**) для мержа в событие |
| bet365/prematch (v4) | results.markets[] (name, outcomes) → OddsSnapshot |
