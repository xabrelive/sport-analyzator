# Настройка RTX 5060 Ti для ML

## 1. Драйвер на хосте

RTX 5060 Ti (Blackwell) требует драйвер 575+ и **open-вариант** (nvidia-driver-580-open).

```bash
# Обновить пакеты
sudo apt update

# Установить open-драйвер (для Blackwell)
sudo apt install -y nvidia-driver-580-open

# Или через NVIDIA repo (если в дистрибутиве нет 580-open):
# https://developer.nvidia.com/cuda-downloads
```

Перезагрузка после установки:
```bash
sudo reboot
```

## 2. Проверка GPU

```bash
nvidia-smi
```

Должна отображаться GeForce RTX 5060 Ti.

## 3. NVIDIA Container Toolkit (для Docker)

```bash
# Установка
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
```

## 4. Пересборка и запуск ML

RTX 5060 Ti поддерживается xgboost-cu12 (Blackwell = sm_100). Текущий Dockerfile.ml уже использует xgboost-cu12.

```bash
# Пересборка образа
docker compose build ml_worker --no-cache

# Retrain
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli retrain --min-rows 500

# Или полный rebuild
./scripts/ml_run_gpu.sh python -m app.ml.worker_cli full-rebuild \
  --sync-limit 500000 --backfill-limit 600000 --min-rows 500
```

## 5. Если xgboost-cu12 не поддерживает 5060 Ti

Попробуйте xgboost-cu13 (в Dockerfile.ml заменить xgboost-cu12 на xgboost-cu13). Blackwell поддерживается в CUDA 13+.
