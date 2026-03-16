"""Evaluation helpers for ML v2 filtered-signal KPI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.config import settings
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.features import FEATURE_COLS_V2, FEATURE_COLS_V2_TRAIN
from app.ml_v2.schema import ensure_schema


def evaluate_filtered_signals(
    min_confidence: float = 0.56,
    min_abs_edge: float = 0.05,
) -> dict[str, Any]:
    """Backtest-like KPI on historical feature table using trained v2 models."""
    ensure_schema()
    client = get_ch_client()
    model_dir = Path(getattr(settings, "ml_model_dir", "/tmp/pingwin_ml_models"))
    match_path = model_dir / "tt_ml_v2_match.joblib"
    set1_path = model_dir / "tt_ml_v2_set1.joblib"
    match_calib_path = model_dir / "tt_ml_v2_match_calib.joblib"
    set1_calib_path = model_dir / "tt_ml_v2_set1_calib.joblib"
    if not (match_path.exists() and set1_path.exists()):
        return {"n": 0, "n_match": 0, "n_set1": 0, "match_hit_rate": 0.0, "set1_hit_rate": 0.0}
    model_match = joblib.load(match_path)
    model_set1 = joblib.load(set1_path)
    calib_match = joblib.load(match_calib_path) if match_calib_path.exists() else None
    calib_set1 = joblib.load(set1_calib_path) if set1_calib_path.exists() else None
    rows = client.query(
        f"""
        SELECT {", ".join(FEATURE_COLS_V2)}, target_match, target_set1
        FROM ml.match_features FINAL
        ORDER BY start_time DESC
        LIMIT 200000
        """
    ).result_rows
    if not rows:
        return {"n": 0, "n_match": 0, "n_set1": 0, "match_hit_rate": 0.0, "set1_hit_rate": 0.0}
    df = pd.DataFrame(rows, columns=[*FEATURE_COLS_V2, "target_match", "target_set1"])
    for col in FEATURE_COLS_V2 + ["target_match", "target_set1"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    # Model trained on FEATURE_COLS_V2_TRAIN (94), not full FEATURE_COLS_V2 (113)
    x = df[FEATURE_COLS_V2_TRAIN].astype(float)
    p_match = model_match.predict_proba(x)[:, 1]
    p_set1 = model_set1.predict_proba(x)[:, 1]
    if calib_match is not None:
        p_match = calib_match.predict(p_match)
    if calib_set1 is not None:
        p_set1 = calib_set1.predict(p_set1)
    w_elo = float(getattr(settings, "ml_v2_ensemble_elo_weight", 0.3))
    w_elo = max(0.0, min(1.0, w_elo))
    p_elo = 1.0 / (1.0 + (10.0 ** (-df["elo_diff"].astype(float).values / 400.0)))
    p_match = (1.0 - w_elo) * p_match + w_elo * p_elo
    p_set1 = (1.0 - w_elo) * p_set1 + w_elo * p_elo
    y_match = df["target_match"].astype(int).tolist()
    y_set1 = df["target_set1"].astype(int).tolist()

    match_hits = 0
    set1_hits = 0
    n_match = 0
    n_set1 = 0
    for i in range(len(df)):
        pm = float(p_match[i])
        ps = float(p_set1[i])
        conf_m = abs(pm - 0.5) * 2.0
        conf_s = abs(ps - 0.5) * 2.0
        if conf_m >= min_confidence and abs(pm - 0.5) >= min_abs_edge:
            n_match += 1
            pred = 1 if pm >= 0.5 else 0
            if pred == int(y_match[i]):
                match_hits += 1
        if conf_s >= min_confidence and abs(ps - 0.5) >= min_abs_edge:
            n_set1 += 1
            pred_s = 1 if ps >= 0.5 else 0
            if pred_s == int(y_set1[i]):
                set1_hits += 1
    n = max(n_match, n_set1)
    return {
        "n": int(n),
        "n_match": int(n_match),
        "n_set1": int(n_set1),
        "match_hit_rate": float(match_hits / max(1, n_match)),
        "set1_hit_rate": float(set1_hits / max(1, n_set1)),
    }

