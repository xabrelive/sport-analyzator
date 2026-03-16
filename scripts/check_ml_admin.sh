#!/bin/bash
# Проверка ML через админ-API: логин, дашборд, verify-models.
# Использование: ADMIN_EMAIL=xabre@live.ru ADMIN_PASSWORD=xxx BACKEND_URL=http://localhost:11001 ./scripts/check_ml_admin.sh
set -e
BACKEND_URL="${BACKEND_URL:-http://localhost:11001}"
EMAIL="${ADMIN_EMAIL:-}"
PASS="${ADMIN_PASSWORD:-}"
if [ -z "$EMAIL" ] || [ -z "$PASS" ]; then
  echo "Задайте ADMIN_EMAIL и ADMIN_PASSWORD"
  exit 1
fi
echo "Login..."
RESP=$(curl -s -X POST "$BACKEND_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
TOKEN=$(echo "$RESP" | jq -r '.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "Ошибка логина: $RESP"
  exit 1
fi
echo "Токен получен."
echo ""
echo "=== ML Dashboard ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/dashboard" | jq '.meta | {ml_last_sync_at_ts, ml_last_retrain_at_ts, ml_last_model_created_at_ts, ml_last_retrain_rows, ml_last_retrain_trained}'
echo ""
echo "=== ML Verify Models (проверка фичей и версии моделей) ==="
VERIFY=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/v1/admin/ml/verify-models?version=v1")
HTTP_CODE=$(echo "$VERIFY" | tail -n1)
VERIFY_BODY=$(echo "$VERIFY" | sed '$d')
if [ "$HTTP_CODE" = "200" ] && echo "$VERIFY_BODY" | jq -e '.ok == true' >/dev/null 2>&1; then
  echo "$VERIFY_BODY" | jq '.'
elif [ "$HTTP_CODE" = "200" ]; then
  echo "$VERIFY_BODY" | jq '.' 2>/dev/null || echo "$VERIFY_BODY"
else
  echo "$VERIFY_BODY" | jq '.' 2>/dev/null || echo "$VERIFY_BODY"
  if [ "$HTTP_CODE" != "200" ]; then
    echo ""
    echo "Эндпоинт вернул HTTP $HTTP_CODE. Запуск локальной верификации в контейнере backend..."
    docker compose exec -T backend python scripts/verify_ml_models.py --version v1 2>/dev/null || \
      echo "(Перезапустите backend с актуальным кодом или выполните: docker compose exec backend python scripts/verify_ml_models.py)"
  fi
fi
