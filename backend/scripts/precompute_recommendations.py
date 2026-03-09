"""
Один раз пересчитать рекомендации только для матчей в линии/лайве (не для завершённых).
Использует ту же логику, что и воркер precompute_active_recommendations.
Нужно запускать в окружении backend (где установлены все зависимости, в т.ч. celery).

Запуск из каталога backend:
  docker compose exec backend uv run python scripts/precompute_recommendations.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# чтобы импорт app работал
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:11002/sport_analyzator")

from app.worker.tasks.collect_betsapi import _run_recommendations_backfill_async


def main() -> None:
    active_limit = 5000
    result = asyncio.run(_run_recommendations_backfill_async(active_limit=active_limit))
    print(
        f"Кандидатов: {result.get('candidates', 0)}, "
        f"без рекомендации: {result.get('missing_before', 0)}, "
        f"создано рекомендаций: {result.get('created', 0)}"
    )


if __name__ == "__main__":
    main()
