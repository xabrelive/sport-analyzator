#!/bin/bash
# End-to-end check for ML v2 retrain/status/GPU logs.
# Usage:
# ADMIN_EMAIL=... ADMIN_PASSWORD=... BACKEND_URL=http://localhost:11001 ./scripts/check_ml_v2_gpu.sh
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:11001}"
EMAIL="${ADMIN_EMAIL:-}"
PASS="${ADMIN_PASSWORD:-}"
MIN_ROWS="${MIN_ROWS:-1000}"
POLL_SEC="${POLL_SEC:-10}"
MAX_POLLS="${MAX_POLLS:-90}"

if [ -z "$EMAIL" ] || [ -z "$PASS" ]; then
  echo "Set ADMIN_EMAIL and ADMIN_PASSWORD"
  exit 1
fi

echo "[1/6] Login..."
RESP=$(curl -s -X POST "$BACKEND_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
TOKEN=$(echo "$RESP" | jq -r '.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed: $RESP"
  exit 1
fi

echo "[2/6] Current ML v2 status:"
curl -s -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/v2/status" | jq '.'

echo "[3/6] Enqueue retrain (GPU):"
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "$BACKEND_URL/api/v1/admin/ml/retrain?min_rows=${MIN_ROWS}" | jq '.'

echo "[4/6] Polling retrain progress..."
PREV_DONE_TS=$(curl -s -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/progress" | jq -r '.retrain.completed_at_ts // 0')
if [ -z "$PREV_DONE_TS" ] || [ "$PREV_DONE_TS" = "null" ]; then
  PREV_DONE_TS=0
fi
for i in $(seq 1 "$MAX_POLLS"); do
  PROG=$(curl -s -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/progress")
  STATUS=$(echo "$PROG" | jq -r '.retrain.status // "unknown"')
  MSG=$(echo "$PROG" | jq -r '.retrain.message // ""')
  DONE_TS=$(echo "$PROG" | jq -r '.retrain.completed_at_ts // 0')
  if [ -z "$DONE_TS" ] || [ "$DONE_TS" = "null" ]; then
    DONE_TS=0
  fi
  echo "  poll #$i status=$STATUS message=$MSG"
  if [ "$STATUS" = "done" ] && [ "$DONE_TS" -gt "$PREV_DONE_TS" ]; then
    echo "$PROG" | jq '.retrain'
    break
  fi
  sleep "$POLL_SEC"
done

echo "[5/6] Final ML v2 status + KPI:"
curl -s -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/v2/status" | jq '.kpi, .meta'

echo "[6/6] GPU proof in ml_worker logs (device=cuda):"
if command -v rg >/dev/null 2>&1; then
  docker compose logs --since=20m ml_worker 2>/dev/null | rg "ML v2 train|device=cuda|CUDA" || true
else
  docker compose logs --since=20m ml_worker 2>/dev/null | awk '/ML v2 train|device=cuda|CUDA/ { print }' || true
fi

echo "Done."
