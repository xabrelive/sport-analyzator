#!/usr/bin/env python3
"""Проверка ML-пайплайна: синхронизация, фичи, обучение, аналитика.

Запуск: docker compose exec backend python -c \"...\" (см. inline-версию в run)
Или: docker compose run --rm -v $(pwd)/scripts:/scripts backend python /scripts/test_ml_pipeline.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

def main():
    errors = []
    ok = []

    # 1. Синхронизация
    try:
        from app.ml.pipeline import sync_finished_to_ml_once
        r = asyncio.run(sync_finished_to_ml_once(limit=500, days_back=365))
        ok.append(f"Sync: synced={r.get('synced', 0)}, skipped={r.get('skipped', 0)}")
    except Exception as e:
        errors.append(f"Sync failed: {e}")

    # 2. Фичи
    try:
        from app.ml.pipeline import backfill_features_once
        n = backfill_features_once(limit=5000)
        ok.append(f"Features: backfilled {n} matches")
    except Exception as e:
        errors.append(f"Features failed: {e}")

    # 3. Данные для обучения
    try:
        from app.ml.model_trainer import load_training_data
        df = load_training_data(limit=500_000)
        ok.append(f"Training data: {len(df)} rows")
        if len(df) < 100:
            errors.append(f"Not enough training data: {len(df)} < 100")
    except Exception as e:
        errors.append(f"Training data failed: {e}")

    # 4. Обучение (если достаточно данных)
    try:
        from app.ml.model_trainer import load_training_data, train_match_model, train_set1_model, save_models
        df = load_training_data(limit=50_000)
        if len(df) >= 100:
            match_model = train_match_model(df, use_gpu=False)
            set1_model = train_set1_model(df, use_gpu=False)
            path = save_models(match_model, set1_model, version="v1")
            ok.append(f"Models trained and saved to {path}")
        else:
            ok.append("Models: skipped (not enough data)")
    except Exception as e:
        errors.append(f"Training failed: {e}")

    # 5. ML inference (аналитика)
    try:
        from app.ml.inference import predict_for_upcoming
        from datetime import datetime, timezone
        from app.ml.db import get_ml_session
        from sqlalchemy import text

        s = get_ml_session()
        row = s.execute(
            text("SELECT p1.external_id, p2.external_id FROM matches m "
                 "JOIN players p1 ON p1.id = m.player1_id JOIN players p2 ON p2.id = m.player2_id "
                 "WHERE m.status = 'finished' LIMIT 1")
        ).fetchone()
        s.close()
        p1, p2 = (str(row[0]), str(row[1])) if row and row[0] and row[1] else (None, None)
        if p1 and p2:
            pred = predict_for_upcoming(p1, p2, "", 1.9, 1.9, datetime.now(timezone.utc))
            if pred:
                ok.append(f"ML analytics: p_match={pred.p_match:.3f}, model_used={pred.model_used}")
            else:
                ok.append("ML analytics: no prediction (insufficient features)")
        else:
            ok.append("ML analytics: skipped (not enough players)")
    except Exception as e:
        errors.append(f"ML inference failed: {e}")

    # Итог
    print("=" * 50)
    print("ML Pipeline Test")
    print("=" * 50)
    for s in ok:
        print("[OK]", s)
    for s in errors:
        print("[FAIL]", s)
    print("=" * 50)
    if errors:
        sys.exit(1)
    print("All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
