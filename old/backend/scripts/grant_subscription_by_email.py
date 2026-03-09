"""
Выдать подписку пользователю по email (например после оплаты или вручную).
Дни прибавляются к текущей подписке того же типа (суммирование), если она ещё действует.

Пример:
  uv run python scripts/grant_subscription_by_email.py xabre@live.ru 7
  — подписка на 7 дней (tg_analytics + signals, все виды) для xabre@live.ru
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:11002/sport_analyzator")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.models.user_subscription import UserSubscription

db_url = settings.database_url
if "+" in (db_url.split("://")[1] if "://" in db_url else ""):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: grant_subscription_by_email.py <email> <days>")
        print("Example: grant_subscription_by_email.py xabre@live.ru 7")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    try:
        days = int(sys.argv[2])
    except ValueError:
        print("days must be an integer")
        sys.exit(1)
    if days < 1:
        print("days must be >= 1")
        sys.exit(1)

    today = datetime.now(timezone.utc).date()

    with Session(engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            print(f"User not found: {email}")
            sys.exit(1)

        for access_type in ("tg_analytics", "signals"):
            scope = "all"
            sport_key = None
            # Текущая макс. дата окончания по такому же типу — суммируем дни
            q = (
                select(UserSubscription.valid_until)
                .where(
                    UserSubscription.user_id == user.id,
                    UserSubscription.access_type == access_type,
                    UserSubscription.scope == scope,
                    UserSubscription.sport_key.is_(None),
                )
            )
            existing = [row[0] for row in session.execute(q).all()]
            base_date = max(existing) if existing else today
            if base_date < today:
                base_date = today
            valid_until = base_date + timedelta(days=days)

            sub = UserSubscription(
                user_id=user.id,
                access_type=access_type,
                scope=scope,
                sport_key=sport_key,
                valid_until=valid_until,
            )
            session.add(sub)
        session.commit()
        # Показываем итоговую дату (одинакова для обоих типов при одинаковом base)
        print(f"Granted {days}-day subscription (tg_analytics + signals, all) to {email}, valid until {valid_until}")


if __name__ == "__main__":
    main()
