#!/bin/bash
# Заполнение ML-таблиц из исходных данных.
# Запускать после sync (матчи уже в pingwin_ml).
# Использование: ./scripts/backfill_ml_tables.sh [N]
set -e
cd "$(dirname "$0")/.."
LIMIT="${1:-10000}"
echo "Backfill ML tables (limit=$LIMIT)..."
docker compose exec backend python -m app.ml.worker_cli player-stats --limit "$LIMIT"
echo "Done. Run backfill-features via admin API or: python -m app.ml.worker_cli backfill --limit 5000"
