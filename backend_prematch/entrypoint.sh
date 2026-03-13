#!/bin/sh
set -e
cd /app
if [ -n "$DATABASE_URL" ]; then
  uv run alembic upgrade head
fi
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 12000
