"""Inference for ML v2 (match/set1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import logging

import joblib
import pandas as pd

from app.config import settings
from app.ml_v2.features import FEATURE_COLS_V2, FEATURE_COLS_V2_TRAIN, build_upcoming_feature_vector

logger = logging.getLogger(__name__)

_CLOCK_FEATURE_COLS_V2 = [
    "hour_strength_diff",
    "morning_strength_diff",
    "evening_strength_diff",
    "weekend_strength_diff",
]


@dataclass
class V2Prediction:
    p_match: float
    p_set1: float
    p_set2: float
    model_used: bool
    quality_score: float
    factors: list[dict[str, Any]]
    regime_bucket: str | None = None  # "rookie"|"low"|"mid"|"pro" если использована bucket-модель


BUCKET_NAMES = {1: "rookie", 2: "low", 3: "mid", 4: "pro"}


def _experience_bucket(feat: dict[str, float]) -> int:
    """Experience regime bucket 1..4: max(p1_exp_bucket, p2_exp_bucket).
    Пороги обучения: 1=rookie (<20), 2=low (20–79), 3=mid (80–299), 4=pro (≥300)."""
    p1 = float(feat.get("p1_exp_bucket", 1.0))
    p2 = float(feat.get("p2_exp_bucket", 1.0))
    return int(min(4, max(1, max(p1, p2))))


def _load_models_v2(feat: dict[str, float] | None = None) -> tuple[Any, Any, Any | None, Any | None, int]:
    """Загружает модель для инференса: при наличии bucket-моделей (b1..b4) — по max(p1_exp_bucket, p2_exp_bucket), иначе общая.
    Возвращает (model_match, model_set1, calib_match, calib_set1, bucket_used) где bucket_used=0 значит общая модель."""
    model_dir = Path(getattr(settings, "ml_model_dir", "/tmp/pingwin_ml_models"))
    bucket = _experience_bucket(feat) if feat else 0
    # Всегда пробуем bucket-модель, если есть feat и файлы существуют (не зависим от ml_v2_use_experience_regimes).
    if feat and bucket >= 1:
        suffix = f"_b{bucket}"
        match_path = model_dir / f"tt_ml_v2{suffix}_match.joblib"
        set1_path = model_dir / f"tt_ml_v2{suffix}_set1.joblib"
        if match_path.exists() and set1_path.exists():
            match_calib_path = model_dir / f"tt_ml_v2{suffix}_match_calib.joblib"
            set1_calib_path = model_dir / f"tt_ml_v2{suffix}_set1_calib.joblib"
            logger.info("ML v2 inference: using regime model bucket=%s (%s)", bucket, BUCKET_NAMES.get(bucket, ""))
            return (
                joblib.load(match_path),
                joblib.load(set1_path),
                joblib.load(match_calib_path) if match_calib_path.exists() else None,
                joblib.load(set1_calib_path) if set1_calib_path.exists() else None,
                bucket,
            )
    match_path = model_dir / "tt_ml_v2_match.joblib"
    set1_path = model_dir / "tt_ml_v2_set1.joblib"
    match_calib_path = model_dir / "tt_ml_v2_match_calib.joblib"
    set1_calib_path = model_dir / "tt_ml_v2_set1_calib.joblib"
    if not (match_path.exists() and set1_path.exists()):
        raise FileNotFoundError("ML v2 models not found")
    match_calib = joblib.load(match_calib_path) if match_calib_path.exists() else None
    set1_calib = joblib.load(set1_calib_path) if set1_calib_path.exists() else None
    return joblib.load(match_path), joblib.load(set1_path), match_calib, set1_calib, 0


def _model_feature_names(model: Any) -> list[str]:
    """Return feature names expected by trained model."""
    names = getattr(model, "feature_name_", None)
    if isinstance(names, list) and names:
        return [str(x) for x in names]
    names = getattr(model, "feature_names_in_", None)
    if names is not None:
        try:
            return [str(x) for x in list(names)]
        except Exception:
            pass
    return list(FEATURE_COLS_V2_TRAIN)


def _apply_clock_feature_guard(feat: dict[str, float]) -> dict[str, float]:
    if not bool(getattr(settings, "ml_v2_disable_clock_features", True)):
        return feat
    out = dict(feat)
    for c in _CLOCK_FEATURE_COLS_V2:
        out[c] = 0.0
    return out


def predict_for_upcoming_v2(
    home_id: str,
    away_id: str,
    league_id: str,
    odds_p1: float,
    odds_p2: float,
    start_time: Any,
) -> V2Prediction | None:
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            start_time = datetime.now(timezone.utc)
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    try:
        feat = build_upcoming_feature_vector(
            home_id=home_id,
            away_id=away_id,
            league_id=league_id or "",
            start_time=start_time,
            odds_p1=float(odds_p1 or 1.9),
            odds_p2=float(odds_p2 or 1.9),
        )
        feat = _apply_clock_feature_guard(feat)
        model_match, model_set1, calib_match, calib_set1, bucket_used = _load_models_v2(feat)
        regime_name = BUCKET_NAMES.get(bucket_used) if bucket_used >= 1 else None
        cols_match = _model_feature_names(model_match)
        cols_set1 = _model_feature_names(model_set1)

        def _predict_pair(features: dict[str, float]) -> tuple[float, float]:
            x_match = pd.DataFrame([{c: float(features.get(c, 0.0)) for c in cols_match}])
            x_set1 = pd.DataFrame([{c: float(features.get(c, 0.0)) for c in cols_set1}])
            p_match_raw = float(model_match.predict_proba(x_match)[0, 1])
            p_set1_raw = float(model_set1.predict_proba(x_set1)[0, 1])
            p_match_ml = float(calib_match.predict([p_match_raw])[0]) if calib_match is not None else p_match_raw
            p_set1_ml = float(calib_set1.predict([p_set1_raw])[0]) if calib_set1 is not None else p_set1_raw
            p_elo = float(1.0 / (1.0 + 10.0 ** (-(float(features.get("elo_diff", 0.0)) / 400.0))))
            w_elo = float(getattr(settings, "ml_v2_ensemble_elo_weight", 0.3))
            w_elo = max(0.0, min(1.0, w_elo))
            p_match = float((1.0 - w_elo) * p_match_ml + w_elo * p_elo)
            p_set1 = float((1.0 - w_elo) * p_set1_ml + w_elo * p_elo)
            return p_match, p_set1

        p_match_direct, p_set1_direct = _predict_pair(feat)
        feat_swap = build_upcoming_feature_vector(
            home_id=away_id,
            away_id=home_id,
            league_id=league_id or "",
            start_time=start_time,
            odds_p1=float(odds_p2 or 1.9),
            odds_p2=float(odds_p1 or 1.9),
        )
        feat_swap = _apply_clock_feature_guard(feat_swap)
        p_match_swap_home, p_set1_swap_home = _predict_pair(feat_swap)
        p_match = float((p_match_direct + (1.0 - p_match_swap_home)) / 2.0)
        p_set1 = float((p_set1_direct + (1.0 - p_set1_swap_home)) / 2.0)
        asym_match = abs((p_match_direct + p_match_swap_home) - 1.0)
        asym_set1 = abs((p_set1_direct + p_set1_swap_home) - 1.0)
        if asym_match > 0.08 or asym_set1 > 0.08:
            logger.info(
                "ML v2 positional asymmetry corrected: match=%.4f set1=%.4f home=%s away=%s",
                asym_match, asym_set1, str(home_id), str(away_id),
            )
        p_set2 = p_set1
        quality = 0.5 + min(0.45, abs(p_match - 0.5) + abs(p_set1 - 0.5))
        factors = [
            {"factor_key": "elo_diff", "factor_label": "Разница Elo", "factor_value": f"{feat.get('elo_diff', 0.0):+.1f}"},
            {"factor_key": "form_diff", "factor_label": "Форма", "factor_value": f"{feat.get('form_diff', 0.0):+.3f}"},
            {"factor_key": "fatigue_ratio", "factor_label": "Fatigue ratio", "factor_value": f"{feat.get('fatigue_ratio', 1.0):.3f}"},
            {"factor_key": "market_diff", "factor_label": "Market diff", "factor_value": f"{feat.get('market_diff', 0.0):+.3f}"},
            {"factor_key": "set1_strength_diff", "factor_label": "Сила 1-го сета", "factor_value": f"{feat.get('set1_strength_diff', 0.0):+.3f}"},
        ]
        if regime_name:
            factors.insert(0, {"factor_key": "model_regime", "factor_label": "Модель", "factor_value": regime_name})
        return V2Prediction(
            p_match=p_match,
            p_set1=p_set1,
            p_set2=p_set2,
            model_used=True,
            quality_score=float(max(0.0, min(1.0, quality))),
            factors=factors,
            regime_bucket=regime_name,
        )
    except Exception as e:
        logger.warning("ML v2 inference failed (home=%s away=%s): %s", home_id, away_id, e)
        return None


def _load_models_nn_v2() -> tuple[Any, Any, list[str]]:
    model_dir = Path(getattr(settings, "ml_model_dir", "/tmp/pingwin_ml_models"))
    m_match = model_dir / "tt_nn_v2_match.joblib"
    m_set1 = model_dir / "tt_nn_v2_set1.joblib"
    meta_path = model_dir / "tt_nn_v2_meta.json"
    if not (m_match.exists() and m_set1.exists()):
        raise FileNotFoundError("NN v2 models not found")
    features = list(FEATURE_COLS_V2_TRAIN)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            f = meta.get("features")
            if isinstance(f, list) and f:
                features = [str(x) for x in f]
        except Exception:
            pass
    return joblib.load(m_match), joblib.load(m_set1), features


def predict_for_upcoming_nn_v2(
    home_id: str,
    away_id: str,
    league_id: str,
    odds_p1: float,
    odds_p2: float,
    start_time: Any,
) -> V2Prediction | None:
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            start_time = datetime.now(timezone.utc)
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    try:
        feat = build_upcoming_feature_vector(
            home_id=home_id,
            away_id=away_id,
            league_id=league_id or "",
            start_time=start_time,
            odds_p1=float(odds_p1 or 1.9),
            odds_p2=float(odds_p2 or 1.9),
        )
        feat = _apply_clock_feature_guard(feat)
        model_match, model_set1, cols = _load_models_nn_v2()

        def _predict_pair(features: dict[str, float]) -> tuple[float, float]:
            x = pd.DataFrame([{c: float(features.get(c, 0.0)) for c in cols}])
            p_match_raw = float(model_match.predict_proba(x)[0, 1])
            p_set1_raw = float(model_set1.predict_proba(x)[0, 1])
            # Temper NN extremes with Elo prior, same policy as ML v2.
            p_elo = float(1.0 / (1.0 + 10.0 ** (-(float(features.get("elo_diff", 0.0)) / 400.0))))
            w_elo = float(getattr(settings, "ml_v2_ensemble_elo_weight", 0.3))
            w_elo = max(0.0, min(1.0, w_elo))
            p_match = float((1.0 - w_elo) * p_match_raw + w_elo * p_elo)
            p_set1 = float((1.0 - w_elo) * p_set1_raw + w_elo * p_elo)
            return p_match, p_set1

        # Positional-bias correction: direct + swapped complement.
        p_match_direct, p_set1_direct = _predict_pair(feat)
        feat_swap = build_upcoming_feature_vector(
            home_id=away_id,
            away_id=home_id,
            league_id=league_id or "",
            start_time=start_time,
            odds_p1=float(odds_p2 or 1.9),
            odds_p2=float(odds_p1 or 1.9),
        )
        feat_swap = _apply_clock_feature_guard(feat_swap)
        p_match_swap_home, p_set1_swap_home = _predict_pair(feat_swap)
        p_match = float((p_match_direct + (1.0 - p_match_swap_home)) / 2.0)
        p_set1 = float((p_set1_direct + (1.0 - p_set1_swap_home)) / 2.0)
        asym_match = abs((p_match_direct + p_match_swap_home) - 1.0)
        asym_set1 = abs((p_set1_direct + p_set1_swap_home) - 1.0)
        if asym_match > 0.08 or asym_set1 > 0.08:
            logger.info(
                "NN v2 positional asymmetry corrected: match=%.4f set1=%.4f home=%s away=%s",
                asym_match,
                asym_set1,
                str(home_id),
                str(away_id),
            )
        p_set2 = p_set1
        quality = 0.5 + min(0.45, abs(p_match - 0.5) + abs(p_set1 - 0.5))
        def _f(key: str, label: str, value: float, norm: float = 1.0) -> dict[str, Any]:
            direction = "home" if value > 0 else ("away" if value < 0 else "neutral")
            return {
                "factor_key": key,
                "factor_label": label,
                "factor_value": f"{value:+.4f}" if abs(value) < 10 else f"{value:+.1f}",
                "contribution": float(value / max(1e-6, norm)),
                "direction": direction,
            }

        factors = [
            {"factor_key": "engine", "factor_label": "Движок", "factor_value": "NN v2", "contribution": 0.0, "direction": "neutral"},
            _f("elo_diff", "Разница Elo", float(feat.get("elo_diff", 0.0)), 150.0),
            _f("latent_strength_diff", "Скрытая сила", float(feat.get("latent_strength_diff", 0.0)), 0.2),
            _f("temporal_strength_diff", "Динамика силы", float(feat.get("temporal_strength_diff", 0.0)), 0.2),
            _f("form_diff", "Форма", float(feat.get("form_diff", 0.0)), 0.2),
            _f("winrate_20_diff", "Winrate 20", float(feat.get("winrate_20_diff", 0.0)), 0.15),
            _f("points_ratio_20_diff", "Points ratio 20", float(feat.get("points_ratio_20_diff", 0.0)), 0.12),
            _f("sets_ratio_20_diff", "Sets ratio 20", float(feat.get("sets_ratio_20_diff", 0.0)), 0.12),
            _f("strength_trend_diff", "Тренд силы", float(feat.get("strength_trend_diff", 0.0)), 0.1),
            _f("fatigue_index_diff", "Усталость", float(feat.get("fatigue_index_diff", 0.0)), 12.0),
            _f("fatigue_pressure_diff", "Нагрузка 24/48/72h", float(feat.get("fatigue_pressure_diff", 0.0)), 4.0),
            _f("elo_momentum_diff", "ELO momentum", float(feat.get("elo_momentum_diff", 0.0)), 0.06),
            _f("h2h_diff", "Личные встречи", float(feat.get("h2h_diff", 0.0)), 0.6),
            _f("set1_strength_diff", "Сила 1-го сета", float(feat.get("set1_strength_diff", 0.0)), 0.2),
            _f("league_rating", "Сила лиги", float(feat.get("league_rating", 0.0)) - 0.5, 0.3),
            _f("style_clash", "Стилевой конфликт", float(feat.get("style_clash", 0.0)), 0.2),
        ]
        return V2Prediction(
            p_match=p_match,
            p_set1=p_set1,
            p_set2=p_set2,
            model_used=True,
            quality_score=float(max(0.0, min(1.0, quality))),
            factors=factors,
            regime_bucket=None,
        )
    except Exception as e:
        logger.warning("NN v2 inference failed (home=%s away=%s): %s", home_id, away_id, e)
        return None

