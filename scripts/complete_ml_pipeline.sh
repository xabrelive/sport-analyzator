#!/bin/bash
# Дозаполнение ML-таблиц, переобучение, проверка.
# Использование: ./scripts/complete_ml_pipeline.sh
# Если ML пустая — используйте ./scripts/bootstrap_ml_full.sh
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Остановка старых run-контейнеров ==="
docker compose stop ml_worker 2>/dev/null || true
for c in $(docker ps -q -f "name=ml_worker-run" 2>/dev/null); do docker stop "$c" 2>/dev/null || true; done

echo ""
echo "=== 2. Текущее состояние ML-таблиц ==="
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "
SELECT 'matches' as tbl, COUNT(*) FROM matches
UNION ALL SELECT 'match_features', COUNT(*) FROM match_features
UNION ALL SELECT 'league_performance', COUNT(*) FROM league_performance;
" 2>/dev/null

ML_MATCHES=$(docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "SELECT COUNT(*) FROM matches;" 2>/dev/null | tr -d ' ')
if [ "${ML_MATCHES:-0}" -lt 100 ]; then
  echo ""
  echo "ВНИМАНИЕ: ML почти пустая (matches=${ML_MATCHES:-0}). Сначала sync!"
  echo "=== 2b. Синхронизация main→ML (лиги, игроки, матчи) ==="
  ./scripts/ml_run_gpu.sh python -m app.ml.worker_cli sync --limit 200000 --days-back 0 --full 2>&1
  echo ""
  echo "=== 2c. Player stats ==="
  ./scripts/ml_run_gpu.sh python -m app.ml.worker_cli player-stats --limit 50000 2>&1
fi

echo ""
echo "=== 3. Backfill оставшихся фичей (6 workers) ==="
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli backfill --limit 300000 --workers 6 2>&1

echo ""
echo "=== 4. Переобучение моделей (GPU) ==="
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli retrain --min-rows 10000 2>&1

echo ""
echo "=== 5. League performance ==="
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli league-performance --limit 100000 2>&1

echo ""
echo "=== 6. Запуск ml_worker и tt_workers ==="
docker compose up -d ml_worker tt_workers 2>&1

echo ""
echo "=== 7. Итоговое состояние таблиц ==="
sleep 3
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "
SELECT 'matches' as tbl, COUNT(*) FROM matches
UNION ALL SELECT 'match_features', COUNT(*) FROM match_features
UNION ALL SELECT 'league_performance', COUNT(*) FROM league_performance;
" 2>/dev/null

echo ""
echo "=== 8. Проверка моделей ==="
docker run --rm -v sport-analyzator_pingwin_ml_models:/mnt alpine ls -la /mnt/*.json /mnt/*.joblib 2>/dev/null || echo "Модели не найдены"

echo ""
echo "Готово. tt_workers (ml_sync_loop, forecast_v2_loop) продолжат автодогрузку и прогнозы."
