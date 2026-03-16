"""Probability calibration helpers for ML v2 binary models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss


def _clip_probs(p: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), 1e-7, 1.0 - 1e-7)


@dataclass
class BinaryProbabilityCalibrator:
    """Calibrates raw probabilities with isotonic or sigmoid mapping."""

    method: str
    model: Any
    train_logloss: float

    @staticmethod
    def fit(raw_probs: np.ndarray, y_true: np.ndarray) -> "BinaryProbabilityCalibrator":
        p = _clip_probs(raw_probs).reshape(-1)
        y = np.asarray(y_true, dtype=int).reshape(-1)
        if len(p) == 0 or len(y) == 0 or len(p) != len(y):
            raise ValueError("Calibration input mismatch")

        # Isotonic: non-parametric monotonic mapping.
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p, y)
        p_iso = _clip_probs(iso.predict(p))
        ll_iso = float(log_loss(y, p_iso))

        # Sigmoid / Platt-like mapping on raw probabilities.
        sig = LogisticRegression(max_iter=1000, solver="lbfgs")
        sig.fit(p.reshape(-1, 1), y)
        p_sig = _clip_probs(sig.predict_proba(p.reshape(-1, 1))[:, 1])
        ll_sig = float(log_loss(y, p_sig))

        if ll_iso <= ll_sig:
            return BinaryProbabilityCalibrator(method="isotonic", model=iso, train_logloss=ll_iso)
        return BinaryProbabilityCalibrator(method="sigmoid", model=sig, train_logloss=ll_sig)

    def predict(self, raw_probs: np.ndarray) -> np.ndarray:
        p = _clip_probs(raw_probs).reshape(-1)
        if self.method == "isotonic":
            out = self.model.predict(p)
            return _clip_probs(out)
        out = self.model.predict_proba(p.reshape(-1, 1))[:, 1]
        return _clip_probs(out)

