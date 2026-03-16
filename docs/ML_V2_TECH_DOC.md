# ML v2 (ClickHouse) - полная техническая документация

Документ описывает текущую production-реализацию ML v2 в проекте:

- откуда берутся данные;
- как устроена ClickHouse ML-база;
- какие фичи считаются и как;
- как запускается обучение на GPU;
- как обновляются прогнозы после retrain;
- какие ручки/скрипты использовать для контроля;
- как работает защита от позиционного bias (P1/P2 symmetry guard).

---

## 1) Архитектура ML v2

Текущий контур состоит из 4 ключевых процессов:

1. `ml_sync` (отдельный контейнер)  
   Запускает `python -m app.ml.worker_cli sync-loop`. **Все ML-таблицы заполняются автоматически каждые 10 минут** (интервал `ML_SYNC_INTERVAL_SEC=600`):
   - sync finished матчей из main PostgreSQL в ClickHouse (`ml.matches`, `ml.match_sets`, `ml.player_match_stats`, `ml.player_elo_history`);
   - backfill `ml.player_daily_stats`;
   - rebuild фичей в `ml.match_features` (incremental, missing, refresh при смене схемы);
   - постановку задачи `retrain` в очередь при достижении порога по времени/объему.

2. `ml_worker` (GPU контейнер, очередь задач)  
   Запускает `python -m app.ml.worker_cli run`, опрашивает очередь каждые 5 секунд и выполняет задачи:
   - `sync`, `backfill`, `retrain`, `full_rebuild`, и пр.
   - retrain для `v2` выполняется только здесь (GPU-only).

3. `tt_workers`  
   Формирует прогнозы. Для `ML_ENGINE=v2` использует `app.ml_v2.inference.predict_for_upcoming_v2`.

4. `backend` (API/админка)  
   Дает ручки управления/мониторинга (`/api/v1/admin/ml/*`, `/api/v1/admin/ml/v2/status`).

---

## 2) Конфигурация (основные переменные)

Ключевые поля в `backend/app/config.py`:

- `ml_engine` (по умолчанию `v2`)
- `ml_use_gpu` (по умолчанию `true`)
- `ml_model_dir` (по умолчанию `/tmp/pingwin_ml_models`)
- `ml_sync_interval_sec` (по умолчанию 600, 10 мин)
- `ml_retrain_interval_sec` (по умолчанию 1800, 30 мин)
- `ml_retrain_min_new_matches` (порог новых данных для retrain)
- `ml_train_year_end`, `ml_val_year_start`, `ml_val_year_end`
- `clickhouse_host`, `clickhouse_port`, `clickhouse_user`, `clickhouse_password`, `clickhouse_database`

В Docker Compose `v2` использует ClickHouse на портах:

- HTTP: `11003`
- TCP/native: `11004`

---

## 3) Поток данных: от main DB до ML dataset

### 3.1 Источник данных (main PostgreSQL)

Базовый источник синка finished матчей: `table_tennis_line_events`.

Фактически используются поля:

- идентификаторы: `id`, `league_id`, `home_id`, `away_id`;
- имена: `league_name`, `home_name`, `away_name`;
- время: `starts_at`, `finished_at`;
- коэффициенты: `odds_1`, `odds_2`;
- результат: `live_sets_score`, `live_score`;
- фильтр: `status = finished`.

**Идентификация игрока:** везде используется только **player ID** (`home_id`/`away_id` в событии → `player1_id`/`player2_id` в `ml.matches`, `player_id` в `ml.player_elo_history` и `ml.player_match_stats`). Имя игрока не используется для сопоставления; один и тот же игрок в разных матчах может быть на позиции P1 или P2 — это не влияет на его рейтинг и историю, т.к. они привязаны к ID.

### 3.2 Синк в ClickHouse

`backend/app/ml_v2/sync.py` (`sync_finished_to_ch_once`) делает:

1. читает finished события из main DB курсорно;
2. парсит сетовый счет (`live_sets_score`, `live_score`);
3. пишет в CH: `ml.players`, `ml.leagues`, `ml.matches`, `ml.match_sets`, `ml.player_match_stats`;
4. **рейтинг (Elo)** не считается в цикле — после вставки матчей вызывается **`recompute_elo_from_matches()`**: читаются все строки из `ml.matches` в порядке `ORDER BY start_time`, рейтинг пересчитывается с первого матча (K=32, старт 1500), затем `TRUNCATE` + `INSERT` в `ml.player_elo_history`. Один источник истины, без привязки к odds;
5. сохраняет cursor `sync_finished_cursor_v2`.

Ручной пересчёт рейтинга: `POST /api/v1/admin/ml/recompute-elo` (пересчёт с первого матча по текущему состоянию `ml.matches`).

---

## 4) Структура ClickHouse ML базы (v2)

DDL определен в `backend/app/ml_v2/schema.py`.

### Базовые таблицы

- `ml.players` - игроки (id/name)
- `ml.leagues` - лиги
- `ml.matches` - матч (время, лига, P1/P2, финальный счет, odds)
- `ml.match_sets` - посетовый счет

### История и агрегаты

- `ml.player_elo_history` - Elo до/после матча
- `ml.player_match_stats` - пер-матч статистика игрока
- `ml.player_daily_stats` - ежедневные агрегаты

### ML dataset и артефакты

- `ml.match_features` - обучающая витрина + target
- `ml.model_runs`, `ml.model_metrics` - метрики прогонов
- `ml.predictions` - хранение предиктов (если используется)
- `ml.job_state` - job cursors/state

---

## 5) Feature engineering (v2)

Код: `backend/app/ml_v2/features.py`.

### Главный принцип: anti-leakage

Для матча с временем `start_time` используются только данные **строго до** `start_time` (`match_time < cutoff`). Текущий матч никогда не входит в расчёт фичей — это эквивалент `shift(1)` в rolling.

**Порядок матчей (без перемешивания внутри дня):** матчи загружаются и обрабатываются в **ORDER BY start_time ASC, match_id ASC**; после загрузки список матчей явно сортируется по `(start_time, match_id)`. История по игрокам загружается с **ORDER BY player_id ASC, match_time ASC, match_id ASC** и после построения дополнительно сортируется по `(match_time, match_id)` внутри каждого игрока. Так матч 11:00 не влияет на фичи матча 10:00.

Пайплайн на каждый матч:

1. выбираем историю игроков строго до `start_time` (в `_compute_player_agg`: `match_time < cutoff` и при rebuild дополнительно `exclude_match_id=mid`, чтобы текущий матч никогда не входил в rolling);
2. считаем rolling-агрегаты только по этой истории (winrate_last_10, points_ratio_20 и т.д. — эквивалент `shift(1)` в pandas);
3. строим матчевые признаки (diff/ratio);
4. записываем фичи и только после этого обновляем H2H/league state для следующих матчей.

### Размер feature space

Текущий production-набор: **113 фич** (`FEATURE_COLS_V2`).

### Категории фич (113)

1. **Dynamic player strength (рейтинг игрока во времени)**
   - Рейтинг считается только по результатам матчей (`recompute_elo_from_matches` по `ml.matches`), без привязки к odds.
   - `elo_diff` — разница рейтингов (главная фича силы), `elo_trend_diff`, `elo_trend_30_diff`, `elo_volatility_diff`, `elo_peak_diff`,
   - `elo_drop_10_diff`, `elo_gain_10_diff`, `elo_recent_diff`, `elo_confidence_gap`, `latent_strength_diff`.

2. **Form / rolling quality**
   - `form_diff`, `winrate_*_diff`, `sets_ratio_*_diff`, `points_ratio_*_diff`,
   - **`strength_trend_diff`** — (points_ratio_10 − points_ratio_30)_p1 − (points_ratio_10 − points_ratio_30)_p2: игрок набирает форму или падает; часто даёт +3–5% accuracy.
   - `dominance_diff`, `dominance_last_*_diff`, `recent_improvement_diff`, `temporal_form_diff`.

3. **Fatigue / schedule pressure (time-based rolling)**
   - TT игроки часто играют 20–40 матчей в день; при 6+ матчах за 4–6 ч winrate падает.
   - `fatigue_diff`, `fatigue_ratio`, `fatigue_pressure_diff`, `fatigue_index_diff`,
   - `matches_3h_diff`, **`matches_6h_diff`**, **`matches_12h_diff`**, `matches_24h_diff`, `matches_3d_diff`, `matches_7d_diff`,
   - `sets_24h_diff`, `points_24h_diff`, `minutes_24h_diff`, `rest_hours_diff`, `rest_days_diff`, `long_match_ratio_diff`,
   - `form_x_fatigue_diff`, `momentum_x_rest_diff`.

4. **Momentum / streak**
   - `momentum_today_diff`, `momentum_last3_diff`, `momentum_last5_diff`,
   - `streak_score`, `win_streak_diff`, `loss_streak_diff`.

5. **Style / stability / tempo**
   - `style_clash`, `aggressive_ratio_diff`, `defensive_ratio_diff`,
   - `fast_match_ratio_diff`, `long_rally_ratio_diff`,
   - `std_points_last20_diff`, `std_sets_last20_diff`, `variance_winrate_diff`, `consistency_score_diff`,
   - `avg_sets_per_match_diff`, `avg_points_per_set_diff`, `match_duration_proxy_diff`, `tempo_diff`,
   - `volatility_combo_diff`.

6. **H2H**
   - `h2h_diff`, `h2h_count`, `h2h_winrate`, `h2h_last_result`, `h2h_last3_diff`, `h2h_last5_diff`, `h2h_recent_diff`,
   - `h2h_dominance`, `h2h_x_form`.

7. **Temporal / league context**
   - `hour_strength_diff`, `morning_strength_diff`, `evening_strength_diff`, `weekend_strength_diff`,
   - `league_upset_rate`, `league_strength`, `league_avg_sets`, `league_variance`, `league_match_volume`,
   - `league_id_encoded`, `league_match_count`, `table_bias`,
   - `league_upset_x_margin`, `league_bias_x_margin`.

8. **Betting market and interactions**
   - `market_margin`, `set1_strength_diff`, `comeback_rate_diff`, `reverse_sweep_rate_diff`, `choke_rate_diff`,
   - `elo_x_fatigue`, `experience_diff`, `experience_ratio`, `points_ratio_last_30_diff`, `sets_ratio_last_30_diff`,
   - `p1_exp_bucket`, `p2_exp_bucket`, `experience_bucket_diff`, `experience_mismatch`, `elo_x_experience`.

### Experience buckets (anti-leakage)

Experience признаки считаются только по истории до матча (`matches_played_before_match`). Пороги для 4 моделей (rookie / low / mid / pro):

- bucket 1 (rookie): `<20` матчей
- bucket 2 (low): `20..79`
- bucket 3 (mid): `80..299`
- bucket 4 (pro): `>=300`

Routing при инференсе: `bucket = max(p1_exp_bucket, p2_exp_bucket)`. Инференс **всегда** подгружает bucket-модель (`tt_ml_v2_b{bucket}_*`), если файлы есть; иначе — общая модель. Пост-матчевые значения для этих признаков не используются.

### Что откуда берется

- Elo/strength признаки -> `ml.player_elo_history`
- Rolling form/style/fatigue -> `ml.player_match_stats`
- H2H/league context -> `ml.matches`
- Targets -> `ml.matches` + `ml.match_sets`
- Market context -> `ml.matches.odds_p1/odds_p2`

### Игрок в приоритете: отключение фич линии (ML_V2_DISABLE_MARKET_FEATURES)

Чтобы модель опиралась на **силу/форму игроков**, а не на коэффициент:

- при `ML_V2_DISABLE_MARKET_FEATURES=true` (по умолчанию) фичи `market_prob_p1`, `market_prob_p2`, `market_diff`, `closing_line`, `market_margin` при обучении и инференсе обнуляются (нейтральные значения);
- обучение и предсказание используют только игровые/лиговые признаки; кэф не участвует в решении модели.

---

## 6) Обучение моделей (GPU-only)

Код: `backend/app/ml_v2/trainer.py`.

### Что обучается

Две бинарные модели LightGBM:

1. `tt_ml_v2_match.joblib` -> вероятность победы P1 в матче
2. `tt_ml_v2_set1.joblib` -> вероятность победы P1 в первом сете

Также сохраняется:

- `tt_ml_v2_meta.json` (версия, фичи, размеры сплитов, timestamp)

### Датасет и сплит

1. загрузка `ml.match_features FINAL`;
2. дедуп по `match_id` (берется последняя версия строки);
3. **Баланс p1/p2 (anti-position bias):** для ~50% строк (детерминированно по `hash(match_id)`): инвертируются все фичи `*_diff`, меняются местами `p1_exp_bucket` ↔ `p2_exp_bucket`, `target_match` и `target_set1` инвертируются. **Ratio-фичи** (`fatigue_ratio`, `experience_ratio`, `fatigue_ratio_log`) при swap преобразуются: ratio → 1/ratio, log → −log, чтобы «первый игрок» в строке оставался согласован с target. Так связь «больше elo_diff / momentum_today_diff и т.д. → чаще победа p1» не теряется: знак фичи и target меняются вместе. **Проверка:** `df["target_match"].mean()` до баланса может быть 0.52–0.55; после — ~0.5.
4. **temporal split по годам** (при `ML_V2_SPLIT_BY_YEAR=true`): **train 2016–2023**, **val 2024**, **test 2025+** (если 2025 нет — половина 2024 в test). Без random split, без утечки будущего. Fallback: 80% / 10% / 10% по квантилям времени.

### Фичи для обучения (FEATURE_COLS_V2_TRAIN)

В обучение подаются не все 113 фич, а **подмножество без мёртвых и избыточных**:

- **Удалены мёртвые** (константные / почти всегда 0): clock (4), market (5), `fast_match_ratio_diff`, `long_match_ratio_diff`, `long_rally_ratio_diff`, `match_duration_proxy_diff`, `league_upset_x_margin`.
- **Удалены избыточные rolling (multicollinearity):** `winrate_3_diff`, `winrate_5_diff`, `winrate_30_diff`, `points_ratio_last_30_diff`, `sets_ratio_last_30_diff`. Оставлены только окна **10, 20, 50** — иначе winrate_10/20/30/50 коррелируют >0.95, модель путается.

Список: `FEATURE_COLS_V2_TRAIN` в `backend/app/ml_v2/features.py`. Inference использует тот же список (из meta/модели).

### Параметры LightGBM (текущие, под TT)

Общие:

- `objective=binary`, `metric=binary_logloss`
- `learning_rate=0.03`, `num_leaves=128`, `max_depth=-1`
- `min_child_samples=20`, `min_child_weight=1e-3`
- `feature_fraction=0.75`, `bagging_fraction=0.8`, `bagging_freq=5`
- `reg_alpha=0.5`, `reg_lambda=1.5`, `max_bin=255`
- `n_estimators=3000`, `early_stopping_rounds=300`
- `device=cuda` (обязательно для v2 retrain)

**Для target_match** (баланс переобучение/недообучение): больше ёмкости, умеренная регуляризация — val raw_logloss ~0.68, test ~0.676:

- `ml_v2_lgb_num_leaves_match=150`, `ml_v2_lgb_min_child_match=20`
- `ml_v2_lgb_reg_alpha_match=0.3`, `ml_v2_lgb_reg_lambda_match=1.0`
- `ml_v2_lgb_learning_rate=0.02`, `ml_lgb_early_stopping_rounds=500`

**Реалистичный logloss для прематч без лайва:** val/test raw_logloss 0.64–0.68 типичен; 0.50–0.51 достижим в основном при лайв-фичах (счёт сета, очки) или существенно более богатых данных.

Клип фичей: `ml_v2_feature_clip_quantile=0.01` (квантили 0.01/0.99). Опционально: `ml_v2_top_k_features=50` — обучение только на топ-K фичей по |corr| с target_match (меньше шума).

### Факторы, влияющие на logloss

| Фактор | Где задаётся | Влияние |
|--------|--------------|---------|
| **Фичи для обучения** | `FEATURE_COLS_V2_TRAIN` (features.py): все из FEATURE_COLS_V2 минус DEAD_FEATURES и REDUNDANT_ROLLING | Мёртвые/константные фичи ухудшают деревья; избыточные rolling (3,5,30) — мультиколлинеарность |
| **Качество данных** | `ml_v2_train_min_matches_played_before`, `ml_v2_train_require_h2h`, `ml_v2_train_max_league_upset_rate` | Фильтр по опыту и H2H уменьшает шум; chaos leagues исключаются |
| **Сплит** | `ml_v2_split_by_year`: train 2016–2023, val 2024, test 2025+ | Случайный сплит даёт утечку; temporal — честный val |
| **Клип фичей** | `ml_v2_feature_clip_quantile` (0.01 → квантили 0.01/0.99) | Слишком жёсткий клип (0.001/0.999) режет полезный сигнал |
| **Баланс p1/p2** | Внутри trainer: swap ~50% строк по match_id | Без баланса порядок игроков даёт bias, val logloss искажается |
| **Experience weight** | sample_weight = clip((matches_played_before+3)/25, 0.15, 1) | Низкий опыт — меньший вес строки; слишком низкий floor — недообучение |
| **Параметры LGB** | config: num_leaves, min_child_*, reg_alpha, reg_lambda | target_match переобучается быстрее — для него отдельные жёсткие параметры (см. выше) |
| **Калибрация** | Isotonic/Sigmoid по val после обучения | Итоговый logloss в API — после калибрации |
| **Ансамбль с Elo** | `ml_v2_ensemble_elo_weight`: p_final = (1-w)*p_ml + w*p_elo | Финальный logloss в eval/API считается уже с ансамблем |

### Диагностика: почему logloss не падает

Если validation logloss застревает около 0.68–0.69 или у **target_match** best_iteration=5 и val logloss потом растёт:

1. **Переобучение match:** включены отдельные параметры для target_match (меньше листьев, больше min_child, сильнее reg). Проверить в логах: `ML v2 train [target_match] ... num_leaves=64`, `min_child_samples=50`. При необходимости усилить: `ML_V2_LGB_REG_ALPHA_MATCH=1.5`, `ML_V2_LGB_REG_LAMBDA_MATCH=3`.
2. Запустить диагностику данных и фичей:
   - `backend/scripts/ml_v2_diagnose_training_data.py` (через Docker: `docker compose run --rm -v "$(pwd)/backend:/app" backend python3 /app/scripts/ml_v2_diagnose_training_data.py`)
3. Скрипт выводит: баланс таргета, константные/почти константные фичи, корреляцию фичей с таргетом. Сигнал в данных есть (например `elo_diff`, `latent_strength_diff` с corr ~0.24) — если logloss высокий при нормальном best_iteration, причина может быть **недообучение**: уменьшить `min_child_samples` для set1 (для match — наоборот, не уменьшать).
4. Часть фичей при текущих настройках обнулена (market при `ML_V2_DISABLE_MARKET_FEATURES`, clock при `ML_V2_DISABLE_CLOCK_FEATURES`) — они не несут информации, дерево их не использует.
5. **Клип:** при необходимости ослабить обрезку выбросов: `ML_V2_FEATURE_CLIP_QUANTILE=0.005` (ближе к старым 0.001/0.999) или увеличить до 0.02.

### Chaos leagues (фильтр лиг)

Лиги с очень высоким upset rate (>45%) по сути рандом — модель там не учится. В обучение из них матчи не попадают:

- `ML_V2_TRAIN_MAX_LEAGUE_UPSET_RATE=0.45` (по умолчанию): строки с `league_upset_rate > 0.45` исключаются из train. Порог можно ослабить (0.48) или отключить (1.0).

### Experience regimes (4 отдельные модели)

Не одна общая модель, а **4 модели** по уровню опыта игроков (matches_played_before):

| Bucket | Опыт (матчей) | Модель       | Описание              |
|--------|----------------|--------------|------------------------|
| 1      | &lt;20         | model_rookie | Rookie vs rookie, очень шумно |
| 2      | 20–79          | model_low    | Low experience        |
| 3      | 80–299         | model_mid    | Mid experience        |
| 4      | ≥300           | model_pro    | Veteran, предсказуемость     |

**Почему так:** rookie-матчи — хаос; veteran-матчи — предсказуемость. Одна модель не может оптимально обучиться на обоих. На TT-датасетах типично: single model 56–58%, experience split 63–68% и около −0.02 logloss.

**Обучение:** `ML_V2_USE_EXPERIENCE_REGIMES=true` (по умолчанию). После общей модели для каждого bucket с числом строк train ≥ `ML_V2_EXPERIENCE_REGIME_MIN_TRAIN` (500) сохраняются `tt_ml_v2_b1_match.joblib` (rookie), `tt_ml_v2_b2_*` (low), `tt_ml_v2_b3_*` (mid), `tt_ml_v2_b4_*` (pro).

**Инференс:** bucket-модели **всегда используются**, если файлы есть (флаг не нужен). Routing: `bucket = max(p1_exp_bucket, p2_exp_bucket)` (1..4). Загружается `tt_ml_v2_b{bucket}_*`; при отсутствии файла — fallback на общую `tt_ml_v2_*`. В ответе предсказания передаётся `regime_bucket`: "rookie"|"low"|"mid"|"pro".

### Confidence filtering

**`BETSAPI_TABLE_TENNIS_V2_CONFIDENCE_FILTER_MIN_PCT`** (0 = выкл): минимальная уверенность для прогноза в процентах. При 75 выдаются только прогнозы с P ≥ 75% — типично accuracy 80–85% при меньшем покрытии (20–30%).

### GPU-only гарантия

В `retrain_models_v2`:

- если `ML_USE_GPU=false`, retrain завершается ошибкой;
- CPU fallback для v2 отключен;
- в stdout лог обязательно выводится строка:
  - `ML v2 train [target_match] device=cuda ...`
  - `ML v2 train [target_set1] device=cuda ...`

### Какие метрики возвращаются

По каждой модели (`match`, `set1`) и по split (`val`, `test`):

- `accuracy`
- `logloss` — после калибровки и ансамбля с Elo (`p_final = (1-w)*p_ml + w*p_elo`, по умолчанию w=0.3). Это то, что видит пользователь в API и по чему оценивается production.
- `raw_logloss` — только выход модели (без калибровки и без Elo). Показатель «как хорошо учится сама модель»; для датасета с сильным сигналом обычно ожидается заметно ниже 0.69 (random ≈ 0.693). Если raw_logloss ≈ 0.68, модель лишь чуть лучше случайной; улучшать стоит фичи/сплит/регуляризацию.
- `brier`
- `n`

**target_set1:** при слабой регуляризации на val часто best_iteration=1 и logloss затем взлетает до 13+. Поэтому для set1 заданы отдельные параметры: `ml_v2_lgb_num_leaves_set1=96`, `ml_v2_lgb_min_child_set1=30`, `ml_v2_lgb_reg_alpha_set1=0.7`, `ml_v2_lgb_reg_lambda_set1=1.8`.

### Calibration вероятностей

После обучения для обоих таргетов дополнительно строится калибратор вероятностей:

- считается `isotonic` и `sigmoid`;
- выбирается метод с лучшим `logloss` на validation;
- сохраняются артефакты:
  - `tt_ml_v2_match_calib.joblib`
  - `tt_ml_v2_set1_calib.joblib`

И inference/eval используют уже **calibrated probabilities**.

---

## 7) Заполнение ML таблиц (ClickHouse) и расписание

### Какие таблицы чем заполняются

Все таблицы ML заполняются **автоматически каждые 10 минут** (интервал `ML_SYNC_INTERVAL_SEC=600`) в процессе `ml_sync_loop` (сервис `ml_sync`).

| Таблица | Заполнение | Авто (каждые 10 мин) |
|--------|------------|----------------------|
| `ml.matches` | sync из main (finished события) | да |
| `ml.match_sets` | sync (сеты по счёту) | да |
| `ml.player_match_stats` | sync (по каждому матчу) | да |
| `ml.player_elo_history` | после sync — `recompute_elo_from_matches()` | да |
| `ml.player_daily_stats` | sync (`_refresh_...`) + `sync_player_daily_stats_to_ch_once` | да |
| `ml.match_features` | `rebuild_features_to_ch` (incremental, missing, refresh) | да |

В каждом цикле: sync → player_daily_stats → incremental features → несколько проходов missing → при смене схемы — refresh (новые колонки заполняются по истории).

**Полное заполнение с нуля:** `python -m app.ml.worker_cli full-rebuild ...` или `./scripts/run_ml_v2_retrain_verbose.sh full`.

### Расписание: sync и retrain

Код: `backend/app/services/ml_sync_loop.py`.

Для `ML_ENGINE=v2`:

1. каждые `ML_SYNC_INTERVAL_SEC`:
   - `sync_finished_to_ch_once`
   - `sync_player_daily_stats_to_ch_once`
   - `rebuild_features_to_ch(mode='missing')`
   - `rebuild_features_to_ch(mode='refresh')` при изменении schema signature
2. проверка условий retrain:
   - `due_by_time`: прошло `ML_RETRAIN_INTERVAL_SEC` с последнего retrain
   - `due_by_volume`: синкнуто/добавлено фичей >= `ML_RETRAIN_MIN_NEW_MATCHES`
3. при выполнении условия:
   - enqueue задачи `retrain` в очередь `ml_worker`.

Итог: sync и feature refresh отделены от retrain, retrain выполняется в GPU-воркере.

---

## 8) Инференс и выдача прогнозов

### 8.1 Вычисление вероятностей

Код: `backend/app/ml_v2/inference.py`.

1. строится feature vector для upcoming матча (`build_upcoming_feature_vector`);
2. подгружаются `tt_ml_v2_match.joblib` и `tt_ml_v2_set1.joblib`;
3. считаются:
   - `p_match`
   - `p_set1`
   - `p_set2` (в текущем rollout приравнен к `p_set1`).
4. применяется ансамбль с Elo:
   - `p_final = (1 - w_elo) * p_ml + w_elo * p_elo`.
5. применяется anti-position-bias guard:
   - инференс прогоняется в двух ориентациях (`home/away` и `away/home`);
   - итог симметризуется: `p = (p_direct + (1 - p_swapped)) / 2`.

### 8.2 Подключение в скоринг

Код: `backend/app/services/ml_scorer.py`.

При `ML_ENGINE=v2` используется только `predict_for_upcoming_v2`.

### 8.3 Политика пересчета прогнозов (one-shot)

Код: `backend/app/services/forecast_v2_pipeline.py`.

Логика:

- прогноз создается один раз для пары `event_id + channel`;
- если запись уже существует, повторный проход не пересчитывает ее (включая live/finished);
- это фиксирует исходный сигнал и исключает drift.

Новые веса/модели применяются к новым событиям.

### 8.4 Отбор прогноза: уверенность в исходе (игрок), не value vs линия

Код: `backend/app/services/pick_selector.py`, `forecast_v2_pipeline.py`.

- Кандидаты фильтруются по `min_confidence_pct` (по умолчанию 58%) и `min_odds`; порог по edge (`min_edge_pct`) по умолчанию 0 — не требуем перевес над линией.
- Сортировка: сначала по качеству тира, затем по **уверенности в исходе** (confidence), затем по edge. Выбирается вариант, в котором модель больше всего уверена в исходе (игрок), а не максимальный «value» по кэфу.
- Цель: больше прогнозов и выше % угадывания за счёт опоры на силу игрока, а не на коэффициент.

---

## 9) Админ API для контроля ML v2

Основные ручки:

- `GET /api/v1/admin/ml/progress` - прогресс задач
- `GET /api/v1/admin/ml/dashboard` - сводка ML
- `GET /api/v1/admin/ml/v2/status` - статус v2 (ClickHouse, queue, kpi, meta)
- `POST /api/v1/admin/ml/retrain` - enqueue retrain
- `POST /api/v1/admin/ml/sync` - enqueue sync
- `POST /api/v1/admin/ml/backfill-features` - enqueue feature backfill
- `POST /api/v1/admin/ml/full-rebuild` - полный цикл

Новый v2 status показывает:

- состояние ClickHouse;
- размер очереди;
- counts ключевых CH таблиц;
- delta main vs CH;
- delta `CH matches` vs `CH match_sets (uniq match_id)` + alert при разрыве;
- мета последнего retrain (`device`, timestamps);
- KPI (`match_hit_rate`, `set1_hit_rate`, `sample_size`).

---

## 10) Проверка корректности и команды эксплуатации

### 10.1 Ручной retrain в GPU worker

```bash
docker compose up -d ml_worker
docker compose exec -T ml_worker python -m app.ml.worker_cli retrain --min-rows 1000
docker compose logs -f ml_worker
```

### 10.2 Полный smoke скриптом

```bash
ADMIN_EMAIL="..." ADMIN_PASSWORD="..." BACKEND_URL="http://localhost:11001" ./scripts/check_ml_v2_gpu.sh
```

Скрипт:

1. логинится в API;
2. ставит retrain;
3. ждёт `retrain.status=done`;
4. печатает `ml/v2/status`;
5. извлекает из логов доказательство `device=cuda`.

### 10.3 Быстрый тест API маршрутов v2

```bash
docker compose exec -T backend python scripts/test_ml_v2_admin_api.py
```

### 10.4 Проверка разрыва matches vs match_sets

```bash
docker compose exec -T clickhouse clickhouse-client --port 11004 --query "
SELECT
  (SELECT uniqExact(match_id) FROM ml.matches FINAL) AS ch_matches,
  (SELECT uniqExact(match_id) FROM ml.match_sets FINAL) AS ch_match_sets_uniq,
  ch_matches - ch_match_sets_uniq AS gap"
```

---

## 11) Где хранятся модели

Путь: `ML_MODEL_DIR` (в Docker: volume `pingwin_ml_models`, путь `/app/ml_models`).

Артефакты v2:

- `tt_ml_v2_match.joblib`
- `tt_ml_v2_set1.joblib`
- `tt_ml_v2_match_calib.joblib` (auto: isotonic/sigmoid, selected by logloss)
- `tt_ml_v2_set1_calib.joblib` (auto: isotonic/sigmoid, selected by logloss)
- `tt_ml_v2_meta.json`

Все сервисы (`backend`, `tt_workers`, `ml_worker`) должны использовать один и тот же `ML_MODEL_DIR`.

---

## 12) Известные ограничения текущего rollout

1. `p_set2` в v2 сейчас равен `p_set1` (временное упрощение).
2. Если в `ml.match_features` слабый сигнал, возможна ранняя остановка на 1-й итерации LightGBM.
3. `evaluate_filtered_signals` - runtime guard KPI, это не полноценный offline бэктестер.
4. Разрыв `ml.matches` vs `ml.match_sets`: матчи без сетов дозаполняются автоматически — в каждом цикле **ml_sync_loop** вызывается `backfill_match_sets_from_main(limit=2000)` (источник: main DB `live_sets_score`/`live_score`). При ручном **sync** / **full-rebuild** (worker_cli) выполняется до 50 проходов backfill по 3000 матчей. Ручной запуск: `POST /api/v1/admin/ml/v2/backfill-match-sets?limit=5000`.

---

## 12.1) Rolling + anti-leakage принципы (обязательно)

В v2 все исторические признаки строятся строго по условию:

- `history.match_time < current_match.start_time`

Порядок вычисления:

1. матчи сортируются по `start_time ASC`;
2. для пары игроков считаются фичи только из истории до времени матча;
3. строка признаков записывается в `ml.match_features`;
4. только после этого матч влияет на H2H/league state для следующих матчей.

Это исключает data leakage вида `history <= current_match`.

---

## 12.2) Calibration вероятностей

После обучения LightGBM v2 выполняется калибровка вероятностей:

- строим калибратор на validation выборке;
- одновременно считаем `isotonic` и `sigmoid` (Platt-like);
- выбираем метод с меньшим `logloss`.

Далее в production используются именно откалиброванные вероятности:

- inference (`predict_for_upcoming_v2`);
- KPI/eval (`evaluate_filtered_signals`).

Это делает пороги confidence (`p > 0.72` / `p < 0.28`) стабильнее и ближе к реальной частоте попаданий.

---

## 12.3) Почему accuracy может не расти после добавления фич

Даже при увеличении числа фич (в т.ч. до 90+) рост `accuracy@0.5` не гарантирован.
Частые причины:

1. шум/неполнота таргета (`set1` особенно чувствителен к качеству `match_sets`);
2. часть новых фич имеет низкий signal (низкий MI), поэтому модель их почти игнорирует;
3. метрика `accuracy` на всей выборке сглаживает эффект, который проявляется лучше в filtered KPI;
4. saturation: на текущем распределении матчей добавление коррелированных фич дает мало прироста;
5. неактуальные данные (матчи/сеты/статы) или неполный backfill истории.

Практический вывод:

- смотреть не только `accuracy`, но и `logloss`, `brier`, а также filtered `match_hit_rate` / `set1_hit_rate`;
- делать MI-ранжирование и pruning слабых фич;
- убедиться в полном покрытии исторических таблиц.

---

## 12.4) Нужно ли больше датасета и дозаполнение таблиц

Кратко: **сначала проверить полноту и качество текущих данных**, потом наращивать объем.

Минимальные проверки:

```bash
# 1) Покрытие фичами (distinct матчи)
docker compose exec -T ml_worker python -c "from app.ml_v2.features import feature_coverage_stats; print(feature_coverage_stats())"

# 2) Объем ключевых таблиц
docker compose exec -T clickhouse clickhouse-client --port 11004 --query "
SELECT 'matches', count() FROM ml.matches
UNION ALL SELECT 'match_features', count() FROM ml.match_features
UNION ALL SELECT 'player_match_stats', count() FROM ml.player_match_stats
UNION ALL SELECT 'player_elo_history', count() FROM ml.player_elo_history
UNION ALL SELECT 'match_sets', count() FROM ml.match_sets"
```

Замечание по `match_features`: для `ReplacingMergeTree` обычный `count()` может быть выше `matches` из-за версий строк.
Для корректного контроля покрытия используйте `uniqExact(match_id)` или `FINAL`.

Если покрытие неполное:

1. запустить `full sync` main -> CH;
2. запустить `backfill features`;
3. повторить retrain;
4. проверить MI и top importances.

Если покрытие полное, но accuracy не растет:

1. усиливать quality фич (не quantity): оставить сильные, удалить шум;
2. улучшать quality labels (особенно set-level);
3. смещать оптимизацию на KPI-filtered сигналы (confidence/edge), а не только на global accuracy.

---

## 13) Чеклист при проблемах

1. Проверить `ML_ENGINE=v2`, `ML_USE_GPU=true`.
2. Проверить, что `ml_worker` запущен и видит GPU.
3. Проверить в логах retrain строку `device=cuda`.
4. Проверить наполнение:
   - `ml.matches`
   - `ml.match_sets`
   - `ml.player_match_stats`
   - `ml.player_elo_history`
   - `ml.match_features`
5. Проверить `/api/v1/admin/ml/v2/status` (delta, timestamps, kpi).
6. Проверить общий `ML_MODEL_DIR` между сервисами.

