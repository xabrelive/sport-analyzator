# Что нужно увидеть (самое важное) — 6 вещей для поиска проблем ML v2

По этим шести пунктам почти всегда можно найти причину плохого logloss или странного поведения модели.

---

## 1️⃣ Конфигурация LightGBM

**Файл:** `backend/app/ml_v2/trainer.py`, функция `_fit_binary()` (примерно строки 232–320).

**Код params и train:**

```python
params = dict(
    objective="binary",
    metric="binary_logloss",
    learning_rate=float(getattr(settings, "ml_v2_lgb_learning_rate", 0.03)),
    num_leaves=num_leaves,
    max_depth=-1,
    feature_fraction=0.75,
    bagging_fraction=0.8,
    bagging_freq=5,
    min_child_samples=min_child,
    min_child_weight=1e-3,
    reg_alpha=reg_alpha,
    reg_lambda=reg_lambda,
    ...
    n_estimators=3000,
)
model = lgb.LGBMClassifier(**params)
model.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(300), ...])
```

**Важные параметры (дефолты и переопределения):**

| Параметр | Общий дефолт | target_match | target_set1 |
|----------|----------------|--------------|-------------|
| num_leaves | 128 | 150 | 96 |
| min_child_samples | 20 | 20 | 30 |
| learning_rate | 0.03 | 0.03 | 0.03 |
| feature_fraction | 0.75 | 0.75 | 0.75 |
| bagging_fraction | 0.8 | 0.8 | 0.8 |
| n_estimators | 3000 | 3000 | 3000 |
| reg_alpha | 0.5 | 1.0 | 0.7 |
| reg_lambda | 1.5 | 2.5 | 1.8 |

**Где задать в проекте:** `backend/app/config.py` (ml_v2_lgb_*) и `.env` (ML_V2_LGB_*).

**Типичная ошибка:** `min_child_samples=100`, `num_leaves=31` — модель почти не строит деревья. У нас для match жёстче (50/64), для set1 — 30/96.

---

## 2️⃣ Feature list

**Файл:** `backend/app/ml_v2/features.py`.

- **Полный список (113 фич):** `FEATURE_COLS_V2` — строки 22–137.
- **Список для обучения (без мёртвых и избыточных):** `FEATURE_COLS_V2_TRAIN` — строка 169:

```python
FEATURE_COLS_V2_TRAIN = [c for c in FEATURE_COLS_V2 if c not in DEAD_FEATURES and c not in REDUNDANT_ROLLING]
```

- **Исключённые мёртвые фичи:** `DEAD_FEATURES` — строки 141–156 (clock, market, fast_match_ratio_diff, long_match_ratio_diff, long_rally_ratio_diff, match_duration_proxy_diff, league_upset_x_margin).
- **Исключённые избыточные rolling:** `REDUNDANT_ROLLING` — строки 158–165 (winrate_3/5/30_diff, points_ratio_last_30_diff, sets_ratio_last_30_diff).

**Что проверить:** нет ли константных фич, утечки таргета (данных после момента матча), фич, которые почти дублируют друг друга.

---

## 3️⃣ Как считается rolling

**Файл:** `backend/app/ml_v2/features.py`, функция `_compute_player_agg()` (строки 270–520).

**Идея:** не pandas groupby/rolling, а ручной «rolling» по истории игрока до `cutoff` (эквивалент shift(1)).

**Анти-утечка (только прошлое):**

```python
rec = [
    h for h in history
    if h["match_time"] < cutoff and (exclude_match_id is None or h.get("match_id") != exclude_match_id)
]
rec_desc = sorted(rec, key=lambda x: x["match_time"], reverse=True)
last10 = rec_desc[:10]
last20 = rec_desc[:20]
last50 = rec_desc[:50]
# ...
wins10 = _safe_div(sum(h["win"] for h in last10), max(1, len(last10)))
points_ratio10 = _safe_div(points10_w, max(1, points10_w + points10_l), 0.5)
# winrate_10_diff, points_ratio_20_diff, dominance_last_50_diff и т.д. — из этих last*.
```

**Источник истории:** `ml.player_match_stats` (ORDER BY player_id, match_time, match_id). В цикле по матчам для каждого матча вызывается `_compute_player_agg(by_player[p1], ..., cutoff=start_time, exclude_match_id=match_id)`.

**Где используется:** в `rebuild_features_to_ch()` — цикл по `matches`, для каждого матча два вызова `_compute_player_agg` (p1 и p2), затем `_compose_match_features()` формирует фичи типа winrate_*_diff, points_ratio_*_diff, dominance_last_*_diff.

Здесь чаще всего ошибки TT-моделей: убедиться, что в rolling входят только матчи **до** текущего и что текущий матч явно исключён (`exclude_match_id`).

---

## 4️⃣ Как формируется target

**Файл 1 — сырые исходы в sync:** `backend/app/ml_v2/sync.py`, `_insert_events_to_ch()` (строки 178–234).

- **Победитель матча:** `1 if hs > as_ else 0` для player1 (home), `1 if as_ > hs else 0` для player2 (away).  
- **Победитель сета 1:** `set1_win = 1 if sets_data[0][0] > sets_data[0][1] else 0` для home (player1).

В `ml.matches`: player1_id = home_id, player2_id = away_id, score_sets_p1 = hs, score_sets_p2 = as_.  
В `ml.player_match_stats`: для каждой стороны записываются win и set1_win.

**Файл 2 — target в фичах (то, что идёт в модель):** `backend/app/ml_v2/features.py`, в цикле по матчам (строка 976):

```python
# target_match: 1 если P1 (player1_id) выиграл матч по сетам, иначе 0
# target_set1: 1 если P1 выиграл первый сет
out_rows.append([
    ...,
    1 if s1 > s2 else 0,           # target_match
    int(target_set1_by_mid.get(mid, 0))  # target_set1 из ml.match_sets (set_number=1)
])
```

Здесь `s1, s2` — счёт по сетам из строки матча (player1 vs player2). Порядок игроков везде один и тот же: **player1_id, player2_id** из `ml.matches` (в фичах — p1, p2). Идентификация только по **player_id**, не по имени и не по позиции.

**Баланс p1/p2:** для ~50% строк в trainer делается «переворот» (swap): все `*_diff` инвертируются, `fatigue_ratio`/`experience_ratio` → 1/ratio, `fatigue_ratio_log` → −log, bucket'ы p1↔p2, target → 1−target. Так **сигнал не теряется**: связь «больше elo_diff / momentum_today_diff → чаще победа p1» сохраняется, потому что знак фичи и target меняются вместе. Без инверсии ratio-фичей они были бы несогласованы с target на перевёрнутых строках.

---

## 5️⃣ Как формируется train/val/test split

**Файл:** `backend/app/ml_v2/trainer.py`, функция `_split()` (строки 185–207).

**Правильный вариант (temporal, по годам):**

```python
df["_year"] = df["start_time"].dt.year
train = df[(df["_year"] >= 2016) & (df["_year"] <= 2023)]   # train: старые
val_2024 = df[df["_year"] == 2024]                          # val: 2024
test = df[df["_year"] >= 2025]                               # test: новые (2025+)
# если test пустой — половина 2024 в val, половина в test
```

Включено при `ml_v2_split_by_year=True` (config / ML_V2_SPLIT_BY_YEAR).

**Fallback (квантили по времени):** 80% / 10% / 10% по порядку строк (старые → train, следующие 10% → val, последние 10% → test).

**Ошибка:** train = новые, test = старые — модель ломается из-за concept drift. У нас наоборот: train 2016–2023, test 2024+.

---

## 6️⃣ Feature importance

**Файл:** `backend/app/ml_v2/trainer.py`, после `model.fit()` в `_fit_binary()` (строки 351–355):

```python
imp = pd.Series(model.feature_importances_, index=FEATURE_COLS_V2_TRAIN).sort_values(ascending=False).head(12)
logger.info("ML v2 train [%s] top importances: %s", target, imp.to_dict())
print(f"ML v2 train [{target}] top_importances={imp.to_dict()}", flush=True)
```

В логах retrain видно строки вида:  
`ML v2 train [target_match] top_importances={'h2h_diff': 209, 'latent_strength_diff': 134, ...}`.

**Где ещё посмотреть:** в ответе API `GET /api/v1/admin/ml/v2/status` в `progress.retrain.result.validation_metrics` и в сохранённом `tt_ml_v2_meta.json` (если туда дописываются importance). Сами значения importance — у обученной модели: `model.feature_importances_`, порядок — `FEATURE_COLS_V2_TRAIN` (или `model.feature_name_`).

**Плохой признак:** почти все importance = 0 — модель по сути не использует фичи (слишком жёсткая регуляризация, константные фичи или неверный split/target).

---

## Автодиагностика при retrain

При каждом запуске `retrain_models_v2` (и при `full-rebuild`) в stdout выводятся:

1. **target:** mean, distribution (value_counts normalize), корреляция `winrate_20_diff` / `points_ratio_20_diff` / `elo_diff` / `dominance_last_50_diff` с `target_match`. Ожидаем mean ≈ 0.5, корреляции ~0.1–0.25.
2. **LOW VAR:** список фичей с `std < 1e-5` (подозрение на сломанный rolling).
3. **describe:** по колонкам `winrate_10_diff`, `points_ratio_20_diff`, `dominance_last_50_diff` (норма: mean около 0, std > 0).
4. **sample 5 rows:** `match_id`, те же фичи, `target_match` — быстрая проверка, что target не перевёрнут.
5. **best_iteration:** после обучения; если ≤ 1 — выводится предупреждение.
6. **feature_importance top 20:** таблица; если все 0 — выводится предупреждение.

Функция: `_diagnose_training_data(train)` и блок после `model.fit()` в `_fit_binary()` в `backend/app/ml_v2/trainer.py`.

---

## Почему logloss ≈ 0.69 (не лучше случайного) и как добиться 0.50–0.51

**Базовый уровень:** случайный бинарный классификатор даёт logloss = ln(2) ≈ **0.693**. Если val raw_logloss ≥ 0.68, модель по сути не учится.

**Возможные причины:**

1. **Утечка при клипе фичей** — раньше квантили для клипа считались по всему датасету (train+val+test). Исправлено: клип считается **только по train**, затем те же границы применяются к val/test (`_clip_by_train_quantiles` в `trainer.py`).
2. **Слишком жёсткая регуляризация** — для target_match по умолчанию стоят `num_leaves_match=96`, `min_child_match=30` (ранее 64/50). Если logloss всё ещё ~0.69, попробуй в .env: `ML_V2_LGB_NUM_LEAVES_MATCH=128`, `ML_V2_LGB_MIN_CHILD_MATCH=20`, ослабить `ML_V2_LGB_REG_ALPHA_MATCH`/`REG_LAMBDA_MATCH`.
3. **Целевая переменная или баланс** — в диагностике смотри: `target_match mean` ≈ 0.5 после баланса p1/p2; корреляции `elo_diff`, `points_ratio_20_diff` с target ≈ 0.15–0.25. Если корреляции ≈ 0 — либо target неправильный, либо rolling/фичи сломаны.
4. **Сплит по времени** — должен быть строго по годам (train 2016–2023, val 2024, test 2025+). При random split модель «видит будущее» и метрики вводят в заблуждение.
5. **best_iteration = 1** — дерево почти не строится. Обычно из‑за утечки или дисбаланса; проверь список выше и при необходимости ослабь регуляризацию (set1: `num_leaves_set1`, `min_child_set1`).

**Цель 0.50–0.51:** для прематч без лайв-данных обычно недостижима; реалистичный диапазон val/test raw_logloss — **0.64–0.68**. Текущая лучшая конфигурация (test match raw ≈ 0.676): `ML_V2_TRAIN_REQUIRE_H2H=false`, все фичи (`ML_V2_TOP_K_FEATURES=0`), `learning_rate=0.02`, `num_leaves_match=150`, `min_child_match=20`, `reg_alpha_match=0.3`, `reg_lambda_match=1.0`, `ml_lgb_early_stopping_rounds=500`. В логе смотри `best_iteration` (норма 50–400) и train/val/test raw_logloss.

---

## Краткая навигация по файлам

| Что | Файл | Где |
|-----|------|-----|
| 1. Параметры LightGBM | `backend/app/ml_v2/trainer.py` | `_fit_binary()`, params и LGBMClassifier |
| 2. Список фич | `backend/app/ml_v2/features.py` | FEATURE_COLS_V2, DEAD_FEATURES, REDUNDANT_ROLLING, FEATURE_COLS_V2_TRAIN |
| 3. Rolling | `backend/app/ml_v2/features.py` | `_compute_player_agg()`, затем `_compose_match_features()` |
| 4. Target | `backend/app/ml_v2/sync.py` (win/set1_win), `backend/app/ml_v2/features.py` (строка с 1 if s1 > s2 else 0 и target_set1_by_mid) |
| 5. Train/val/test | `backend/app/ml_v2/trainer.py` | `_split()` |
| 6. Feature importance | `backend/app/ml_v2/trainer.py` | после fit в `_fit_binary()`, model.feature_importances_ |

Дополнительно: общая архитектура и конфиги — `docs/ML_V2_TECH_DOC.md`.
