#!/bin/bash
# Завершает зависшие ML-процессы, занимающие GPU.
# Использование: ./scripts/kill_stuck_ml_gpu.sh [PID1 PID2 ...]
# Без аргументов — останавливает docker ml_worker и убивает процессы из nvidia-smi.
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Остановка ml_worker (docker) ==="
docker compose stop ml_worker 2>/dev/null || true
for c in $(docker ps -q -f "name=ml_worker" 2>/dev/null); do
  echo "  Останавливаю контейнер $c"
  docker stop -t 3 "$c" 2>/dev/null || true
done

echo ""
echo "=== 2. Завершение процессов на GPU (nvidia-smi) ==="
KILL_CMD="kill"
command -v sudo &>/dev/null && KILL_CMD="sudo kill"
if command -v nvidia-smi &>/dev/null; then
  PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' \r' || true)
  if [ -n "$PIDS" ]; then
    for pid in $PIDS; do
      [ -z "$pid" ] || [[ ! "$pid" =~ ^[0-9]+$ ]] && continue
      if $KILL_CMD -0 "$pid" 2>/dev/null; then
        echo "  SIGTERM PID $pid"
        $KILL_CMD -15 "$pid" 2>/dev/null || true
      fi
    done
    sleep 2
    for pid in $PIDS; do
      [ -z "$pid" ] || [[ ! "$pid" =~ ^[0-9]+$ ]] && continue
      if $KILL_CMD -0 "$pid" 2>/dev/null; then
        echo "  SIGKILL PID $pid"
        $KILL_CMD -9 "$pid" 2>/dev/null || true
      fi
    done
  else
    echo "  Нет процессов на GPU"
  fi
else
  echo "  nvidia-smi не найден"
fi

# Явные PIDs из аргументов
if [ $# -gt 0 ]; then
  echo ""
  echo "=== 3. Завершение указанных PIDs: $* ==="
  for pid in "$@"; do
    if $KILL_CMD -0 "$pid" 2>/dev/null; then
      $KILL_CMD -9 "$pid" 2>/dev/null && echo "  Убит PID $pid" || true
    fi
  done
fi

echo ""
echo "=== Готово ==="
echo "Проверка: nvidia-smi"
nvidia-smi 2>/dev/null || true
