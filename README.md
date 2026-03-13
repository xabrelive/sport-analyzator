# Sport Analyzator (PingWin)

Настольный теннис: линия, лайв, ML-прогнозы (XGBoost + Monte Carlo), value-сигналы.

## Запуск (Docker, GPU)

```bash
cp .env.example .env   # отредактировать TELEGRAM_BOT_TOKEN, BETSAPI_TOKEN и др.
./up.sh                # docker compose up -d с GPU
```

**Порты:** frontend 11000, backend 11001, postgres 11002.

**Без GPU:** `SKIP_GPU=1 ./up.sh`

**Требования:** [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). При ошибке `nvidia-persistenced/socket`: `sudo nvidia-smi -pm 0`.

**Удаление папки old/ (если есть):** `sudo rm -rf old/`

## Сервисы

- **postgres** — основная БД + pingwin_ml (ML-модели, Elo, фичи)
- **backend** — FastAPI (без воркеров при RUN_BACKGROUND_WORKERS=false)
- **frontend** — Next.js
- **telegram_bot** — бот и каналы
- **tt_workers** — BetsAPI (линия, лайв, odds), **автодогрузка main→ML** (ml_sync_loop каждые 60 сек), прогнозы
- **ml_worker** — очередь ML-задач (Full rebuild, backfill, retrain)

**Важно:** для автодогрузки данных в ML-базу должны быть запущены **tt_workers** и **ml_worker**.
