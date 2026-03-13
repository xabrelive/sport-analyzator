#!/bin/bash
# Быстрый ML rebuild: параллельный backfill (6 workers), sync большими батчами.
# Использование: ./scripts/fast_ml_rebuild.sh
set -e
cd "$(dirname "$0")/.."

echo "=== Быстрый ML rebuild (параллельный backfill, большие батчи) ==="
echo "Убедитесь: tt_workers и ml_worker запущены (docker compose up -d)"
echo ""

# Полный цикл с параллельным backfill
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild \
  --sync-limit 200000 \
  --backfill-limit 600000 \
  --player-stats-limit 100000 \
  --league-limit 100000 \
  --min-rows 500 2>&1

echo ""
echo "=== Проверка таблиц ==="
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "
SELECT 'matches' as tbl, COUNT(*) FROM matches
UNION ALL SELECT 'match_features', COUNT(*) FROM match_features
UNION ALL SELECT 'league_performance', COUNT(*) FROM league_performance;
" 2>/dev/null

echo ""
echo "Готово. tt_workers продолжат автодогрузку (ml_sync_loop каждые 60 сек)."
