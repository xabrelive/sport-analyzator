#!/bin/bash
# Запуск ml_worker на AMD MI50 (ROCm). Без NVIDIA.
# Требует: ROCm на хосте, /dev/kfd, /dev/dri
# Использование: ./scripts/ml_run_amd.sh python -m app.ml.worker_cli retrain --min-rows 500
set -e
cd "$(dirname "$0")/.."

docker build -f backend/Dockerfile.ml.amd -t sport-analyzator-ml_worker-amd:latest backend/
docker run --rm \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video \
  --network sport-analyzator_default \
  -v sport-analyzator_pingwin_ml_models:/app/ml_models \
  -e DATABASE_URL="postgresql://pingwin:pingwin@postgres:11002/pingwin" \
  -e DATABASE_URL_ML="postgresql://pingwin:pingwin@postgres:11002/pingwin_ml" \
  -e ML_MODEL_DIR=/app/ml_models -e ML_USE_AMD_GPU=1 -e ML_BACKFILL_WORKERS=16 -e PYTHONUNBUFFERED=1 \
  --env-file .env \
  sport-analyzator-ml_worker-amd:latest \
  "$@"
