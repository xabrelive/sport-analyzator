#!/usr/bin/env python3
"""Smoke test for ML v2 admin API routes (status + retrain enqueue)."""
from __future__ import annotations

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
    from fastapi.testclient import TestClient

    from app.main import app
    from app.api.v1 import admin

    async def override_require_superadmin():
        return _mock_user()

    app.dependency_overrides[admin.require_superadmin] = override_require_superadmin
    try:
        client = TestClient(app)
        r_status = client.get("/api/v1/admin/ml/v2/status")
        r_retrain = client.post("/api/v1/admin/ml/retrain", params={"min_rows": 1000})
    finally:
        app.dependency_overrides.pop(admin.require_superadmin, None)

    if r_status.status_code != 200:
        print(f"FAIL: /ml/v2/status HTTP {r_status.status_code}: {r_status.text}")
        return 1
    if r_retrain.status_code != 200:
        print(f"FAIL: /ml/retrain HTTP {r_retrain.status_code}: {r_retrain.text}")
        return 1

    data = r_status.json()
    if not isinstance(data, dict) or "engine" not in data or "queue_size" not in data:
        print(f"FAIL: bad /ml/v2/status response: {data}")
        return 1

    retrain_payload = r_retrain.json()
    if not isinstance(retrain_payload, dict) or "ok" not in retrain_payload:
        print(f"FAIL: bad /ml/retrain response: {retrain_payload}")
        return 1

    print("OK: ML v2 admin status/retrain routes are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
