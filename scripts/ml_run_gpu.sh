#!/bin/bash
# Запуск ml_worker с GPU (docker compose run не поддерживает --gpus).
# Использование: ./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild --sync-limit 200000 ...
set -e
cd "$(dirname "$0")/.."

docker compose build ml_worker -q 2>/dev/null || true
docker run --rm --gpus all \
  --network sport-analyzator_default \
  -v sport-analyzator_pingwin_ml_models:/app/ml_models \
  -e DATABASE_URL="postgresql://pingwin:pingwin@postgres:11002/pingwin" \
  -e DATABASE_URL_ML="postgresql://pingwin:pingwin@postgres:11002/pingwin_ml" \
  -e ML_MODEL_DIR=/app/ml_models -e ML_USE_GPU=true -e ML_GPU_ONLY=true -e ML_BACKFILL_WORKERS=16 -e PYTHONUNBUFFERED=1 \
  -e NVIDIA_VISIBLE_DEVICES=all \
  --env-file .env \
  sport-analyzator-ml_worker:latest \
  "$@"
