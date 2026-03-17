"""Training pipeline for ML v2 targets: match and set1."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.config import settings
from app.ml_v2.calibration import BinaryProbabilityCalibrator
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.features import FEATURE_COLS_V2, FEATURE_COLS_V2_TRAIN
from app.ml_v2.schema import ensure_schema

logger = logging.getLogger(__name__)

_CLOCK_FEATURE_COLS_V2 = [
    "hour_strength_diff",
    "morning_strength_diff",
    "evening_strength_diff",
    "weekend_strength_diff",
]
_MARKET_FEATURE_COLS_V2 = [
    "market_prob_p1",
    "market_prob_p2",
    "market_diff",
    "closing_line",
    "market_margin",
]


@dataclass
class TrainResult:
    trained: bool
    rows: int
    path: str
    metrics: dict[str, Any]


def _load_feature_frame() -> pd.DataFrame:
    ensure_schema()
    client = get_ch_client()
    query = f"""
        SELECT
          match_id, start_time,
          {", ".join(FEATURE_COLS_V2)},
          target_match, target_set1
        FROM ml.match_features FINAL
        ORDER BY start_time ASC
    """
    rows = client.query(query).result_rows
    cols = [
        "match_id", "start_time", *FEATURE_COLS_V2, "target_match", "target_set1"
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=cols)
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    # Proper training dataset hygiene: deduplicate by match_id and keep latest row.
    df = df.sort_values(["start_time", "match_id"]).drop_duplicates(subset=["match_id"], keep="last")
    for c in FEATURE_COLS_V2 + ["target_match", "target_set1"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    # Клип только после сплита по train (без утечки val/test). См. retrain_models_v2.
    # Keep only binary targets.
    df = df[df["target_match"].isin([0, 1]) & df["target_set1"].isin([0, 1])].copy()
    return df


def _balance_p1_p2(df: pd.DataFrame) -> pd.DataFrame:
    """Убирает p1/p2 bias: для ~50% строк (детерминированно по match_id) меняем местами P1 и P2.

    Сигнал не теряется: для каждой перевёрнутой строки мы инвертируем и фичи, и target вместе.
    - *_diff (p1 − p2) → −(p1 − p2) = (p2 − p1); target → 1 − target. Связь «больше diff → чаще победа p1» сохраняется.
    - ratio-фичи (p1/p2): при swap должны дать (p2/p1) = 1/ratio, иначе признак и target несогласованы.
    """
    if df.empty or "match_id" not in df.columns:
        return df
    df = df.copy()
    target_mean_before = float(df["target_match"].astype(float).mean())
    def _swap_bit(s: str) -> bool:
        return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16) % 2 == 0

    swap_mask = df["match_id"].astype(str).map(_swap_bit).values
    n_swap = int(swap_mask.sum())
    # *_diff = (p1 − p2) → при swap становится (p2 − p1) = −diff
    diff_cols = [c for c in df.columns if c.endswith("_diff")]
    for c in diff_cols:
        if c in df.columns:
            df.loc[swap_mask, c] = -df.loc[swap_mask, c].astype(float)
    # ratio-фичи (p1/p2): при swap должны быть (p2/p1) = 1/ratio
    for c in ("fatigue_ratio", "experience_ratio"):
        if c not in df.columns:
            continue
        x = df.loc[swap_mask, c].astype(float)
        x = np.clip(x, 1e-6, 1e6)
        df.loc[swap_mask, c] = 1.0 / x
    if "fatigue_ratio_log" in df.columns:
        df.loc[swap_mask, "fatigue_ratio_log"] = -df.loc[swap_mask, "fatigue_ratio_log"].astype(float)
    if "p1_exp_bucket" in df.columns and "p2_exp_bucket" in df.columns:
        p1_val = df.loc[swap_mask, "p1_exp_bucket"].copy()
        df.loc[swap_mask, "p1_exp_bucket"] = df.loc[swap_mask, "p2_exp_bucket"].values
        df.loc[swap_mask, "p2_exp_bucket"] = p1_val.values
    df.loc[swap_mask, "target_match"] = 1 - df.loc[swap_mask, "target_match"].astype(int).values
    df.loc[swap_mask, "target_set1"] = 1 - df.loc[swap_mask, "target_set1"].astype(int).values
    target_mean_after = float(df["target_match"].astype(float).mean())
    logger.info(
        "ML v2 p1/p2 balance: swapped %s rows, target_match.mean before=%.4f after=%.4f",
        n_swap,
        target_mean_before,
        target_mean_after,
    )
    print(
        f"ML v2 p1/p2 balance: swapped={n_swap} target_mean before={target_mean_before:.4f} after={target_mean_after:.4f}",
        flush=True,
    )
    return df


def _apply_training_quality_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    min_exp = max(0, int(getattr(settings, "ml_v2_train_min_matches_played_before", 0) or 0))
    require_h2h = bool(getattr(settings, "ml_v2_train_require_h2h", False))
    league_upset_cap = float(getattr(settings, "ml_v2_train_max_league_upset_rate", 0.45))
    before = len(df)
    out = df
    if min_exp > 0 and "matches_played_before" in out.columns:
        out = out[out["matches_played_before"] >= float(min_exp)].copy()
    if require_h2h and "h2h_count" in out.columns:
        out = out[out["h2h_count"] >= 1.0].copy()
    # Chaos leagues: лиги с upset rate > порога — почти рандом, исключаем из обучения.
    if league_upset_cap < 1.0 and "league_upset_rate" in out.columns:
        out = out[out["league_upset_rate"] <= league_upset_cap].copy()
    logger.info(
        "ML v2 quality-filter: before=%s after=%s min_exp=%s require_h2h=%s league_upset_cap=%.2f",
        before,
        len(out),
        min_exp,
        require_h2h,
        league_upset_cap,
    )
    print(
        f"ML v2 quality-filter before={before} after={len(out)} min_exp={min_exp} require_h2h={require_h2h} league_upset_cap={league_upset_cap}",
        flush=True,
    )
    return out


def _log_signal_strength_snapshot(df: pd.DataFrame, target: str = "target_match") -> None:
    if df.empty or target not in df.columns:
        return
    key_cols = [
        "elo_diff",
        "strength_trend_diff",
        "dominance_last_50_diff",
        "points_ratio_20_diff",
        "sets_ratio_20_diff",
        "fatigue_ratio",
        "fatigue_index_diff",
        "matches_6h_diff",
        "matches_12h_diff",
        "winrate_20_diff",
        "momentum_today_diff",
    ]
    cols = [c for c in key_cols if c in df.columns]
    if len(cols) < 2:
        return
    sample = df.tail(min(200_000, len(df))).copy()
    X = sample[cols].astype(float)
    y = sample[target].astype(int).values
    try:
        mi = mutual_info_classif(X, y, random_state=42)
        pairs = sorted(zip(cols, mi), key=lambda x: -float(x[1]))
        line = ", ".join(f"{k}={float(v):.6g}" for k, v in pairs)
        logger.info("ML v2 signal snapshot [%s]: %s", target, line)
        print(f"ML v2 signal snapshot [{target}]: {line}", flush=True)
    except Exception as exc:
        logger.warning("ML v2 signal snapshot failed: %s", exc)


def _diagnose_training_data(train: pd.DataFrame) -> None:
    """Диагностика перед обучением: target, дисперсия фичей, сэмпл. Если best_iteration=1 и logloss≈0.693 — смотреть сюда."""
    if train.empty:
        return
    y = train["target_match"].astype(int)
    print("=== ML v2 diagnostic: target ===", flush=True)
    print("target_match mean:", float(y.mean()), flush=True)
    try:
        vc = y.value_counts(normalize=True).sort_index()
        print("target_match distribution (normalize=True):", vc.to_dict(), flush=True)
    except Exception as e:
        logger.warning("target value_counts failed: %s", e)
    # Корреляция сильных фич с target (ожидаем ~0.1–0.25 для TT; ~0 → target или rolling сломан).
    for col in ["winrate_20_diff", "points_ratio_20_diff", "elo_diff", "dominance_last_50_diff"]:
        if col in train.columns and col in FEATURE_COLS_V2_TRAIN:
            try:
                c = np.corrcoef(train[col].astype(float).values, y.values)[0, 1]
                print(f"  corr({col}, target_match): {float(c):.4f}", flush=True)
            except Exception:
                pass
    # Дисперсия фичей: константы → rolling сломан.
    print("=== ML v2 diagnostic: feature variance (LOW VAR = подозрительно) ===", flush=True)
    low_var = []
    for col in FEATURE_COLS_V2_TRAIN:
        if col not in train.columns:
            continue
        v = float(train[col].astype(float).std())
        if v < 0.00001:
            low_var.append((col, v))
    if low_var:
        for col, v in low_var[:30]:
            print(f"  LOW VAR: {col} std={v:.2e}", flush=True)
        if len(low_var) > 30:
            print(f"  ... and {len(low_var) - 30} more", flush=True)
    else:
        print("  (no near-constant features)", flush=True)
    # describe ключевых rolling-фич (норма: mean не 0, std не 0).
    key_cols = [c for c in ["winrate_10_diff", "points_ratio_20_diff", "dominance_last_50_diff"] if c in train.columns]
    if key_cols:
        print("=== ML v2 diagnostic: describe rolling (mean≈0, std>0 — ок) ===", flush=True)
        try:
            print(train[key_cols].astype(float).describe().to_string(), flush=True)
        except Exception as e:
            logger.warning("describe failed: %s", e)
    # 5 строк: match_id + фичи + target (проверка что target не перевёрнут).
    sample_cols = ["match_id", "winrate_20_diff", "points_ratio_20_diff", "dominance_last_50_diff", "target_match"]
    sample_cols = [c for c in sample_cols if c in train.columns]
    if sample_cols:
        print("=== ML v2 diagnostic: sample 5 rows ===", flush=True)
        try:
            print(train[sample_cols].head(5).to_string(), flush=True)
        except Exception as e:
            logger.warning("sample head failed: %s", e)


def _clip_by_train_quantiles(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
    clip_q: float = 0.01,
) -> None:
    """Клип фичей по квантилям только по train (без утечки val/test). Изменяет train/val/test in-place."""
    for c in FEATURE_COLS_V2:
        if c not in train.columns:
            continue
        lo = float(train[c].astype(float).quantile(clip_q))
        hi = float(train[c].astype(float).quantile(1.0 - clip_q))
        if lo < hi:
            train[c] = train[c].astype(float).clip(lower=lo, upper=hi)
            if c in val.columns:
                val[c] = val[c].astype(float).clip(lower=lo, upper=hi)
            if c in test.columns:
                test[c] = test[c].astype(float).clip(lower=lo, upper=hi)


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Temporal split по годам (train 2016–2023, val 2024, test 2025+) — без утечки будущего.
    if bool(getattr(settings, "ml_v2_split_by_year", True)):
        df = df.copy()
        df["_year"] = df["start_time"].dt.year
        train = df[(df["_year"] >= 2016) & (df["_year"] <= 2023)].drop(columns=["_year"]).copy()
        val_2024 = df[df["_year"] == 2024].copy()
        test = df[df["_year"] >= 2025].drop(columns=["_year"]).copy()
        if len(test) == 0 and len(val_2024) >= 2:
            nv = len(val_2024)
            val = val_2024.iloc[: nv // 2].drop(columns=["_year"]).copy()
            test = val_2024.iloc[nv // 2 :].drop(columns=["_year"]).copy()
        else:
            val = val_2024.drop(columns=["_year"]).copy()
        return train, val, test
    # Fallback: квантили по времени 80% / 10% / 10%.
    n = len(df)
    train_end_idx = int(n * 0.80)
    val_end_idx = int(n * 0.90)
    train = df.iloc[:train_end_idx].copy()
    val = df.iloc[train_end_idx:val_end_idx].copy()
    test = df.iloc[val_end_idx:].copy()
    return train, val, test


def _apply_clock_feature_guard(X: pd.DataFrame) -> pd.DataFrame:
    if not bool(getattr(settings, "ml_v2_disable_clock_features", True)):
        return X
    out = X.copy()
    for c in _CLOCK_FEATURE_COLS_V2:
        if c in out.columns:
            out[c] = 0.0
    return out


def _apply_market_feature_guard(X: pd.DataFrame) -> pd.DataFrame:
    """Обнуляем фичи линии при ml_v2_disable_market_features — модель опирается на игрока, не на кэф."""
    if not bool(getattr(settings, "ml_v2_disable_market_features", True)):
        return X
    out = X.copy()
    for c in _MARKET_FEATURE_COLS_V2:
        if c in out.columns:
            out[c] = 0.5 if c in ("market_prob_p1", "market_prob_p2") else 0.0
    return out


def _fit_binary(
    train: pd.DataFrame,
    val: pd.DataFrame,
    target: str,
    use_gpu: bool,
    feature_cols: list[str] | None = None,
) -> lgb.LGBMClassifier:
    y_train = train[target].astype(int)
    pos = int((y_train == 1).sum())
    neg = int((y_train == 0).sum())
    imbalance_ratio = (max(pos, neg) / max(1, min(pos, neg))) if min(pos, neg) > 0 else 1.0
    # Конфиг под TT: меньше мёртвых фичей, temporal split, сильный сигнал (latent_strength_diff, elo_diff).
    min_child = int(getattr(settings, "ml_v2_lgb_min_child_samples", 20))
    num_leaves = int(getattr(settings, "ml_v2_lgb_num_leaves", 128))
    reg_alpha = 0.5
    reg_lambda = 1.5
    # target_match часто переобучается (best_iteration=5, val logloss растёт): сильнее регуляризация.
    if target == "target_match":
        num_leaves = int(getattr(settings, "ml_v2_lgb_num_leaves_match", 64))
        min_child = max(min_child, int(getattr(settings, "ml_v2_lgb_min_child_match", 50)))
        reg_alpha = float(getattr(settings, "ml_v2_lgb_reg_alpha_match", 1.0))
        reg_lambda = float(getattr(settings, "ml_v2_lgb_reg_lambda_match", 2.5))
    # target_set1: при слабой регуляризации best_iteration=1 и val logloss взлетает до 13+ — ограничиваем дерево.
    if target == "target_set1":
        num_leaves = int(getattr(settings, "ml_v2_lgb_num_leaves_set1", 96))
        min_child = max(min_child, int(getattr(settings, "ml_v2_lgb_min_child_set1", 30)))
        reg_alpha = float(getattr(settings, "ml_v2_lgb_reg_alpha_set1", 0.7))
        reg_lambda = float(getattr(settings, "ml_v2_lgb_reg_lambda_set1", 1.8))
    params = dict(
        objective="binary",
        metric="binary_logloss",
        learning_rate=float(getattr(settings, "ml_v2_lgb_learning_rate", 0.03)),
        num_leaves=num_leaves,
        max_depth=-1,
        feature_fraction=0.75,
        bagging_fraction=0.8,
        bagging_freq=5,
        min_child_samples=min_child,
        min_child_weight=1e-3,
        reg_alpha=reg_alpha,
        reg_lambda=reg_lambda,
        min_split_gain=0.0,
        max_bin=255,
        n_estimators=3000,
        verbosity=-1,
        n_jobs=min(16, os.cpu_count() or 4),
    )
    # CUDA tree learner can collapse on balanced binary targets when is_unbalance is enabled.
    # Use explicit scale_pos_weight only for materially imbalanced targets.
    if imbalance_ratio >= 1.25 and pos > 0:
        params["scale_pos_weight"] = float(neg / max(1, pos))
    if use_gpu:
        params["device"] = "cuda"
        params["n_jobs"] = 1
    else:
        params["device"] = "cpu"
    feats = feature_cols if feature_cols is not None else FEATURE_COLS_V2_TRAIN
    # Только отобранные фичи (без мёртвых и избыточных rolling).
    X_train = train[feats].astype(float)
    X_val = val[feats].astype(float)
    y_val = val[target].astype(int)
    sample_weight_train = None
    if "matches_played_before" in train.columns:
        exp = pd.to_numeric(train["matches_played_before"], errors="coerce").fillna(0.0).astype(float).values
        # Stronger cold-start guard: low-history players are much noisier in TT.
        sample_weight_train = np.clip((exp + 3.0) / 25.0, 0.15, 1.0)
        logger.info(
            "ML v2 train [%s]: experience weighting enabled, mean_weight=%.4f low_exp(<10)=%s",
            target,
            float(np.mean(sample_weight_train)),
            int(np.sum(exp < 10.0)),
        )
    logger.info(
        "ML v2 train [%s]: device=%s train_rows=%s val_rows=%s",
        target,
        params["device"],
        len(train),
        len(val),
    )
    if bool(getattr(settings, "ml_v2_disable_clock_features", True)):
        logger.info("ML v2 train [%s]: clock features disabled: %s", target, _CLOCK_FEATURE_COLS_V2)
    print(
        f"ML v2 train [{target}] device={params['device']} train_rows={len(train)} val_rows={len(val)} imbalance_ratio={imbalance_ratio:.3f}",
        flush=True,
    )
    model = lgb.LGBMClassifier(**params)
    model.fit(
        X_train,
        y_train,
        sample_weight=sample_weight_train,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lgb.log_evaluation(25),
            lgb.early_stopping(int(getattr(settings, "ml_lgb_early_stopping_rounds", 300)), verbose=True),
        ],
    )
    # If model collapses at iteration 1, retry with permissive profile.
    if int(getattr(model, "best_iteration_", 0) or 0) <= 1:
        retry = dict(params)
        retry.update(
            learning_rate=0.035,
            num_leaves=127,
            min_child_samples=12,
            reg_lambda=0.2,
            n_estimators=4000,
        )
        logger.warning(
            "ML v2 train [%s]: degenerate best_iteration=%s, retry with permissive profile",
            target,
            model.best_iteration_,
        )
        model = lgb.LGBMClassifier(**retry)
        model.fit(
            X_train,
            y_train,
            sample_weight=sample_weight_train,
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.log_evaluation(25),
                lgb.early_stopping(300, verbose=True),
            ],
        )
    best_it = int(getattr(model, "best_iteration_", 0) or 0)
    print(f"ML v2 train [{target}] best_iteration={best_it} num_trees={int(getattr(model, 'n_estimators_', 0) or 0)}", flush=True)
    if best_it <= 1:
        print(f"ML v2 WARNING: best_iteration={best_it} → модель не видит сигнал (проверь target, leakage, rolling, split)", flush=True)
    try:
        imp = pd.Series(model.feature_importances_, index=feats).sort_values(ascending=False)
        logger.info("ML v2 train [%s] top importances: %s", target, imp.head(12).to_dict())
        print(f"ML v2 train [{target}] top_importances (top 12)={imp.head(12).to_dict()}", flush=True)
        print("ML v2 train [%s] feature_importance top 20:" % target, flush=True)
        print(imp.head(20).to_string(), flush=True)
        if imp.max() == 0 or (imp.head(20) == 0).all():
            print("ML v2 WARNING: все importance = 0 → модель не использует фичи", flush=True)
    except Exception as e:
        logger.warning("feature_importances failed: %s", e)
    return model


def _metrics(
    model: lgb.LGBMClassifier,
    df: pd.DataFrame,
    target: str,
    calibrator: BinaryProbabilityCalibrator | None = None,
) -> dict[str, float]:
    """Метрики на df: raw_logloss — только модель; logloss — после калибровки и ансамбля с Elo."""
    if df.empty:
        return {"n": 0, "accuracy": 0.0, "logloss": 0.0, "raw_logloss": 0.0, "brier": 0.0}
    cols = list(getattr(model, "feature_name_", [])) or FEATURE_COLS_V2_TRAIN
    X = df[[c for c in cols if c in df.columns]].astype(float)
    y = df[target].astype(int).values
    p_raw = model.predict_proba(X)[:, 1]
    raw_logloss = float(log_loss(y, np.clip(p_raw, 1e-9, 1 - 1e-9)))
    p = p_raw.copy()
    if calibrator is not None:
        p = calibrator.predict(p)
    # Final production probability uses simple ML+Elo ensemble.
    if "elo_diff" in df.columns:
        w_elo = float(getattr(settings, "ml_v2_ensemble_elo_weight", 0.3))
        w_elo = max(0.0, min(1.0, w_elo))
        p_elo = 1.0 / (1.0 + (10.0 ** (-df["elo_diff"].astype(float).values / 400.0)))
        p = (1.0 - w_elo) * p + w_elo * p_elo
    return {
        "n": int(len(df)),
        "accuracy": float(accuracy_score(y, (p >= 0.5).astype(int))),
        "logloss": float(log_loss(y, np.clip(p, 1e-9, 1 - 1e-9))),
        "raw_logloss": raw_logloss,
        "brier": float(brier_score_loss(y, p)),
    }


def _fit_nn_binary(
    train: pd.DataFrame,
    val: pd.DataFrame,
    target: str,
    feature_cols: list[str],
) -> Pipeline:
    """Train a compact MLP pipeline for prematch NN channel."""
    X_train = train[feature_cols].astype(float)
    y_train = train[target].astype(int)
    X_val = val[feature_cols].astype(float)
    y_val = val[target].astype(int)

    hidden = tuple(
        int(x.strip())
        for x in str(getattr(settings, "ml_v2_nn_hidden_layers", "128,64")).split(",")
        if x.strip().isdigit()
    ) or (128, 64)
    clf = MLPClassifier(
        hidden_layer_sizes=hidden,
        activation="relu",
        solver="adam",
        alpha=float(getattr(settings, "ml_v2_nn_alpha", 1e-4)),
        learning_rate_init=float(getattr(settings, "ml_v2_nn_learning_rate", 1e-3)),
        batch_size=int(getattr(settings, "ml_v2_nn_batch_size", 256)),
        max_iter=int(getattr(settings, "ml_v2_nn_max_iter", 120)),
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=10,
        random_state=42,
    )
    pipe = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("mlp", clf),
        ]
    )
    pipe.fit(X_train, y_train)
    try:
        p_val = pipe.predict_proba(X_val)[:, 1]
        ll = float(log_loss(y_val.values, np.clip(p_val, 1e-9, 1 - 1e-9)))
        acc = float(accuracy_score(y_val.values, (p_val >= 0.5).astype(int)))
        logger.info("NN v2 train [%s]: val_logloss=%.6f val_acc=%.4f", target, ll, acc)
        print(f"NN v2 train [{target}] val_logloss={ll:.6f} val_acc={acc:.4f}", flush=True)
    except Exception as exc:
        logger.warning("NN v2 metrics [%s] failed: %s", target, exc)
    return pipe


def retrain_models_v2(min_rows: int = 1000) -> dict[str, Any]:
    ensure_schema()
    df = _load_feature_frame()
    df = _apply_training_quality_filters(df)
    # Баланс p1/p2: убираем позиционный bias (target.mean() ~ 0.5).
    df = _balance_p1_p2(df)
    _log_signal_strength_snapshot(df, target="target_match")
    if len(df) < min_rows:
        return {"trained": False, "rows": len(df), "reason": "not_enough_data_v2"}

    train, val, test = _split(df)
    if len(train) < min_rows or len(val) < 500:
        return {
            "trained": False,
            "rows": len(df),
            "reason": "split_not_enough_data",
            "train_rows": len(train),
            "val_rows": len(val),
        }

    # Клип по квантилям только по train (без утечки val/test).
    clip_q = float(getattr(settings, "ml_v2_feature_clip_quantile", 0.01))
    _clip_by_train_quantiles(train, val, test, clip_q)

    # Распределение по годам (проверка, что train не пустой и есть val/test).
    if "start_time" in train.columns:
        for part, label in [(train, "train"), (val, "val"), (test, "test")]:
            years = part["start_time"].dt.year
            print(f"ML v2 split {label}: rows={len(part)} years={sorted(years.unique().tolist())}", flush=True)

    _diagnose_training_data(train)

    # Опционально: топ-K фичей по |corr| с target_match (меньше шума, быстрее обучение).
    top_k = int(getattr(settings, "ml_v2_top_k_features", 0) or 0)
    if top_k > 0 and top_k < len(FEATURE_COLS_V2_TRAIN):
        y_tr = train["target_match"].astype(float).values
        corrs: list[tuple[str, float]] = []
        for c in FEATURE_COLS_V2_TRAIN:
            if c not in train.columns:
                continue
            r = np.corrcoef(train[c].astype(float).values, y_tr)[0, 1]
            if np.isfinite(r):
                corrs.append((c, float(r)))
        corrs.sort(key=lambda x: -abs(x[1]))
        feature_cols_used = [c for c, _ in corrs[:top_k]]
        print(f"ML v2 top_k_features={top_k}: using {len(feature_cols_used)} features (by |corr| with target_match)", flush=True)
    else:
        feature_cols_used = FEATURE_COLS_V2_TRAIN

    # Experience regime bucket: max(p1_exp_bucket, p2_exp_bucket), 1..4 (rookie..pro).
    for part in (train, val, test):
        p1_b = part["p1_exp_bucket"].astype(float).fillna(1.0)
        p2_b = part["p2_exp_bucket"].astype(float).fillna(1.0)
        part["_bucket"] = np.clip(np.maximum(p1_b.values, p2_b.values), 1, 4).astype(int)

    use_gpu = bool(getattr(settings, "ml_use_gpu", True))
    if not use_gpu:
        raise RuntimeError("ML v2 retrain requires GPU (ML_USE_GPU=true)")
    m_match = _fit_binary(train, val, "target_match", use_gpu=use_gpu, feature_cols=feature_cols_used)
    m_set1 = _fit_binary(train, val, "target_set1", use_gpu=use_gpu, feature_cols=feature_cols_used)
    x_val = val[feature_cols_used].astype(float)
    calib_match = BinaryProbabilityCalibrator.fit(
        m_match.predict_proba(x_val)[:, 1],
        val["target_match"].astype(int).values,
    )
    calib_set1 = BinaryProbabilityCalibrator.fit(
        m_set1.predict_proba(x_val)[:, 1],
        val["target_set1"].astype(int).values,
    )
    logger.info(
        "ML v2 calibration: match=%s(%.6f), set1=%s(%.6f)",
        calib_match.method,
        calib_match.train_logloss,
        calib_set1.method,
        calib_set1.train_logloss,
    )
    print(
        "ML v2 calibration methods:"
        f" match={calib_match.method} ll={calib_match.train_logloss:.6f},"
        f" set1={calib_set1.method} ll={calib_set1.train_logloss:.6f}",
        flush=True,
    )

    model_dir = Path(getattr(settings, "ml_model_dir", "/tmp/pingwin_ml_models"))
    model_dir.mkdir(parents=True, exist_ok=True)
    prefix = model_dir / "tt_ml_v2"
    joblib.dump(m_match, f"{prefix}_match.joblib")
    joblib.dump(m_set1, f"{prefix}_set1.joblib")
    joblib.dump(calib_match, f"{prefix}_match_calib.joblib")
    joblib.dump(calib_set1, f"{prefix}_set1_calib.joblib")
    meta = {
        "version": "v2",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "features": feature_cols_used,
        "n_features": int(len(feature_cols_used)),
        "train_rows": int(len(train)),
        "val_rows": int(len(val)),
        "test_rows": int(len(test)),
        "calibration": {
            "match": {"method": calib_match.method, "fit_logloss": float(calib_match.train_logloss)},
            "set1": {"method": calib_set1.method, "fit_logloss": float(calib_set1.train_logloss)},
        },
    }
    with open(f"{prefix}_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info("ML v2 models saved: match/set1 with %s features", len(feature_cols_used))
    print(f"ML v2 models saved: features={len(feature_cols_used)}", flush=True)

    # Experience regimes: 4 отдельные модели — rookie / low / mid / pro (bucket 1..4).
    # routing: bucket = max(p1_exp_bucket, p2_exp_bucket); rookie=хаос, veteran=предсказуемость.
    BUCKET_NAMES = {1: "rookie", 2: "low", 3: "mid", 4: "pro"}
    regime_min = int(getattr(settings, "ml_v2_experience_regime_min_train", 500))
    use_regimes = bool(getattr(settings, "ml_v2_use_experience_regimes", False))
    print(f"ML v2 experience regimes: use_regimes={use_regimes} (ML_V2_USE_EXPERIENCE_REGIMES), min_train={regime_min}", flush=True)
    if use_regimes:
        bucket_counts: dict[int, int] = {}
        for b in (1, 2, 3, 4):
            train_b = train[train["_bucket"] == b]
            val_b = val[val["_bucket"] == b]
            bucket_counts[b] = len(train_b)
            name = BUCKET_NAMES.get(b, f"b{b}")
            if len(train_b) < regime_min or len(val_b) < 50:
                msg = f"ML v2 bucket {b} ({name}): skip (train={len(train_b)} val={len(val_b)}, need train>={regime_min} val>=50)"
                logger.info("ML v2 bucket %s (%s): skip (train=%s val=%s)", b, name, len(train_b), len(val_b))
                print(msg, flush=True)
                continue
            m_m = _fit_binary(train_b, val_b, "target_match", use_gpu=use_gpu, feature_cols=feature_cols_used)
            m_s = _fit_binary(train_b, val_b, "target_set1", use_gpu=use_gpu, feature_cols=feature_cols_used)
            x_v = val_b[feature_cols_used].astype(float)
            cal_m = BinaryProbabilityCalibrator.fit(
                m_m.predict_proba(x_v)[:, 1], val_b["target_match"].astype(int).values
            )
            cal_s = BinaryProbabilityCalibrator.fit(
                m_s.predict_proba(x_v)[:, 1], val_b["target_set1"].astype(int).values
            )
            prefix_b = model_dir / f"tt_ml_v2_b{b}"
            joblib.dump(m_m, f"{prefix_b}_match.joblib")
            joblib.dump(m_s, f"{prefix_b}_set1.joblib")
            joblib.dump(cal_m, f"{prefix_b}_match_calib.joblib")
            joblib.dump(cal_s, f"{prefix_b}_set1_calib.joblib")
            name = BUCKET_NAMES.get(b, f"b{b}")
            logger.info("ML v2 bucket %s (%s): saved (train=%s val=%s)", b, name, len(train_b), len(val_b))
            print(f"ML v2 model_{name} (b{b}) saved: train={len(train_b)} val={len(val_b)}", flush=True)
        meta["experience_regimes"] = True
        meta["bucket_train_counts"] = bucket_counts
        with open(f"{prefix}_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print("ML v2 experience regimes: bucket models saved (tt_ml_v2_b1..b4_*). Inference will use them when present.", flush=True)
    else:
        print("ML v2 experience regimes: disabled. Set ML_V2_USE_EXPERIENCE_REGIMES=true and retrain to get 4 bucket models (rookie/low/mid/pro).", flush=True)

    nn_enabled = bool(getattr(settings, "ml_v2_enable_nn", True))
    if nn_enabled:
        nn_match = _fit_nn_binary(train, val, "target_match", feature_cols_used)
        nn_set1 = _fit_nn_binary(train, val, "target_set1", feature_cols_used)
        nn_prefix = model_dir / "tt_nn_v2"
        joblib.dump(nn_match, f"{nn_prefix}_match.joblib")
        joblib.dump(nn_set1, f"{nn_prefix}_set1.joblib")
        with open(f"{nn_prefix}_meta.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": "nn_v2",
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "features": feature_cols_used,
                    "n_features": int(len(feature_cols_used)),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"NN v2 models saved: {nn_prefix}_match/set1.joblib", flush=True)
    else:
        print("NN v2 training disabled (ML_V2_ENABLE_NN=false).", flush=True)

    metrics = {
        "match": {
            "train": _metrics(m_match, train, "target_match", None),
            "val": _metrics(m_match, val, "target_match", calib_match),
            "test": _metrics(m_match, test, "target_match", calib_match),
        },
        "set1": {
            "train": _metrics(m_set1, train, "target_set1", None),
            "val": _metrics(m_set1, val, "target_set1", calib_set1),
            "test": _metrics(m_set1, test, "target_set1", calib_set1),
        },
    }
    best_it_match = int(getattr(m_match, "best_iteration_", 0) or 0)
    best_it_set1 = int(getattr(m_set1, "best_iteration_", 0) or 0)
    print(
        f"ML v2 best_iteration: match={best_it_match} set1={best_it_set1} (если 1–5 — модель почти не учится или переобучается)",
        flush=True,
    )
    # Baseline: случайный классификатор имеет logloss = ln(2) ≈ 0.693. Цель: 0.50–0.51.
    print("ML v2 baseline: random classifier logloss = 0.693 (цель: val raw_logloss 0.50–0.51)", flush=True)
    # В лог: raw_logloss = только модель; logloss = после калибровки и ансамбля с Elo (0.3).
    for name, data in [("match", metrics["match"]), ("set1", metrics["set1"])]:
        for split in ("train", "val", "test"):
            m = data.get(split, {})
            if m.get("n", 0) == 0:
                continue
            raw = m.get("raw_logloss")
            fin = m.get("logloss")
            if raw is not None and fin is not None:
                logger.info("ML v2 %s %s: raw_logloss=%.6f logloss(calib+elo)=%.6f", name, split, raw, fin)
                print(f"ML v2 {name} {split}: raw_logloss={raw:.6f} logloss(calib+elo)={fin:.6f}", flush=True)
            if raw is not None and raw >= 0.68:
                print(
                    f"ML v2 WARNING: {name} {split} raw_logloss={raw:.3f} ≈ random (0.693). Проверь: target, утечку, сплит, регуляризацию (num_leaves, min_child). Цель: 0.50–0.51.",
                    flush=True,
                )
    # Если на train тоже ~0.69 — недообучение: модель не выучивает сигнал. Попробуй ослабить регуляризацию или ML_V2_TRAIN_REQUIRE_H2H=false.
    train_match_raw = (metrics.get("match") or {}).get("train") or {}
    if (train_match_raw.get("raw_logloss") or 0) >= 0.68:
        print(
            "ML v2 TIP: train raw_logloss ≈ random → недообучение. Попробуй: ML_V2_LGB_NUM_LEAVES_MATCH=128, ML_V2_LGB_MIN_CHILD_MATCH=20, или ML_V2_TRAIN_REQUIRE_H2H=false (больше данных).",
            flush=True,
        )
    return {
        "trained": True,
        "rows": int(len(df)),
        "path": str(prefix),
        "train_device": "cuda",
        "best_iteration_match": best_it_match,
        "best_iteration_set1": best_it_set1,
        "validation_metrics": metrics,
    }

