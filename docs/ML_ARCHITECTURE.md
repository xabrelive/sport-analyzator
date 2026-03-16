# ML-архитектура: прематч-прогнозы настольного тенниса

Полное описание системы машинного обучения для прогнозирования исходов матчей TT.

---

## 1. Обзор

ML-система предсказывает исходы предстоящих матчей (победа в матче, в 1-м и 2-м сете) на основе:

- **Elo+** — улучшенный рейтинг с margin, dynamic K, loss streak, recency, league adjustment
- **Форма** — последние 5/10 матчей (win rate, dominance)
- **Усталость** — матчи за 3h, 6h, 24h
- **H2H** — очные встречи
- **Коэффициенты** — odds, implied prob, market margin
- **XGBoost/LightGBM** — модели P_set с калибровкой
- **League ROI** — фильтрация по прибыльности лиг
- **Детекция договорных** — подозрительные матчи

**Целевая точность**: Match 75–80%, Set1 72–77%. **ROI**: 8–15% при правильной фильтрации.

---

## 2. Базы данных

### Основная БД (`pingwin`)

| Таблица | Назначение |
|---------|------------|
| table_tennis_line_events | Матчи из BetsAPI (линия, лайв, результаты) |
| table_tennis_forecasts_v2 | Прогнозы V2 (платный/VIP канал) |
| table_tennis_forecast_early_scan | Stage 1: ранний скрининг 6–12h (event_id, minutes_to_match, p_match, has_value) |

### ML-БД (`pingwin_ml`)

Схемы: `02_ml_schema.sql` … `09_add_duration_to_matches.sql`

| Таблица | Назначение |
|---------|------------|
| **players** | Игроки (external_id = BetsAPI home_id/away_id) |
| **leagues** | Лиги (справочник) |
| **matches** | Завершённые матчи (player1_id, player2_id, score_sets_p1/p2, start_time, league_id) |
| **match_sets** | Счёт по сетам (set_number, score_p1, score_p2) |
| **odds** | Прематч-коэффициенты (opening) |
| **player_ratings** | Elo-рейтинг, matches_played, last_match_at |
| **match_features** | Фичи матча (снимок на момент матча) |
| **signals** | Value-сигналы |
| **suspicious_matches** | Подозрительные матчи (odds_shift, comeback_flag, model_error) |
| **league_performance** | ROI по лигам (rolling last 500 matches, roi_pct, upset_rate) |
| **player_daily_stats** | player_id, date, matches_played, wins, losses, momentum, fatigue_index = min(30, matches×3) |
| **player_style** | tempo, aggression, comeback, close_match (для set prediction) |
| **player_elo_history** | player_id, match_id, elo_before, elo_after, match_date — для elo_recent и elo_volatility (std last 20) |

---

## 3. Поток данных

**Главная БД** (`pingwin`) — единый источник для фронта и загрузки из BetsAPI. ML **никогда не обращается к BetsAPI** — только читает из main и пишет прогнозы обратно в main.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ГЛАВНАЯ БД (pingwin)                                                        │
│  • table_tennis_line_events — матчи (BetsAPI → tt_workers)                   │
│  • table_tennis_forecasts_v2 — прогнозы (ML пишет сюда)                      │
│  • Фронт читает отсюда для отображения                                       │
└─────────────────────────────────────────────────────────────────────────────┘
         ↑ BetsAPI                    ↑ прогнозы
         │                            │
    tt_workers                   forecast_v2_loop
    (line, odds, live,            (читает main, ML inference,
     results loops)                 пишет в main)
         │
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  ML-БД (pingwin_ml) — только для ML                                          │
│  matches, match_features, players, odds, league_performance, …                │
└─────────────────────────────────────────────────────────────────────────────┘
         ↑ main→ML sync
         │
    ml_sync_loop (в tt_workers, каждые ML_SYNC_INTERVAL_SEC, по умолчанию 10 мин)
    ml_worker full-rebuild (по запросу)
```

**ML-таблицы** заполняются на каждой итерации `ml_sync_loop` (каждые 10 мин по умолчанию):

```
main DB (finished матчи) → sync_finished_to_ml / sync_full_main_to_ml
                            ↓
              pingwin_ml: matches, players, match_sets, odds (backfill_odds_from_main)
                            ↓
              backfill_duration_from_main_once → matches.duration_minutes
              backfill_features_once → match_features
              backfill_player_daily_stats_once → player_daily_stats
              backfill_player_style_once → player_style
              backfill_player_elo_history_once → player_elo_history
              check_suspicious_matches_once → suspicious_matches
              update_league_performance_once → league_performance
                            ↓
              retrain_models_if_needed → tt_ml_v1_*.joblib
                            ↓
              forecast_v2_loop → predict_for_upcoming → table_tennis_forecasts_v2 (main)
```

---

## 4. Стадии прогноза (Forecast stages)

| Стадия | Окно | Действие |
|--------|------|----------|
| **Stage 1** | 6–12h | Ранний скрининг. Считаем, не публикуем. `table_tennis_forecast_early_scan` |
| **Stage 2** | 1–3h | Основной расчёт. Публикуем, отображаем, записываем в статистику |
| **Stage 3** | 10–20min | Финальный (опционально). Добавляются odds_shift, последние матчи |

**Окно публикации**: 60–180 минут до матча. Не пересчитываем после публикации.

### Условия для Stage 2 (run_forecast_v2_once)

- `status == scheduled`
- `starts_at > now`
- `starts_at <= now + 3h`
- `starts_at >= now + 60min` (window_start)
- `starts_at <= now + 180min` (window_end)
- `created_at <= now - delay_minutes` (задержка 5 мин после появления)
- `odds_1`, `odds_2` не null

### Early scan (run_early_scan_once)

- Окно: 6–12 часов до матча
- Сохраняет: event_id, minutes_to_match, p_match, has_value (EV ≥ 0.08 и odds 1.6–2.6)
- Интервал: 600 сек (betsapi_table_tennis_early_scan_interval_sec)

---

## 5. Архитектурные улучшения (TT best practices)

| Проблема | Решение |
|----------|---------|
| Ручная формула p_point | **LightGBM p_set** → Monte Carlo. features → ML model → p_set → MC → p_match |
| Elo только point_diff | **margin = sets_diff×10 + point_diff** (3:0 vs 3:2 — разные матчи) |
| Form: last 5/10 | **Time decay**: weight = exp(-days/14) |
| fatigue_diff только | **fatigue_ratio** = fatigue_p1/(fatigue_p2+1) — один свежий, другой 10 матчей |
| dominance last 10 | **dominance_last_50** — points_won/total_points за ~50 сетов (стабильнее) |
| implied_prob, log_odds | **CLV** = odds_open/odds_close. CLV>1.1 — рынок сильно двигался |

---

## 6. Elo+ (улучшенный рейтинг для TT)

Классический Elo плохо работает для TT: короткие матчи, много матчей в день, важна разница очков.

### Точная формула обновления

```
expected = 1 / (1 + 10^((r2 - r1) / 400))
actual = 1 если P1 выиграл, иначе 0

margin = sets_diff × 10 + point_diff
margin_mult = log(margin + 1) × 0.6
margin_mult = clamp(margin_mult, 0.5, 2.0)

K = min(K1, K2)   # новичок не меняет рейтинг ветерана
loss_factor = ((1 + ls1×0.05) + (1 + ls2×0.05)) / 2   # ls = loss_streak (до 15 матчей)
recency = exp(-days_ago / 30)
league_mult = _league_multiplier(league_id)

delta = K × margin_mult × loss_factor × recency × league_mult × (actual - expected)
new_r1 = r1 + delta
new_r2 = r2 - delta
```

### Компоненты

| Компонент | Формула / логика |
|-----------|------------------|
| **margin** | `sets_diff × 10 + point_diff` — разница сетов важнее разницы очков (3:0 vs 3:2) |
| **margin_mult** | `log(margin + 1) × 0.6`, cap [0.5, 2.0] |
| **Dynamic K** | matches_played < 50 → K=40; < 200 → K=24; else K=16 |
| **Loss streak** | `1 + loss_streak × 0.05` — при серии поражений рейтинг падает быстрее (до 15 матчей) |
| **Recency** | `exp(-days_ago / 30)` — свежие матчи важнее |
| **League adjustment** | pro=1.2, mid=1.0, weak=0.8 (по ключевым словам в league_id) |

### League multiplier (ключевые слова)

- **1.2**: pro, wtt, ittf, world, championship
- **1.0**: cup, challenge, open
- **0.8**: остальные (слабые лиги)

---

## 7. Фичи (MatchFeatures)

### Базовые

| Фича | Формула |
|------|---------|
| elo_diff | elo_p1 - elo_p2 |
| form_diff | form_p1 - form_p2, где form = 0.4×wr5 + 0.3×wr10 + 0.3×dominance |
| fatigue_diff | fatigue_p2 - fatigue_p1; fatigue = min(100, matches_24h × 12) |
| h2h_diff | h2h_p1_wr - 0.5 |
| winrate_10_diff | wr10_p1 - wr10_p2; wr = weighted win rate, weight = exp(-days/14) |
| odds_diff | (imp1 - imp2) / (imp1 + imp2), imp = 1/odds |
| h2h_count | Количество очных встреч |

### Tempo (быстрые/медленные игроки)

| Фича | Описание |
|------|----------|
| avg_sets_per_match_diff | Среднее сетов за матч (P1 - P2) |
| sets_over35_rate_diff | Доля матчей >3.5 сетов |

### Streak и momentum

| Фича | Описание |
|------|----------|
| streak_score | min(5, win_streak) − min(5, loss_streak) для P1 минус для P2 |
| momentum_today_diff | (wins - losses) сегодня, P1 - P2 |

### Время и плотность

| Фича | Формула |
|------|---------|
| minutes_since_last_match_diff | mins_p2 - mins_p1 (минуты с последнего матча до cutoff) |
| matches_last_1h/3h/6h/today | Количество матчей игрока за 1ч, 3ч, 6ч, с начала дня |
| minutes_to_match | (start_time - as_of_time).total_seconds() / 60 |
| fatigue_index | matches_last_1h×12 + matches_last_3h×8 + matches_last_6h×4 + matches_today×1.5 |
| fatigue_index_diff | fatigue_index_p2 - fatigue_index_p1 |
| fatigue_decay | matches_last_3h×10 + matches_last_6h×5 + matches_today×2 |
| fatigue_ratio | fatigue_p1 / (fatigue_p2 + 1) |
| odds_shift | odds_open / odds_current. > 1.1 — рынок уже что-то знает |

### Доминирование и волатильность

| Фича | Формула |
|------|---------|
| dominance_diff | points_won / total_points за последние 10 матчей (P1 - P2) |
| dominance_last_50_diff | points_won / total_points за ~50 сетов (стабильнее) |
| std_points_diff_last10_p1/p2 | std(point_diff) по последним 10 матчам |
| std_sets_last10_p1/p2 | std(total_sets) по последним 10 матчам |

### Поведение по сетам

| Фича | Описание |
|------|----------|
| set1_strength_diff | set1_winrate - overall_winrate |
| comeback_rate_diff | Доля матчей «проиграл 1-й сет, выиграл матч» |

### Odds extended

| Фича | Описание |
|------|----------|
| log_odds_ratio | log(odds_p2 / odds_p1) |
| implied_prob_p1/p2 | 1/odds |
| market_margin | (1/odds_p1 + 1/odds_p2) - 1 |

### Типы матчей (прибыльные)

| Фича | Описание |
|------|----------|
| is_repeat_meeting | Игроки играли вчера |
| is_series_match | Игрок играет 8+ матчей за день |
| style_mismatch | \|avg_sets_p1 - avg_sets_p2\| (attacker vs defender proxy) |
| hours_since_last_h2h | Часы с последней очной встречи (< 24h — сильный сигнал) |
| daily_performance_trend | win_rate_last_3 − win_rate_today (trend < −0.3 → сливает, confidence ↓) |
| matchup_strength | Σ(won × exp(-days/30)) / Σ(exp(-days/30)) по H2H |
| matches_played_p1/p2 | Количество матчей игрока (min >= 100) |
| closing_line_value | odds_open / odds_close (из таблицы odds по match_id) |

### Лиги

| Фича | Описание |
|------|----------|
| league_avg_sets | Среднее сетов в лиге за год |
| league_strength | Placeholder |
| league_avg_point_diff | Placeholder |

---

## 8. Inference (расчёт прематча)

### Цепочка вызова

```
API / Карточка матча / forecast_v2_pipeline
    → ml_scorer.score_match_for_forecast(event)
    → ml.inference.predict_for_upcoming(home_id, away_id, league_id, odds, start_time, match_id)
```

### Шаги `predict_for_upcoming`

1. **Проверка игроков** — если home_id/away_id нет в `players`, возвращается `None`.

2. **FeatureEngine.compute_for_match** — фичи по данным **до** start_time (`cutoff = start_time - 1 sec`).

3. **Основной путь** (приоритет): LightGBM/XGBoost **p_set** → Monte Carlo 20k → p_match, p_set1, p_set2.

4. **Fallback** (если set-модель недоступна): ручная формула **p_point** → Monte Carlo:
   - см. раздел «Формула p_point (fallback)» ниже
   - `run_monte_carlo(p_point, 20_000)` → p_match, p_set1, p_set2

5. **ValueDetector** — EV = P×Odds - 1 > 0.08.

6. **SignalFilter** — P>0.72, EV>0.08, edge>0.08, confidence>0.7, sample_size≥50, odds 1.6–2.6, **league_passes_filter**.

7. **Confidence** — снижается при высокой волатильности (std_points_diff, elo_volatility) и при upset_rate лиги > 40%.

8. **Suspicious** — проверка `suspicious_matches` по match_id.

### Формула p_point (fallback)

```
logit = 0.004 × elo_diff
     + 1.8 × form_diff
     + 0.9 × momentum_diff
     + 0.5 × (fatigue_decay_diff / 25)
     + 0.6 × (h2h_diff × 2) × h2h_mult
     + 0.4 × (matchup_strength_diff × 2)

h2h_mult = 1.0 + max(0, (24 - min(24, hours_since_last_h2h)) / 24) × 0.5   # 1.0–1.5
fatigue_decay = matches_last_3h×10 + matches_last_6h×5 + matches_today×2

p_point = sigmoid(logit) = 1 / (1 + exp(-logit))
```

### Monte Carlo (из p_set)

При наличии set-модели: каждый сет = Bernoulli(p_set). Симуляция матча до 3 побед в сетах (BO5). 20 000 итераций. Возвращает: p_match, p_set1, p_set2, p_3_0, p_3_1, p_3_2, p_total_over_35.

### Monte Carlo (из p_point, fallback)

При fallback: point-by-point. Сет: первый до 11, разница ≥ 2. Матч: до 3 сетов. Сеты симулируются последовательно.

### Аналитический P_match из P_set

```
P(3-0) = p^3
P(3-1) = 3 × p^3 × (1-p)
P(3-2) = 6 × p^3 × (1-p)^2
P_match = P(3-0) + P(3-1) + P(3-2)
```

Используется в league_performance при симуляции ROI.

---

## 9. Value detection и фильтры

### Формулы

```
EV = P × Odds - 1
implied = 1 / Odds
edge = P_model - implied
```

### Kelly (размер ставки)

```
full_kelly = (P × odds - 1) / (odds - 1)
kelly_capped = clamp(full_kelly, 0, 0.25)
bet_size_fraction = 0.25 × full_kelly   # quarter Kelly
```

### ValueDetector

| Параметр | Значение |
|----------|----------|
| min_ev | 0.08 |
| min_odds | 1.6 |
| max_odds | 2.6 |

Рынки: match, set1, set2. Стороны: p1, p2. Для каждой пары (market, side) проверяется EV ≥ 0.08 и odds в [1.6, 2.6].

### SignalFilter

| Параметр | Значение |
|----------|----------|
| min_probability | 0.72 |
| min_ev | 0.08 |
| min_edge | 0.08 (P_model − P_market) |
| min_confidence | 0.7 |
| min_sample_size | 50 |
| min_player_matches | 100 |
| min_odds | 1.6 |
| max_odds | 2.6 |
| require_league_roi | true |

### league_passes_filter

- `league_roi > 7%` (MIN_LEAGUE_ROI_PCT)
- `league_matches > 500` (MIN_LEAGUE_MATCHES)
- `upset_rate < 40%` (MAX_LEAGUE_UPSET_RATE)

### Confidence score

```
sample_norm = min(1.0, sample_size / 60)
confidence = 0.4×sample_norm + 0.3×stability + 0.2×form_consistency + 0.1×market_agreement - league_penalty
```

- **form_consistency** = `max(0.3, 1 - (std_p1 + std_p2)/20)` — волатильность игроков
- **early_line_boost**: line_age < 90 сек → market_agreement += 0.1 (часто ошибочные коэффициенты)
- **elo_volatility**: если `elo_volatility_p1 + elo_volatility_p2 > 50` → form_consistency × max(0.5, 1 - (sum - 50)/100)
- **league_penalty** = `league_confidence_reduction(league_id)` при upset_rate > 40%
- **daily_performance_trend < -0.3** → confidence × 0.7 (игрок сливает)
- **player_std_sum > 15** → confidence × max(0.5, 1 - (sum - 15)/30)

---

## 10. League ROI tracking

### Таблица league_performance

| Колонка | Описание |
|---------|----------|
| league_id | ID лиги |
| matches | Количество матчей |
| wins, losses | Победы/поражения по симулированным сигналам |
| roi_pct | (profit / stake) × 100 |
| avg_ev, avg_odds | Средние EV и odds |
| upset_rate | underdog_wins / matches |
| underdog_wins | Победы аутсайдера по коэффициентам |

### Фильтр лиг

Сигнал **используется** только если:

- `league_roi > 7%` (MIN_LEAGUE_ROI_PCT)
- `matches > 500` (MIN_LEAGUE_MATCHES)
- `upset_rate < 40%` (MAX_LEAGUE_UPSET_RATE)

### API админки

| Endpoint | Назначение |
|----------|------------|
| `GET /admin/ml/dashboard` | Таблицы (записей), наполнение (%), main→ML сравнение, прогресс, очередь |
| `GET /admin/ml/stats` | matches, match_features, players, leagues |
| `GET /admin/ml/verify` | Сравнение main vs ML (матчи, игроки, лиги) |
| `GET /admin/ml/progress` | Прогресс sync, backfill, retrain, player_stats, league_performance |
| `GET /admin/ml/league-performance` | ROI по лигам (rolling 500) |
| `POST /admin/ml/sync` | Синхронизация матчей (очередь) |
| `POST /admin/ml/backfill-features` | Backfill фичей (очередь) |
| `POST /admin/ml/player-stats` | Backfill player_daily_stats, player_style, player_elo_history (очередь) |
| `POST /admin/ml/league-performance` | Пересчёт league_performance (очередь) |
| `POST /admin/ml/retrain` | Переобучение моделей (очередь) |

---

## 11. Детекция договорных матчей

### Isolation Forest + heuristic fallback

**Isolation Forest**: фичи `[odds_shift, set_pattern, model_error, comeback, point_diff_variance]`. contamination=0.1, n_estimators=100. Сохраняется в `anomaly_isolation_forest.joblib`.

### Heuristic: формула suspicious_score

```
total = 0.2×odds_shift + 0.2×odds_crash + 0.15×reverse_line
      + 0.15×set_pattern + 0.15×absurd_sets + 0.1×comeback + 0.05×model_err
total = min(1.0, total × 1.2)
```

### Признаки (heuristic)

| Признак | Формула / логика |
|---------|------------------|
| **odds_shift** | \|open - close\| > 0.7 → 0.5 + (shift - 0.7); иначе shift/0.7 |
| **odds_crash** | (open - close)/open > 0.4 → 0.6 + (drop - 0.4) |
| **reverse_line** | Фаворит по open стал аутсайдером по close, но проиграл → 0.9 |
| **set_pattern** | alternations / (len-1) × 1.5 — чередование побед по сетам |
| **absurd_sets** | Сеты с разницей ≥ 8 (11-2, 11-3). ≥2 таких + alternations → 0.5 + count×0.2 |
| **comeback** | 0:2 → 3:2 → 0.8 |
| **model_error** | err = 1 - P_model при победе, P_model при поражении; err × 1.5 |
| **point_diff_variance** | std(diffs по сетам) / 15 |

### Порог

`suspicious_score ≥ 0.65` (SUSPICIOUS_THRESHOLD) → матч в `suspicious_matches`.

### API

При отображении карточки матча: `suspicious`, `suspicious_score`, `suspicious_reason`.

---

## 12. Построение датасета (без data leakage)

### Pipeline

1. Матч: `match_time = m.start_time`
2. Только данные до матча: `cutoff = start_time - 1 sec`
3. Фичи: `features = compute_for_match(p1, p2, start_time, ...)`
4. Target: `target_match = 1/0`, `target_set1 = 1/0` (из match_sets)

### backfill_features_once

- Для каждого матча без фичей вызывается `FeatureEngine.compute_for_match` с `cutoff = start_time - 1s`
- Фичи сохраняются в `match_features`
- **Нет leakage**: Elo, form, H2H считаются только по матчам до текущего

---

## 13. Модели

### Архитектура

- **Основной путь**: LightGBM/XGBoost **p_set** → Monte Carlo 20k → p_match, p_set1, p_set2
- **Fallback**: p_point_from_features → Monte Carlo
- **P_match** — из Monte Carlo (сеты не независимы)
- **Калибровка**: CalibratedClassifierCV (method=sigmoid, Platt scaling)
- **GroupKFold(5)** по player1_id при калибровке (если ≥5 уникальных игроков)
- **scale_pos_weight** = (y==0).sum() / max(1, (y==1).sum()) — балансировка

### XGBoost (если доступен)

```
objective=binary:logistic, eval_metric=auc
max_depth=6, learning_rate=0.05, n_estimators=300
tree_method=hist, device=cuda|cpu
```

### LightGBM (fallback при отсутствии XGB)

```
objective=binary, metric=auc
num_leaves=31, learning_rate=0.05, n_estimators=300
device=cuda|cpu
sample_weight=balanced
```

### Set-level обучение

`load_set_training_data`: все сеты из match_sets + match_features. target_set = 1 если P1 выиграл сет. Ловит нелинейные взаимодействия (fatigue×league, elo×volatility).

### FEATURE_COLS (для обучения и inference)

```
# Базовые
elo_diff, form_diff, fatigue_diff, h2h_diff, winrate_10_diff, odds_diff, h2h_count
# Tempo, streak
avg_sets_per_match_diff, sets_over35_rate_diff, streak_score,
minutes_since_last_match_diff, dominance_diff
# Volatility
std_points_diff_last10_p1, std_points_diff_last10_p2, elo_volatility_diff
# Odds
log_odds_ratio, implied_prob_p1, market_margin
# Momentum, sets
momentum_today_diff, set1_strength_diff, comeback_rate_diff
# Сильные фичи v3
dominance_last_50_diff, fatigue_index_diff, fatigue_ratio, minutes_to_match,
odds_shift_p1, odds_shift_p2, daily_performance_trend_diff,
dominance_trend_diff, style_clash
```

### Сохранение

- `ML_MODEL_DIR/tt_ml_v1_match.joblib`, `tt_ml_v1_set1.joblib` (CalibratedClassifierCV)
- `tt_ml_v1_meta.json` — version, features

---

## 14. Обновление данных и переобучение

### ml_sync_loop (каждые 10 мин по умолчанию)

**ML только читает из main DB.** BetsAPI не используется. Все таблицы заполняются автоматически:

1. sync_leagues_to_ml, sync_players_to_ml
2. sync_finished_to_ml_once (90 дней) или полный sync при первом запуске
3. backfill_duration_from_main_once → matches.duration_minutes
4. backfill_odds_from_main_once → odds (из main.odds_1/odds_2)
5. backfill_features_once → match_features
6. check_suspicious_matches_once → suspicious_matches
7. backfill_player_daily_stats_once → player_daily_stats
8. backfill_player_style_once → player_style
9. backfill_player_elo_history_once → player_elo_history
10. update_league_performance_once → league_performance (rolling 500 matches)
11. retrain_models_if_needed — если synced ≥ 500 или features_added ≥ 500

### ml_worker (очередь)

Задачи: `sync`, `backfill`, `retrain`, `league_performance`, `player_stats`

### Админка

- **GET /admin/ml/dashboard** — таблицы, наполнение (%), main→ML сравнение, прогресс, очередь
- **POST /admin/ml/player-stats** — backfill player_daily_stats, player_style, player_elo_history

### Конфиг

| Параметр | По умолчанию |
|----------|--------------|
| ml_sync_interval_sec | 600 (10 мин) |
| ml_sync_days_back | 0 (весь архив) |
| ml_sync_batch_size | 3000 |
| ml_retrain_min_new_matches | 500 |

---

## 15. Pick selector и KPI guard

### select_pick

Кандидаты: match/set1/set2 × home/away. Фильтр: `odds ≥ min_odds`, `confidence ≥ min_confidence_pct`, `edge ≥ min_edge_pct`.

**Сортировка** (по убыванию):
1. quality_tier (A ≥ 0.75, B ≥ 0.55, C ≥ 0.35, D иначе)
2. value_score = edge_pct + odds_bonus (odds 1.6–2.5: bonus = (capped - 1.6) × 1.5)
3. confidence_score
4. market: match выше set1/set2

**confidence_score** = probability_pct × (0.4 + 0.6 × quality_score)

### quality_score (ml_scorer)

```
quality_score = 0.65 × min(1, sample_size/60) + 0.35 × min(1, h2h_count/12)
```

### KPI guard (динамические пороги)

Корректирует `dynamic_min_confidence_pct` и `dynamic_min_edge_pct` по результатам за 24ч:

| Условие | Действие |
|---------|----------|
| picks_ratio < 0.5 | conf −2, edge −0.7 |
| picks_ratio < 0.8 | conf −1, edge −0.4 |
| picks_ratio > 1.3 и resolved ≥ 30 | conf +0.7, edge +0.2 |
| hit_rate < target | conf +1.2, edge +0.5 |
| hit_rate > target + 4 | conf −0.6, edge −0.2 |

Ограничения: conf ∈ [floor, ceiling], edge ∈ [floor, ceiling]. По умолчанию: base_conf=74%, base_edge=3%.

---

## 16. Где используется ML

| Место | Использование |
|------|---------------|
| Карточка матча (API) | `_compute_ml_analytics` → вероятности, value_signals, features, suspicious |
| forecast_v2_pipeline | Прематч-прогнозы для paid/VIP канала |
| ml_scorer | Скор для выбора pick (select_pick) |

---

## 17. Конфиг (прогнозы и ML)

| Параметр | По умолчанию |
|----------|--------------|
| betsapi_table_tennis_forecast_min_minutes_before | 60 |
| betsapi_table_tennis_forecast_max_minutes_before | 180 |
| betsapi_table_tennis_forecast_delay_minutes | 5 |
| betsapi_table_tennis_early_scan_interval_sec | 600 |
| betsapi_table_tennis_min_odds_for_forecast | 1.6 |
| betsapi_table_tennis_v2_base_min_confidence | 74.0 |
| betsapi_table_tennis_v2_base_min_edge | 3.0 |
| betsapi_table_tennis_v2_target_hit_rate | 85.0 |
| betsapi_table_tennis_v2_target_picks_per_day | 300 |
| betsapi_table_tennis_v2_min_confidence_floor | 68.0 |
| betsapi_table_tennis_v2_min_confidence_ceiling | 88.0 |
| betsapi_table_tennis_v2_min_edge_floor | 2.0 |
| betsapi_table_tennis_v2_min_edge_ceiling | 8.0 |
| ml_sync_interval_sec | 600 (10 мин) |
| ml_model_dir | /tmp/pingwin_ml_models |
| ml_use_gpu | true |
| ml_retrain_min_new_matches | 500 |
| ml_sync_batch_size | 3000 |

---

## 18. Миграции

```bash
psql -d pingwin_ml -f ml_db/init/schema/02_ml_schema.sql
psql -d pingwin_ml -f ml_db/init/schema/03_ml_features_v2.sql
psql -d pingwin_ml -f ml_db/init/schema/04_suspicious_matches_v2.sql
psql -d pingwin_ml -f ml_db/init/schema/05_league_performance.sql
psql -d pingwin_ml -f ml_db/init/schema/06_player_daily_stats.sql
psql -d pingwin_ml -f ml_db/init/schema/07_player_style.sql
psql -d pingwin_ml -f ml_db/init/schema/08_player_elo_history.sql
psql -d pingwin_ml -f ml_db/init/schema/09_add_duration_to_matches.sql
psql -d pingwin_ml -f ml_db/init/schema/10_ml_features_v3_strong.sql
```

Или: `./ml_db/scripts/create_ml_db_standalone.sh`

---

## 19. Модули ML

| Модуль | Назначение |
|--------|------------|
| `feature_engine.py` | MatchFeatures, compute_for_match, upsert_match_features |
| `model_trainer.py` | load_training_data, train, calibrate, save/load models |
| `inference.py` | predict_for_upcoming, p_point→Monte Carlo, value_signals |
| `probability.py` | p_point_from_features, run_monte_carlo, p_match_from_p_set_analytical |
| `value_detector.py` | ValueDetector, expected_value, kelly_fraction |
| `signal_filter.py` | SignalFilter, confidence_score, volatility_filter |
| `league_performance.py` | get_league_stats, update_league_performance_once (rolling 500) |
| `player_stats.py` | backfill_player_daily_stats, backfill_player_style, backfill_player_elo_history |
| `anomaly.py` | compute_suspicion_score, save_suspicious, is_match_suspicious |
| `pipeline.py` | sync, backfill_duration, backfill_features, check_suspicious, Elo+ update |
| `worker_cli.py` | sync, backfill, retrain, league-performance, player-stats |
