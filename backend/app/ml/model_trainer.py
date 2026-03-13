"""ML модели: XGBoost/LightGBM с поддержкой GPU."""
from __future__ import annotations

import json
import logging
import os
import threading
import warnings
from pathlib import Path
from typing import Any

import numpy as np

# XGBoost/LightGBM predict() не thread-safe — сериализуем доступ (GPU и CPU)
_ml_predict_lock = threading.Lock()
import pandas as pd
from sqlalchemy import text

from app.config import settings
from app.ml.db import get_ml_engine, get_ml_session

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    # Базовые
    "elo_diff", "form_diff", "fatigue_diff", "h2h_diff", "winrate_10_diff",
    "odds_diff", "h2h_count",
    # Tempo, streak
    "avg_sets_per_match_diff", "sets_over35_rate_diff", "streak_score",
    "minutes_since_last_match_diff", "dominance_diff",
    # Volatility
    "std_points_diff_last10_p1", "std_points_diff_last10_p2",
    "elo_volatility_diff",
    # Odds
    "log_odds_ratio", "implied_prob_p1", "market_margin",
    # Momentum, sets
    "momentum_today_diff", "set1_strength_diff", "comeback_rate_diff",
    # Сильные фичи v3
    "dominance_last_50_diff",
    "fatigue_index_diff", "fatigue_ratio",
    "minutes_to_match",
    "odds_shift_p1", "odds_shift_p2",
    "daily_performance_trend_diff",
    "dominance_trend_diff",
    "style_clash",
]
TARGET_MATCH = "target_match"
TARGET_SET1 = "target_set1"
TARGET_SET = "target_set"  # любой сет (для p_set → Monte Carlo)


def _detect_gpu() -> dict[str, Any]:
    """Определяет доступность GPU для XGBoost/LightGBM.
    ML_USE_GPU=false — принудительно CPU.
    ML_USE_AMD_GPU=1 — AMD MI50 (ROCm/HIP), device=hip.
    Иначе — NVIDIA CUDA."""
    if not getattr(settings, "ml_use_gpu", True):
        logger.info("ML: GPU отключён (ml_use_gpu=false), используем CPU")
        return {"tree_method": "hist", "device": "cpu"}
    if os.environ.get("ML_USE_AMD_GPU", "").strip() in ("1", "true", "yes"):
        logger.info("ML: AMD GPU (ROCm/HIP), XGBoost device=hip")
        return {"tree_method": "hist", "device": "hip"}
    use_gpu = False
    cuda_reason = ""
    def _cuda_driver_ok() -> tuple[bool, str]:
        try:
            import ctypes
            cu = ctypes.CDLL("libcuda.so.1")
            rc_init = int(cu.cuInit(0))
            if rc_init != 0:
                return False, f"cuInit={rc_init}"
            cnt = ctypes.c_int()
            rc_count = int(cu.cuDeviceGetCount(ctypes.byref(cnt)))
            if rc_count != 0:
                return False, f"cuDeviceGetCount={rc_count}"
            if int(cnt.value) < 1:
                return False, "cuDeviceGetCount=0"
            return True, f"gpu_count={int(cnt.value)}"
        except Exception as e:
            return False, f"cuda_driver_probe_error={e}"
    try:
        import subprocess
        for cmd in [["nvidia-smi", "-L"], ["/usr/bin/nvidia-smi", "-L"]]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and "GPU" in (r.stdout or ""):
                    use_gpu = True
                    logger.info("ML: GPU обнаружен (%s), XGBoost будет использовать CUDA", (r.stdout or "").strip()[:80])
                    break
            except (FileNotFoundError, Exception):
                continue
        if not use_gpu and os.environ.get("NVIDIA_VISIBLE_DEVICES", "").strip() not in ("", "void"):
            use_gpu = True
            logger.info("ML: NVIDIA_VISIBLE_DEVICES задан, пробуем CUDA")
    except Exception as e:
        logger.debug("ML GPU detect: %s", e)
    if use_gpu:
        ok, cuda_reason = _cuda_driver_ok()
        if not ok:
            logger.warning("ML: CUDA недоступна для XGBoost (%s), переключаемся на CPU", cuda_reason)
            use_gpu = False
        else:
            logger.info("ML: CUDA Driver API OK (%s)", cuda_reason)
    if not use_gpu:
        logger.info("ML: GPU не найден, используем CPU")
    return {"tree_method": "hist", "device": "cuda:0" if use_gpu else "cpu"}


def load_training_data(limit: int = 100_000, min_sample_size: int = 10) -> pd.DataFrame:
    """Загружает датасет из match_features + matches для обучения."""
    engine = get_ml_engine()
    base_sql = """
        SELECT mf.match_id, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
               mf.winrate_10_diff, mf.odds_diff, mf.h2h_count,
               m.score_sets_p1, m.score_sets_p2, m.player1_id, m.player2_id,
               CASE WHEN m.score_sets_p1 > m.score_sets_p2 THEN 1 ELSE 0 END as target_match,
               (SELECT CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END
                FROM match_sets ms WHERE ms.match_id = m.id AND ms.set_number = 1
                AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL LIMIT 1) as target_set1
        FROM match_features mf
        JOIN matches m ON m.id = mf.match_id
        WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL AND m.score_sets_p2 IS NOT NULL
        ORDER BY m.start_time ASC
        LIMIT :lim
    """
    v2_cols = ", mf.avg_sets_per_match_diff, mf.sets_over35_rate_diff, mf.streak_score, " \
              "mf.minutes_since_last_match_diff, mf.dominance_diff, " \
              "mf.std_points_diff_last10_p1, mf.std_points_diff_last10_p2, " \
              "mf.log_odds_ratio, mf.implied_prob_p1, mf.market_margin, " \
              "mf.momentum_today_diff, mf.set1_strength_diff, mf.comeback_rate_diff"
    v3_cols = ", mf.dominance_last_50_diff, mf.fatigue_index_diff, mf.fatigue_ratio, " \
              "mf.minutes_to_match, mf.odds_shift_p1, mf.odds_shift_p2, " \
              "mf.elo_volatility_p1, mf.elo_volatility_p2, mf.elo_volatility_diff, " \
              "mf.daily_performance_trend_diff, mf.dominance_trend_diff, mf.style_clash"
    sql_v3 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + v3_cols + ",")
    sql_v2 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + ",")
    try:
        df = pd.read_sql(text(sql_v3), engine.connect(), params={"lim": limit})
    except Exception:
        try:
            df = pd.read_sql(text(sql_v2), engine.connect(), params={"lim": limit})
        except Exception:
            df = pd.read_sql(text(base_sql), engine.connect(), params={"lim": limit})

    df["target_set1"] = df["target_set1"].fillna(0.5).astype(int)
    for c in FEATURE_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(0)
        else:
            df[c] = 0.0
    return df


def load_set_training_data(limit: int = 200_000) -> pd.DataFrame:
    """Загружает set-level датасет: все сеты из match_sets + match_features.
    LightGBM на сетах ловит нелинейные взаимодействия (fatigue×league, elo×volatility)."""
    engine = get_ml_engine()
    v2_cols = ", mf.avg_sets_per_match_diff, mf.sets_over35_rate_diff, mf.streak_score, " \
              "mf.minutes_since_last_match_diff, mf.dominance_diff, " \
              "mf.std_points_diff_last10_p1, mf.std_points_diff_last10_p2, " \
              "mf.log_odds_ratio, mf.implied_prob_p1, mf.market_margin, " \
              "mf.momentum_today_diff, mf.set1_strength_diff, mf.comeback_rate_diff"
    v3_cols = ", mf.dominance_last_50_diff, mf.fatigue_index_diff, mf.fatigue_ratio, " \
              "mf.minutes_to_match, mf.odds_shift_p1, mf.odds_shift_p2, " \
              "mf.elo_volatility_diff, mf.daily_performance_trend_diff, " \
              "mf.dominance_trend_diff, mf.style_clash"
    sql = f"""
        SELECT mf.match_id, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
               mf.winrate_10_diff, mf.odds_diff, mf.h2h_count {v2_cols} {v3_cols},
               CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END as target_set
        FROM match_sets ms
        JOIN matches m ON m.id = ms.match_id
        JOIN match_features mf ON mf.match_id = m.id
        WHERE m.status = 'finished' AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL
        ORDER BY m.start_time ASC
        LIMIT :lim
    """
    try:
        df = pd.read_sql(text(sql), engine.connect(), params={"lim": limit})
    except Exception:
        sql_fallback = f"""
            SELECT mf.match_id, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
                   mf.winrate_10_diff, mf.odds_diff, mf.h2h_count {v2_cols},
                   CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END as target_set
            FROM match_sets ms
            JOIN matches m ON m.id = ms.match_id
            JOIN match_features mf ON mf.match_id = m.id
            WHERE m.status = 'finished' AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL
            ORDER BY m.start_time ASC
            LIMIT :lim
        """
        try:
            df = pd.read_sql(text(sql_fallback), engine.connect(), params={"lim": limit})
        except Exception:
            return pd.DataFrame()
    df["target_set"] = df["target_set"].fillna(0.5).astype(int)
    for c in FEATURE_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(0)
        else:
            df[c] = 0.0
    return df


def _train_binary_model(df: pd.DataFrame, target_col: str, use_gpu: bool | None = None) -> Any:
    """Обучает бинарную модель (match или set1)."""
    if use_gpu is None:
        use_gpu = getattr(settings, "ml_use_gpu", True)
    cols = [c for c in FEATURE_COLS if c in df.columns]
    if not cols:
        cols = [c for c in FEATURE_COLS[:7] if c in df.columns]
    X = df[cols].fillna(0)
    y = df[target_col]
    scale_pos_weight = max(0.1, (y == 0).sum() / max(1, (y == 1).sum()))

    try:
        import xgboost as xgb
    except ImportError:
        import lightgbm as lgb
        from sklearn.utils.class_weight import compute_sample_weight
        gpu = _detect_gpu()
        params = {
            "objective": "binary",
            "metric": "auc",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "n_estimators": 300,
            "verbose": -1,
        }
        if use_gpu and gpu["device"] == "cuda":
            params["device"] = "cuda"
        model = lgb.LGBMClassifier(**params)
        sw = compute_sample_weight("balanced", y)
        model.fit(X, y, sample_weight=sw)
        return model

    gpu = _detect_gpu() if use_gpu else {"tree_method": "hist", "device": "cpu"}
    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 300,
        "tree_method": gpu["tree_method"],
        "device": gpu["device"],
        "verbosity": 0,
        "scale_pos_weight": scale_pos_weight,
    }
    if gpu["device"] in ("cuda", "cuda:0", "hip"):
        logger.info("XGBoost: обучение на GPU (device=%s)", gpu["device"])
    try:
        model = xgb.XGBClassifier(**params)
        if gpu["device"] in ("cuda", "cuda:0", "hip"):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                model.fit(X, y)
            for warn in w:
                msg = str(warn.message)
                if "No visible GPU is found" in msg or "Device is changed from GPU to CPU" in msg:
                    raise RuntimeError(msg)
        else:
            model.fit(X, y)
    except Exception as e:
        err_str = str(e).lower()
        if "no visible gpu is found" in err_str or "device is changed from gpu to cpu" in err_str:
            raise RuntimeError(f"XGBoost не видит GPU внутри контейнера: {e}") from e
        if "nokernelimage" in err_str or "no kernel image" in err_str or "cudaerror" in err_str or "hiperror" in err_str:
            logger.warning("XGBoost GPU failed (%s), fallback на CPU", e)
            params["device"] = "cpu"
            params["tree_method"] = "hist"
            model = xgb.XGBClassifier(**params)
            model.fit(X, y)
        else:
            raise
    return model


def train_match_model(df: pd.DataFrame, use_gpu: bool | None = None) -> Any:
    """Обучает модель победы в матче (XGBoost)."""
    return _train_binary_model(df, TARGET_MATCH, use_gpu)


def train_set1_model(df: pd.DataFrame, use_gpu: bool = True) -> Any:
    """Обучает модель победы в 1-м сете (target_set1)."""
    return _train_binary_model(df, TARGET_SET1, use_gpu)


def train_set_model(df: pd.DataFrame, use_gpu: bool = True) -> Any:
    """Обучает модель победы в сете (любой сет). p_set → Monte Carlo → p_match."""
    return _train_binary_model(df, TARGET_SET, use_gpu)


def train_p_point_logistic(df: pd.DataFrame, version: str = "v1") -> Any:
    """Обучает LogisticRegression для p_set (fallback). Веса учатся вместо жёсткой формулы."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    cols = [c for c in FEATURE_COLS if c in df.columns]
    if not cols:
        cols = [c for c in FEATURE_COLS[:10] if c in df.columns]
    X = df[cols].fillna(0)
    y = df[TARGET_SET] if TARGET_SET in df.columns else df.get("target_set1", df.get(TARGET_MATCH))
    if y is None or len(y) < 50:
        return None
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=0.1,
            max_iter=2000,
            solver="lbfgs",
            class_weight="balanced",
            random_state=42,
        )),
    ])
    model.fit(X, y)
    return {"model": model, "cols": cols}


def save_models(
    match_model: Any,
    set1_model: Any,
    set_model: Any | None = None,
    p_point_model: Any | None = None,
    version: str = "v1",
) -> str:
    """Сохраняет модели на диск (joblib для CalibratedClassifierCV, иначе XGB/LGB native)."""
    import joblib
    model_dir = Path(getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
    model_dir.mkdir(parents=True, exist_ok=True)
    prefix = model_dir / f"tt_ml_{version}"
    models = [("match", match_model), ("set1", set1_model)]
    if set_model is not None:
        models.append(("set", set_model))
    if p_point_model is not None:
        models.append(("p_point", p_point_model))
    for name, model in models:
        path = f"{prefix}_{name}.joblib"
        if hasattr(model, "calibrated_classifiers_"):
            joblib.dump(model, path)
        else:
            try:
                model.save_model(path.replace(".joblib", ".json"))
            except AttributeError:
                joblib.dump(model, path)
    meta = {"version": version, "features": FEATURE_COLS}
    with open(f"{prefix}_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    return str(prefix)


def load_models(version: str = "v1") -> tuple[Any, Any, Any | None, Any | None]:
    """Загружает модели с диска. Возвращает (match_model, set1_model, set_model|None, p_point_model|None)."""
    import joblib
    model_dir = Path(getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
    prefix = model_dir / f"tt_ml_{version}"
    joblib_match = Path(f"{prefix}_match.joblib")
    json_match = Path(f"{prefix}_match.json")
    set_model = None
    p_point_model = None
    set_joblib = Path(f"{prefix}_set.joblib")
    p_point_joblib = Path(f"{prefix}_p_point.joblib")
    if set_joblib.exists():
        set_model = joblib.load(set_joblib)
    if p_point_joblib.exists():
        p_point_model = joblib.load(p_point_joblib)
    if joblib_match.exists():
        match_model = joblib.load(joblib_match)
        set1_model = joblib.load(f"{prefix}_set1.joblib")
    elif json_match.exists():
        import xgboost as xgb
        match_model = xgb.XGBClassifier()
        match_model.load_model(str(json_match))
        set1_model = xgb.XGBClassifier()
        set1_model.load_model(str(prefix) + "_set1.json")
        if set_model is None and Path(f"{prefix}_set.json").exists():
            set_model = xgb.XGBClassifier()
            set_model.load_model(str(prefix) + "_set.json")
    elif (Path(str(prefix) + "_match.txt").exists() and Path(str(prefix) + "_set1.txt").exists()):
        import lightgbm as lgb

        class _LGBWrapper:
            def __init__(self, booster):
                self._booster = booster

            def predict_proba(self, X):
                p = self._booster.predict(X)
                return np.column_stack([1 - p, p])

        match_model = _LGBWrapper(lgb.Booster(model_file=str(prefix) + "_match.txt"))
        set1_model = _LGBWrapper(lgb.Booster(model_file=str(prefix) + "_set1.txt"))
        if set_model is None and Path(f"{prefix}_set.txt").exists():
            set_model = _LGBWrapper(lgb.Booster(model_file=str(prefix) + "_set.txt"))
    else:
        raise FileNotFoundError(
            f"ML-модели не найдены в {model_dir}. Запустите retrain (Full rebuild или Переобучить)."
        )
    return match_model, set1_model, set_model, p_point_model


def _calibrate_model(model: Any, X: pd.DataFrame, y: pd.Series, groups: pd.Series | None) -> Any:
    """Калибровка модели (Platt scaling) для улучшения вероятностей."""
    try:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.model_selection import GroupKFold
        if len(X) > 120_000:
            # Калибровка на сэмпле заметно сокращает CPU-время, сохраняя качество.
            idx = np.random.default_rng(42).choice(len(X), size=120_000, replace=False)
            X = X.iloc[idx]
            y = y.iloc[idx]
            if groups is not None:
                groups = groups.iloc[idx]
        if groups is not None and groups.notna().all() and len(groups.unique()) >= 5:
            gkf = GroupKFold(n_splits=3)
            cv = list(gkf.split(X, y, groups=groups))
        else:
            cv = 3
        calibrated = CalibratedClassifierCV(model, cv=cv, method="sigmoid")
        calibrated.fit(X, y)
        return calibrated
    except Exception as e:
        logger.warning("Calibration skipped: %s", e)
        return model


def _verify_xgboost_gpu() -> bool:
    """Проверяет, что XGBoost реально использует GPU (warmup)."""
    try:
        import subprocess
        import sys
        probe_code = (
            "import warnings, numpy as np, xgboost as xgb; "
            "X=np.random.rand(256,8).astype('float32'); "
            "y=np.random.randint(0,2,256).astype('int32'); "
            "m=xgb.XGBClassifier(tree_method='hist',device='cuda:0',n_estimators=3,verbosity=0); "
            "warnings.simplefilter('always'); "
            "m.fit(X,y); "
            "print('XGB_GPU_WARMUP_OK')"
        )
        r = subprocess.run(
            [sys.executable, "-c", probe_code],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode != 0:
            logger.warning("XGBoost GPU warmup failed (rc=%s): %s", r.returncode, out.strip()[:800])
            return False
        if "No visible GPU is found" in out or "Device is changed from GPU to CPU" in out:
            logger.warning("XGBoost GPU warmup warning: %s", out.strip()[:800])
            return False
        if "XGB_GPU_WARMUP_OK" not in out:
            logger.warning("XGBoost GPU warmup ambiguous output: %s", out.strip()[:800])
            return False
        logger.info("XGBoost: GPU warmup OK")
        return True
    except Exception as e:
        logger.warning("XGBoost GPU warmup failed: %s", e)
        return False


def retrain_models_if_needed(min_rows: int = 100, version: str = "v1", progress_callback: Any = None) -> dict[str, Any]:
    """Переобучение моделей на всех данных. Вызывать после синхронизации новых матчей."""
    gpu_only = os.environ.get("ML_GPU_ONLY", "true").strip().lower() in ("1", "true", "yes")

    def _log(msg: str) -> None:
        logger.info(msg)
        print(msg, flush=True)

    if progress_callback:
        progress_callback(current=0, total=7, message="Загрузка данных…")
    df = load_training_data(limit=500_000)
    if len(df) < min_rows:
        return {"trained": False, "rows": len(df), "reason": "not_enough_data"}
    if progress_callback:
        progress_callback(current=1, total=7, message=f"Загружено {len(df)} строк. Обучение match-модели…")
    use_gpu = getattr(settings, "ml_use_gpu", True)
    gpu = _detect_gpu()
    device = gpu.get("device", "cpu")
    if use_gpu and str(device).startswith("cuda"):
        if not _verify_xgboost_gpu():
            raise RuntimeError(
                "GPU включен, но XGBoost не может использовать CUDA внутри контейнера. "
                "Проверьте совместимость CUDA image и драйвера."
            )
    _log(f"  Match-модель: старт ({len(df)} строк, {'CUDA' if use_gpu else 'CPU'}, ~5–15 мин GPU / ~20–40 мин CPU)")
    match_model = train_match_model(df, use_gpu=use_gpu)
    _log("  Match-модель: готово")
    if progress_callback:
        progress_callback(current=2, total=7, message="Обучение set1-модели…")
    _log("  Set1-модель: старт")
    set1_model = train_set1_model(df, use_gpu=use_gpu)
    _log("  Set1-модель: готово")
    set_model = None
    df_set = load_set_training_data(limit=200_000)
    if len(df_set) >= min_rows:
        if progress_callback:
            progress_callback(current=3, total=7, message="Обучение set-модели (LightGBM)…")
        _log("  Set-модель: старт")
        set_model = train_set_model(df_set, use_gpu=use_gpu)
        _log("  Set-модель: готово")
    p_point_model = None
    if gpu_only:
        _log("  GPU-only режим: пропускаем калибровку и p_point (CPU-этапы)")
    else:
        if progress_callback:
            progress_callback(current=4, total=7, message="Калибровка моделей…")
        _log("  Калибровка…")
        groups = df.get("player1_id")
        cols = [c for c in FEATURE_COLS if c in df.columns] or FEATURE_COLS[:7]
        X = df[cols].fillna(0)
        match_model = _calibrate_model(match_model, X, df[TARGET_MATCH], groups)
        set1_model = _calibrate_model(set1_model, X, df[TARGET_SET1], groups)
        if set_model is not None:
            X_set = df_set[cols].fillna(0) if cols[0] in df_set.columns else df_set[[c for c in FEATURE_COLS if c in df_set.columns]].fillna(0)
            set_model = _calibrate_model(set_model, X_set, df_set[TARGET_SET], df_set.get("match_id"))
        if len(df_set) >= min_rows:
            if progress_callback:
                progress_callback(current=4, total=7, message="Обучение p_point (logistic)…")
            p_point_model = train_p_point_logistic(df_set, version=version)
    if progress_callback:
        progress_callback(current=5, total=7, message="Сохранение моделей…")
    _log("  Сохранение моделей…")
    path = save_models(match_model, set1_model, set_model=set_model, p_point_model=p_point_model, version=version)
    if progress_callback:
        progress_callback(current=6, total=7, message="Готово")
    _log(f"  Retrain завершён: {path}")
    return {"trained": True, "rows": len(df), "path": path}


def predict_proba(model: Any, features: dict[str, float]) -> float:
    """Вероятность победы P1 (матч или сет1). Поддерживает tree-модели и p_point dict {model, cols}."""
    if isinstance(model, dict) and "model" in model and "cols" in model:
        cols = model["cols"]
        m = model["model"]
    else:
        cols = FEATURE_COLS
        m = model
    X = pd.DataFrame([{c: features.get(c, 0) for c in cols}])
    with _ml_predict_lock:
        proba = m.predict_proba(X)[0, 1]
    return float(proba)
