#!/usr/bin/env python3
"""Тест эндпоинта GET /api/v1/admin/ml/verify-models через TestClient (без реального сервера).
Проверяет, что маршрут зарегистрирован и возвращает структуру верификации.

Запуск из backend/ (с venv или в контейнере):
  python scripts/test_verify_models_api.py
  python scripts/test_verify_models_api.py --no-models-required   # 200 даже если моделей нет (ok: false)

В контейнере:
  docker compose exec backend python scripts/test_verify_models_api.py --no-models-required
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_user():
    class MockUser:
        id = "test-admin-id"
        is_superadmin = True
        email = "test@test"

    return MockUser()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-models-required",
        action="store_true",
        help="Успех теста даже если модели не найдены (ok: false)",
    )
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from app.main import app
    from app.api.v1 import admin

    async def override_require_superadmin():
        return _mock_user()

    app.dependency_overrides[admin.require_superadmin] = override_require_superadmin
    try:
        client = TestClient(app)
        r = client.get("/api/v1/admin/ml/verify-models", params={"version": "v1"})
    finally:
        app.dependency_overrides.pop(admin.require_superadmin, None)

    if r.status_code == 404:
        print("FAIL: эндпоинт не найден (404). Проверьте регистрацию роута /api/v1/admin/ml/verify-models")
        return 1

    if r.status_code != 200:
        print(f"FAIL: HTTP {r.status_code} — {r.text}")
        return 1

    try:
        data = r.json()
    except Exception as e:
        print(f"FAIL: ответ не JSON: {e}")
        return 1

    if not isinstance(data, dict):
        print("FAIL: ответ не объект")
        return 1

    if data.get("ok") is True:
        print("OK: верификация моделей прошла, эндпоинт работает.")
        if data.get("warnings"):
            print("  Предупреждения:", data["warnings"])
        return 0

    if args.no_models_required and "error" in data:
        print("OK: эндпоинт отвечает (модели не найдены — ожидаемо без volume).")
        return 0

    print("FAIL: ответ без ok или с ошибкой:", data.get("error", data))
    return 1


if __name__ == "__main__":
    sys.exit(main())
