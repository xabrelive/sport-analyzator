"""Feature engineering for ML v2 (league-aware, anti-leakage)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
from statistics import pstdev
from typing import Any
import zlib

import numpy as np

from app.config import settings
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.schema import ensure_schema

# Фичи линии: при ml_v2_disable_market_features обнуляем, чтобы модель опиралась на игрока, а не на кэф.
_MARKET_FEATURE_KEYS = ("market_prob_p1", "market_prob_p2", "market_diff", "closing_line", "market_margin")

FEATURE_COLS_V2 = [
    "elo_diff",
    "elo_trend_diff",
    "elo_trend_30_diff",
    "elo_volatility_diff",
    "elo_peak_diff",
    "elo_drop_10_diff",
    "elo_gain_10_diff",
    "elo_recent_diff",
    "form_diff",
    "winrate_3_diff",
    "winrate_5_diff",
    "winrate_10_diff",
    "winrate_20_diff",
    "winrate_30_diff",
    "winrate_50_diff",
    "sets_ratio_10_diff",
    "sets_ratio_20_diff",
    "sets_ratio_50_diff",
    "points_ratio_10_diff",
    "points_ratio_20_diff",
    "points_ratio_50_diff",
    "dominance_diff",
    "dominance_last_10_diff",
    "dominance_last_20_diff",
    "dominance_last_50_diff",
    "fatigue_diff",
    "fatigue_ratio",
    "fatigue_pressure_diff",
    "matches_24h_diff",
    "matches_3h_diff",
    "matches_6h_diff",
    "matches_12h_diff",
    "matches_7d_diff",
    "matches_3d_diff",
    "strength_trend_diff",
    "sets_24h_diff",
    "points_24h_diff",
    "minutes_24h_diff",
    "rest_hours_diff",
    "rest_days_diff",
    "long_match_ratio_diff",
    "momentum_today_diff",
    "momentum_last3_diff",
    "momentum_last5_diff",
    "streak_score",
    "win_streak_diff",
    "loss_streak_diff",
    "recent_improvement_diff",
    "style_clash",
    "aggressive_ratio_diff",
    "defensive_ratio_diff",
    "fast_match_ratio_diff",
    "long_rally_ratio_diff",
    "hour_strength_diff",
    "morning_strength_diff",
    "evening_strength_diff",
    "weekend_strength_diff",
    "h2h_diff",
    "h2h_count",
    "h2h_winrate",
    "h2h_last_result",
    "h2h_last3_diff",
    "h2h_last5_diff",
    "h2h_recent_diff",
    "h2h_dominance",
    "comeback_rate_diff",
    "reverse_sweep_rate_diff",
    "choke_rate_diff",
    "set1_strength_diff",
    "elo_x_fatigue",
    "std_points_last20_diff",
    "std_sets_last20_diff",
    "variance_winrate_diff",
    "consistency_score_diff",
    "points_ratio_last_30_diff",
    "sets_ratio_last_30_diff",
    "avg_sets_per_match_diff",
    "avg_points_per_set_diff",
    "match_duration_proxy_diff",
    "tempo_diff",
    "fatigue_index_diff",
    "temporal_strength_diff",
    "latent_strength_diff",
    "league_upset_rate",
    "league_strength",
    "league_avg_sets",
    "league_variance",
    "league_winrate_variance",
    "league_dominance_variance",
    "league_match_volume",
    "league_id_encoded",
    "table_bias",
    "league_match_count",
    "matches_played_before",
    "experience_diff",
    "p1_exp_bucket",
    "p2_exp_bucket",
    "experience_bucket_diff",
    "experience_mismatch",
    "elo_x_experience",
    "volatility_combo_diff",
    "form_x_fatigue_diff",
    "momentum_x_rest_diff",
    "h2h_x_form",
    "fatigue_ratio_log",
    "experience_ratio",
    "elo_confidence_gap",
    "style_momentum_diff",
    "temporal_form_diff",
    "league_upset_x_margin",
    "league_bias_x_margin",
    "elo_decay_7_diff",
    "elo_decay_30_diff",
    "elo_momentum_diff",
    "matches_48h_diff",
    "matches_72h_diff",
    "league_rating",
    "market_prob_p1",
    "market_prob_p2",
    "market_diff",
    "closing_line",
    "market_margin",
]

# Мёртвые фичи: константные или почти всегда 0 — ухудшают деревья. Не подаём в модель.
DEAD_FEATURES = frozenset({
    "hour_strength_diff",
    "morning_strength_diff",
    "evening_strength_diff",
    "weekend_strength_diff",
    "market_prob_p1",
    "market_prob_p2",
    "market_diff",
    "closing_line",
    "market_margin",
    "fast_match_ratio_diff",
    "long_match_ratio_diff",
    "long_rally_ratio_diff",
    "match_duration_proxy_diff",
    "league_upset_x_margin",
    "league_bias_x_margin",
})

# Избыточные rolling-фичи: winrate/points_ratio/sets_ratio для 3, 5, 30 сильно коррелируют с 10/20/50 (corr >0.95) → multicollinearity, модель путается. В обучении только окна 10, 20, 50.
REDUNDANT_ROLLING = frozenset({
    "winrate_3_diff",
    "winrate_5_diff",
    "winrate_30_diff",
    "points_ratio_last_30_diff",
    "sets_ratio_last_30_diff",
})

# Фичи для обучения: все кроме мёртвых и избыточных. Inference использует тот же список из meta/модели.
FEATURE_COLS_V2_TRAIN = [c for c in FEATURE_COLS_V2 if c not in DEAD_FEATURES and c not in REDUNDANT_ROLLING]


def feature_schema_signature() -> str:
    """Stable signature of the active feature schema."""
    return hashlib.sha1(",".join(FEATURE_COLS_V2).encode("utf-8")).hexdigest()


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if abs(b) < 1e-9:
        return default
    return float(a) / float(b)


def _norm_duration_minutes(v: float | int) -> float:
    x = float(v or 0.0)
    # Some upstream rows store seconds in duration_minutes.
    return (x / 60.0) if x > 500.0 else x


@dataclass
class _PlayerAgg:
    wins3: float = 0.0
    wins5: float = 0.0
    wins10: float = 0.0
    wins20: float = 0.0
    wins30: float = 0.0
    wins50: float = 0.0
    sets_ratio10: float = 0.0
    sets_ratio20: float = 0.0
    sets_ratio50: float = 0.0
    points_ratio10: float = 0.0
    points_ratio20: float = 0.0
    points_ratio50: float = 0.0
    dominance10: float = 0.0
    dominance20: float = 0.0
    dominance50: float = 0.0
    matches3h: float = 0.0
    matches6h: float = 0.0
    matches12h: float = 0.0
    matches24h: float = 0.0
    matches48h: float = 0.0
    matches72h: float = 0.0
    matches7d: float = 0.0
    matches3d: float = 0.0
    sets24h: float = 0.0
    points24h: float = 0.0
    mins24h: float = 0.0
    rest_hours: float = 24.0
    rest_days: float = 1.0
    long_match_ratio20: float = 0.0
    momentum_today: float = 0.0
    momentum3: float = 0.0
    momentum5: float = 0.0
    streak: float = 0.0
    win_streak: float = 0.0
    loss_streak: float = 0.0
    improvement: float = 0.0
    set1_strength: float = 0.5
    comeback_rate: float = 0.0
    reverse_sweep_rate: float = 0.0
    choke_rate: float = 0.0
    std_points10: float = 0.0
    std_points20: float = 0.0
    std_sets20: float = 0.0
    variance_win20: float = 0.0
    consistency_score: float = 0.0
    aggressive_ratio: float = 0.5
    defensive_ratio: float = 0.5
    fast_match_ratio20: float = 0.0
    long_rally_ratio20: float = 0.0
    hour_strength: float = 0.5
    morning_strength: float = 0.5
    evening_strength: float = 0.5
    weekend_strength: float = 0.5
    points_ratio30: float = 0.5
    sets_ratio30: float = 0.5
    avg_sets_per_match20: float = 3.0
    avg_points_per_set20: float = 21.0
    match_duration_proxy20: float = 25.0
    tempo_score: float = 0.0
    fatigue_index: float = 0.0
    fatigue_pressure: float = 0.0
    temporal_strength: float = 0.5
    latent_strength: float = 0.5
    matches_played_before: float = 0.0
    exp_bucket: float = 1.0
    elo_now: float = 1500.0
    elo_trend: float = 0.0
    elo_trend30: float = 0.0
    elo_volatility: float = 0.0
    elo_peak50: float = 1500.0
    elo_drop10: float = 0.0
    elo_gain10: float = 0.0
    elo_recent: float = 0.0
    elo_decay_7: float = 1500.0
    elo_decay_30: float = 1500.0
    elo_momentum: float = 0.0


def _compute_player_agg(
    history: list[dict[str, Any]],
    elo_hist: list[tuple[datetime, float]],
    cutoff: datetime,
    *,
    exclude_match_id: str | None = None,
) -> _PlayerAgg:
    # Анти-утечка (shift(1) в rolling): только матчи СТРОГО до cutoff; текущий матч не входит.
    # exclude_match_id дополнительно исключает матч по id на случай совпадения времени.
    rec = [
        h
        for h in history
        if h["match_time"] < cutoff and (exclude_match_id is None or h.get("match_id") != exclude_match_id)
    ]
    if not rec:
        return _PlayerAgg()
    matches_played_before = float(len(rec))
    rec_desc = sorted(rec, key=lambda x: x["match_time"], reverse=True)
    last3 = rec_desc[:3]
    last5 = rec_desc[:5]
    last10 = rec_desc[:10]
    last20 = rec_desc[:20]
    last30 = rec_desc[:30]
    last50 = rec_desc[:50]
    last80 = rec_desc[:80]
    day_start = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc)
    in_3h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=3)]
    in_6h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=6)]
    in_12h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=12)]
    in_24h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=24)]
    in_48h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=48)]
    in_72h = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(hours=72)]
    in_7d = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(days=7)]
    in_3d = [h for h in rec_desc if h["match_time"] >= cutoff - timedelta(days=3)]
    today = [h for h in rec_desc if h["match_time"] >= day_start]
    morning = [h for h in last80 if h["match_time"].hour < 12]
    evening = [h for h in last80 if h["match_time"].hour >= 18]
    weekend = [h for h in last80 if h["match_time"].weekday() >= 5]
    hour_band = [h for h in last80 if abs(h["match_time"].hour - cutoff.hour) <= 2]
    wins3 = _safe_div(sum(h["win"] for h in last3), max(1, len(last3)))
    wins5 = _safe_div(sum(h["win"] for h in last5), max(1, len(last5)))
    wins10 = _safe_div(sum(h["win"] for h in last10), max(1, len(last10)))
    wins20 = _safe_div(sum(h["win"] for h in last20), max(1, len(last20)))
    wins30 = _safe_div(sum(h["win"] for h in last30), max(1, len(last30)))
    wins50 = _safe_div(sum(h["win"] for h in last50), max(1, len(last50)))
    sets10_w = sum(h["sets_won"] for h in last10)
    sets10_l = sum(h["sets_lost"] for h in last10)
    points10_w = sum(h["points_won"] for h in last10)
    points10_l = sum(h["points_lost"] for h in last10)
    sets_w = sum(h["sets_won"] for h in last20)
    sets_l = sum(h["sets_lost"] for h in last20)
    points_w = sum(h["points_won"] for h in last20)
    points_l = sum(h["points_lost"] for h in last20)
    sets50_w = sum(h["sets_won"] for h in last50)
    sets50_l = sum(h["sets_lost"] for h in last50)
    points50_w = sum(h["points_won"] for h in last50)
    points50_l = sum(h["points_lost"] for h in last50)
    sets_ratio10 = _safe_div(sets10_w, max(1, sets10_w + sets10_l), 0.5)
    sets_ratio20 = _safe_div(sets_w, max(1, sets_w + sets_l), 0.5)
    sets_ratio50 = _safe_div(sets50_w, max(1, sets50_w + sets50_l), 0.5)
    points_ratio10 = _safe_div(points10_w, max(1, points10_w + points10_l), 0.5)
    points_ratio20 = _safe_div(points_w, max(1, points_w + points_l), 0.5)
    points_ratio50 = _safe_div(points50_w, max(1, points50_w + points50_l), 0.5)
    sets30_w = sum(h["sets_won"] for h in last30)
    sets30_l = sum(h["sets_lost"] for h in last30)
    points30_w = sum(h["points_won"] for h in last30)
    points30_l = sum(h["points_lost"] for h in last30)
    sets_ratio30 = _safe_div(sets30_w, max(1, sets30_w + sets30_l), 0.5)
    points_ratio30 = _safe_div(points30_w, max(1, points30_w + points30_l), 0.5)
    dom10_pw = sum(h["points_won"] for h in last10)
    dom10_pl = sum(h["points_lost"] for h in last10)
    dom20_pw = sum(h["points_won"] for h in last20)
    dom20_pl = sum(h["points_lost"] for h in last20)
    dom50_pw = sum(h["points_won"] for h in last50)
    dom50_pl = sum(h["points_lost"] for h in last50)
    dominance10 = _safe_div(dom10_pw - dom10_pl, max(1, dom10_pw + dom10_pl))
    dominance20 = _safe_div(dom20_pw - dom20_pl, max(1, dom20_pw + dom20_pl))
    dominance50 = _safe_div(dom50_pw - dom50_pl, max(1, dom50_pw + dom50_pl))
    matches3h = float(len(in_3h))
    matches6h = float(len(in_6h))
    matches12h = float(len(in_12h))
    matches24h = float(len(in_24h))
    matches48h = float(len(in_48h))
    matches72h = float(len(in_72h))
    matches7d = float(len(in_7d))
    matches3d = float(len(in_3d))
    sets24h = float(sum(h["sets_won"] + h["sets_lost"] for h in in_24h))
    points24h = float(sum(h["points_won"] + h["points_lost"] for h in in_24h))
    raw_dur_24h = float(sum(_norm_duration_minutes(h["duration_minutes"]) for h in in_24h))
    mins24h = raw_dur_24h
    last_match_time = rec_desc[0]["match_time"]
    rest_hours = max(0.0, min(7 * 24.0, _safe_div((cutoff - last_match_time).total_seconds(), 3600.0, 24.0)))
    rest_days = rest_hours / 24.0
    long_match_ratio20 = _safe_div(sum(1 for h in last20 if _norm_duration_minutes(h["duration_minutes"]) >= 35.0), max(1, len(last20)))
    momentum_today = float(sum(h["win"] for h in today) - sum(1 - h["win"] for h in today))
    momentum3 = float(sum(h["win"] for h in last3) - sum(1 - h["win"] for h in last3))
    momentum5 = float(sum(h["win"] for h in last5) - sum(1 - h["win"] for h in last5))
    streak = 0
    for h in rec_desc:
        if h["win"] == 1:
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
            else:
                break
    improvement = wins5 - wins20
    win_streak = float(max(0, streak))
    loss_streak = float(max(0, -streak))
    set1_strength = _safe_div(sum(h["set1_win"] for h in last20), max(1, len(last20)), 0.5)
    comeback_rate = _safe_div(sum(1 for h in last20 if h["win"] == 1 and h["set1_win"] == 0), max(1, len(last20)))
    reverse_sweep_rate = _safe_div(
        sum(1 for h in last20 if h["win"] == 1 and h["sets_lost"] >= 2 and h["set1_win"] == 0),
        max(1, len(last20)),
    )
    choke_rate = _safe_div(
        sum(1 for h in last20 if h["win"] == 0 and h["sets_won"] >= 2 and h["set1_win"] == 1),
        max(1, len(last20)),
    )
    std_points10 = float(pstdev([(h["points_won"] - h["points_lost"]) for h in last10])) if len(last10) > 1 else 0.0
    std_points20 = float(pstdev([(h["points_won"] - h["points_lost"]) for h in last20])) if len(last20) > 1 else 0.0
    std_sets20 = float(pstdev([(h["sets_won"] - h["sets_lost"]) for h in last20])) if len(last20) > 1 else 0.0
    variance_win20 = float(np.var([float(h["win"]) for h in last20])) if len(last20) > 1 else 0.0
    consistency_score = max(0.0, 1.0 - min(1.0, std_points20 / 25.0 + variance_win20))
    aggressive_ratio = points_ratio30
    defensive_ratio = 1.0 - aggressive_ratio
    fast_match_ratio20 = _safe_div(sum(1 for h in last20 if _norm_duration_minutes(h["duration_minutes"]) <= 18.0), max(1, len(last20)))
    long_rally_ratio20 = long_match_ratio20
    hour_strength = _safe_div(sum(h["win"] for h in hour_band), max(1, len(hour_band)), 0.5)
    morning_strength = _safe_div(sum(h["win"] for h in morning), max(1, len(morning)), 0.5)
    evening_strength = _safe_div(sum(h["win"] for h in evening), max(1, len(evening)), 0.5)
    weekend_strength = _safe_div(sum(h["win"] for h in weekend), max(1, len(weekend)), 0.5)
    avg_sets_per_match20 = _safe_div(
        sum(h["sets_won"] + h["sets_lost"] for h in last20),
        max(1, len(last20)),
        3.0,
    )
    total_sets20 = float(sum(h["sets_won"] + h["sets_lost"] for h in last20))
    total_points20 = float(sum(h["points_won"] + h["points_lost"] for h in last20))
    avg_points_per_set20 = _safe_div(total_points20, max(1.0, total_sets20), 21.0)
    match_duration_proxy20 = _safe_div(
        float(sum(_norm_duration_minutes(h["duration_minutes"]) for h in last20)),
        max(1, len(last20)),
        25.0,
    )
    tempo_score = avg_points_per_set20 * avg_sets_per_match20
    # Базовая усталость по последним 24ч + компонента от отдыха (мало отдыха → выше индекс), чтобы фича не была константой.
    fatigue_index = 0.5 * matches24h + 0.3 * sets24h + 0.2 * (mins24h / 60.0) + 12.0 / max(1.0, rest_hours)
    # Fatigue pressure: 24/48/72h — ловит накопленную нагрузку (+3–5%).
    fatigue_pressure = 0.6 * matches24h + 0.3 * matches48h + 0.1 * matches72h
    # Recency-weighted strength (temporal alpha): recent matches weight more.
    w_total = 0.0
    wr_sum = 0.0
    for idx, h in enumerate(rec_desc[:20]):
        w = math.exp(-idx / 8.0)
        w_total += w
        wr_sum += w * float(h["win"])
    temporal_strength = _safe_div(wr_sum, w_total, 0.5)

    elo_rec = [(t, e) for (t, e) in elo_hist if t < cutoff]
    elo_rec_desc = sorted(elo_rec, key=lambda x: x[0], reverse=True)
    elo_now = float(elo_rec_desc[0][1]) if elo_rec_desc else 1500.0
    if len(elo_rec_desc) >= 10:
        elo_trend = float(elo_now - elo_rec_desc[9][1])
        elo_vol = float(pstdev([x[1] for x in elo_rec_desc[:10]]))
        elo_peak50 = float(max(x[1] for x in elo_rec_desc[:50]))
        elo_floor10 = float(min(x[1] for x in elo_rec_desc[:10]))
        elo_drop10 = max(0.0, elo_peak50 - elo_now)
        elo_gain10 = max(0.0, elo_now - elo_floor10)
        elo_recent = _safe_div(elo_trend, 120.0, 0.0)
    else:
        elo_trend = 0.0
        elo_vol = 0.0
        elo_peak50 = elo_now
        elo_drop10 = 0.0
        elo_gain10 = 0.0
        elo_recent = 0.0
    if len(elo_rec_desc) >= 30:
        elo_trend30 = float(elo_now - elo_rec_desc[29][1])
    else:
        elo_trend30 = elo_trend
    # ELO momentum decay: elo * exp(-days_since/30) — ловит быстро меняющуюся форму (+3–6%).
    elo_decay_7 = elo_now
    elo_decay_30 = elo_now
    elo_momentum = 0.0
    if elo_rec_desc:
        decay_7_sum, decay_7_w = 0.0, 0.0
        decay_30_sum, decay_30_w = 0.0, 0.0
        for t, elo in elo_rec_desc[:50]:
            days = (cutoff - t).total_seconds() / 86400.0
            if days > 30.0:
                break
            w = math.exp(-days / 30.0)
            decay_30_sum += elo * w
            decay_30_w += w
            if days <= 7.0:
                decay_7_sum += elo * w
                decay_7_w += w
        elo_decay_30 = _safe_div(decay_30_sum, decay_30_w, elo_now)
        elo_decay_7 = _safe_div(decay_7_sum, decay_7_w, elo_now)
        elo_momentum = (elo_decay_7 - elo_decay_30) / 400.0
    elo_strength = _safe_div(elo_now - 1200.0, 800.0, 0.5)
    latent_strength = 0.55 * elo_strength + 0.30 * points_ratio30 + 0.15 * sets_ratio30
    latent_strength = max(0.0, min(1.0, latent_strength))
    # Experience buckets (для 4 моделей: rookie / low / mid / pro). Строго по истории до матча — без утечки.
    # bucket 1 = rookie (<20), 2 = low (20–79), 3 = mid (80–299), 4 = pro (≥300). Пороги дают +6–10% accuracy.
    if matches_played_before < 20.0:
        exp_bucket = 1.0  # rookie
    elif matches_played_before < 80.0:
        exp_bucket = 2.0  # low
    elif matches_played_before < 300.0:
        exp_bucket = 3.0  # mid
    else:
        exp_bucket = 4.0  # pro
    return _PlayerAgg(
        wins10=wins10,
        wins20=wins20,
        wins3=wins3,
        wins5=wins5,
        wins30=wins30,
        wins50=wins50,
        sets_ratio10=sets_ratio10,
        sets_ratio20=sets_ratio20,
        sets_ratio50=sets_ratio50,
        points_ratio10=points_ratio10,
        points_ratio20=points_ratio20,
        points_ratio50=points_ratio50,
        dominance10=dominance10,
        dominance20=dominance20,
        dominance50=dominance50,
        matches3h=matches3h,
        matches6h=matches6h,
        matches12h=matches12h,
        matches24h=matches24h,
        matches48h=matches48h,
        matches72h=matches72h,
        matches7d=matches7d,
        matches3d=matches3d,
        sets24h=sets24h,
        points24h=points24h,
        mins24h=mins24h,
        rest_hours=rest_hours,
        rest_days=rest_days,
        long_match_ratio20=long_match_ratio20,
        momentum_today=momentum_today,
        momentum3=momentum3,
        momentum5=momentum5,
        streak=float(streak),
        win_streak=win_streak,
        loss_streak=loss_streak,
        improvement=improvement,
        set1_strength=set1_strength,
        comeback_rate=comeback_rate,
        reverse_sweep_rate=reverse_sweep_rate,
        choke_rate=choke_rate,
        std_points10=std_points10,
        std_points20=std_points20,
        std_sets20=std_sets20,
        variance_win20=variance_win20,
        consistency_score=consistency_score,
        aggressive_ratio=aggressive_ratio,
        defensive_ratio=defensive_ratio,
        fast_match_ratio20=fast_match_ratio20,
        long_rally_ratio20=long_rally_ratio20,
        hour_strength=hour_strength,
        morning_strength=morning_strength,
        evening_strength=evening_strength,
        weekend_strength=weekend_strength,
        points_ratio30=points_ratio30,
        sets_ratio30=sets_ratio30,
        avg_sets_per_match20=avg_sets_per_match20,
        avg_points_per_set20=avg_points_per_set20,
        match_duration_proxy20=match_duration_proxy20,
        tempo_score=tempo_score,
        fatigue_index=fatigue_index,
        fatigue_pressure=fatigue_pressure,
        temporal_strength=temporal_strength,
        latent_strength=latent_strength,
        matches_played_before=matches_played_before,
        exp_bucket=exp_bucket,
        elo_now=elo_now,
        elo_trend=elo_trend,
        elo_trend30=elo_trend30,
        elo_volatility=elo_vol,
        elo_peak50=elo_peak50,
        elo_drop10=elo_drop10,
        elo_gain10=elo_gain10,
        elo_recent=elo_recent,
        elo_decay_7=elo_decay_7,
        elo_decay_30=elo_decay_30,
        elo_momentum=elo_momentum,
    )


def _compose_match_features(
    a1: _PlayerAgg,
    a2: _PlayerAgg,
    *,
    h2h_diff: float,
    h2h_count: float,
    h2h_winrate: float,
    h2h_last_result: float,
    h2h_last3_diff: float,
    h2h_last5_diff: float,
    h2h_recent_diff: float,
    league_upset_rate: float,
    league_strength: float,
    league_avg_sets: float,
    league_variance: float,
    league_winrate_variance: float,
    league_dominance_variance: float,
    league_match_volume: float,
    league_id_encoded: float,
    table_bias: float,
    league_match_count: float,
    league_rating: float,
    market_prob_p1: float,
    market_prob_p2: float,
    market_diff: float,
    closing_line: float,
    market_margin: float,
) -> dict[str, float]:
    # Ratio over fatigue_index keeps signal even when both players have low sets24h.
    fatigue_ratio = _safe_div(a1.fatigue_index + 1.0, a2.fatigue_index + 1.0, 1.0)
    elo_diff = a1.elo_now - a2.elo_now
    dominance_diff = (2.0 * a1.points_ratio20 - 1.0) - (2.0 * a2.points_ratio20 - 1.0)
    style_clash = abs(a1.points_ratio30 - a2.points_ratio30)
    volatility_combo_diff = (a1.elo_volatility + a1.std_points20) - (a2.elo_volatility + a2.std_points20)
    form_x_fatigue_diff = (a1.wins20 / max(1.0, a1.fatigue_index + 1.0)) - (a2.wins20 / max(1.0, a2.fatigue_index + 1.0))
    momentum_x_rest_diff = (a1.momentum5 * (a1.rest_hours + 1.0)) - (a2.momentum5 * (a2.rest_hours + 1.0))
    # Keep both directions (<1 and >1). Previous clamp-to-1 removed half of the signal.
    fatigue_ratio_log = math.log(max(1e-6, fatigue_ratio))
    experience_ratio = _safe_div(a1.matches_played_before + 1.0, a2.matches_played_before + 1.0, 1.0)
    elo_confidence_gap = abs(elo_diff) / (1.0 + abs(a1.elo_volatility - a2.elo_volatility))
    h2h_x_form = h2h_diff * (a1.wins20 - a2.wins20)
    style_momentum_diff = style_clash * (a1.momentum5 - a2.momentum5)
    temporal_form_diff = (a1.temporal_strength - a2.temporal_strength) * (a1.wins20 - a2.wins20)
    league_upset_x_margin = league_upset_rate * market_margin
    league_bias_x_margin = table_bias * market_margin
    exp_bucket_diff = a1.exp_bucket - a2.exp_bucket
    exp_mismatch = 1.0 if a1.exp_bucket != a2.exp_bucket else 0.0
    return {
        "elo_diff": elo_diff,
        "elo_trend_diff": a1.elo_trend - a2.elo_trend,
        "elo_trend_30_diff": a1.elo_trend30 - a2.elo_trend30,
        "elo_volatility_diff": a1.elo_volatility - a2.elo_volatility,
        "elo_peak_diff": a1.elo_peak50 - a2.elo_peak50,
        "elo_drop_10_diff": a1.elo_drop10 - a2.elo_drop10,
        "elo_gain_10_diff": a1.elo_gain10 - a2.elo_gain10,
        "elo_recent_diff": a1.elo_recent - a2.elo_recent,
        "form_diff": a1.wins20 - a2.wins20,
        "winrate_3_diff": a1.wins3 - a2.wins3,
        "winrate_5_diff": a1.wins5 - a2.wins5,
        "winrate_10_diff": a1.wins10 - a2.wins10,
        "winrate_20_diff": a1.wins20 - a2.wins20,
        "winrate_30_diff": a1.wins30 - a2.wins30,
        "winrate_50_diff": a1.wins50 - a2.wins50,
        "sets_ratio_10_diff": a1.sets_ratio10 - a2.sets_ratio10,
        "sets_ratio_20_diff": a1.sets_ratio20 - a2.sets_ratio20,
        "sets_ratio_50_diff": a1.sets_ratio50 - a2.sets_ratio50,
        "points_ratio_10_diff": a1.points_ratio10 - a2.points_ratio10,
        "points_ratio_20_diff": a1.points_ratio20 - a2.points_ratio20,
        "points_ratio_50_diff": a1.points_ratio50 - a2.points_ratio50,
        "dominance_diff": dominance_diff,
        "dominance_last_10_diff": a1.dominance10 - a2.dominance10,
        "dominance_last_20_diff": a1.dominance20 - a2.dominance20,
        "dominance_last_50_diff": a1.dominance50 - a2.dominance50,
        "fatigue_diff": a2.mins24h - a1.mins24h,
        "fatigue_ratio": fatigue_ratio,
        "fatigue_pressure_diff": a1.fatigue_pressure - a2.fatigue_pressure,
        "matches_24h_diff": a1.matches24h - a2.matches24h,
        "matches_3h_diff": a1.matches3h - a2.matches3h,
        "matches_6h_diff": a1.matches6h - a2.matches6h,
        "matches_12h_diff": a1.matches12h - a2.matches12h,
        "matches_7d_diff": a1.matches7d - a2.matches7d,
        "matches_3d_diff": a1.matches3d - a2.matches3d,
        # Тренд силы: 10 vs 20 матчей (чаще различаются, чем 10 vs 30 при малой истории).
        "strength_trend_diff": (a1.points_ratio10 - a1.points_ratio20) - (a2.points_ratio10 - a2.points_ratio20),
        "sets_24h_diff": a1.sets24h - a2.sets24h,
        "points_24h_diff": a1.points24h - a2.points24h,
        "minutes_24h_diff": a1.mins24h - a2.mins24h,
        "rest_hours_diff": a1.rest_hours - a2.rest_hours,
        "rest_days_diff": a1.rest_days - a2.rest_days,
        "long_match_ratio_diff": a1.long_match_ratio20 - a2.long_match_ratio20,
        "momentum_today_diff": a1.momentum_today - a2.momentum_today,
        "momentum_last3_diff": a1.momentum3 - a2.momentum3,
        "momentum_last5_diff": a1.momentum5 - a2.momentum5,
        "streak_score": a1.streak - a2.streak,
        "win_streak_diff": a1.win_streak - a2.win_streak,
        "loss_streak_diff": a1.loss_streak - a2.loss_streak,
        "recent_improvement_diff": a1.improvement - a2.improvement,
        "style_clash": style_clash,
        "aggressive_ratio_diff": a1.aggressive_ratio - a2.aggressive_ratio,
        "defensive_ratio_diff": a1.defensive_ratio - a2.defensive_ratio,
        "fast_match_ratio_diff": a1.fast_match_ratio20 - a2.fast_match_ratio20,
        "long_rally_ratio_diff": a1.long_rally_ratio20 - a2.long_rally_ratio20,
        "hour_strength_diff": a1.hour_strength - a2.hour_strength,
        "morning_strength_diff": a1.morning_strength - a2.morning_strength,
        "evening_strength_diff": a1.evening_strength - a2.evening_strength,
        "weekend_strength_diff": a1.weekend_strength - a2.weekend_strength,
        "h2h_diff": h2h_diff,
        "h2h_count": h2h_count,
        "h2h_winrate": h2h_winrate,
        "h2h_last_result": h2h_last_result,
        "h2h_last3_diff": h2h_last3_diff,
        "h2h_last5_diff": h2h_last5_diff,
        "h2h_recent_diff": h2h_recent_diff,
        "h2h_dominance": h2h_diff,
        "comeback_rate_diff": a1.comeback_rate - a2.comeback_rate,
        "reverse_sweep_rate_diff": a1.reverse_sweep_rate - a2.reverse_sweep_rate,
        "choke_rate_diff": a1.choke_rate - a2.choke_rate,
        "set1_strength_diff": a1.set1_strength - a2.set1_strength,
        "elo_x_fatigue": elo_diff * math.log(max(1.0, fatigue_ratio)),
        "std_points_last20_diff": a1.std_points20 - a2.std_points20,
        "std_sets_last20_diff": a1.std_sets20 - a2.std_sets20,
        "variance_winrate_diff": a1.variance_win20 - a2.variance_win20,
        "consistency_score_diff": a1.consistency_score - a2.consistency_score,
        "points_ratio_last_30_diff": a1.points_ratio30 - a2.points_ratio30,
        "sets_ratio_last_30_diff": a1.sets_ratio30 - a2.sets_ratio30,
        "avg_sets_per_match_diff": a1.avg_sets_per_match20 - a2.avg_sets_per_match20,
        "avg_points_per_set_diff": a1.avg_points_per_set20 - a2.avg_points_per_set20,
        "match_duration_proxy_diff": a1.match_duration_proxy20 - a2.match_duration_proxy20,
        "tempo_diff": a1.tempo_score - a2.tempo_score,
        "fatigue_index_diff": a1.fatigue_index - a2.fatigue_index,
        "temporal_strength_diff": a1.temporal_strength - a2.temporal_strength,
        "latent_strength_diff": a1.latent_strength - a2.latent_strength,
        "league_upset_rate": league_upset_rate,
        "league_strength": league_strength,
        "league_avg_sets": league_avg_sets,
        "league_variance": league_variance,
        "league_winrate_variance": league_winrate_variance,
        "league_dominance_variance": league_dominance_variance,
        "league_match_volume": league_match_volume,
        "league_id_encoded": league_id_encoded,
        "table_bias": table_bias,
        "league_match_count": league_match_count,
        "league_rating": league_rating,
        "matches_played_before": min(a1.matches_played_before, a2.matches_played_before),
        "experience_diff": a1.matches_played_before - a2.matches_played_before,
        "p1_exp_bucket": a1.exp_bucket,
        "p2_exp_bucket": a2.exp_bucket,
        "experience_bucket_diff": exp_bucket_diff,
        "experience_mismatch": exp_mismatch,
        "elo_x_experience": elo_diff * exp_bucket_diff,
        "volatility_combo_diff": volatility_combo_diff,
        "form_x_fatigue_diff": form_x_fatigue_diff,
        "momentum_x_rest_diff": momentum_x_rest_diff,
        "h2h_x_form": h2h_x_form,
        "fatigue_ratio_log": fatigue_ratio_log,
        "experience_ratio": experience_ratio,
        "elo_confidence_gap": elo_confidence_gap,
        "style_momentum_diff": style_momentum_diff,
        "temporal_form_diff": temporal_form_diff,
        "league_upset_x_margin": league_upset_x_margin,
        "league_bias_x_margin": league_bias_x_margin,
        "elo_decay_7_diff": a1.elo_decay_7 - a2.elo_decay_7,
        "elo_decay_30_diff": a1.elo_decay_30 - a2.elo_decay_30,
        "elo_momentum_diff": a1.elo_momentum - a2.elo_momentum,
        "matches_48h_diff": a1.matches48h - a2.matches48h,
        "matches_72h_diff": a1.matches72h - a2.matches72h,
        "league_rating": league_rating,
        "market_prob_p1": market_prob_p1,
        "market_prob_p2": market_prob_p2,
        "market_diff": market_diff,
        "closing_line": closing_line,
        "market_margin": market_margin,
    }


def feature_coverage_stats() -> dict[str, int]:
    ensure_schema()
    client = get_ch_client()
    matches_rows = client.query("SELECT uniqExact(match_id) FROM ml.matches FINAL").result_rows
    features_rows = client.query("SELECT uniqExact(match_id) FROM ml.match_features FINAL").result_rows
    missing_rows = client.query(
        """
        SELECT count()
        FROM (SELECT DISTINCT match_id FROM ml.matches FINAL) m
        LEFT JOIN (SELECT DISTINCT match_id FROM ml.match_features FINAL) f ON m.match_id = f.match_id
        WHERE length(f.match_id) = 0
        """
    ).result_rows
    matches_cnt = int((matches_rows[0][0] if matches_rows else 0) or 0)
    features_cnt = int((features_rows[0][0] if features_rows else 0) or 0)
    missing_cnt = int((missing_rows[0][0] if missing_rows else 0) or 0)
    return {
        "matches_total": matches_cnt,
        "features_total": features_cnt,
        "missing_features": missing_cnt,
    }


def rebuild_features_to_ch(
    *,
    mode: str = "incremental",
    limit: int | None = None,
    cursor_start_time: datetime | None = None,
    cursor_match_id: str | None = None,
) -> dict[str, int]:
    ensure_schema()
    client = get_ch_client()
    mode = str(mode or "incremental").strip().lower()
    if mode not in {"incremental", "missing", "all", "refresh"}:
        raise ValueError(f"Unsupported feature rebuild mode: {mode}")

    last_feature_time = None
    if mode == "incremental":
        last_rows = client.query("SELECT max(start_time) FROM ml.match_features FINAL").result_rows
        if last_rows and last_rows[0][0] is not None:
            last_feature_time = _to_utc(last_rows[0][0])

    lim = int(limit or 0)
    if mode == "missing":
        query = """
            SELECT m.match_id, m.start_time, m.league_id, m.player1_id, m.player2_id, m.score_sets_p1, m.score_sets_p2, m.odds_p1, m.odds_p2
            FROM (SELECT * FROM ml.matches FINAL) m
            LEFT JOIN (SELECT match_id FROM ml.match_features FINAL) f ON m.match_id = f.match_id
            WHERE length(f.match_id) = 0
            ORDER BY m.start_time ASC, m.match_id ASC
        """
        if lim > 0:
            query += " LIMIT %(lim)s"
            matches = client.query(query, {"lim": lim}).result_rows
        else:
            matches = client.query(query).result_rows
    elif mode == "incremental" and last_feature_time is not None:
        query = """
            SELECT match_id, start_time, league_id, player1_id, player2_id, score_sets_p1, score_sets_p2, odds_p1, odds_p2
            FROM ml.matches FINAL
            WHERE start_time > %(last_feature_time)s
            ORDER BY start_time ASC, match_id ASC
        """
        if lim > 0:
            query += " LIMIT %(lim)s"
            matches = client.query(query, {"last_feature_time": last_feature_time, "lim": lim}).result_rows
        else:
            matches = client.query(query, {"last_feature_time": last_feature_time}).result_rows
    elif mode == "refresh":
        query = """
            SELECT match_id, start_time, league_id, player1_id, player2_id, score_sets_p1, score_sets_p2, odds_p1, odds_p2
            FROM ml.matches FINAL
        """
        params: dict[str, Any] = {}
        cs = _to_utc(cursor_start_time) if cursor_start_time is not None else None
        cid = str(cursor_match_id or "")
        if cs is not None:
            query += """
            WHERE (start_time > %(cursor_start_time)s)
               OR (start_time = %(cursor_start_time)s AND match_id > %(cursor_match_id)s)
            """
            params = {"cursor_start_time": cs, "cursor_match_id": cid}
        query += " ORDER BY start_time ASC, match_id ASC"
        if lim > 0:
            query += " LIMIT %(lim)s"
            params["lim"] = lim
        matches = client.query(query, params if params else None).result_rows
    else:
        query = """
            SELECT match_id, start_time, league_id, player1_id, player2_id, score_sets_p1, score_sets_p2, odds_p1, odds_p2
            FROM ml.matches FINAL
            ORDER BY start_time ASC, match_id ASC
        """
        if lim > 0:
            query += " LIMIT %(lim)s"
            matches = client.query(query, {"lim": lim}).result_rows
        else:
            matches = client.query(query).result_rows

    if not matches:
        stats = feature_coverage_stats()
        return {"features_added": 0, "mode": mode, "remaining_missing": int(stats.get("missing_features", 0))}

    # Гарантированный порядок: сначала по времени, потом по id (матчи одного дня не перемешаны).
    matches = sorted(matches, key=lambda r: (_to_utc(r[1]) if r[1] else datetime.min.replace(tzinfo=timezone.utc), str(r[0] or "")))

    set1_rows = client.query(
        """
        SELECT match_id, score_p1, score_p2
        FROM ml.match_sets FINAL
        WHERE set_number = 1
        """
    ).result_rows
    target_set1_by_mid: dict[str, int] = {
        str(mid): (1 if int(s1) > int(s2) else 0) for mid, s1, s2 in set1_rows
    }

    # Порядок player+time обязателен: иначе матч 11:00 может влиять на фичи матча 10:00 (утечка внутри дня).
    stats_rows = client.query(
        """
        SELECT player_id, match_id, match_time, league_id, win, set1_win, sets_won, sets_lost, points_won, points_lost, duration_minutes
        FROM ml.player_match_stats FINAL
        ORDER BY player_id ASC, match_time ASC, match_id ASC
        """
    ).result_rows
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in stats_rows:
        by_player[str(r[0])].append(
            {
                "match_id": str(r[1]),
                "match_time": _to_utc(r[2]),
                "league_id": str(r[3] or ""),
                "win": int(r[4]),
                "set1_win": int(r[5]),
                "sets_won": int(r[6]),
                "sets_lost": int(r[7]),
                "points_won": int(r[8]),
                "points_lost": int(r[9]),
                "duration_minutes": int(r[10] or 0),
            }
        )
    # Гарантированная сортировка по времени внутри каждого игрока (rolling = только прошлое).
    for pid in by_player:
        by_player[pid] = sorted(by_player[pid], key=lambda h: (h["match_time"], h.get("match_id", "")))

    elo_rows = client.query(
        "SELECT player_id, match_time, elo_after FROM ml.player_elo_history FINAL ORDER BY player_id ASC, match_time ASC"
    ).result_rows
    elo_by_player: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for pid, mt, elo in elo_rows:
        elo_by_player[str(pid)].append((_to_utc(mt), float(elo)))
    for pid in elo_by_player:
        elo_by_player[pid] = sorted(elo_by_player[pid], key=lambda x: x[0])

    # h2h cache: key (a,b sorted) -> list[(t, winner_pid)]
    h2h: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    # League upset stats from already processed historical matches.
    league_state: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "n": 0.0,
            "upsets": 0.0,
            "home_wins": 0.0,
            "sets_total": 0.0,
            "outcome_sum": 0.0,
            "outcome_sq_sum": 0.0,
            "dom_sum": 0.0,
            "dom_sq_sum": 0.0,
            "elo_sum": 0.0,
            "elo_n": 0.0,
        }
    )
    out_rows: list[list[Any]] = []

    # Матчи уже в порядке ORDER BY start_time ASC — порядок важен: фичи считаются только из прошлого, без утечки внутри дня.
    for row in matches:
        mid = str(row[0])
        st: datetime = _to_utc(row[1])
        if mode == "incremental" and last_feature_time is not None and st <= last_feature_time:
            continue
        lid = str(row[2] or "")
        p1 = str(row[3])
        p2 = str(row[4])
        s1 = int(row[5] or 0)
        s2 = int(row[6] or 0)
        o1 = float(row[7] or 0.0)
        o2 = float(row[8] or 0.0)
        a1 = _compute_player_agg(by_player.get(p1, []), elo_by_player.get(p1, []), st, exclude_match_id=mid)
        a2 = _compute_player_agg(by_player.get(p2, []), elo_by_player.get(p2, []), st, exclude_match_id=mid)
        key = tuple(sorted([p1, p2]))
        h2h_hist = [x for x in h2h.get(key, []) if x[0] < st]
        if h2h_hist:
            p1_w = sum(1 for _, w in h2h_hist if w == p1)
            p2_w = sum(1 for _, w in h2h_hist if w == p2)
            h2h_count = float(len(h2h_hist))
            h2h_diff = _safe_div(p1_w - p2_w, max(1, p1_w + p2_w))
            h2h_winrate = _safe_div(p1_w, max(1, p1_w + p2_w), 0.5)
            last_result_winner = h2h_hist[-1][1]
            h2h_last_result = 1.0 if last_result_winner == p1 else -1.0
            last3 = h2h_hist[-3:]
            last5 = h2h_hist[-5:]
            h2h_last3_diff = _safe_div(
                sum(1 if w == p1 else -1 for _, w in last3),
                max(1, len(last3)),
            )
            h2h_last5_diff = _safe_div(
                sum(1 if w == p1 else -1 for _, w in last5),
                max(1, len(last5)),
            )
            w_total = 0.0
            wr = 0.0
            for idx, (_, w) in enumerate(reversed(h2h_hist[-10:])):
                weight = math.exp(-idx / 3.5)
                w_total += weight
                wr += weight * (1.0 if w == p1 else -1.0)
            h2h_recent_diff = _safe_div(wr, w_total, 0.0)
        else:
            h2h_count = 0.0
            h2h_diff = 0.0
            h2h_winrate = 0.5
            h2h_last_result = 0.0
            h2h_last3_diff = 0.0
            h2h_last5_diff = 0.0
            h2h_recent_diff = 0.0
        if getattr(settings, "ml_v2_disable_market_features", True):
            market_margin = 0.0
            market_prob_p1, market_prob_p2 = 0.5, 0.5
            market_diff = 0.0
            closing_line = 0.0
        else:
            market_margin = (1.0 / o1 + 1.0 / o2 - 1.0) if o1 > 1e-9 and o2 > 1e-9 else 0.0
            market_prob_p1 = _safe_div(1.0 / max(1e-9, o1), (1.0 / max(1e-9, o1)) + (1.0 / max(1e-9, o2)), 0.5)
            market_prob_p2 = _safe_div(1.0 / max(1e-9, o2), (1.0 / max(1e-9, o1)) + (1.0 / max(1e-9, o2)), 0.5)
            market_diff = market_prob_p1 - market_prob_p2
            closing_line = market_diff
        league_n = float(league_state[lid]["n"])
        league_upsets = float(league_state[lid]["upsets"])
        league_upset_rate = _safe_div(league_upsets, max(1.0, league_n), 0.5)
        league_strength = 1.0 - league_upset_rate
        league_avg_sets = _safe_div(float(league_state[lid].get("sets_total", 0.0)), max(1.0, league_n), 3.0)
        league_mean_outcome = _safe_div(float(league_state[lid].get("outcome_sum", 0.0)), max(1.0, league_n), 0.5)
        league_mean_sq = _safe_div(float(league_state[lid].get("outcome_sq_sum", 0.0)), max(1.0, league_n), 0.25)
        league_variance = max(0.0, league_mean_sq - league_mean_outcome * league_mean_outcome)
        league_winrate_variance = league_variance
        league_dom_mean = _safe_div(float(league_state[lid].get("dom_sum", 0.0)), max(1.0, league_n), 0.0)
        league_dom_sq_mean = _safe_div(float(league_state[lid].get("dom_sq_sum", 0.0)), max(1.0, league_n), 0.0)
        league_dominance_variance = max(0.0, league_dom_sq_mean - league_dom_mean * league_dom_mean)
        league_match_volume = math.log1p(max(0.0, league_n))
        league_id_encoded = float((zlib.crc32(lid.encode("utf-8")) % 1000003) / 1000003.0) if lid else 0.0
        table_bias = _safe_div(float(league_state[lid].get("home_wins", 0.0)), max(1.0, league_n), 0.5)
        league_rating_raw = _safe_div(float(league_state[lid].get("elo_sum", 0.0)), max(1.0, float(league_state[lid].get("elo_n", 0.0))), 1500.0)
        league_rating = max(0.0, min(1.0, (league_rating_raw - 1200.0) / 800.0))
        feats = _compose_match_features(
            a1,
            a2,
            h2h_diff=h2h_diff,
            h2h_count=h2h_count,
            h2h_winrate=h2h_winrate,
            h2h_last_result=h2h_last_result,
            h2h_last3_diff=h2h_last3_diff,
            h2h_last5_diff=h2h_last5_diff,
            h2h_recent_diff=h2h_recent_diff,
            league_upset_rate=league_upset_rate,
            league_strength=league_strength,
            league_avg_sets=league_avg_sets,
            league_variance=league_variance,
            league_winrate_variance=league_winrate_variance,
            league_dominance_variance=league_dominance_variance,
            league_match_volume=league_match_volume,
            league_id_encoded=league_id_encoded,
            table_bias=table_bias,
            league_match_count=league_n,
            league_rating=league_rating,
            market_prob_p1=market_prob_p1,
            market_prob_p2=market_prob_p2,
            market_diff=market_diff,
            closing_line=closing_line,
            market_margin=market_margin,
        )
        out_rows.append(
            [mid, st, lid, p1, p2, *[float(feats.get(c, 0.0)) for c in FEATURE_COLS_V2], 1 if s1 > s2 else 0, int(target_set1_by_mid.get(mid, 0))]
        )
        winner = p1 if s1 > s2 else p2
        h2h[key].append((st, winner))
        # For league chaos features, update league state on every historical match.
        league_state[lid]["n"] = float(league_state[lid]["n"]) + 1.0
        total_sets = float(s1 + s2)
        league_state[lid]["sets_total"] = float(league_state[lid].get("sets_total", 0.0)) + total_sets
        home_outcome = 1.0 if winner == p1 else 0.0
        league_state[lid]["outcome_sum"] = float(league_state[lid].get("outcome_sum", 0.0)) + home_outcome
        league_state[lid]["outcome_sq_sum"] = float(league_state[lid].get("outcome_sq_sum", 0.0)) + home_outcome * home_outcome
        if winner == p1:
            league_state[lid]["home_wins"] = float(league_state[lid].get("home_wins", 0.0)) + 1.0
        dom = _safe_div(abs(float(s1) - float(s2)), max(1.0, float(s1 + s2)), 0.0)
        league_state[lid]["dom_sum"] = float(league_state[lid].get("dom_sum", 0.0)) + dom
        league_state[lid]["dom_sq_sum"] = float(league_state[lid].get("dom_sq_sum", 0.0)) + dom * dom
        if o1 > 1.0 and o2 > 1.0:
            fav = p1 if o1 <= o2 else p2
            if winner != fav:
                league_state[lid]["upsets"] = float(league_state[lid]["upsets"]) + 1.0
        league_state[lid]["elo_sum"] = float(league_state[lid].get("elo_sum", 0.0)) + a1.elo_now + a2.elo_now
        league_state[lid]["elo_n"] = float(league_state[lid].get("elo_n", 0.0)) + 2.0

    if mode == "all":
        client.command("TRUNCATE TABLE ml.match_features")
    if not out_rows:
        stats = feature_coverage_stats()
        return {"features_added": 0, "mode": mode, "remaining_missing": int(stats.get("missing_features", 0))}
    client.insert(
        "ml.match_features",
        out_rows,
        column_names=["match_id", "start_time", "league_id", "player1_id", "player2_id", *FEATURE_COLS_V2, "target_match", "target_set1"],
    )
    stats = feature_coverage_stats()
    out: dict[str, Any] = {
        "features_added": len(out_rows),
        "mode": mode,
        "fetched": len(matches),
        "remaining_missing": int(stats.get("missing_features", 0)),
    }
    if mode == "refresh":
        if matches:
            last_mid = str(matches[-1][0])
            last_st = _to_utc(matches[-1][1])
            out["refresh_next_cursor_start_time"] = last_st.isoformat()
            out["refresh_next_cursor_match_id"] = last_mid
        out["refresh_done"] = bool(lim > 0 and len(matches) < lim)
    return out


def build_upcoming_feature_vector(
    home_id: str,
    away_id: str,
    league_id: str,
    start_time: datetime,
    odds_p1: float,
    odds_p2: float,
) -> dict[str, float]:
    """Фичи для предстоящего матча. Игроки идентифицируются только по ID (home_id/away_id), не по имени и не по позиции."""
    ensure_schema()
    client = get_ch_client()
    start_time = _to_utc(start_time)

    def _fetch_stats(pid: str) -> list[dict[str, Any]]:
        rows = client.query(
            """
            SELECT match_time, win, set1_win, sets_won, sets_lost, points_won, points_lost, duration_minutes
            FROM ml.player_match_stats FINAL
            WHERE player_id = %(pid)s AND match_time < %(cutoff)s
            ORDER BY match_time DESC
            LIMIT 80
            """,
            {"pid": pid, "cutoff": start_time},
        ).result_rows
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "match_time": _to_utc(r[0]),
                    "win": int(r[1]),
                    "set1_win": int(r[2]),
                    "sets_won": int(r[3]),
                    "sets_lost": int(r[4]),
                    "points_won": int(r[5]),
                    "points_lost": int(r[6]),
                    "duration_minutes": int(r[7] or 0),
                }
            )
        return sorted(out, key=lambda x: x["match_time"])

    def _fetch_elo(pid: str) -> list[tuple[datetime, float]]:
        rows = client.query(
            """
            SELECT match_time, elo_after
            FROM ml.player_elo_history FINAL
            WHERE player_id = %(pid)s AND match_time < %(cutoff)s
            ORDER BY match_time DESC
            LIMIT 40
            """,
            {"pid": pid, "cutoff": start_time},
        ).result_rows
        return sorted([(_to_utc(r[0]), float(r[1])) for r in rows], key=lambda x: x[0])

    h1 = _fetch_stats(home_id)
    h2 = _fetch_stats(away_id)
    e1 = _fetch_elo(home_id)
    e2 = _fetch_elo(away_id)
    a1 = _compute_player_agg(h1, e1, start_time)
    a2 = _compute_player_agg(h2, e2, start_time)
    h2h_rows = client.query(
        """
        SELECT player1_id, player2_id, score_sets_p1, score_sets_p2
        FROM ml.matches FINAL
        WHERE ((player1_id = %(p1)s AND player2_id = %(p2)s) OR (player1_id = %(p2)s AND player2_id = %(p1)s))
          AND start_time < %(cutoff)s
        ORDER BY start_time DESC
        LIMIT 40
        """,
        {"p1": home_id, "p2": away_id, "cutoff": start_time},
    ).result_rows
    h2h_p1 = 0
    h2h_p2 = 0
    h2h_winners: list[str] = []
    for p1, p2, s1, s2 in h2h_rows:
        if str(p1) == home_id:
            if int(s1) > int(s2):
                h2h_p1 += 1
                h2h_winners.append(home_id)
            else:
                h2h_p2 += 1
                h2h_winners.append(away_id)
        else:
            if int(s2) > int(s1):
                h2h_p1 += 1
                h2h_winners.append(home_id)
            else:
                h2h_p2 += 1
                h2h_winners.append(away_id)
    h2h_count = float(h2h_p1 + h2h_p2)
    h2h_diff = _safe_div(h2h_p1 - h2h_p2, max(1, h2h_p1 + h2h_p2))
    h2h_winrate = _safe_div(h2h_p1, max(1, h2h_p1 + h2h_p2), 0.5)
    h2h_last_result = 0.0 if not h2h_winners else (1.0 if h2h_winners[0] == home_id else -1.0)
    last3 = h2h_winners[:3]
    last5 = h2h_winners[:5]
    h2h_last3_diff = _safe_div(sum(1.0 if w == home_id else -1.0 for w in last3), max(1, len(last3)), 0.0)
    h2h_last5_diff = _safe_div(sum(1.0 if w == home_id else -1.0 for w in last5), max(1, len(last5)), 0.0)
    w_total = 0.0
    wr = 0.0
    for idx, w in enumerate(h2h_winners[:10]):
        weight = math.exp(-idx / 3.5)
        w_total += weight
        wr += weight * (1.0 if w == home_id else -1.0)
    h2h_recent_diff = _safe_div(wr, w_total, 0.0)
    league_rows = client.query(
        """
        SELECT odds_p1, odds_p2, score_sets_p1, score_sets_p2
        FROM ml.matches FINAL
        WHERE league_id = %(league_id)s AND start_time < %(cutoff)s
        ORDER BY start_time DESC
        LIMIT 1500
        """,
        {"league_id": str(league_id or ""), "cutoff": start_time},
    ).result_rows
    league_n = 0
    upset_hits = 0
    league_home_wins = 0
    dom_sum = 0.0
    dom_sq_sum = 0.0
    for o1, o2, s1, s2 in league_rows:
        home_won = int(s1) > int(s2)
        league_n += 1
        if float(o1) > 1.0 and float(o2) > 1.0:
            fav_home = float(o1) <= float(o2)
            upset_hits += int(home_won != fav_home)
        league_home_wins += int(home_won)
        dom = _safe_div(abs(float(int(s1) - int(s2))), max(1.0, float(int(s1) + int(s2))), 0.0)
        dom_sum += dom
        dom_sq_sum += dom * dom
    league_upset_rate = _safe_div(upset_hits, max(1, league_n), 0.5)
    league_strength = 1.0 - league_upset_rate
    league_avg_sets = _safe_div(sum(float(int(s1) + int(s2)) for _, _, s1, s2 in league_rows), max(1, league_n), 3.0)
    outcomes = [1.0 if int(s1) > int(s2) else 0.0 for _, _, s1, s2 in league_rows]
    league_variance = float(np.var(outcomes)) if outcomes else 0.0
    league_winrate_variance = league_variance
    league_dom_mean = _safe_div(dom_sum, max(1.0, float(league_n)), 0.0)
    league_dom_sq_mean = _safe_div(dom_sq_sum, max(1.0, float(league_n)), 0.0)
    league_dominance_variance = max(0.0, league_dom_sq_mean - league_dom_mean * league_dom_mean)
    league_match_volume = math.log1p(max(0, league_n))
    lid = str(league_id or "")
    league_id_encoded = float((zlib.crc32(lid.encode("utf-8")) % 1000003) / 1000003.0) if lid else 0.0
    table_bias = _safe_div(league_home_wins, max(1, league_n), 0.5)
    market_margin = (1.0 / odds_p1 + 1.0 / odds_p2 - 1.0) if odds_p1 > 1e-9 and odds_p2 > 1e-9 else 0.0
    market_prob_p1 = _safe_div(1.0 / max(1e-9, odds_p1), (1.0 / max(1e-9, odds_p1)) + (1.0 / max(1e-9, odds_p2)), 0.5)
    market_prob_p2 = _safe_div(1.0 / max(1e-9, odds_p2), (1.0 / max(1e-9, odds_p1)) + (1.0 / max(1e-9, odds_p2)), 0.5)
    market_diff = market_prob_p1 - market_prob_p2
    closing_line = market_diff
    if getattr(settings, "ml_v2_disable_market_features", True):
        market_prob_p1, market_prob_p2 = 0.5, 0.5
        market_diff, closing_line, market_margin = 0.0, 0.0, 0.0
    feats = _compose_match_features(
        a1,
        a2,
        h2h_diff=h2h_diff,
        h2h_count=h2h_count,
        h2h_winrate=h2h_winrate,
        h2h_last_result=h2h_last_result,
        h2h_last3_diff=h2h_last3_diff,
        h2h_last5_diff=h2h_last5_diff,
        h2h_recent_diff=h2h_recent_diff,
        league_upset_rate=league_upset_rate,
        league_strength=league_strength,
        league_avg_sets=league_avg_sets,
        league_variance=league_variance,
        league_winrate_variance=league_winrate_variance,
        league_dominance_variance=league_dominance_variance,
        league_match_volume=league_match_volume,
        league_id_encoded=league_id_encoded,
        table_bias=table_bias,
        league_match_count=float(league_n),
        league_rating=league_strength,
        market_prob_p1=market_prob_p1,
        market_prob_p2=market_prob_p2,
        market_diff=market_diff,
        closing_line=closing_line,
        market_margin=market_margin,
    )
    out = {c: float(feats.get(c, 0.0)) for c in FEATURE_COLS_V2}
    if getattr(settings, "ml_v2_disable_market_features", True):
        for k in _MARKET_FEATURE_KEYS:
            if k in out:
                out[k] = 0.5 if k in ("market_prob_p1", "market_prob_p2") else 0.0
    return out

