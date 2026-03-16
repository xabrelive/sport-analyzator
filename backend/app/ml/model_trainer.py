"""ML модели: LightGBM (GPU) + вспомогательные CPU-модели."""
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
    # Базовые (Tier S)
    "elo_diff",
    "elo_probability",  # P_elo = 1/(1+10^(-elo_diff/400)) — +3–5% к качеству как фича
    "form_diff", "fatigue_diff", "h2h_diff", "winrate_10_diff",
    "odds_diff", "h2h_count",
    # Tempo, streak
    "avg_sets_per_match_diff", "sets_over35_rate_diff", "streak_score",
    "minutes_since_last_match_diff", "dominance_diff",
    # Volatility (Tier A)
    "std_points_diff_last10_p1", "std_points_diff_last10_p2",
    "elo_volatility_diff",
    # Odds (Tier S)
    "log_odds_ratio", "implied_prob_p1", "market_margin",
    # Momentum, sets (Tier A)
    "momentum_today_diff", "set1_strength_diff", "comeback_rate_diff",
    # Сильные фичи v3
    "dominance_last_50_diff",
    "fatigue_index_diff", "fatigue_ratio",
    "minutes_to_match",
    "odds_shift_p1", "odds_shift_p2",
    "daily_performance_trend_diff",
    "dominance_trend_diff",
    "style_clash",
    # H2H recency (Tier A): повторная встреча < 24h — очень сильный сигнал
    "hours_since_last_h2h",
    # League (Tier A): доля побед андердога в лиге
    "league_upset_rate",
]
TARGET_MATCH = "target_match"
TARGET_SET1 = "target_set1"
TARGET_SET = "target_set"  # любой сет (для p_set → Monte Carlo)

# Ожидаемые фичи в топ-10 по важности. Если нет — возможна ошибка в расчёте фичей.
EXPECTED_TOP_FEATURES = [
    "elo_diff",
    "dominance_last_50_diff",
    "fatigue_ratio",
    "form_diff",
    "odds_shift_p1",
    "odds_shift_p2",
]


def _detect_gpu() -> dict[str, Any]:
    """Определяет доступность GPU для LightGBM.
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


def load_training_data(
    limit: int = 100_000,
    min_sample_size: int = 20,
    train_year_start: int = 2017,
    train_year_end: int = 2022,
    warmup_year_end: int = 2016,
    odds_min: float = 0.0,
    odds_max: float = 999.0,
) -> pd.DataFrame:
    """Загружает датасет для обучения с временным сплитом и опциональным фильтром по кф.

    - train_year_start..train_year_end: только эти годы идут в обучение (2017–2022 по умолчанию).
    - warmup_year_end (2016): матчи до и включая этот год — только для накопления статистики, не в train.
    - odds_min/odds_max: фильтр по кф (например 1.4–3.0), чтобы не учиться только на фаворитах; 0 и 999 = без фильтра.
    - ORDER BY m.start_time ASC — без перемешивания.
    - limit <= 0: безлимит (загружаются все строки за указанные годы)."""
    if limit <= 0:
        limit = 2147483647  # PostgreSQL LIMIT без ограничения по факту
    engine = get_ml_engine()
    year_filter_sql = " AND EXTRACT(YEAR FROM m.start_time) >= :train_year_start AND EXTRACT(YEAR FROM m.start_time) <= :train_year_end"
    base_sql = """
        SELECT mf.match_id, m.start_time, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
               mf.winrate_10_diff, mf.odds_diff, mf.h2h_count, mf.odds_p1, mf.odds_p2,
               m.score_sets_p1, m.score_sets_p2, m.player1_id, m.player2_id,
               CASE WHEN m.score_sets_p1 > m.score_sets_p2 THEN 1 ELSE 0 END as target_match,
               (SELECT CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END
                FROM match_sets ms WHERE ms.match_id = m.id AND ms.set_number = 1
                AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL LIMIT 1) as target_set1
        FROM match_features mf
        JOIN matches m ON m.id = mf.match_id
        WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL AND m.score_sets_p2 IS NOT NULL
""" + year_filter_sql + """
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
              "mf.daily_performance_trend_diff, mf.dominance_trend_diff, mf.style_clash, " \
              "mf.hours_since_last_h2h, mf.league_upset_rate"
    sample_filter = " AND (mf.sample_size IS NULL OR mf.sample_size >= :min_sample)"
    sql_v3 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + v3_cols + ",").replace(
        "ORDER BY m.start_time ASC", sample_filter + "\n        ORDER BY m.start_time ASC"
    )
    sql_v2 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + ",")
    params_v3 = {"lim": limit, "min_sample": min_sample_size, "train_year_start": train_year_start, "train_year_end": train_year_end}
    params_base = {"lim": limit, "train_year_start": train_year_start, "train_year_end": train_year_end}
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql_v3), conn, params=params_v3)
    except Exception:
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql_v2), conn, params=params_base)
        except Exception:
            with engine.connect() as conn:
                df = pd.read_sql(text(base_sql), conn, params=params_base)
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    df["target_set1"] = df["target_set1"].fillna(0.5).astype(int)
    for c in FEATURE_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    if "elo_diff" in df.columns and "elo_probability" in FEATURE_COLS:
        df["elo_probability"] = 1.0 / (1.0 + 10.0 ** (-df["elo_diff"].astype(float) / 400.0))

    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
        df["year"] = df["start_time"].dt.year
    if odds_min > 0 or odds_max < 999:
        o1 = df.get("odds_p1", pd.Series(dtype=float))
        o2 = df.get("odds_p2", pd.Series(dtype=float))
        if len(o1) and len(o2):
            # Оставляем матчи, где хотя бы один коэффициент в диапазоне (оба в зоне 1.4–3.0 даёт баланс)
            in_range = ((o1 >= odds_min) & (o1 <= odds_max)) | ((o2 >= odds_min) & (o2 <= odds_max))
            df = df[in_range].copy()
    return df


def load_validation_data(
    year_start: int = 2023,
    year_end: int = 2024,
    limit: int = 100_000,
    min_sample_size: int = 20,
) -> pd.DataFrame:
    """Загружает данные для оценки модели (валидация): только матчи за year_start–year_end.
    Те же колонки, что и в train; без перемешивания, по времени."""
    engine = get_ml_engine()
    year_filter = " AND EXTRACT(YEAR FROM m.start_time) >= :y_start AND EXTRACT(YEAR FROM m.start_time) <= :y_end"
    base_sql = """
        SELECT mf.match_id, m.start_time, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
               mf.winrate_10_diff, mf.odds_diff, mf.h2h_count, mf.odds_p1, mf.odds_p2,
               m.score_sets_p1, m.score_sets_p2, m.player1_id, m.player2_id,
               CASE WHEN m.score_sets_p1 > m.score_sets_p2 THEN 1 ELSE 0 END as target_match,
               (SELECT CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END
                FROM match_sets ms WHERE ms.match_id = m.id AND ms.set_number = 1
                AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL LIMIT 1) as target_set1
        FROM match_features mf
        JOIN matches m ON m.id = mf.match_id
        WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL AND m.score_sets_p2 IS NOT NULL
""" + year_filter + """
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
              "mf.daily_performance_trend_diff, mf.dominance_trend_diff, mf.style_clash, " \
              "mf.hours_since_last_h2h, mf.league_upset_rate"
    sample_filter = " AND (mf.sample_size IS NULL OR mf.sample_size >= :min_sample)"
    sql_v3 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + v3_cols + ",")
    sql_v3 = sql_v3.replace("ORDER BY m.start_time", sample_filter + "\n        ORDER BY m.start_time")
    sql_v2 = base_sql.replace("mf.h2h_count,", "mf.h2h_count" + v2_cols + ",")
    params = {"lim": limit, "y_start": year_start, "y_end": year_end, "min_sample": min_sample_size}
    params_base = {"lim": limit, "y_start": year_start, "y_end": year_end}
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql_v3), conn, params=params)
    except Exception:
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql_v2), conn, params=params_base)
        except Exception:
            with engine.connect() as conn:
                df = pd.read_sql(text(base_sql), conn, params=params_base)
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
    if df.empty:
        return df
    df["target_set1"] = df["target_set1"].fillna(0.5).astype(int)
    for c in FEATURE_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    # Elo как вероятность — сильная фича для ставок
    if "elo_diff" in df.columns and "elo_probability" in FEATURE_COLS:
        df["elo_probability"] = 1.0 / (1.0 + 10.0 ** (-df["elo_diff"].astype(float) / 400.0))
    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    return df


def get_closing_odds(match_ids: list[int]) -> dict[int, tuple[float, float]]:
    """Последние (closing) коэффициенты по матчам: (odds_p1, odds_p2)."""
    if not match_ids:
        return {}
    engine = get_ml_engine()
    # PostgreSQL: последняя запись по created_at для каждого match_id
    sql = """
        SELECT DISTINCT ON (match_id) match_id, odds_p1, odds_p2
        FROM odds
        WHERE match_id = ANY(:ids)
        ORDER BY match_id, created_at DESC
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"ids": match_ids}).fetchall()
        return {int(r[0]): (float(r[1] or 1.0), float(r[2] or 1.0)) for r in rows}
    except Exception as e:
        logger.debug("get_closing_odds: %s", e)
        return {}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def load_set_training_data(
    limit: int = 0,
    train_year_start: int = 2017,
    train_year_end: int = 2022,
) -> pd.DataFrame:
    """Загружает set-level датасет: сеты из match_sets + match_features за указанные годы.
    limit <= 0: безлимит (все сеты за годы)."""
    if limit <= 0:
        limit = 2147483647
    engine = get_ml_engine()
    year_filter_sql = " AND EXTRACT(YEAR FROM m.start_time) >= :train_year_start AND EXTRACT(YEAR FROM m.start_time) <= :train_year_end"
    v2_cols = ", mf.avg_sets_per_match_diff, mf.sets_over35_rate_diff, mf.streak_score, " \
              "mf.minutes_since_last_match_diff, mf.dominance_diff, " \
              "mf.std_points_diff_last10_p1, mf.std_points_diff_last10_p2, " \
              "mf.log_odds_ratio, mf.implied_prob_p1, mf.market_margin, " \
              "mf.momentum_today_diff, mf.set1_strength_diff, mf.comeback_rate_diff"
    v3_cols = ", mf.dominance_last_50_diff, mf.fatigue_index_diff, mf.fatigue_ratio, " \
              "mf.minutes_to_match, mf.odds_shift_p1, mf.odds_shift_p2, " \
              "mf.elo_volatility_diff, mf.daily_performance_trend_diff, " \
              "mf.dominance_trend_diff, mf.style_clash, mf.hours_since_last_h2h, mf.league_upset_rate"
    sql = f"""
        SELECT mf.match_id, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
               mf.winrate_10_diff, mf.odds_diff, mf.h2h_count {v2_cols} {v3_cols},
               CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END as target_set
        FROM match_sets ms
        JOIN matches m ON m.id = ms.match_id
        JOIN match_features mf ON mf.match_id = m.id
        WHERE m.status = 'finished' AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL
        {year_filter_sql}
        ORDER BY m.start_time ASC
        LIMIT :lim
    """
    params = {"lim": limit, "train_year_start": train_year_start, "train_year_end": train_year_end}
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
    except Exception:
        sql_fallback = f"""
            SELECT mf.match_id, mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
                   mf.winrate_10_diff, mf.odds_diff, mf.h2h_count {v2_cols},
                   CASE WHEN ms.score_p1 > ms.score_p2 THEN 1 ELSE 0 END as target_set
            FROM match_sets ms
            JOIN matches m ON m.id = ms.match_id
            JOIN match_features mf ON mf.match_id = m.id
            WHERE m.status = 'finished' AND ms.score_p1 IS NOT NULL AND ms.score_p2 IS NOT NULL
            {year_filter_sql}
            ORDER BY m.start_time ASC
            LIMIT :lim
        """
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql_fallback), conn, params=params)
        except Exception:
            return pd.DataFrame()
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
    df["target_set"] = df["target_set"].fillna(0.5).astype(int)
    for c in FEATURE_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    if "elo_diff" in df.columns and "elo_probability" in FEATURE_COLS:
        df["elo_probability"] = 1.0 / (1.0 + 10.0 ** (-df["elo_diff"].astype(float) / 400.0))
    return df


def _hyperparams_path() -> Path:
    """Путь к файлу с подобранными гиперпараметрами (опционально)."""
    model_dir = Path(getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
    return model_dir / "tt_ml_hyperparams.json"


def _load_hyperparams() -> dict[str, Any]:
    """Загружает гиперпараметры из файла (если есть). Ключи как в LGBMClassifier."""
    path = _hyperparams_path()
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Load hyperparams: %s", e)
        return {}


def _train_binary_model(df: pd.DataFrame, target_col: str, use_gpu: bool | None = None) -> Any:
    """Обучает бинарную модель (match или set1). Конфиг LightGBM под настольный теннис."""
    if use_gpu is None:
        use_gpu = getattr(settings, "ml_use_gpu", True)
    cols = [c for c in FEATURE_COLS if c in df.columns]
    if not cols:
        cols = [c for c in FEATURE_COLS[:7] if c in df.columns]
    raw_X = df[cols]
    nan_counts = raw_X.isna().sum().sort_values(ascending=False)
    std_series = raw_X.fillna(0).astype(float).std()
    low_std_cnt = int((std_series <= 1e-6).sum())
    X = raw_X.fillna(0).astype(float)
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    y_rate = float(y.mean()) if len(y) else 0.0

    logger.info(
        "  LightGBM [%s]: features=%s, low_std<=1e-6=%s, y_rate=%.4f",
        target_col,
        len(cols),
        low_std_cnt,
        y_rate,
    )
    print(
        f"  LightGBM [{target_col}]: features={len(cols)}, low_std<=1e-6={low_std_cnt}, y_rate={y_rate:.4f}",
        flush=True,
    )
    if int(nan_counts.iloc[0]) > 0:
        logger.info("  LightGBM [%s]: top NaN columns %s", target_col, nan_counts.head(5).to_dict())
        print(
            f"  LightGBM [{target_col}]: top NaN columns {nan_counts.head(5).to_dict()}",
            flush=True,
        )
    logger.debug("  LightGBM [%s]: top std columns %s", target_col, std_series.sort_values(ascending=False).head(10).to_dict())

    import lightgbm as lgb

    gpu = _detect_gpu() if use_gpu else {"device": "cpu"}
    # Базовая конфигурация LightGBM для TT: не душим сплиты на слабых/шумных фичах.
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "learning_rate": 0.02,
        "num_leaves": 127,
        "max_depth": -1,
        "min_child_samples": 20,
        "min_child_weight": 0.001,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "max_bin": 255,
        "min_split_gain": 0.0,
        "is_unbalance": True,
        "verbosity": -1,
        "n_estimators": 5000,
        "n_jobs": min(16, (os.cpu_count() or 4)),
    }
    if use_gpu and str(gpu["device"]).startswith("cuda"):
        params["device"] = "cuda"
        params["n_jobs"] = 1  # GPU не использует n_jobs
    elif use_gpu and str(gpu.get("device")) == "hip":
        params["device"] = "hip"
        params["n_jobs"] = 1
    else:
        params["device"] = "cpu"
    # Переопределение из hyperparameter search (tt_ml_hyperparams.json)
    overrides = _load_hyperparams()
    # Совместимость со старыми именами параметров в сохранённых hyperparams.
    if "feature_fraction" not in overrides and "colsample_bytree" in overrides:
        overrides["feature_fraction"] = overrides["colsample_bytree"]
    if "bagging_fraction" not in overrides and "subsample" in overrides:
        overrides["bagging_fraction"] = overrides["subsample"]
    for k, v in overrides.items():
        if k in params:
            params[k] = v
    # Guard rails: старые/агрессивные override могут полностью блокировать splits.
    try:
        params["min_child_samples"] = int(max(5, min(int(params.get("min_child_samples", 20)), 80)))
        params["min_split_gain"] = float(max(0.0, min(float(params.get("min_split_gain", 0.0)), 0.002)))
        params["reg_alpha"] = float(max(0.0, min(float(params.get("reg_alpha", 0.0)), 2.0)))
        params["reg_lambda"] = float(max(0.1, min(float(params.get("reg_lambda", 1.0)), 3.0)))
    except Exception:
        pass
    params_no_override = dict(params)

    # Early stopping: последние 10% по времени как validation
    early_stopping_rounds = int(getattr(settings, "ml_lgb_early_stopping_rounds", 300))
    log_period = int(getattr(settings, "ml_lgb_log_period", 100))  # вывод метрик каждые N итераций
    n = len(X)

    def _fit_once(run_params: dict[str, Any]) -> tuple[Any, int, float | None]:
        model_inner = lgb.LGBMClassifier(**run_params)
        if n >= 2000 and early_stopping_rounds > 0:
            split = int(n * 0.90)
            X_train, X_val = X.iloc[:split], X.iloc[split:]
            y_train, y_val = y.iloc[:split], y.iloc[split:]
            n_train, n_val = len(X_train), len(X_val)
            logger.info(
                "  LightGBM [%s]: train n=%s, val n=%s, early_stopping_rounds=%s",
                target_col, n_train, n_val, early_stopping_rounds,
            )
            print(
                f"  LightGBM [{target_col}]: train n={n_train}, val n={n_val}, early_stopping_rounds={early_stopping_rounds}",
                flush=True,
            )
            callbacks_list = [lgb.early_stopping(early_stopping_rounds, verbose=True)]
            if log_period > 0:
                try:
                    callbacks_list.append(lgb.log_evaluation(period=log_period))
                except AttributeError:
                    pass  # старые версии LightGBM без log_evaluation
            model_inner.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                callbacks=callbacks_list,
            )
        else:
            logger.info("  LightGBM [%s]: n=%s, без early stopping (fit на всех данных)", target_col, n)
            print(f"  LightGBM [{target_col}]: n={n}, обучение без early stopping", flush=True)
            model_inner.fit(X, y)

        best_it_inner = getattr(model_inner, "best_iteration_", None) or getattr(model_inner, "n_estimators", 0)
        best_score_inner = None
        try:
            if hasattr(model_inner, "booster_") and model_inner.booster_ is not None:
                bs = getattr(model_inner.booster_, "best_score", None) or {}
                if isinstance(bs, dict):
                    for v in bs.values():
                        if isinstance(v, dict) and "binary_logloss" in v:
                            best_score_inner = v["binary_logloss"]
                            break
        except Exception:
            pass
        logger.info(
            "  LightGBM [%s]: best_iteration=%s (max %s), best_valid_logloss=%s",
            target_col, best_it_inner, run_params.get("n_estimators", 5000), best_score_inner,
        )
        print(
            f"  LightGBM [{target_col}]: best_iteration={best_it_inner}, best_valid_logloss={best_score_inner}",
            flush=True,
        )
        return model_inner, int(best_it_inner), best_score_inner

    if n >= 2000 and early_stopping_rounds > 0:
        model, best_it, best_score = _fit_once(params)
        # Авто-retry для degenerate обучения (best_iteration=1 и logloss около 0.693).
        if best_it <= 3 and (best_score is None or float(best_score) >= 0.6928):
            logger.warning(
                "  LightGBM [%s]: degenerate training detected (best_it=%s, logloss=%s). Retrying with softer params.",
                target_col,
                best_it,
                best_score,
            )
            soft_params = dict(params_no_override)
            soft_params.update(
                {
                    "learning_rate": 0.03,
                    "num_leaves": 255,
                    "min_child_samples": 10,
                    "min_split_gain": 0.0,
                    "reg_alpha": 0.0,
                    "reg_lambda": 0.5,
                    "feature_fraction": 0.95,
                    "bagging_fraction": 0.95,
                }
            )
            model, best_it2, best_score2 = _fit_once(soft_params)
            # GPU может застревать в "no split"; делаем финальный fallback на CPU.
            if best_it2 <= 3 and (best_score2 is None or float(best_score2) >= 0.6928):
                dev = str(params.get("device", "cpu"))
                if dev in {"cuda", "cuda:0", "hip"}:
                    logger.warning(
                        "  LightGBM [%s]: still degenerate on %s; final retry on CPU.",
                        target_col,
                        dev,
                    )
                    cpu_params = dict(soft_params)
                    cpu_params["device"] = "cpu"
                    cpu_params["n_jobs"] = min(16, (os.cpu_count() or 4))
                    model, _, _ = _fit_once(cpu_params)
    else:
        model, _, _ = _fit_once(params)
    return model


def train_match_model(df: pd.DataFrame, use_gpu: bool | None = None) -> Any:
    """Обучает модель победы в матче (LightGBM)."""
    return _train_binary_model(df, TARGET_MATCH, use_gpu)


def train_set1_model(df: pd.DataFrame, use_gpu: bool = True) -> Any:
    """Обучает модель победы в 1-м сете (target_set1)."""
    return _train_binary_model(df, TARGET_SET1, use_gpu)


def train_set_model(df: pd.DataFrame, use_gpu: bool = True) -> Any:
    """Обучает модель победы в сете (любой сет). p_set → Monte Carlo → p_match."""
    return _train_binary_model(df, TARGET_SET, use_gpu)


# Диапазоны для hyperparameter search (после базового обучения).
LGBM_HYPERPARAM_GRID = {
    "num_leaves": list(range(64, 257, 32)),  # 64..256
    "learning_rate": [0.01, 0.012, 0.015, 0.02, 0.025, 0.03],
    "min_child_samples": [20, 30, 40, 50, 80, 100],
    "feature_fraction": [0.7, 0.75, 0.8, 0.85, 0.9],
    "bagging_fraction": [0.7, 0.75, 0.8, 0.85, 0.9],
    "reg_alpha": [0.0, 0.1, 0.5, 1.0],
    "reg_lambda": [0.5, 1.0, 1.5, 2.0],
    "min_split_gain": [0.0, 0.0005, 0.001],
}


def run_hyperparameter_search(
    df: pd.DataFrame,
    target_col: str = TARGET_MATCH,
    n_iter: int = 25,
    use_gpu: bool = True,
) -> dict[str, Any]:
    """Поиск гиперпараметров LightGBM (RandomizedSearchCV + TimeSeriesSplit). Сохраняет лучшие в tt_ml_hyperparams.json."""
    from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
    import lightgbm as lgb

    cols = [c for c in FEATURE_COLS if c in df.columns] or FEATURE_COLS[:7]
    X = df[cols].fillna(0)
    y = df[target_col]
    if len(X) < 3000:
        logger.warning("Hyperparameter search: мало данных (%s), нужны хотя бы 3000 строк", len(X))
        return {}

    gpu = _detect_gpu() if use_gpu else {"device": "cpu"}
    base_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "max_depth": -1,
        "min_child_weight": 0.001,
        "bagging_freq": 5,
        "max_bin": 255,
        "min_split_gain": 0.0,
        "is_unbalance": True,
        "verbosity": -1,
        "n_estimators": 1500,
        "random_state": 42,
        "min_child_samples": 30,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
    }
    if use_gpu and str(gpu["device"]).startswith("cuda"):
        base_params["device"] = "cuda"
        base_params["n_jobs"] = 1
    elif use_gpu and str(gpu.get("device")) == "hip":
        base_params["device"] = "hip"
        base_params["n_jobs"] = 1
    else:
        base_params["device"] = "cpu"
        base_params["n_jobs"] = min(4, (os.cpu_count() or 4))

    tscv = TimeSeriesSplit(n_splits=3)
    clf = lgb.LGBMClassifier(**base_params)
    search = RandomizedSearchCV(
        clf,
        LGBM_HYPERPARAM_GRID,
        n_iter=n_iter,
        cv=tscv,
        scoring="neg_binary_logloss",
        verbose=0,
        n_jobs=1,
        random_state=42,
    )
    search.fit(X, y)
    best = dict(search.best_params_)
    path = _hyperparams_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(best, f, indent=2)
        logger.info("Hyperparameter search: лучшие параметры сохранены в %s: %s", path, best)
    except Exception as e:
        logger.warning("Не удалось сохранить гиперпараметры в %s: %s", path, e)
    return best


def train_p_point_logistic(df: pd.DataFrame, version: str = "v1", use_gpu: bool = False) -> Any:
    """Обучает LogisticRegression для p_set (fallback). При use_gpu и cuML — на GPU."""
    from sklearn.linear_model import LogisticRegression as SklearnLR
    from sklearn.preprocessing import StandardScaler
    cols = [c for c in FEATURE_COLS if c in df.columns]
    if not cols:
        cols = [c for c in FEATURE_COLS[:10] if c in df.columns]
    X = df[cols].fillna(0).astype(float)
    y = df[TARGET_SET] if TARGET_SET in df.columns else df.get("target_set1", df.get(TARGET_MATCH))
    if y is None or len(y) < 50:
        return None
    y = np.asarray(y, dtype=np.int32)
    if use_gpu and _try_cuml():
        try:
            from cuml.linear_model import LogisticRegression as CumlLR
            from cuml.preprocessing import StandardScaler as CumlScaler
            scaler_gpu = CumlScaler()
            X_scaled = scaler_gpu.fit_transform(X)
            clf_gpu = CumlLR(C=0.1, max_iter=2000)
            clf_gpu.fit(X_scaled, y)
            def _to_numpy(a):
                if a is None:
                    return np.array(0.0)
                if hasattr(a, "to_numpy"):
                    return np.asarray(a.to_numpy(), dtype=float)
                if hasattr(a, "values"):
                    return np.asarray(a.values, dtype=float)
                return np.asarray(a, dtype=float)
            coef = _to_numpy(clf_gpu.coef_)
            intercept = _to_numpy(clf_gpu.intercept_)
            scale = _to_numpy(scaler_gpu.scale_).ravel()
            mean = _to_numpy(scaler_gpu.mean_).ravel()
            # Перенос весов в sklearn Pipeline (inference без cuML)
            from sklearn.pipeline import Pipeline
            sk_scaler = StandardScaler()
            sk_scaler.mean_ = mean
            sk_scaler.scale_ = scale
            sk_scaler.n_features_in_ = len(cols)
            sk_clf = SklearnLR(C=0.1, max_iter=1, random_state=42, solver="lbfgs")
            sk_clf.fit(X.iloc[:2], y[:2])  # минимальный fit для инициализации
            coef_1d = (coef / scale).ravel()
            sk_clf.coef_ = coef_1d.reshape(1, -1)
            sk_clf.intercept_ = np.array([float(intercept.ravel()[0]) - float(coef_1d @ mean)])
            sk_clf.classes_ = np.array([0, 1])
            model = Pipeline([("scaler", sk_scaler), ("clf", sk_clf)])
            logger.info("  p_point (LogisticRegression): обучен на GPU (cuML)")
            return {"model": model, "cols": cols}
        except Exception as e:
            logger.warning("p_point GPU failed, falling back to CPU: %s", e)
    from sklearn.pipeline import Pipeline
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", SklearnLR(
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
    """Сохраняет модели на диск (joblib для всех моделей, включая LightGBM)."""
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
        joblib.dump(model, path)
    # Сохраняем полный список фичей и фактический список из модели (для проверки после загрузки)
    train_cols = None
    m = match_model
    if getattr(m, "base_model", None) is not None:
        m = m.base_model
    if hasattr(m, "feature_names_in_") and m.feature_names_in_ is not None:
        train_cols = list(m.feature_names_in_)
    meta = {"version": version, "features": FEATURE_COLS, "training_features": train_cols or FEATURE_COLS}
    with open(f"{prefix}_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    return str(prefix)


def _model_summary(name: str, model: Any) -> dict[str, Any]:
    """Краткая сводка по модели для проверки после загрузки."""
    out: dict[str, Any] = {"name": name}
    if model is None:
        out["loaded"] = False
        return out
    out["loaded"] = True
    # Tree-модель или обёртка (calibration)
    base = getattr(model, "base_model", model)
    out["n_features"] = getattr(base, "n_features_in_", None) or len(getattr(base, "feature_names_in_", []) or [])
    fnames = getattr(base, "feature_names_in_", None)
    if fnames is not None:
        out["feature_names"] = list(fnames)
        missing = set(FEATURE_COLS) - set(fnames)
        if missing:
            out["missing_vs_feature_cols"] = list(missing)
    out["classes_"] = getattr(base, "classes_", None) is not None
    if hasattr(base, "n_estimators"):
        out["n_estimators"] = getattr(base, "n_estimators", None)
    if hasattr(base, "best_iteration_"):
        out["best_iteration"] = getattr(base, "best_iteration_", None)
    if isinstance(model, dict) and "cols" in model:
        out["p_point_cols"] = len(model["cols"])
    return out


def verify_models_after_load(
    match_model: Any,
    set1_model: Any,
    set_model: Any | None,
    p_point_model: Any | None,
    version: str = "v1",
) -> None:
    """Проверяет загруженные модели: фичи, классы, число деревьев. Логирует предупреждения при несоответствии."""
    meta_path = Path(getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")) / f"tt_ml_{version}_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            expected_features = meta.get("features") or FEATURE_COLS
            logger.debug("ML meta: version=%s, expected features=%s", meta.get("version"), len(expected_features))
        except Exception:
            expected_features = FEATURE_COLS
    else:
        expected_features = FEATURE_COLS

    for name, model in [("match", match_model), ("set1", set1_model), ("set", set_model), ("p_point", p_point_model)]:
        if model is None:
            continue
        s = _model_summary(name, model)
        if not s.get("loaded"):
            continue
        n = s.get("n_features") or 0
        if n > 0 and n != len(FEATURE_COLS):
            logger.warning(
                "ML модель %s: число фичей %s (ожидается %s). Проверьте совпадение с FEATURE_COLS.",
                name, n, len(FEATURE_COLS),
            )
        if s.get("missing_vs_feature_cols"):
            logger.warning("ML модель %s: в обучении не участвовали фичи %s", name, s["missing_vs_feature_cols"][:5])
        logger.debug("ML %s: n_features=%s, classes=%s, n_estimators=%s", name, n, s.get("classes_"), s.get("n_estimators"))

    n_match = _model_summary("match", match_model).get("n_features") or 0
    n_set1 = _model_summary("set1", set1_model).get("n_features") or 0
    logger.info(
        "ML %s модели загружены: match %s фичей, set1 %s фичей, set=%s, p_point=%s",
        version,
        n_match,
        n_set1,
        set_model is not None,
        p_point_model is not None,
    )


def load_models(version: str = "v1") -> tuple[Any, Any, Any | None, Any | None]:
    """Загружает модели с диска. Возвращает (match_model, set1_model, set_model|None, p_point_model|None)."""
    import joblib
    model_dir = Path(getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
    prefix = model_dir / f"tt_ml_{version}"
    match_path = Path(f"{prefix}_match.joblib")
    set1_path = Path(f"{prefix}_set1.joblib")
    set_path = Path(f"{prefix}_set.joblib")
    p_point_path = Path(f"{prefix}_p_point.joblib")

    if not (match_path.exists() and set1_path.exists()):
        raise FileNotFoundError(
            f"ML-модели не найдены в {model_dir}. Запустите retrain (Full rebuild или Переобучить)."
        )

    match_model = joblib.load(match_path)
    set1_model = joblib.load(set1_path)
    set_model = joblib.load(set_path) if set_path.exists() else None
    p_point_model = joblib.load(p_point_path) if p_point_path.exists() else None

    try:
        verify_models_after_load(match_model, set1_model, set_model, p_point_model, version=version)
    except Exception as e:
        logger.debug("ML verify after load: %s", e)

    return match_model, set1_model, set_model, p_point_model


def _try_cuml():
    """Опциональный импорт cuML (GPU). Возвращает модуль cuml или None."""
    try:
        import cuml  # noqa: F401
        return True
    except ImportError:
        return False


class _PlattCalibratedWrapper:
    """Обёртка: базовая модель + Platt scaling (coef*proba + intercept). Сериализуется с joblib."""

    def __init__(self, base_model: Any, coef: float, intercept: float):
        self.base_model = base_model
        self.coef = float(coef)
        self.intercept = float(intercept)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = np.asarray(self.base_model.predict_proba(X)[:, 1], dtype=float)
        cal = 1.0 / (1.0 + np.exp(-(self.coef * p + self.intercept)))
        return np.column_stack([1.0 - cal, cal])

    @property
    def feature_importances_(self):
        return getattr(self.base_model, "feature_importances_", None)

    @property
    def feature_names_in_(self):
        return getattr(self.base_model, "feature_names_in_", None)


def _calibrate_model(model: Any, X: pd.DataFrame, y: pd.Series, groups: pd.Series | None) -> Any:
    """Калибровка модели (Platt scaling). При наличии cuML и GPU — на GPU."""
    X = X.astype(float)
    y = y.astype(int).values
    if len(X) > 120_000:
        idx = np.random.default_rng(42).choice(len(X), size=120_000, replace=False)
        X = X.iloc[idx]
        y = y[idx]
    try:
        use_gpu = getattr(settings, "ml_use_gpu", True)
        if use_gpu and _try_cuml():
            from cuml.linear_model import LogisticRegression as CumlLR
            proba = np.asarray(model.predict_proba(X)[:, 1], dtype=float).reshape(-1, 1)
            clf = CumlLR(C=1e10, max_iter=2000)
            clf.fit(proba, y)
            def _to_numpy(a):
                if a is None:
                    return np.array(0.0)
                if hasattr(a, "to_numpy"):
                    return np.asarray(a.to_numpy(), dtype=float)
                if hasattr(a, "values"):
                    return np.asarray(a.values, dtype=float)
                return np.asarray(a, dtype=float)
            c = _to_numpy(clf.coef_)
            i = _to_numpy(clf.intercept_)
            coef = float(np.asarray(c).ravel()[0])
            intercept = float(np.asarray(i).ravel()[0])
            logger.info("  Калибровка (Platt): на GPU (cuML)")
            return _PlattCalibratedWrapper(model, coef, intercept)
        from sklearn.calibration import CalibratedClassifierCV
        calibrated = CalibratedClassifierCV(model, cv="prefit", method="sigmoid")
        calibrated.fit(X, y)
        return calibrated
    except Exception as e:
        logger.warning("Calibration skipped: %s", e)
        return model


def get_and_log_feature_importance(
    model: Any,
    feature_names: list[str],
    model_name: str = "match",
) -> list[tuple[str, int]]:
    """Логирует feature importance и проверяет, что ключевые фичи в топ-10."""
    try:
        imp = getattr(model, "feature_importances_", None)
        if imp is None:
            return []
        names = getattr(model, "feature_names_in_", None) or feature_names
        if len(names) != len(imp):
            names = feature_names[: len(imp)]
        pairs = sorted(zip(names, imp.astype(int)), key=lambda x: -x[1])
        top = [p[0] for p in pairs[:15]]
        logger.info("  [%s] Feature importance top-15: %s", model_name, ", ".join(f"{n}({i})" for n, i in pairs[:15]))
        print(f"  [{model_name}] Feature importance top-15: " + ", ".join(f"{n}={i}" for n, i in pairs[:15]), flush=True)
        top10 = set(p[0] for p in pairs[:10])
        missing = [f for f in EXPECTED_TOP_FEATURES if f not in top10]
        if missing:
            logger.warning(
                "  [%s] Ожидаемые фичи не в топ-10: %s — проверьте расчёт фичей.",
                model_name,
                missing,
            )
            print(
                f"  Внимание: ожидаемые в топ-10 фичи отсутствуют: {missing}. Проверьте расчёт фичей.",
                flush=True,
            )
        return pairs
    except Exception as e:
        logger.debug("Feature importance: %s", e)
        return []


def _verify_lightgbm_gpu() -> bool:
    """Проверяет, что LightGBM реально использует GPU (warmup)."""
    try:
        import lightgbm as lgb
        import numpy as np

        X = np.random.rand(256, 8).astype("float32")
        y = np.random.randint(0, 2, 256).astype("int32")
        train_data = lgb.Dataset(X, label=y)
        params = {
            "objective": "binary",
            "metric": "auc",
            "device": "cuda",
            "verbose": -1,
        }
        lgb.train(params, train_data, num_boost_round=10)
        logger.info("LightGBM: GPU warmup OK")
        return True
    except Exception as e:
        logger.warning("LightGBM GPU warmup failed: %s", e)
        return False


def retrain_models_if_needed(min_rows: int = 100, version: str = "v1", progress_callback: Any = None) -> dict[str, Any]:
    """Переобучение моделей на всех данных. Вызывать после синхронизации новых матчей."""
    if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
        from app.ml_v2.trainer import retrain_models_v2

        return retrain_models_v2(min_rows=min_rows)

    gpu_only = os.environ.get("ML_GPU_ONLY", "true").strip().lower() in ("1", "true", "yes")

    def _log(msg: str, *args: object) -> None:
        if args:
            logger.info(msg, *args)
            print(msg % args, flush=True)
        else:
            logger.info(msg)
            print(msg, flush=True)

    if progress_callback:
        progress_callback(current=0, total=7, message="Загрузка данных…")
    train_start = int(getattr(settings, "ml_train_year_start", 2017))
    train_end = int(getattr(settings, "ml_train_year_end", 2022))
    val_start_cfg = int(getattr(settings, "ml_val_year_start", 2023))
    if train_end >= val_start_cfg:
        adjusted = max(train_start, val_start_cfg - 1)
        logger.warning(
            "ML split overlap detected: train_end=%s >= val_start=%s; using train_end=%s",
            train_end,
            val_start_cfg,
            adjusted,
        )
        train_end = adjusted
    warmup_end = int(getattr(settings, "ml_warmup_year_end", 2016))
    odds_min = float(getattr(settings, "ml_train_odds_min", 0.0) or 0.0)
    odds_max = float(getattr(settings, "ml_train_odds_max", 999.0) or 999.0)
    min_sample_size = int(getattr(settings, "ml_train_min_sample_size", 0) or 0)
    df = load_training_data(
        limit=getattr(settings, "ml_train_limit", 1_500_000),
        min_sample_size=min_sample_size,
        train_year_start=train_start,
        train_year_end=train_end,
        warmup_year_end=warmup_end,
        odds_min=odds_min,
        odds_max=odds_max,
    )
    train_limit = getattr(settings, "ml_train_limit", 0) or 0
    if train_limit > 0 and len(df) >= train_limit:
        logger.warning(
            "ML train (match/set1): загружено ровно limit=%s — в БД может быть больше матчей. Увеличьте ml_train_limit.",
            train_limit,
        )
    logger.info(
        "ML train: годы %s–%s, %s, загружено матчей=%s",
        train_start, train_end, "безлимит" if train_limit <= 0 else f"limit={train_limit}", len(df),
    )
    if len(df) < min_rows:
        return {"trained": False, "rows": len(df), "reason": "not_enough_data"}
    if progress_callback:
        progress_callback(current=1, total=7, message=f"Загружено {len(df)} строк. Обучение match-модели…")
    use_gpu = getattr(settings, "ml_use_gpu", True)
    gpu = _detect_gpu()
    device = gpu.get("device", "cpu")
    if use_gpu and str(device).startswith("cuda"):
        # В GPU-only режиме считаем ошибкой любую ситуацию, когда CUDA не может быть использована.
        if not _verify_lightgbm_gpu():
            raise RuntimeError(
                "GPU включен, но LightGBM не может использовать CUDA внутри контейнера. "
                "Проверьте совместимость CUDA image и драйвера."
            )
    _log(f"  Match-модель: старт ({len(df)} строк, {'CUDA' if use_gpu else 'CPU'}, ~5–15 мин GPU / ~20–40 мин CPU)")
    match_model = train_match_model(df, use_gpu=use_gpu)
    _log("  Match-модель: готово")
    cols_match = [c for c in FEATURE_COLS if c in df.columns] or FEATURE_COLS[:7]
    get_and_log_feature_importance(match_model, cols_match, "match")
    if progress_callback:
        progress_callback(current=2, total=7, message="Обучение set1-модели…")
    _log("  Set1-модель: старт")
    set1_model = train_set1_model(df, use_gpu=use_gpu)
    _log("  Set1-модель: готово")
    get_and_log_feature_importance(set1_model, cols_match, "set1")
    set_model = None
    set_limit = int(getattr(settings, "ml_train_set_limit", 0) or 0)
    df_set = load_set_training_data(
        limit=set_limit,
        train_year_start=train_start,
        train_year_end=train_end,
    )
    if set_limit > 0 and len(df_set) >= set_limit:
        logger.warning(
            "ML train (set/p_point): загружено ровно limit=%s сетов — в БД может быть больше. Увеличьте ml_train_set_limit.",
            set_limit,
        )
    logger.info(
        "ML train set-level: годы %s–%s, %s, загружено сетов=%s",
        train_start, train_end, "безлимит" if set_limit <= 0 else f"limit={set_limit}", len(df_set),
    )
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
            p_point_model = train_p_point_logistic(df_set, version=version, use_gpu=use_gpu)
    if progress_callback:
        progress_callback(current=5, total=7, message="Сохранение моделей…")
    _log("  Сохранение моделей…")
    path = save_models(match_model, set1_model, set_model=set_model, p_point_model=p_point_model, version=version)
    metrics: dict[str, Any] = {}
    try:
        val_start = int(getattr(settings, "ml_val_year_start", 2023))
        val_end = int(getattr(settings, "ml_val_year_end", 2024))
        val_limit = int(getattr(settings, "ml_val_limit", 100_000) or 100_000)
        min_val_sample = int(getattr(settings, "ml_train_min_sample_size", 0) or 0)
        df_val = load_validation_data(year_start=val_start, year_end=val_end, limit=val_limit, min_sample_size=min_val_sample)
        if df_val.empty and min_val_sample > 0:
            logger.info("  Валидация: при min_sample_size=%s данных нет, пробуем min_sample_size=0", min_val_sample)
            df_val = load_validation_data(year_start=val_start, year_end=val_end, limit=val_limit, min_sample_size=0)
        if len(df_val) >= 100:
            mid_list = df_val["match_id"].dropna().astype(int).unique().tolist()
            closing_odds_map = get_closing_odds(mid_list) if mid_list else None
            metrics = compute_validation_metrics(
                match_model,
                df_val,
                set_model=set_model,
                closing_odds_map=closing_odds_map or None,
            )
            if "error" not in metrics:
                _log("  Метрики (validation): accuracy=%.4f logloss=%.4f Brier=%.4f ROI=%s CLV=%s (n=%s, n_bets=%s)",
                     metrics.get("accuracy", 0),
                     metrics.get("logloss", 0),
                     metrics.get("brier", 0),
                     metrics.get("roi") if metrics.get("roi") is not None else "n/a",
                     metrics.get("clv") if metrics.get("clv") is not None else "n/a",
                     metrics.get("n", 0),
                     metrics.get("n_bets", 0))
                clv_val = metrics.get("clv")
                if clv_val is not None:
                    cv = float(clv_val)
                    _log("  CLV %s 0 → модель %s рынка", ">" if cv > 0 else "<=", "сильнее" if cv > 0 else "не сильнее")
        else:
            _log("  Валидация: мало данных за %s–%s (n=%s)", val_start, val_end, len(df_val))
    except Exception as e:
        logger.warning("Validation metrics failed: %s", e)
    if progress_callback:
        progress_callback(current=6, total=7, message="Готово")
    _log(f"  Retrain завершён: {path}")
    return {"trained": True, "rows": len(df), "path": path, "validation_metrics": metrics}


def predict_proba(model: Any, features: dict[str, float]) -> float:
    """Вероятность победы P1 (матч или сет1). Поддерживает tree-модели и p_point dict {model, cols}."""
    if isinstance(model, dict) and "model" in model and "cols" in model:
        cols = model["cols"]
        m = model["model"]
    else:
        m = model
        # Порядок колонок как при обучении: модель могла обучиться на подмножестве фичей
        cols = list(getattr(m, "feature_names_in_", None) or FEATURE_COLS)
    X = pd.DataFrame([{c: features.get(c, 0) for c in cols}])
    with _ml_predict_lock:
        proba = m.predict_proba(X)[0, 1]
    return float(proba)


def _p_elo_from_diff(elo_diff: float) -> float:
    """P1 win prob from Elo diff (как в inference)."""
    return 1.0 / (1.0 + 10.0 ** (-float(elo_diff) / 400.0))


def compute_validation_metrics(
    match_model: Any,
    df_val: pd.DataFrame,
    set_model: Any | None = None,
    closing_odds_map: dict[int, tuple[float, float]] | None = None,
    min_edge: float = 0.05,
    odds_min: float = 1.5,
    odds_max: float = 3.0,
) -> dict[str, Any]:
    """Считает метрики на валидации: accuracy, logloss, Brier, ROI, CLV.

    CLV (Closing Line Value) — главная метрика: CLV > 0 значит модель сильнее рынка.
    Ансамбль: P = w_elo * P_elo + (1 - w_elo) * P_ml (match_model)."""
    if df_val.empty or TARGET_MATCH not in df_val.columns:
        return {"error": "empty_or_no_target", "n": 0}

    from sklearn.metrics import log_loss

    w_elo = float(getattr(settings, "ml_ensemble_elo_weight", 0.35))
    base = getattr(match_model, "base_model", match_model)
    fn = getattr(base, "feature_names_in_", None)
    if fn is not None:
        cols = list(np.asarray(fn).ravel())
    else:
        cols = [c for c in FEATURE_COLS if c in df_val.columns] or FEATURE_COLS[:7]
    X = df_val.reindex(columns=cols, fill_value=0)
    with _ml_predict_lock:
        p_ml = np.asarray(match_model.predict_proba(X)[:, 1], dtype=float).ravel()
    p_elo = np.asarray(df_val["elo_diff"].map(_p_elo_from_diff).values, dtype=float).ravel()
    p = w_elo * p_elo + (1.0 - w_elo) * p_ml
    y = np.asarray(df_val[TARGET_MATCH].values, dtype=float).ravel()

    n = len(y)
    pred_class = (p >= 0.5).astype(float)
    accuracy = float(np.mean(pred_class == y))
    try:
        logloss = float(log_loss(y, np.clip(p, 1e-15, 1 - 1e-15)))
    except Exception:
        logloss = float("nan")
    brier = float(np.mean((p - y) ** 2))
    roi: float | None = None
    clv: float | None = None
    n_bets = 0

    odds_p1 = df_val.get("odds_p1", pd.Series(dtype=float))
    odds_p2 = df_val.get("odds_p2", pd.Series(dtype=float))
    if isinstance(odds_p1, pd.DataFrame):
        odds_p1 = odds_p1.iloc[:, 0]
    if isinstance(odds_p2, pd.DataFrame):
        odds_p2 = odds_p2.iloc[:, 0]
    match_ids = df_val.get("match_id")
    if match_ids is None:
        match_ids = pd.Series(dtype=int)
    if isinstance(match_ids, pd.DataFrame):
        match_ids = match_ids.iloc[:, 0]
    has_odds = (
        "odds_p1" in df_val.columns
        and "odds_p2" in df_val.columns
        and (odds_p1.notna().any() if hasattr(odds_p1, "notna") else False)
        and (odds_p2.notna().any() if hasattr(odds_p2, "notna") else False)
    )
    if has_odds:
        o1 = np.asarray(odds_p1, dtype=float).ravel()
        o2 = np.asarray(odds_p2, dtype=float).ravel()
        edge_p1 = p - (1.0 / np.where(o1 > 1e-9, o1, np.nan))
        edge_p2 = (1.0 - p) - (1.0 / np.where(o2 > 1e-9, o2, np.nan))
        in_range_p1 = (o1 >= odds_min) & (o1 <= odds_max)
        in_range_p2 = (o2 >= odds_min) & (o2 <= odds_max)
        value_bet_p1 = ((edge_p1 >= min_edge) & in_range_p1).astype(bool)
        value_bet_p2 = ((edge_p2 >= min_edge) & in_range_p2).astype(bool)
        # Один ставочный выбор на матч: приоритет у большей edge
        bet_on_p1 = np.asarray(value_bet_p1 & (~value_bet_p2 | (edge_p1 >= edge_p2)), dtype=bool).ravel()
        bet_on_p2 = np.asarray(value_bet_p2 & (~value_bet_p1 | (edge_p2 > edge_p1)), dtype=bool).ravel()
        profits: list[float] = []
        clv_list: list[float] = []
        match_ids_arr = np.asarray(match_ids, dtype=float).ravel() if match_ids is not None else np.array([])
        for i in range(n):
            mid = None
            if i < len(match_ids_arr) and not np.isnan(match_ids_arr[i]):
                try:
                    mid = int(match_ids_arr[i])
                except (ValueError, TypeError):
                    pass
            if bool(bet_on_p1.flat[i]):
                o = float(o1[i])
                won = bool(float(np.asarray(y).flat[i]) == 1.0)
                profits.append((o - 1.0) if won else -1.0)
                if closing_odds_map and mid is not None and mid in closing_odds_map:
                    close_p1, _ = closing_odds_map[mid]
                    c1 = float(np.asarray(close_p1).flat[0]) if np.ndim(close_p1) != 0 else float(close_p1)
                    if c1 > 1e-9:
                        clv_list.append((o / c1 - 1.0) if won else -1.0)
                n_bets += 1
            elif bool(bet_on_p2.flat[i]):
                o = float(o2[i])
                won = bool(float(np.asarray(y).flat[i]) == 0.0)
                profits.append((o - 1.0) if won else -1.0)
                if closing_odds_map and mid is not None and mid in closing_odds_map:
                    _, close_p2 = closing_odds_map[mid]
                    c2 = float(np.asarray(close_p2).flat[0]) if np.ndim(close_p2) != 0 else float(close_p2)
                    if c2 > 1e-9:
                        clv_list.append((o / c2 - 1.0) if won else -1.0)
                n_bets += 1
        if n_bets > 0:
            roi = float(sum(profits) / n_bets)
        if clv_list:
            clv = float(sum(clv_list) / len(clv_list))

    return {
        "n": int(n),
        "accuracy": float(accuracy),
        "logloss": float(logloss),
        "brier": float(brier),
        "roi": roi,
        "clv": clv,
        "n_bets": int(n_bets),
    }
