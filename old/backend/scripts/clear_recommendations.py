"""
Очистка сохранённых рекомендаций (match_recommendations).
После запуска рекомендации и статистика по ним обнуляются; воркер пересчитает их
при следующем цикле линии/лайва или по задаче precompute_active_recommendations.

Запуск:
  uv run python scripts/clear_recommendations.py
  docker compose exec backend uv run python scripts/clear_recommendations.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:11002/sport_analyzator")

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.config import settings

db_url = settings.database_url
if "+" in (db_url.split("//")[1] if "//" in db_url else ""):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)
session_factory = sessionmaker(engine, autocommit=False, autoflush=False)


def main() -> None:
    with session_factory() as session:
        r = session.execute(text("SELECT COUNT(*) FROM match_recommendations"))
        count = r.scalar() or 0
        session.execute(text("TRUNCATE TABLE match_recommendations"))
        session.commit()
    print(f"Удалено рекомендаций: {count}")
    print("Статистика (угадано/не угадано) пересчитается после появления новых рекомендаций.")


if __name__ == "__main__":
    main()
