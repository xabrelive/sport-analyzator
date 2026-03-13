"""Файловая очередь ML-задач. API добавляет, воркер (отдельный контейнер) выполняет."""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _queue_dir() -> Path:
    base = os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")
    return Path(base) / "queue"


def _queue_file() -> Path:
    return _queue_dir() / "jobs.json"


def _lock_path() -> Path:
    return _queue_dir() / ".lock"


def _ensure_queue() -> None:
    _queue_dir().mkdir(parents=True, exist_ok=True)
    if not _queue_file().exists():
        _queue_file().write_text('{"jobs":[]}')


def enqueue(job_type: str, params: dict[str, Any]) -> bool:
    """Добавляет задачу в очередь. Не блокирует."""
    _ensure_queue()
    job = {"id": str(uuid.uuid4()), "type": job_type, "params": params}
    for _ in range(10):
        try:
            with open(_queue_file(), "r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                data = json.load(f)
                data.setdefault("jobs", []).append(job)
                f.seek(0)
                f.write(json.dumps(data, ensure_ascii=False))
                f.truncate()
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return True
        except (BlockingIOError, OSError, json.JSONDecodeError):
            time.sleep(0.1)
    return False


def dequeue() -> dict[str, Any] | None:
    """Забирает первую задачу из очереди. Для воркера."""
    _ensure_queue()
    for _ in range(5):
        try:
            with open(_queue_file(), "r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                data = json.load(f)
                jobs = data.get("jobs", [])
                if not jobs:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    return None
                job = jobs.pop(0)
                data["jobs"] = jobs
                f.seek(0)
                f.write(json.dumps(data, ensure_ascii=False))
                f.truncate()
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return job
        except (BlockingIOError, OSError, json.JSONDecodeError):
            time.sleep(0.1)
    return None


def queue_size() -> int:
    """Количество задач в очереди."""
    if not _queue_file().exists():
        return 0
    try:
        data = json.loads(_queue_file().read_text())
        return len(data.get("jobs", []))
    except Exception:
        return 0
