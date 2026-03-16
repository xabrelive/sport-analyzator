#!/bin/bash
# ML v2: заполнение таблиц ClickHouse (sync → backfill) и обучение (общая + 4 модели по experience regimes).
#
# Использование:
#   ./scripts/run_ml_v2_retrain_verbose.sh           # только retrain (таблицы уже заполнены)
#   ./scripts/run_ml_v2_retrain_verbose.sh full       # полный цикл: sync → backfill → retrain (заполнить все ML таблицы и обучить)
#   MIN_ROWS=2000 ./scripts/run_ml_v2_retrain_verbose.sh full
#
# 4 модели (rookie/low/mid/pro) обучаются при ML_V2_USE_EXPERIENCE_REGIMES=true в .env.
set -euo pipefail

MIN_ROWS="${MIN_ROWS:-1000}"
MODE="${1:-retrain}"  # retrain | full

echo "== Ensure services =="
docker compose up -d clickhouse postgres ml_worker >/dev/null 2>&1 || true
docker compose up -d clickhouse postgres >/dev/null
echo "Waiting for clickhouse/postgres..."
sleep 5

if [ "${MODE}" = "full" ]; then
  echo "== Full pipeline: sync, backfill, retrain =="
  docker compose exec -T -e PYTHONUNBUFFERED=1 ml_worker python -m app.ml.worker_cli full-rebuild --sync-limit 50000 --backfill-limit 100000 --min-rows "${MIN_ROWS}"
else
  echo "== ML v2 retrain only, min_rows=${MIN_ROWS} =="
  docker compose exec -T -e PYTHONUNBUFFERED=1 ml_worker python -m app.ml.worker_cli retrain --min-rows "${MIN_ROWS}"
fi

echo ""
echo "== Training progress snapshot (progress.json from shared volume) =="
docker compose exec -T backend python - <<'PY'
from app.services.ml_progress import get_progress
import json
print(json.dumps(get_progress().get("retrain", {}), ensure_ascii=False, indent=2))
PY

echo ""
echo "Done. Check .env: ML_V2_USE_EXPERIENCE_REGIMES=true for 4 models (rookie/low/mid/pro)."
