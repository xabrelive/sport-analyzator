# Sport Analyzator (PingWin)

Настольный теннис: линия, лайв, ML-прогнозы (XGBoost + Monte Carlo), value-сигналы.

## Запуск (Docker, GPU)

```bash
cp .env.example .env   # отредактировать TELEGRAM_BOT_TOKEN, BETSAPI_TOKEN и др.
./up.sh                # docker compose up -d с GPU
```

**Порты:** frontend 12000, backend (в контейнере 12000, с хоста 12001), postgres 12002→12000, redis 12003→12000.

**Без GPU:** `SKIP_GPU=1 ./up.sh`

**Требования:** [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). При ошибке `nvidia-persistenced/socket`: `sudo nvidia-smi -pm 0`.

**Удаление папки old/ (если есть):** `sudo rm -rf old/`

### Сброс БД (таблицы создадутся заново при старте)

- **Только БД:** `./scripts/reset-db.sh` — удаляет базу `sport_analyzator`, создаёт её заново и перезапускает backend (alembic при старте создаст все таблицы).
- **Полный сброс данных Postgres (включая объём):** `docker compose down && docker volume rm sport-analyzator_postgres_data && docker compose up -d` — после этого при первом старте БД и таблицы создадутся заново.

## Сервисы

- **postgres** — основная БД + pingwin_ml (ML-модели, Elo, фичи)
- **backend** — FastAPI (без воркеров при RUN_BACKGROUND_WORKERS=false)
- **frontend** — Next.js
- **telegram_bot** — бот и каналы
- **tt_workers** — BetsAPI (линия, лайв, odds), **автодогрузка main→ML** (ml_sync_loop каждые 60 сек), прогнозы
- **ml_worker** — очередь ML-задач (Full rebuild, backfill, retrain)

**Важно:** для автодогрузки данных в ML-базу должны быть запущены **tt_workers** и **ml_worker**.
