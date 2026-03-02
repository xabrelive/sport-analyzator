# Sport Analyzator Backend

FastAPI + Celery workers for table tennis (and other sports) odds and probability.

## После первого запуска (Docker)

1. **Миграции** применяются при старте (`alembic upgrade head`).

2. **Тестовые данные для главной (лайв, линия, статистика):** выполните один раз:
   ```bash
   docker compose exec backend uv run python scripts/seed_test_data.py
   ```
   Проверить наличие данных: `docker compose exec backend uv run python scripts/check_db.py`

3. **Тестовый пользователь** для входа по почте: **test@example.com** / **test123** (создаётся сидом, уже подтверждён).
