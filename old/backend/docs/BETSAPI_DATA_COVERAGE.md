# BetsAPI: что приходит в запросах и что мы храним

По каждому запросу — какие поля приходят, что мы записываем в БД и что **не** храним (и можно ли добавить).

---

## 1. GET /v3/events/upcoming и GET /v3/events/inplay

**Что приходит в каждом элементе `results`:**

| Поле API        | Тип    | Описание |
|-----------------|--------|----------|
| `id`            | int/str| ID события |
| `sport_id`      | int    | ID вида спорта (92 = НТ) |
| `time`          | unix   | Время начала |
| `time_status`   | str    | "0"=линия, "1"=лайв, "3"/"100"=завершён |
| `league`        | dict   | `id`, `name`, `cc` |
| `home`          | dict   | `id`, `name`, `image_id`, `cc` |
| `away`          | dict   | то же |
| `ss`            | str/null | Счёт по сетам (строка) |
| `scores`        | dict   | Только inplay: "1"→{home, away}, "2"→... |
| `status`        | str    | Иногда: "ended", "closed", "finished" |
| `bet365_id`     | —      | В inplay иногда есть |
| `pager`         | —      | На уровне ответа, не в элементе |

**Что мы храним:**

| Поле API   | Куда пишем |
|------------|------------|
| `id`       | `Match.provider_match_id` |
| `time`     | `Match.start_time` |
| `league.id`, `league.name`, `league.cc` | `League` (get_or_create), `Match.league_id` |
| `home.id`, `home.name` | `Player` (get_or_create), `Match.home_player_id` |
| `away.id`, `away.name` | `Player`, `Match.away_player_id` |
| `home.image_id`, `away.image_id` | `Player.image_id` |
| `home.cc`, `away.cc` | `Player.country` |
| `bet365_id` | `Match.bet365_id` |
| `time_status` + `status` | Определение завершения → `Match.status` (LIVE/FINISHED) |
| `ss`, `scores` | Парсим → `MatchScore` (set_number, home_score, away_score) |

**Что не храним:**

| Поле       | Примечание |
|------------|------------|
| `sport_id` | Всегда 92 у нас, не нужно. |

---

## 2. GET /v1/event/view?event_id=id1,id2,...

**Что приходит:** объект события как в списках **плюс**:

| Поле API   | Описание |
|------------|----------|
| `timeline` | Таймлайн события |
| `extra`    | bestofsets, stadium_data и т.д. |
| `confirmed_at` | Время подтверждения |
| `score`    | Строка счёта (дублирует/дополняет ss) |
| `timer`    | Таймер матча (лайв) |

**Что мы делаем:** мержим в событие из списка (коллектор). В нормалайзере пишем в Match:

| Поле view  | Куда пишем |
|------------|------------|
| `extra`    | `Match.extra` (JSONB) |
| `extra.bestofsets` | Парсим → `Match.sets_to_win` (3→BO3→2, 5→BO5→3, 7→BO7→4) |
| `timeline` | `Match.timeline` (JSONB) — для аналитики |
| `timer`    | `Match.current_timer` — текущая минута/секунда в сете (лайв) |
| `confirmed_at` | `Match.confirmed_at` (datetime) |
| При первом inplay со счётом | `Match.started_at` |
| При завершении матча | `Match.finished_at` |

Итого: **формат матча (BO3/BO5)** из `extra.bestofsets`, **таймер**, **timeline**, **extra**, **confirmed_at**, **started_at**, **finished_at** — всё храним и отображаем (во сколько начался/закончился матч; по sets_to_win видно, до скольких сетов играют).

---

## 3. GET /v4/bet365/prematch?FI=bet365_id

**Источник bet365_id:** из ответа `GET /v1/event/view` (поле `bet365_id` по каждому событию). Коэффициенты запрашиваем **только по событиям, у которых есть bet365_id**.

**Что приходит:**

- `results.markets` — список рынков (name/id, outcomes с name/NA, price/OD). Формат может использовать сокращения BetsAPI (MG, MA, PA и т.д.). Парсер `_parse_v4_prematch_odds` приводит к формату `[ { name: "b365", markets: [ { name, outcomes: [ { name, price } ] } ] } ]` для нормалайзера.

**Что мы делаем в коллекторе:** для каждого матча из `ids_for_odds` берём `bet365_id` из уже загруженного event/view; если есть — один запрос `GET /v4/bet365/prematch?FI=bet365_id`. Результат парсим и передаём в нормалайзер как один снимок (без истории по времени, в отличие от прежнего v2).

**Что пишем в БД:**

- Один снимок по каждому рынку → записи `OddsSnapshot` с `phase`=line или live. Поля: `match_id`, `bookmaker`="b365", `market` (из name/id рынка, напр. 1_1, 92_1), `selection`, `odds`, `implied_probability`, `phase`. Поле **Match.odds_stats** больше не обновляется (в v4 prematch нет аналога results.stats).

**Итог по коэффициентам:**

- **Сохраняем:** один снимок прематч-коэффициентов по рынкам из v4; рынки 1_1 (победитель матча), 92_1, 92_2, 92_3 и др. при наличии в ответе.
- **Не используем:** запросы v2/event/odds отключены (данных по НТ в v2 больше нет).

**Линия без коэффициентов:** если у события нет `bet365_id` в view или v4 prematch возвращает пустой ответ, матч остаётся без line-кф (статус **pending_odds** и не попадает в `/matches/upcoming`). Нужен **ENABLE_SCHEDULED_COLLECTORS=true**, чтобы задача линии запускалась по расписанию.

---

## Онлайн последовательность (line/live/odds)

**Важно:** задача линии (`fetch-betsapi-line`) запускается по расписанию **только при `ENABLE_SCHEDULED_COLLECTORS=true`** в `.env`. Если флаг выключен, коэффициенты по линии **не запрашиваются** — в разделе «Линия» матчи будут без кф. Запросы к BetsAPI делаются корректно (GET /v4/bet365/prematch по матчам с bet365_id без line-кф в БД); проблема только в том, что при выключенном расписании задача не выполняется.

Актуальная схема — **единый пайплайн** (данные получаем один раз и используем везде):

1. **Линия (`mode=line`)** — интервал `prematch_poll_interval_seconds` (по умолчанию 300 сек):
   - `GET /v3/events/upcoming`
   - `GET /v1/event/view` по всем id из upcoming
   - `GET /v4/bet365/prematch` **только** по матчам с bet365_id, у которых в БД ещё нет line-коэффициентов (лимит `betsapi_line_max_odds_requests_per_run`)
   - Нормализация и запись в БД
   - **В режиме line в normalizer не передаём `current_event_ids`** — логика «пропал из inplay» выполняется только в live/full, иначе все LIVE-матчи ошибочно помечались бы как пропавшие
   - Коэффициенты пишем до перехода матча в лайв; после перехода в лайв line-кф не обновляем

2. **Лайв (`mode=live`)** — интервал `live_poll_interval_seconds` (по умолчанию 8 сек):
   - `GET /v3/events/inplay`
   - `GET /v1/event/view` по всем inplay (счёт, сеты, таймер)
   - `GET /v4/bet365/prematch` **только один раз** на старте матча (по матчам с bet365_id, у которых ещё нет `live_odds_fixed_at`); после записи кф выставляется `Match.live_odds_fixed_at`, дальше кф не запрашиваем
   - Обновляем только ход матча (счёт, сеты), коэффициенты в лайве не обновляем
   - Нормализация, помечаем «пропавшие» матчи для повторных запросов (`mark_disappeared_matches`)

3. **Пропал из лайва без результата** (`run_disappeared_retry`):
   - Матч был LIVE, исчез из inplay, результата нет → выставляется `next_disappeared_retry_at` (первая попытка через 15 мин)
   - Повторные запросы `GET /v1/event/view`: 1-й раз через 15 мин, 2-й через 1 ч, 3-й через 2 ч (`disappeared_retry_delays_seconds`, не более `disappeared_retry_max_attempts`)

4. **Защита от наложения циклов**:
   - Для line/full используется `pg_try_advisory_xact_lock` на время fetch; для live блокировка не используется
   - При 429 от BetsAPI цикл пропускается, статусы не меняем

5. **Архив (`ended`)**:
   - Авто: раз в `betsapi_history_auto_interval_seconds` (по умолчанию 7200 = 2 ч) за **текущий и предыдущий день** (`betsapi_history_auto_days=2`)
   - Ручная загрузка: `POST /api/v1/matches/load-history` — любой диапазон дней

6. **Догрузка результатов при сбоях** (`backfill_missing_results`):
   - Матчи без результата, по которым пора сделать попытку (2 ч, 7 ч, 24 ч от начала) — до 3 попыток на матч
   - Запрос только `event/view` по одному матчу; в normalizer передаём `current_event_ids=None`, чтобы не помечать остальные LIVE как пропавшие

---

## 4. Сводка по запросам и полям

| Запрос        | Что приходит (главное)           | Что храним                         | Что не храним |
|---------------|-----------------------------------|------------------------------------|----------------|
| **upcoming**  | id, time, time_status, league, home, away, ss | Match, League, Player (вкл. image_id, country), start_time, provider_match_id, bet365_id | sport_id |
| **inplay**    | то же + scores, status, bet365_id | + MatchScore, Match.status, MatchResult, started_at, finished_at | — |
| **event/view**| + timeline, extra, timer, confirmed_at | Match.timeline, Match.extra, Match.current_timer, Match.confirmed_at, Match.sets_to_win из extra.bestofsets | — |
| **bet365/prematch (v4)** | results.markets[] (name, outcomes) | Один снимок → OddsSnapshot (market, selection, odds, phase=line|live) | — |

---

## 5. Отображение на фронте

- **Во сколько начался матч:** `Match.started_at` (выставляется при первом inplay со счётом).
- **Во сколько закончился:** `Match.finished_at` или `MatchResult.finished_at`.
- **BO3/BO5:** `Match.sets_to_win` (2 = до 2 сетов = BO3, 3 = BO5) — из `extra.bestofsets` в event/view. Встречаются также матчи до 7 сетов (BO7).
- **Таймлайн:** `Match.timeline` — для аналитики.
- **Текущий таймер сета:** `Match.current_timer`.
- **Тоталы и гандикап:** в `OddsSnapshot` поле `line_value` (линия тотала или гандикапа); для рынка 92_3 исходы `selection` = "over" / "under".

**Какие рынки бывают на сайте букмекера (и чего может не быть в API):**  
На сайте bet365 для НТ есть те же рынки, что отдаёт BetsAPI. GET /v4/bet365/prematch возвращает доступные рынки по событию (часто 1_1 = победитель матча, 92_1, 92_2, 92_3 и др. при наличии в тарифе).

**Рынки (одинаковые в bet365 и BetsAPI), подписи на фронте (MARKET_LABELS):**

| Ключ (API / фронт) | Название (bet365 / BetsAPI) |
|--------------------|-----------------------------|
| 92_1, winner, win | Match Winner 2-Way |
| 92_2, handicap | Asian Handicap |
| 92_3, total | Over/Under |
| 92_4 | Total Points (Match) |
| 92_5 | Total Points (1st Set) |
| 92_6 | Total Points (2nd Set) |
| 92_7 | Asian Handicap (1st Set) |
| 92_8 | Asian Handicap (2nd Set) |
| 92_9 | Home Total Points |
| 92_10 | Home Total Points (1st Set) |
| 92_11 | Home Total Points (2nd Set) |
| 92_12 | Total Points (3rd Set) |
| 92_13 | Total Points (4th Set) |
| 92_14 | Total Points (5th Set) |
| 92_15 | Total Points (6th Set) |
| 92_16 | Total Points (7th Set) |
| 92_17 | Asian Handicap (3rd Set) |
| 92_18 | Asian Handicap (4th Set) |
| 92_19 | Asian Handicap (5th Set) |
| 92_20 | Asian Handicap (6th Set) |
| 92_21 | Asian Handicap (7th Set) |
| 92_22+ | Additional Market |

**Примечание:** матчи могут играться до 3, 5 или 7 сетов (BO3, BO5, BO7). Рынки по 3–7-му сетам (тотал очков и фора/победа в сете) в API могут идти под разными id (92_12–92_21 или иначе); точное соответствие уточняйте в документации BetsAPI. На фронте для неизвестных 92_X выводится «Рынок 92_X».

Скрипт проверки ответов API: `PYTHONPATH=backend python3 backend/scripts/inspect_betsapi_responses.py`.
Верификация парсинга коэффициентов (мок ответа API → формат для нормалайзера): `PYTHONPATH=backend python3 backend/scripts/verify_odds_parsing.py`.

---

## 6. Ручная загрузка архива (история с 2016)

**Эндпоинт:** `POST /api/v1/matches/load-history`  
**Параметры (body):** `day_from` (YYYYMMDD, по умолчанию 20160901), `day_to` (по умолчанию сегодня), `delay_seconds` (пауза между запросами, по умолчанию 7).

**Что делаем:** в фоне (Celery) по дням от `day_from` до `day_to` запрашиваем `GET /v3/events/ended?day=YYYYMMDD&page=1,2,...` (до 100 страниц на день). Между запросами — пауза `delay_seconds` секунд. Каждый ответ нормализуем и пишем в БД.

**Куда пишем:** те же таблицы — **Match**, **MatchScore**, **MatchResult**. Поля из ответа ended те же: id → provider_match_id, time → start_time, league/home/away → League/Player, ss/scores → MatchScore, итог → MatchResult.

**Дубликаты:** если матч с таким `provider_match_id` уже есть в БД — событие пропускаем (не создаём вторую запись матча).

**Прогресс по дням:** в таблице **betsapi_archive_progress** сохраняются дни, за которые все страницы обработаны (когда API вернул пустой ответ — переходим к следующему дню). При следующем запуске эти дни пропускаются. Лимита по числу страниц в день нет: идём по страницам 1, 2, 3, … до первой пустой страницы. Статус: `GET /api/v1/matches/load-history/status?day_from=20160901&day_to=...` — в ответе `completed` (дни, все страницы обработаны) и `not_completed` (ещё нет).

**Примеры запросов:**

```bash
# Запустить/продолжить загрузку архива (с 1 сентября 2016 по сегодня).
# resume_from_progress=true: НЕ сбрасывает уже загруженные дни, продолжает с места остановки.
# delay_seconds=1 (или 0) для максимально быстрой загрузки.
# Backpressure для normalize (чтобы очередь не росла бесконечно при скачках страниц):
# BETSAPI_HISTORY_NORMALIZE_QUEUE_MAX_DEPTH=10000
# BETSAPI_HISTORY_BACKPRESSURE_SLEEP_SECONDS=0.5
curl -X POST http://localhost:11001/api/v1/matches/load-history \
  -H "Content-Type: application/json" \
  -d '{"day_from": "20240401", "day_to": null, "delay_seconds": 10, "resume_from_progress": true}'

# Ответ: {"task_id": "abc-123-...", "message": "Задача загрузки архива запущена..."}

# Загрузить только за указанный период
curl -X POST http://localhost:11001/api/v1/matches/load-history \
  -H "Content-Type: application/json" \
  -d '{"day_from": "20240101", "day_to": "20260305", "delay_seconds": 2}'

# Узнать, за какие дни всё уже обработано, за какие — ещё нет
curl "http://localhost:11001/api/v1/matches/load-history/status?day_from=20160901&day_to=20251231"

# Ответ: {"day_from": "...", "day_to": "...", "completed": [...], "not_completed": [...], "single_page_days": [...]}
# single_page_days — дни, завершённые с last_processed_page=1 (кандидаты на пересборку).

# Пересобрать архив за недостающие дни и за дни с одной страницей (сброс прогресса + запуск загрузки):
# 1) Сбросить прогресс по одностраничным дням в диапазоне
curl -X POST http://localhost:11001/api/v1/matches/load-history/reset-progress \
  -H "Content-Type: application/json" \
  -d '{"day_from": "20200101", "day_to": "20251231", "reset_single_page_only": true}'

# 2) Запустить загрузку (подхватятся not_completed и сброшенные дни)
curl -X POST http://localhost:11001/api/v1/matches/load-history \
  -H "Content-Type: application/json" \
  -d '{"day_from": "20200101", "day_to": "20251231", "delay_seconds": 1, "resume_from_progress": true}'

# Или одной командой (скрипт сам вызовет статус, сброс и load-history):
# cd backend && uv run python scripts/rebuild_archive_missing_and_single_page.py 20200101 20251231
```

**Если загрузка не стартует:** задача выполняется в Celery (очередь `history`). Перезапустите history-воркеры: `docker compose restart celery_history celery_history_2`. В логах при запуске задачи должно появиться: `load_betsapi_history started: day_from=...`. Если видите `BETSAPI_TOKEN not set` — задайте токен в окружении воркера (тот же `.env`, что и у backend).

---

## 7. Проверка ответа API поставщика за конкретный день

В задаче загрузки архива в прогресс всегда пишется **текущий** `day` из цикла по дням — запись идёт в тот день, который обрабатывается.

**Прямой запрос к BetsAPI за день (чтобы посмотреть, что вернул поставщик):**

- **URL:** `GET https://api.b365api.com/v3/events/ended`
- **Параметры:** `token`, `sport_id` (92 = наст. теннис), `day` (YYYYMMDD), `page` (1, 2, …)

**Пример (токен из `.env`, переменная BETSAPI_TOKEN):**

```bash
export BETSAPI_TOKEN="ваш_токен_из_env"

# За 1 января 2025, страница 1
curl -s "https://api.b365api.com/v3/events/ended?token=${BETSAPI_TOKEN}&sport_id=92&day=20250101&page=1" | jq .

# Страница 2
curl -s "https://api.b365api.com/v3/events/ended?token=${BETSAPI_TOKEN}&sport_id=92&day=20250101&page=2" | jq .
```

В ответе: `success: true` — запрос принят; `results` — массив событий (пустой `[]` = страница пустая, день по этой странице закончен). Если первая же страница по дню даёт пустой `results`, день сразу помечается завершённым и появляется в `completed` в статусе.

---

## 8. Почему не записались архивные матчи

Частые причины:

1. **Не применена миграция 011** — в таблице `betsapi_archive_progress` должна быть колонка `last_processed_page`. Без неё задача загрузки архива падает на первом же SELECT. Выполните: `docker compose exec backend uv run alembic upgrade head`, затем `docker compose restart celery_worker`.
2. **Задача не выполняется** — в логах Celery должно быть `load_betsapi_history started: day_from=...`. Если нет — проверьте очередь `collect`.
3. **API по дню возвращает пустой список** — тогда матчей в БД не будет, день попадёт в `completed`.

**Скрипт диагностики:** `docker compose exec backend uv run python scripts/diagnose_archive_load.py 20250101` — покажет наличие колонки, ответ API за день и записи в БД.