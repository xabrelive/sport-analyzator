#!/bin/bash
# Полный bootstrap ML: sync из main → backfill → retrain → прогнозы.
# ML берёт все данные только из основной БД (tt_workers/backend загружают в main).
# Использование: ./scripts/bootstrap_ml_full.sh
# Требует: nvidia-container-toolkit для GPU (если используется).
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Запуск postgres и backend ==="
docker compose up -d postgres
sleep 5
docker compose up -d backend
sleep 8

echo ""
echo "=== 2. Проверка main DB (все данные загружаются tt_workers/backend, ML только читает) ==="
MAIN_MATCHES=$(docker compose exec -T postgres psql -U pingwin -d pingwin -p 11002 -t -c "
  SELECT COUNT(*) FROM table_tennis_line_events WHERE status = 'finished' AND live_sets_score IS NOT NULL AND live_sets_score LIKE '%-%';
" 2>/dev/null | tr -d ' ')
echo "Finished матчей в main: ${MAIN_MATCHES:-0}"

if [ "${MAIN_MATCHES:-0}" -lt 100 ]; then
  echo "ВНИМАНИЕ: Мало матчей в main (<100). Запустите tt_workers или load_archive_to_main вручную для загрузки данных."
  echo "Продолжаем — ML sync скопирует то, что есть."
fi

echo ""
echo "=== 4. Остановка ml_worker (чтобы не мешал) ==="
docker compose stop ml_worker 2>/dev/null || true

echo ""
echo "=== 5. Полный ML rebuild: sync → player_stats → backfill → league_performance → retrain ==="
echo "    (Прогресс в логах. Админка /dashboard/admin#admin-ml — live-обновление.)"
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild \
  --sync-limit 200000 --backfill-limit 600000 --player-stats-limit 100000 --league-limit 100000 --min-rows 500 2>&1

echo ""
echo "=== 6. Запуск ml_worker и tt_workers ==="
docker compose up -d ml_worker tt_workers
sleep 5

echo ""
echo "=== 7. Итоговое состояние ==="
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "
SELECT 'matches' as tbl, COUNT(*) FROM matches
UNION ALL SELECT 'match_features', COUNT(*) FROM match_features
UNION ALL SELECT 'players', COUNT(*) FROM players
UNION ALL SELECT 'league_performance', COUNT(*) FROM league_performance;
" 2>/dev/null

echo ""
echo "Модели:"
docker run --rm -v sport-analyzator_pingwin_ml_models:/mnt alpine ls -la /mnt/*.json /mnt/*.joblib 2>/dev/null || echo "  (модели не найдены)"

echo ""
echo "=== Готово. tt_workers создают прогнозы (forecast_v2_loop). Проверьте /line и карточки матчей."
