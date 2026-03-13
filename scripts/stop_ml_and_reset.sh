#!/bin/bash
# Остановить все ML-процессы и сбросить прогресс на фронте.
# Использование: ./scripts/stop_ml_and_reset.sh
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Остановка ml_worker и ml_worker-run ==="
docker compose stop ml_worker 2>/dev/null || true
for c in $(docker ps -q -f "name=ml_worker" 2>/dev/null); do
  echo "  Останавливаю $c"
  docker stop "$c" 2>/dev/null || true
done

echo ""
echo "=== 2. Сброс progress.json (фронт покажет «idle» вместо «обучение») ==="
IDLE_JSON='{"sync":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null},"backfill":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null},"retrain":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null},"league_performance":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null},"player_stats":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null},"full_rebuild":{"status":"idle","message":"","current":0,"total":0,"result":null,"error":null}}'
docker run --rm -v sport-analyzator_pingwin_ml_models:/mnt alpine sh -c "echo '$IDLE_JSON' > /mnt/progress.json && echo '  progress.json сброшен'"

echo ""
echo "Если процессы зависли на GPU, завершите их:"
echo "  ./scripts/kill_stuck_ml_gpu.sh"
echo "  # или явно: ./scripts/kill_stuck_ml_gpu.sh 2436296 2450247"
echo ""
echo "=== Готово ==="
echo "Фронт обновится через ~2.5 сек (poll). Можно запускать rebuild с нуля:"
echo "  ./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild --sync-limit 500000 --backfill-limit 600000 --min-rows 500"
echo ""
echo "tt_workers (ml_sync_loop) продолжает работать. Чтобы остановить и его:"
echo "  docker compose stop tt_workers"
