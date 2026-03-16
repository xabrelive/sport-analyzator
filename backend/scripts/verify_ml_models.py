#!/usr/bin/env python3
"""Верификация загруженных ML-моделей: фичи, классы, число деревьев.
Работает без API — можно запускать в контейнере или локально с теми же путями к моделям.

Запуск из backend/ (или из контейнера, рабочая директория /app):
  python scripts/verify_ml_models.py
  python scripts/verify_ml_models.py --version v1

В контейнере (backend или ml_worker, volume с моделями):
  docker compose exec backend python scripts/verify_ml_models.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.model_trainer import FEATURE_COLS, _model_summary, load_models


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка загруженных ML-моделей")
    parser.add_argument("--version", default="v1", help="Версия моделей tt_ml_{version}_*.joblib")
    args = parser.parse_args()
    version = args.version

    from pathlib import Path
    from app.config import settings

    model_dir = Path(
        getattr(settings, "ml_model_dir", None)
        or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")
    )
    prefix = model_dir / f"tt_ml_{version}"
    meta_path = Path(str(prefix) + "_meta.json")
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    try:
        match_model, set1_model, set_model, p_point_model = load_models(version=version)
    except FileNotFoundError as e:
        print(json.dumps({"ok": False, "error": str(e), "meta": meta}, indent=2))
        sys.exit(1)

    report = {
        "ok": True,
        "version": version,
        "model_dir": str(model_dir),
        "expected_features_count": len(FEATURE_COLS),
        "meta_training_features": len(meta.get("training_features") or meta.get("features") or []),
        "models": {
            "match": _model_summary("match", match_model),
            "set1": _model_summary("set1", set1_model),
            "set": _model_summary("set", set_model),
            "p_point": _model_summary("p_point", p_point_model),
        },
    }
    n_match = report["models"]["match"].get("n_features") or 0
    n_set1 = report["models"]["set1"].get("n_features") or 0
    report["warnings"] = []
    if n_match > 0 and n_match != len(FEATURE_COLS):
        report["warnings"].append(f"match: n_features={n_match}, ожидается {len(FEATURE_COLS)}")
    if n_set1 > 0 and n_set1 != len(FEATURE_COLS):
        report["warnings"].append(f"set1: n_features={n_set1}, ожидается {len(FEATURE_COLS)}")
    for name, s in report["models"].items():
        if s.get("missing_vs_feature_cols"):
            report["warnings"].append(
                f"{name}: отсутствуют фичи в обучении: {s['missing_vs_feature_cols'][:8]}"
            )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["warnings"]:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
