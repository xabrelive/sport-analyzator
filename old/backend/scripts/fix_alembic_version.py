"""
Приводит таблицу alembic_version в порядок, если в БД записана ревизия,
которой нет в репозитории (например 014_recommendation_outcomes).
После этого можно выполнить: alembic upgrade head

Запуск: из каталога backend:
  uv run python scripts/fix_alembic_version.py
  alembic upgrade head
"""
from __future__ import annotations

import os
import sys

# чтобы подхватить .env
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from sqlalchemy import create_engine, text

from app.config import settings

# синхронный URL для миграций
db_url = settings.database_url
if "asyncpg" in db_url:
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)

# ревизия, на которую откатываем запись в alembic_version (до применения 014_match_recommendations)
STAMP_REVISION = "013_user_subscriptions"


def main() -> None:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT version_num FROM alembic_version"))
        row = r.fetchone()
        if not row:
            print("alembic_version пуста — выполните: alembic stamp 013_user_subscriptions")
            print("затем: alembic upgrade head")
            return
        current = row[0]
        print(f"Текущая ревизия в БД: {current}")

        if current == "014_recommendation_outcomes":
            print(f"Неизвестная ревизия в репозитории. Записываю: {STAMP_REVISION}")
            conn.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": STAMP_REVISION})
            conn.commit()
            print("Готово. Выполните: alembic upgrade head")
        elif current == "014_match_recommendations":
            print("База уже на последней ревизии (014_match_recommendations).")
        else:
            print("Выполните при необходимости: alembic upgrade head")


if __name__ == "__main__":
    main()
