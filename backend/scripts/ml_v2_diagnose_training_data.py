#!/usr/bin/env python3
"""Диагностика данных и фичей ML v2: почему logloss застревает ~0.683.
Проверяет: баланс таргета, константные фичи, корреляцию с таргетом, baseline logloss."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

# Загружаем данные так же, как тренер
from app.ml_v2.features import FEATURE_COLS_V2, FEATURE_COLS_V2_TRAIN
from app.ml_v2.schema import ensure_schema
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.trainer import (
    _load_feature_frame,
    _apply_training_quality_filters,
    _split,
)
from app.config import settings


def main() -> None:
    ensure_schema()
    df = _load_feature_frame()
    df = _apply_training_quality_filters(df)
    if len(df) < 1000:
        print("Мало строк после фильтров:", len(df))
        return

    train, val, test = _split(df)
    # Те же фичи, что в тренере (без мёртвых и избыточных)
    X_train = train[FEATURE_COLS_V2_TRAIN].astype(float)
    y_train = train["target_match"].astype(int).values

    print("=" * 60)
    print("1) БАЛАНС ТАРГЕТА (target_match)")
    print("=" * 60)
    n = len(y_train)
    ones = int(np.sum(y_train))
    zeros = n - ones
    mean_p = ones / max(1, n)
    # Baseline logloss если предсказывать константу p
    baseline_ll = -mean_p * np.log(mean_p + 1e-15) - (1 - mean_p) * np.log(1 - mean_p + 1e-15)
    random_ll = np.log(2)  # 0.693
    print(f"  Train: n={n}, P1 wins (1)={ones} ({100*mean_p:.2f}%), P2 wins (0)={zeros} ({100*(1-mean_p):.2f}%)")
    print(f"  Baseline logloss (predict p=mean): {baseline_ll:.6f}")
    print(f"  Random (0.5): {random_ll:.6f}")
    print(f"  Текущий val logloss ~0.683 — лишь чуть лучше random, значит сигнал слабый или фичи не информативны.")
    print()

    print("=" * 60)
    print("2) КОНСТАНТНЫЕ И ПОЧТИ КОНСТАНТНЫЕ ФИЧИ")
    print("=" * 60)
    stds = X_train.std()
    zero_share = (X_train == 0).mean()
    constant = [c for c in FEATURE_COLS_V2_TRAIN if c in stds.index and stds[c] < 1e-10]
    near_constant = [c for c in FEATURE_COLS_V2_TRAIN if c in stds.index and 1e-10 <= stds[c] < 0.01]
    print(f"  Строго константные (std=0): {len(constant)} — {constant[:15]}{'...' if len(constant) > 15 else ''}")
    print(f"  Почти константные (std < 0.01): {len(near_constant)} — {near_constant[:15]}{'...' if len(near_constant) > 15 else ''}")
    # Доля нулей
    high_zeros = [(c, float(zero_share[c])) for c in FEATURE_COLS_V2_TRAIN if c in zero_share.index and zero_share[c] > 0.95]
    high_zeros.sort(key=lambda x: -x[1])
    print(f"  Фичи с >95% нулей: {len(high_zeros)} — {high_zeros[:12]}")
    print()

    print("=" * 60)
    print("3) КОРРЕЛЯЦИЯ ФИЧЕЙ С target_match (топ по |corr|)")
    print("=" * 60)
    corrs = {}
    for c in FEATURE_COLS_V2_TRAIN:
        if c not in X_train.columns:
            continue
        r = np.corrcoef(X_train[c].astype(float).values, y_train.astype(float))[0, 1]
        if np.isfinite(r):
            corrs[c] = float(r)
    sorted_corrs = sorted(corrs.items(), key=lambda x: -abs(x[1]))
    for c, r in sorted_corrs[:25]:
        print(f"  {c}: {r:+.4f}")
    print(f"  ... всего фичей с конечной корреляцией: {len(corrs)}")
    if not sorted_corrs or abs(sorted_corrs[0][1]) < 0.05:
        print("  ВНИМАНИЕ: максимальная |corr| очень мала — фичи почти не связаны с исходом.")
    print()

    print("=" * 60)
    print("4) ФИЧИ ДЛЯ ОБУЧЕНИЯ")
    print("=" * 60)
    print(f"  Всего в FEATURE_COLS_V2: {len(FEATURE_COLS_V2)}, в FEATURE_COLS_V2_TRAIN (без мёртвых/избыточных): {len(FEATURE_COLS_V2_TRAIN)}")
    print()

    print("=" * 60)
    print("5) РЕКОМЕНДАЦИИ")
    print("=" * 60)
    if constant or len(near_constant) > 20:
        print("  - Убрать или заменить константные/почти константные фичи (деревья их не используют).")
    if sorted_corrs and abs(sorted_corrs[0][1]) < 0.08:
        print("  - Слабый линейный сигнал: попробовать нелинейные комбинации или другие фичи силы игрока.")
    if sorted_corrs and abs(sorted_corrs[0][1]) >= 0.15:
        print("  - Сигнал в данных есть (топ corr >= 0.15). Если logloss высокий — скорее недообучение: уменьшить min_child_samples (ML_V2_LGB_MIN_CHILD_SAMPLES=40 или 30).")
    print("  - Константные фичи (clock, market при disable) можно не подавать в модель — они не несут информации.")
    print("  - Проверить, что target_match = 1 именно когда выиграл player1 (первый в паре), без перепутывания.")
    print("  - Убедиться, что в match_features нет утечки (данные только до start_time матча).")
    print()
    print("Готово.")


if __name__ == "__main__":
    main()
