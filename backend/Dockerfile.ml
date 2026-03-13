FROM nvidia/cuda:13.0.2-devel-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-venv python3-pip \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY pyproject.toml ./
COPY . .

RUN pip install --break-system-packages --no-cache-dir .

ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 11001
CMD ["python", "-m", "app.ml.worker_cli", "run"]
