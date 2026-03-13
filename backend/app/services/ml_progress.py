"""Прогресс ML-операций: синхронизация, backfill, retrain.

Операции выполняются в отдельном процессе (app.ml.worker_cli), прогресс пишется в файл.
Основной API читает прогресс из файла — не блокирует пользователей.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT = {
    "sync": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
    "backfill": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
    "retrain": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
    "league_performance": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
    "player_stats": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
    "full_rebuild": {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None},
}


def _progress_file() -> Path:
    base = __import__("os").environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")
    return Path(base) / "progress.json"


def get_progress() -> dict[str, dict[str, Any]]:
    """Читает прогресс из файла (пишется воркером в отдельном процессе)."""
    path = _progress_file()
    if not path.exists():
        return {k: dict(v) for k, v in _DEFAULT.items()}
    try:
        data = json.loads(path.read_text())
        out = {}
        for k in ("sync", "backfill", "retrain", "league_performance", "player_stats", "full_rebuild"):
            out[k] = dict(_DEFAULT.get(k, {}))
            out[k].update(data.get(k, {}))
        return out
    except Exception:
        return {k: dict(v) for k, v in _DEFAULT.items()}


def is_running(op: str) -> bool:
    return get_progress().get(op, {}).get("status") == "running"


def reset_progress(op: str | None = None) -> None:
    """Сбрасывает прогресс операций. op=None — все, иначе только указанную."""
    path = _progress_file()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        keys = [op] if op and op in _DEFAULT else list(_DEFAULT.keys())
        for k in keys:
            data[k] = dict(_DEFAULT.get(k, {}))
        path.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass
