"""
Очистка тестовых данных из БД. Таблицы users не трогаем.
После запуска можно собирать реальные данные (например, из BetsAPI).

Порядок из-за FK. Запуск:
  uv run python scripts/clear_test_data.py
  docker compose exec backend uv run python scripts/clear_test_data.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:5432/sport_analyzator")

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.config import settings

db_url = settings.database_url
if "+" in (db_url.split("//")[1] if "//" in db_url else ""):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)
session_factory = sessionmaker(engine, autocommit=False, autoflush=False)


def clear_test_data(session: Session) -> None:
    session.execute(text("TRUNCATE TABLE signals RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE match_results RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE odds_snapshots RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE match_scores RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE matches RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE leagues RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE players RESTART IDENTITY CASCADE"))
    session.commit()
    print("Cleared: signals, match_results, odds_snapshots, match_scores, matches, leagues, players. Users kept.")


def main() -> None:
    with session_factory() as session:
        clear_test_data(session)


if __name__ == "__main__":
    main()
