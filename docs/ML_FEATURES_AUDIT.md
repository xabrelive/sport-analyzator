# ML Features Audit: полный список фич для TT

## 1. Сравнение: что есть vs что нужно

### A. Рейтинг игрока (Elo++)

| Фича | Статус | Комментарий |
|------|--------|-------------|
| elo_global | ✅ | `player_ratings.rating` |
| elo_league | ❌ | Нет отдельного Elo по лиге |
| elo_surface | ❌ | TT без surface |
| elo_last30days | ❌ | Нет |
| elo_last7days | ❌ | Нет |
| elo_diff | ✅ | P1 - P2 |
| elo_trend_7d | ❌ | Нет |
| elo_trend_30d | ❌ | Нет |
| elo_volatility | ❌ | Нет |
| elo_vs_opponent_style | ❌ | Нет |

### B. Форма игрока

| Фича | Статус | Комментарий |
|------|--------|-------------|
| winrate_5 | ✅ | wr5_p1, wr5_p2 внутри form |
| avg_points_diff_5 | ❌ | Нет отдельно |
| sets_winrate_5 | ❌ | Нет |
| comeback_rate_5 | ❌ | Нет |
| winrate_10 | ✅ | winrate_10_diff |
| avg_points_diff_10 | ⚠️ | Есть point_diff в history, но не в фичах |
| sets_winrate_10 | ⚠️ | Частично через dominance |
| winrate_20 | ❌ | Только 10 |
| dominance_index_20 | ❌ | Только 10 |
| form_diff | ✅ | 0.4×wr5 + 0.3×wr10 + 0.3×dominance |

### C. Momentum (критическая фича)

| Фича | Статус | Комментарий |
|------|--------|-------------|
| wins_today | ✅ | wins_today_p1/p2 |
| losses_today | ✅ | Через wins_today (wins - losses) |
| momentum_today_diff | ✅ | (wins - losses) P1 - P2 |
| sets_diff_today | ❌ | Нет |
| points_diff_today | ❌ | Нет |

### D. Усталость

| Фича | Статус | Комментарий |
|------|--------|-------------|
| matches_24h | ⚠️ | fatigue_p1/p2 (матчи за 24ч × 12) |
| matches_12h | ❌ | Нет |
| matches_6h | ✅ | matches_last_6h_p1/p2 |
| matches_3h | ✅ | matches_last_3h_p1/p2 |
| matches_today | ✅ | matches_today_p1/p2 |
| minutes_played_today | ❌ | Нет |
| fatigue_index | ⚠️ | Упрощённый (24h × 12) |

### E. Head-to-Head

| Фича | Статус | Комментарий |
|------|--------|-------------|
| h2h_matches | ✅ | h2h_count |
| h2h_winrate | ✅ | h2h_p1_wr, h2h_diff |
| h2h_last5 | ❌ | Нет |
| h2h_points_diff | ❌ | Нет |
| h2h_sets_diff | ❌ | Нет |

### F. Поведение по сетам

| Фича | Статус | Комментарий |
|------|--------|-------------|
| set1_winrate | ✅ | Через set1_strength |
| set1_strength | ✅ | set1_winrate - overall_winrate |
| set2_winrate | ❌ | Нет |
| set3/4/5_winrate | ❌ | Нет |

### G. Comeback способность

| Фича | Статус | Комментарий |
|------|--------|-------------|
| comeback_rate | ✅ | comeback_rate_p1/p2, comeback_rate_diff |

### H. Доминирование

| Фича | Статус | Комментарий |
|------|--------|-------------|
| avg_points_diff | ⚠️ | В dominance (points_won/total) |
| avg_sets_diff | ⚠️ | Через avg_sets_per_match |
| dominance_diff | ✅ | points_won / total_points |

### I. Стиль игры

| Фича | Статус | Комментарий |
|------|--------|-------------|
| short_set_rate | ❌ | Нет |
| long_set_rate | ❌ | Нет |
| close_match_rate | ❌ | Нет |

### J. Временные паттерны

| Фича | Статус | Комментарий |
|------|--------|-------------|
| winrate_morning | ❌ | Нет |
| winrate_day | ❌ | Нет |
| winrate_evening | ❌ | Нет |

### K. Лиги

| Фича | Статус | Комментарий |
|------|--------|-------------|
| league_strength | ⚠️ | Placeholder 0 |
| league_avg_sets | ✅ | Есть |
| league_avg_point_diff | ⚠️ | Placeholder 0 |
| league_volatility | ❌ | Нет |

### L. Коэффициенты

| Фича | Статус | Комментарий |
|------|--------|-------------|
| odds_p1, odds_p2 | ✅ | Есть |
| implied_prob_p1 | ✅ | Есть |
| implied_prob_p2 | ✅ | Есть |
| odds_diff | ✅ | Есть |
| log_odds_ratio | ✅ | Есть |
| market_margin | ✅ | Есть |
| odds_entropy | ❌ | Нет |

### M. Движение линии

| Фича | Статус | Комментарий |
|------|--------|-------------|
| odds_open | ❌ | Нет (есть только opening) |
| odds_current | ⚠️ | Текущие odds |
| odds_change | ❌ | Нет |
| odds_velocity | ❌ | Нет |

### N. Аномалии

| Фича | Статус | Комментарий |
|------|--------|-------------|
| unexpected_odds_move | ❌ | Нет |
| reverse_line_movement | ❌ | Нет |
| sharp_money_signal | ❌ | Нет |

### O. Психологический фактор

| Фича | Статус | Комментарий |
|------|--------|-------------|
| close_match_winrate | ❌ | Нет |
| tiebreak_winrate | ❌ | TT без тайбрейка |

### P. Стабильность

| Фича | Статус | Комментарий |
|------|--------|-------------|
| performance_std | ✅ | std_points_diff_last10, std_sets_last10 |
| winrate_variance | ❌ | Нет |

### Q. Tempo (уже есть)

| Фича | Статус | Комментарий |
|------|--------|-------------|
| avg_sets_per_match | ✅ | Есть |
| sets_over35_rate | ✅ | Есть |
| streak_score | ✅ | min(5, win) - min(5, loss) |

---

## 2. Построение датасета из архива (без leakage)

### Текущая реализация ✅

```python
# backfill_features_once (pipeline.py)
# Для каждого матча:
#   match_time = m.start_time
#   features = engine.compute_for_match(match_id, p1, p2, start_time, ...)
#   cutoff = start_time - timedelta(seconds=1)  # ТОЛЬКО данные ДО матча
```

**FeatureEngine.compute_for_match**:
- `cutoff = start_time - timedelta(seconds=1)`
- Все запросы: `WHERE m.start_time < :cutoff`
- **Нет data leakage** ✅

### Итоговая таблица

```
match_features (match_id, elo_diff, form_diff, fatigue_diff, h2h_diff, ...)
    JOIN matches (score_sets_p1, score_sets_p2, player1_id, player2_id)
    → target_match = 1/0
    → target_set1 = 1/0 (из match_sets)
```

**target_set2** — пока нет в обучении (p_set2 = p_set1).

---

## 3. Главный трюк: p_point vs P_set

### Два подхода

| Подход | Описание | Реализация |
|--------|----------|------------|
| **p_point** | Logistic → p_point → Monte Carlo → p_set, p_match | Fallback (модели нет) |
| **P_set** | XGBoost → P_set1 → аналитический P_match | Основной путь |

### Текущая логика

1. **Основной**: P_set модель (XGBoost) → P_set1 → `p_match_from_p_set_analytical(p_set1)`
2. **Fallback**: `p_point_from_features(elo, form, fatigue, h2h)` → Monte Carlo 10k → p_match, p_set1, p_set2

### p_point формула (текущая)

```python
logit = elo_diff/400 + form_diff*2 + fatigue_diff*0.01 + h2h_diff*1.5
p_point = sigmoid(logit)
```

Рекомендуемая расширенная:

```python
logit = 0.003*elo_diff + 1.5*form_diff + 0.7*momentum_diff + 0.5*h2h_diff + 0.2*fatigue_diff
```

---

## 4. Value detection

### Формула ✅

```
EV = P × Odds - 1
```

### Фильтры ✅

| Параметр | Значение |
|----------|----------|
| P | > 0.72 |
| EV | > 0.08 |
| sample_size | ≥ 30 |
| confidence | ≥ 0.7 |
| odds | 1.6 - 2.4 |

---

## 5. Ожидаемая точность

| Метрика | Целевой диапазон |
|---------|------------------|
| Match winner | 72–78% |
| Set1 | 70–75% |

---

## 6. Приоритеты для добавления

### Высокий приоритет (реализовано ✅)

1. **momentum_today** — wins_today, momentum_today_diff ✅
2. **set1_strength** — set1_winrate - overall_winrate ✅
3. **comeback_rate** — матчи проиграл 1-й сет, но выиграл матч ✅
4. **Monte Carlo** — 30k в fallback ✅
5. **model_set2** — отдельная модель для 2-го сета (если есть target_set2) — TODO

### Средний приоритет

6. **elo_trend** — elo_last7 - elo_last30 (нужны снимки Elo)
7. **player_volatility** — winrate_variance, performance_std
8. **h2h_last5, h2h_sets_diff**
9. **fatigue_index** — matches_24h×5 + matches_12h×10

### Низкий (требует данных)

10. **odds_movement** — odds_open, odds_close, odds_change (нужна история)
11. **player_vs_opponent_cluster** — attacker/defender/balanced (кластеризация)
12. **Временные паттерны** — winrate_by_hour
13. **league_strength** — нормализация по лиге

### Бонус (player cluster)

- **player_vs_opponent_cluster** — +3–5% точности при наличии кластеров

---

## 7. Схема данных для новых фич

| Фича | Источник данных |
|------|-----------------|
| momentum_today | matches WHERE start_time >= day_start |
| set1_strength | match_sets (set_number=1) + matches |
| comeback_rate | matches (lost set1, won match) |
| elo_trend | player_ratings_history (нужна новая таблица) |
| odds_movement | odds (snapshot_type, created_at) |
