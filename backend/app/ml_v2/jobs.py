"""Orchestration helpers for ML v2 jobs."""
from __future__ import annotations

import asyncio
from typing import Any

from app.ml_v2.eval import evaluate_filtered_signals
from app.ml_v2.features import rebuild_features_to_ch
from app.ml_v2.sync import sync_finished_to_ch_once
from app.ml_v2.trainer import retrain_models_v2


def run_sync_features_train_once(sync_limit: int = 5000) -> dict[str, Any]:
    sync_res = asyncio.run(sync_finished_to_ch_once(limit=sync_limit))
    feat_res = rebuild_features_to_ch()
    train_res = retrain_models_v2(min_rows=1000)
    kpi = evaluate_filtered_signals()
    return {"sync": sync_res, "features": feat_res, "train": train_res, "kpi": kpi}

