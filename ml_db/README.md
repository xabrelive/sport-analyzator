# ML Database & Pipeline

Вторая база `pingwin_ml` для ML-моделей: Elo, фичи, XGBoost/LightGBM, Monte Carlo, Value-сигналы, аномалии.

## Быстрый старт

### 1. Создать БД (если postgres уже запущен)

```bash
./ml_db/scripts/create_ml_db_standalone.sh
```

При первом `docker compose up` БД создаётся автоматически.

### 2. Синхронизация данных

```bash
cd backend && python -m asyncio -c "
from app.ml.pipeline import sync_finished_to_ml_once
import asyncio
r = asyncio.run(sync_finished_to_ml_once(limit=1000))
print(r)
"
```

Или через скрипт:

```bash
python ml_db/scripts/sync_and_features.py --limit 1000
```

### 3. Расчёт фичей (match_features)

Скрипт `sync_and_features.py` также делает backfill фичей. Или отдельно:

```bash
python ml_db/scripts/sync_and_features.py --features-only
```

### 4. Обучение моделей (GPU)

```bash
python ml_db/scripts/train_models.py --limit 50000 --version v1
```

Без GPU: `--no-gpu`

Модели сохраняются в `ML_MODEL_DIR` (по умолчанию `/tmp/pingwin_ml_models`).

### 5. Переменные окружения

- `DATABASE_URL_ML` — подключение к pingwin_ml
- `ML_MODEL_DIR` — каталог сохранения моделей
- `ML_SYNC_INTERVAL_SEC` — интервал синхронизации в воркере (0 = отключено)
- `ML_SYNC_DAYS_BACK` — 0 = весь архив, иначе N дней назад (по умолчанию 0)

## Архитектура

```
table_tennis_line_events (finished) → sync → pingwin_ml (matches, players, match_sets, odds)
                                                    ↓
                                            Feature Engine (Elo, form, fatigue, H2H)
                                                    ↓
                                            match_features
                                                    ↓
                                            XGBoost/LightGBM (GPU)
                                                    ↓
                                            Probability Engine + Monte Carlo
                                                    ↓
                                            Value Detector → Signal Filter
                                                    ↓
                                            signals / Telegram
```

## GPU

1. Установи nvidia-container-toolkit: `sudo nvidia-ctk runtime configure --runtime=docker`
2. Перезапусти Docker: `sudo systemctl restart docker`
3. Запуск с GPU: `./scripts/run-with-gpu.sh up -d` или
   `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`
4. `ML_USE_GPU=true` — XGBoost использует `device=cuda` при обучении

Без GPU-оверрайда backend работает на CPU (nvidia-smi недоступен в контейнере).
