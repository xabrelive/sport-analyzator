# Датасет ML: как избежать утечки и дубликатов

> Актуальная полная документация по текущему прод-контуру `ML v2 (ClickHouse)` находится в `docs/ML_V2_TECH_DOC.md`.

## 1. Data leakage (утечка будущего)

**Правило:** для матча `i` в признаках используется только информация по матчам **строго до** `i`.

### Реализация в коде

- **cutoff** = `start_time - 1` секунда. Все запросы к истории: `WHERE start_time < :cutoff` (или `match_date < :cutoff`).
- **Elo:** берётся из `player_elo_history`: для каждого игрока — `elo_after` последнего матча до `cutoff`. **Не** из `player_ratings` (там рейтинг после всех матчей → утечка).
- **winrate_last_10, dominance, fatigue, h2h:** считаются только по матчам с `start_time < cutoff`.
- **league_upset_rate:** по матчам лиги с `start_time < cutoff`.

### Порядок пайплайна при backfill

1. Синхронизация матчей main → ML (`matches`, `match_sets`, `odds`).
2. **Сначала** заполнить `player_elo_history` по хронологии (`backfill_player_elo_history_once`).
3. Затем расчёт фичей и запись в `match_features` (`backfill_features_*`).

Иначе при пустой `player_elo_history` Elo будет default (1500) без утечки, но модель будет слабее до первого прогона истории.

---

## 2. Симметрия признаков

Модель должна получать **разницы** между игроками, а не два отдельных блока «игрок 1» / «игрок 2», чтобы не закладывать порядок (кто home/away).

**Используются в основном diff-фичи:**

- `elo_diff`, `form_diff`, `fatigue_diff`, `h2h_diff`, `winrate_10_diff`
- `dominance_diff`, `dominance_last_50_diff`, `dominance_trend_diff`
- `avg_sets_per_match_diff`, `set1_strength_diff`, `comeback_rate_diff`
- `momentum_today_diff`, `daily_performance_trend_diff`, `fatigue_index_diff`, `fatigue_ratio`
- `minutes_since_last_match_diff`, `streak_score`, `style_clash`, `elo_volatility_diff`

Отдельные `*_p1`/`*_p2` (например, `std_points_diff_last10_p1/p2`, `odds_shift_p1/p2`) используются там, где одной разницы недостаточно; модель всё равно обучается на одном матче = одна строка с фиксированным порядком P1/P2.

---

## 3. Дубликаты матчей

**Один матч = одна строка в датасете.**

- В ML-БД матч хранится один раз: `matches.id` (PK), `player1_id` = home, `player2_id` = away.
- Обучение: `FROM match_features mf JOIN matches m ON m.id = mf.match_id` — одна строка на матч.
- Не должно быть двух записей для одной пары (A vs B и B vs A) как двух разных матчей. Sync из main привязывает матч к одному `external_id` и одной паре (home, away).

При добавлении новых источников данных нужно сохранять уникальность по смыслу матча (например, пара игроков + время старта или внешний id).

---

## 4. Временной сплит (train / validation / test)

**Схема без перемешивания:**

| Период   | Назначение |
|----------|------------|
| 2016     | **Warmup** — только накопление статистики (Elo, rolling), в обучение не входит |
| 2017–2022| **Training** — обучение моделей (дообучение каждые 30 мин) |
| 2023–2024| **Validation** — подбор гиперпараметров / early stopping (при необходимости) |
| 2025+    | **Test** — финальная оценка |

- Матчи загружаются `ORDER BY m.start_time ASC`.
- В `load_training_data` по умолчанию в выборку попадают только годы `train_year_start`…`train_year_end` (2017–2022); матчи до `warmup_year_end` (2016) исключаются из обучающей выборки.
- **Лимиты:** `ml_train_limit` — макс. матчей для моделей match/set1 (по умолчанию 1.5M); `ml_train_set_limit` — макс. сетов для моделей set/p_point (по умолчанию 2M). Сетов в БД обычно в 2–3 раза больше матчей; при объёме >1M сетов задайте `ML_TRAIN_SET_LIMIT=2000000` или выше, чтобы дообучение использовало все данные. Те же годы (`train_year_*`) применяются и к set-level выборке.

### Балансировка датасета

Чтобы модель не затачивалась под фаворитов (odds 1.30), можно включить фильтр по коэффициентам при обучении: `ml_train_odds_min=1.4`, `ml_train_odds_max=3.0` — в train попадают матчи, где хотя бы один кф в этом диапазоне.

---

## 5. Pipeline построения датасета

1. **Сортировка:** `ORDER BY match_time` (в коде — `m.start_time`).
2. **Rolling-статистика:** для каждого игрока считаются last_5/10/20/50 матчей; фичи строятся с `cutoff = start_time - 1 sec` (только прошлые матчи).
3. **Обновление после матча:** при backfill фичей матчи обрабатываются в хронологическом порядке; `player_elo_history` обновляется пошагово; при расчёте фичей для матча `i` используются только данные по матчам `< i`.

---

## 6. Какие таблицы и данные реально используются

Ниже фактические источники из `backend/app/ml/model_trainer.py` и связанных сервисов.

### 6.1 Таблицы для обучения (ML DB)

| Таблица | Где используется | Что берём |
|--------|-------------------|-----------|
| `matches` | `load_training_data`, `load_validation_data`, `load_set_training_data` | `id`, `start_time`, `status`, `score_sets_p1`, `score_sets_p2`, `player1_id`, `player2_id`, `league_id` |
| `match_features` | те же функции | все ML-фичи (`elo_diff`, `form_diff`, `fatigue_diff`, ...), `odds_p1`, `odds_p2`, `sample_size` |
| `match_sets` | `load_training_data` (target_set1), `load_set_training_data` (target_set) | `score_p1`, `score_p2`, `set_number` |
| `odds` | `get_closing_odds` (валидация/CLV) | `match_id`, `odds_p1`, `odds_p2`, `created_at` (берётся последний снимок) |

### 6.2 Таблицы для расчёта фичей (feature_engine / sync)

| Таблица | Для чего |
|--------|----------|
| `player_elo_history` | Elo на момент матча без утечки будущего |
| `player_stats` / `player_daily_features` | форма, темп, волатильность, усталость |
| `league_performance` | `league_upset_rate`, штрафы confidence по лиге |

### 6.3 Какие таргеты учатся

| Модель | Таргет | Как считается |
|-------|--------|---------------|
| `match_model` | `target_match` | `1`, если `score_sets_p1 > score_sets_p2`, иначе `0` |
| `set1_model` | `target_set1` | результат 1-го сета из `match_sets` |
| `set_model` | `target_set` | результат любого сета из `match_sets` |
| `p_point_model` (fallback) | `target_set` | logistic fallback, если `set_model` нет |

### 6.4 Полный список фичей (FEATURE_COLS)

`elo_diff`, `elo_probability`, `form_diff`, `fatigue_diff`, `h2h_diff`, `winrate_10_diff`, `odds_diff`, `h2h_count`, `avg_sets_per_match_diff`, `sets_over35_rate_diff`, `streak_score`, `minutes_since_last_match_diff`, `dominance_diff`, `std_points_diff_last10_p1`, `std_points_diff_last10_p2`, `elo_volatility_diff`, `log_odds_ratio`, `implied_prob_p1`, `market_margin`, `momentum_today_diff`, `set1_strength_diff`, `comeback_rate_diff`, `dominance_last_50_diff`, `fatigue_index_diff`, `fatigue_ratio`, `minutes_to_match`, `odds_shift_p1`, `odds_shift_p2`, `daily_performance_trend_diff`, `dominance_trend_diff`, `style_clash`, `hours_since_last_h2h`, `league_upset_rate`.

---

## 7. Гибридная модель (реалистичные метрики)

- **Слой 1 — Elo:** `P_elo = 1 / (1 + 10^(-elo_diff/400))`.
- **Слой 2 — ML по рынкам:**  
  - `match_model` даёт `P_match_raw`,  
  - `set1_model` даёт `P_set1`,  
  - `set_model` (или `p_point_model`) через Monte Carlo даёт `P_set2`.
- **Слой 3 — ансамбль для матча:** `P_match = w * P_elo + (1 - w) * P_match_raw` (`w = ml_ensemble_elo_weight`).
- **Выход:** predict probability → value detection (EV/edge/odds) → signal filter.

Практический ориентир для TT:

- random: ~50%
- Elo: ~61–65%
- ML (без жёсткой фильтрации): ~63–69%
- ML + market features: ~68–72%

`80%+` обычно достигается не на всём потоке матчей, а на узком наборе после фильтрации value-сигналов.

### Конфигурация LightGBM для TT

Рабочие базовые параметры: `learning_rate=0.02`, `num_leaves=127`, `min_child_samples=30`, `feature_fraction=0.85`, `bagging_fraction=0.85`, `bagging_freq=5`, `reg_alpha=0`, `reg_lambda=1`, `min_split_gain=0`, `n_estimators=5000`, early stopping 300 раундов (последние 10% данных — validation). Полный набор задаётся в `model_trainer._train_binary_model`.

**Фича elo_probability:** вероятность Elo входит в модель как отдельный признак: `P_elo = 1 / (1 + 10^(-elo_diff/400))`. Это часто даёт +3–5% к качеству для ставок.

**Калибровка и p_point на GPU:** при установленном cuML (RAPIDS) калибровка (Platt scaling) и обучение p_point (LogisticRegression) выполняются на GPU; веса сохраняются в формате sklearn, inference работает без cuML.

**Три параметра, которые сильнее всего влияют на результат:** `num_leaves`, `learning_rate`, `min_data_in_leaf` (в коде — `min_child_samples`). Их стоит подбирать в первую очередь.

---

## 8. Production pipeline (архитектура)

Правильная последовательность этапов:

```
match data
    ↓
feature engineering
    ↓
ELO probability (фича + ансамбль)
    ↓
LightGBM
    ↓
probability
    ↓
Monte Carlo simulation
    ↓
value detection
```

Реализация: синхронизация матчей → расчёт фичей (feature_engine) → Elo как фича `elo_probability` и в ансамбле → LightGBM (match/set модели) → P_match, P_set1/2 → Monte Carlo при необходимости → ValueDetector + SignalFilter → сигналы.

---

## 8.1. Цепочка: обучение → прогнозы (одна конфигурация)

Чтобы прогнозы использовали **ту же модель**, что переобучается на дополненных данных:

| Этап | Где | Что происходит |
|------|-----|----------------|
| **Данные** | tt_workers (ml_sync_loop) | Каждые 10 мин: main→ML sync, backfill фичей, odds, player_stats, league_performance. |
| **Очередь retrain** | ml_sync_loop | По расписанию (ML_RETRAIN_INTERVAL_SEC=1800) или при объёме ставит задачу «retrain» в очередь. |
| **Обучение** | ml_worker | Выполняет `retrain_models_if_needed(version="v1")`: загрузка по годам ML_TRAIN_YEAR_START–ML_TRAIN_YEAR_END (по умолчанию 2017–2022), лимит ML_TRAIN_LIMIT, сохранение в `ML_MODEL_DIR/tt_ml_v1_*.joblib`. |
| **Сохранение** | model_trainer.save_models | Файлы: `tt_ml_v1_match.joblib`, `tt_ml_v1_set1.joblib`, `tt_ml_v1_set.joblib`, `tt_ml_v1_p_point.joblib` (если есть). |
| **Прогнозы** | inference.predict_for_upcoming | При каждом вызове: `load_models(version="v1")` читает те же файлы из `ML_MODEL_DIR` (без кэша — каждый запрос загружает с диска). |
| **Кто вызывает** | forecast_v2_pipeline, API, anomaly, league_performance | ml_scorer.score_match_for_forecast → predict_for_upcoming → load_models → predict_proba. |

**Важно:** backend, tt_workers и ml_worker монтируют один volume `pingwin_ml_models:/app/ml_models` и используют один `ML_MODEL_DIR`. После переобучения в ml_worker следующий прогноз в tt_workers или API подхватит новые файлы. Параметры обучения (годы, лимит) задаются в `.env` и передаются в ml_worker и ml_train_gpu через docker-compose (например, `ML_TRAIN_YEAR_END=2022`, `ML_TRAIN_LIMIT=1500000`).

---

## 9. Hyperparameter search и Feature importance

**После базового обучения** стоит выполнить подбор гиперпараметров:

- **API:** `POST /admin/ml/hyperparameter-search?n_iter=25&limit=100000` — RandomizedSearchCV по диапазонам (num_leaves 64–256, learning_rate 0.01–0.03, min_child_samples 20–100, feature_fraction/bagging_fraction 0.7–0.9, min_split_gain 0–0.001, reg_alpha 0–1, reg_lambda 0.5–2). Лучшие параметры сохраняются в `tt_ml_hyperparams.json` и подхватываются при следующем retrain.

**Feature importance:** после каждого обучения выводится топ-15 фичей по важности. В топ-10 **должны** входить: `elo_diff`, `dominance_last_50_diff`, `fatigue_ratio`, `odds_shift_p1`/`odds_shift_p2`, `form_diff`. Если какой-то из них нет — возможна ошибка в расчёте фичей.

---

## 10. Фильтрация сигналов (обязательный этап)

Без фильтрации модель не даёт 80%+ accuracy по отобранным матчам. В коде (`SignalFilter`, `ValueDetector`) используются:

| Фильтр | Порог | Смысл |
|--------|--------|--------|
| edge | > 0.05 | P_model − P_market (разница с линией) |
| EV | > 0.08 | Expected value = P × Odds − 1 |
| odds | 1.5–3.0 | Золотая зона для отбора |
| fatigue_ratio | < 2 | Один игрок не должен быть сильно уставшим |
| league_upset_rate | < 40% | Лиги с частыми апсетами отбрасываем |

После фильтрации обычно остаётся **8–15% матчей**, но ROI растёт.

---

## 11. Оценка модели (метрики)

После переобучения считаются метрики на **validation** (годы `ml_val_year_start`–`ml_val_year_end`, по умолчанию 2023–2024):

| Метрика | Описание |
|--------|----------|
| **accuracy** | Доля матчей, где `(P ≥ 0.5) == исход` |
| **logloss** | Логарифмические потери (калибровка вероятностей) |
| **Brier** | Средний квадрат ошибки `(P − outcome)²` |
| **ROI** | Симулированные ставки: ставим при edge > 0.05 и odds 1.5–3.0; ROI = сумма прибыли / число ставок |
| **CLV** | **Closing Line Value** — главная метрика |

**CLV > 0** означает, что модель в среднем получала лучшие коэффициенты, чем закрывающая линия (мы ставили выгоднее рынка). То есть **модель сильнее рынка**.

- CLV считается только по тем же value-ставкам (edge, odds), для которых есть closing odds в таблице `odds` (последний снимок по матчу).
- Метрики выводятся в лог после каждого retrain и возвращаются в `validation_metrics` в ответе API переобучения.

---

## 12. Чеклист «как исправить обучение»

Если обучение или метрики «ломаются», идти в таком порядке:

1. **Проверить объём данных**
   - `ml_train_year_start/end`, `ml_train_limit`, `ml_train_set_limit`
   - хватает ли строк в `matches`, `match_features`, `match_sets`.

2. **Проверить целостность таргетов**
   - нет ли пустых `score_sets_p1/score_sets_p2`,
   - `target_match/target_set1/target_set` не вырождаются в один класс.

3. **Проверить фичи**
   - `match_features` заполнена для нужных матчей,
   - нет массовых `NULL`/`NaN` в ключевых фичах (`elo_diff`, `form_diff`, `fatigue_ratio`, `odds_shift_*`),
   - top-importance содержит ожидаемые сильные фичи.

4. **Проверить sequence pipeline**
   - сначала sync main→ML и backfill Elo/history,
   - потом backfill feature rows,
   - только потом retrain.

5. **Проверить единый путь моделей**
   - `ML_MODEL_DIR` одинаковый у `tt_workers`, `ml_worker`, `ml_train_gpu`,
   - после retrain появились файлы `tt_ml_v1_match.joblib`, `tt_ml_v1_set1.joblib`, `tt_ml_v1_set.joblib` (и опционально `p_point`).

6. **Если валидация упала**
   - смотреть traceback в `retrain_models_if_needed`,
   - частая причина: массивы в булевых условиях (`if np_array`), нужно явное scalar-приведение (`.item()`, `.flat[i]`, `bool(...)` на скаляре).

7. **Проверить inference после обучения**
   - матч использует `match_model`,
   - 1-й сет использует `set1_model`,
   - 2-й сет использует `set_model` (или fallback через `p_point_model` + MC),
   - фильтры odds/EV/edge соответствуют текущей конфигурации.
