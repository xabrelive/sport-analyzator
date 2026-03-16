#!/bin/bash
# Собирает базовый образ для GPU (CUDA + LightGBM + cuML). Запускать один раз или при смене backend/requirements-ml-base.txt.
# После этого «docker compose build ml_train_gpu» занимает секунды.
set -e
cd "$(dirname "$0")/.."
docker build -f backend/Dockerfile.ml.base -t sport-analyzator-ml-base:latest ./backend
echo "Базовый образ готов. Собираем контейнер обучения на GPU..."
docker compose build ml_train_gpu
echo "Готово. Переобучение на GPU: docker compose run --rm ml_train_gpu"
echo "Или: ./up.sh и затем по необходимости docker compose run --rm ml_train_gpu"
