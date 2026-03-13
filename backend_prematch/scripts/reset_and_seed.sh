#!/usr/bin/env sh
# Сброс данных и заполнение тестовыми. Миграции должны быть применены (alembic upgrade head).
# Использование: ./scripts/reset_and_seed.sh
# В Docker: docker compose exec backend sh scripts/reset_and_seed.sh
set -e
cd "$(dirname "$0")/.."
echo "Running migrations (ensure all tables exist)..."
uv run alembic upgrade head
echo "Seeding test data (truncates leagues, players, matches, signals, etc.; keeps users)..."
uv run python scripts/seed_test_data.py
echo "Done."
