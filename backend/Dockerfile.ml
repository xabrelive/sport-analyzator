# Использует предсобранный базовый образ (CUDA + LightGBM). Без него сборка ~10 мин.
# Один раз соберите базу: docker build -f Dockerfile.ml.base -t sport-analyzator-ml-base:latest .
# Или: make -C .. build-ml-base
ARG ML_BASE_IMAGE=sport-analyzator-ml-base:latest
FROM ${ML_BASE_IMAGE}

COPY pyproject.toml ./
COPY app ./app

RUN pip install --break-system-packages --no-deps .
RUN pip install --break-system-packages clickhouse-connect

ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 11001
CMD ["python", "-m", "app.ml.worker_cli", "run"]
