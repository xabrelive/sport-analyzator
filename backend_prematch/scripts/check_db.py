"""
Проверка наличия данных в БД (матчи в линии, лайве, пользователи).
Если запланированных матчей нет — напоминает запустить seed_test_data.py.

Запуск: uv run python scripts/check_db.py
В Docker: docker compose exec backend uv run python scripts/check_db.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:12002/sport_analyzator")

from sqlalchemy import create_engine, text

from app.config import settings

db_url = settings.database_url
if "+" in (db_url.split("://")[1] if "://" in db_url else ""):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)


def main() -> None:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM matches WHERE status = 'scheduled'"))
        scheduled = r.scalar() or 0
        r = conn.execute(text("SELECT COUNT(*) FROM matches WHERE status = 'live'"))
        live = r.scalar() or 0
        r = conn.execute(text("SELECT COUNT(*) FROM leagues"))
        leagues = r.scalar() or 0
        r = conn.execute(text("SELECT COUNT(*) FROM players"))
        players = r.scalar() or 0
    print(f"В БД: scheduled (линия)={scheduled}, live={live}, leagues={leagues}, players={players}")
    if scheduled == 0 or live == 0:
        print("Чтобы на главной отображались матчи в лайве и в линии, выполните:")
        print("  docker compose exec backend uv run python scripts/seed_test_data.py")
        print("или локально: uv run python scripts/seed_test_data.py")
        sys.exit(1)
    print("OK, данных достаточно для отображения на главной.")


if __name__ == "__main__":
    main()
