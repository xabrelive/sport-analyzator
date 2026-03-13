#!/bin/bash
# Полный сброс ML, прогнозов и пересборка с нуля.
# Использование: ./scripts/reset_ml_and_rebuild.sh
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Остановка воркеров, postgres должен остаться ==="
docker compose stop backend ml_worker tt_workers 2>/dev/null || true
docker compose up -d postgres 2>/dev/null || true
sleep 3

echo ""
echo "=== 2. Очистка ML-таблиц (pingwin_ml) ==="
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 <<'EOSQL'
TRUNCATE TABLE
  player_elo_history,
  player_daily_stats,
  player_style,
  league_performance,
  suspicious_matches,
  signals,
  match_features,
  match_events,
  odds_live,
  odds,
  match_sets,
  matches,
  player_ratings,
  players,
  leagues
CASCADE;
EOSQL

echo ""
echo "=== 3. Очистка прогнозов и статистики (main DB) ==="
docker compose exec -T postgres psql -U pingwin -d pingwin -p 11002 <<'EOSQL'
TRUNCATE TABLE
  user_forecast_notifications,
  telegram_channel_notifications,
  table_tennis_forecast_explanations,
  table_tennis_forecasts_v2,
  table_tennis_forecast_early_scan,
  table_tennis_model_runs
CASCADE;
EOSQL

echo ""
echo "=== 4. Очистка ML-моделей и очереди ==="
docker compose run --rm --no-deps backend sh -c '
  rm -f /app/ml_models/tt_ml_v1_* /app/ml_models/anomaly_isolation_forest.joblib
  rm -f /app/ml_models/progress.json
  rm -rf /app/ml_models/queue
  echo "ML models cleared"
' 2>/dev/null || true

echo ""
echo "=== 5. Сборка и запуск сервисов ==="
docker compose build backend ml_worker tt_workers
docker compose up -d postgres
sleep 5
docker compose up -d backend ml_worker tt_workers
sleep 8

echo ""
echo "=== 5b. Загрузка архива BetsAPI в main DB (finished матчи для ML) ==="
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python scripts/load_archive_to_main.py --days 90 2>/dev/null || true

echo ""
echo "=== 6. Полный rebuild ML (sync → backfill 6 workers → player_stats → league_performance → retrain) ==="
echo "    С параллельным backfill ~5–15 мин (вместо 5+ часов)."
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild \
  --sync-limit 200000 \
  --backfill-limit 600000 \
  --player-stats-limit 100000 \
  --league-limit 100000 \
  --min-rows 500 2>&1

echo ""
echo "=== 7. Проверка наполнения ML-таблиц ==="
docker compose exec -T postgres psql -U pingwin -d pingwin_ml -p 11002 -t -c "
SELECT 'matches' as tbl, COUNT(*) FROM matches
UNION ALL SELECT 'match_features', COUNT(*) FROM match_features
UNION ALL SELECT 'players', COUNT(*) FROM players
UNION ALL SELECT 'leagues', COUNT(*) FROM leagues
UNION ALL SELECT 'player_daily_stats', COUNT(*) FROM player_daily_stats
UNION ALL SELECT 'player_style', COUNT(*) FROM player_style
UNION ALL SELECT 'player_elo_history', COUNT(*) FROM player_elo_history
UNION ALL SELECT 'league_performance', COUNT(*) FROM league_performance;
" 2>/dev/null

echo ""
echo "=== Готово. tt_workers и forecast_v2_loop автоматически создадут новые прогнозы. ==="
