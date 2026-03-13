# ML worker с XGBoost, собранным из source под RTX 5060 Ti.
FROM nvidia/cuda:13.0.2-devel-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-venv python3-pip \
    build-essential libpq-dev curl git cmake ninja-build \
    autoconf automake libtool pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --break-system-packages --no-cache-dir -e . \
    && pip uninstall -y xgboost xgboost-cu13 xgboost-cu12 2>/dev/null || true \
    && git clone --recurse-submodules --depth 1 --branch v3.2.0 https://github.com/dmlc/xgboost.git /tmp/xgb \
    && cmake -S /tmp/xgb -B /tmp/xgb/build -GNinja \
       -DUSE_CUDA=ON -DUSE_NCCL=OFF -DCMAKE_CUDA_ARCHITECTURES=120 \
    && cmake --build /tmp/xgb/build -j4 \
    && pip install --break-system-packages --no-cache-dir "xgboost==3.2.0" \
    && cp /tmp/xgb/lib/libxgboost.so /usr/local/lib/python3.12/dist-packages/xgboost/lib/libxgboost.so \
    && rm -rf /tmp/xgb

COPY . .
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 11001
CMD ["python", "-m", "app.ml.worker_cli", "run"]
