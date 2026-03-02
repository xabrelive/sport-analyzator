# Sport Analyzator — настольный теннис

Сервис сбора данных, расчёта вероятностей, поиска value и сигналов для настольного тенниса.

## Стек

- **Backend:** Python 3.12+, FastAPI
- **БД:** PostgreSQL 16
- **Кэш/очередь:** Redis 7
- **Планировщик:** Celery + Redis
- **Telegram:** отдельный сервис (python-telegram-bot)
- **Frontend:** Next.js 14, Tailwind, WebSocket

## Архитектура

```
Sports Data API / Odds API
         ↓
   Data Collectors (Celery)
         ↓
      Redis Queue
         ↓
     Normalizer
         ↓
    PostgreSQL
         ↓
Probability Engine ← → Value Detector → Signal Engine
         ↓                    ↓
    Backend API          Telegram Bot
         ↓
   Frontend (Live UI)
```

## Запуск

```bash
cp .env.example .env
# Заполнить API-ключи и TELEGRAM_BOT_TOKEN

docker compose up -d postgres redis
cd backend && uv sync && alembic upgrade head
uv run uvicorn app.main:app --reload

# В другом терминале — воркеры
cd backend && celery -A app.worker.celery_app worker -l info
cd backend && celery -A app.worker.celery_app beat -l info

# Frontend
cd frontend && pnpm install && pnpm dev

# Telegram bot
cd telegram_bot && uv run python -m app.main
```

## Структура

- `backend/` — FastAPI, модели, API, коллекторы, нормализатор, probability/value/signal engine
- `telegram_bot/` — бот для рассылки сигналов
- `frontend/` — админка с live-таблицей матчей

## Этапы

1. **Сбор данных** — коллекторы (Sportradar, The Odds API), нормализатор, очередь
2. **Хранение** — PostgreSQL (matches, sets, odds_history, results)
3. **Вероятности** — Beta-Bayes + марковская модель сета
4. **Value** — EV = (P × odds) − 1, порог
5. **Сигналы** — фильтры, отправка в Telegram
6. **Фронт** — Live / Upcoming / Finished, WebSocket, цветовая индикация value
