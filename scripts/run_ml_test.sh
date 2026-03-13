#!/bin/bash
# Запуск теста ML-пайплайна внутри backend-контейнера.
set -e
cd "$(dirname "$0")/.."
docker compose exec backend python -c '
import asyncio, sys
errors, ok = [], []
try:
    from app.ml.pipeline import sync_finished_to_ml_once
    r = asyncio.run(sync_finished_to_ml_once(limit=500, days_back=365))
    ok.append("Sync: synced=%s, skipped=%s" % (r.get("synced", 0), r.get("skipped", 0)))
except Exception as e: errors.append(f"Sync: {e}")
try:
    from app.ml.pipeline import backfill_features_once
    n = backfill_features_once(limit=5000)
    ok.append(f"Features: backfilled {n} matches")
except Exception as e: errors.append(f"Features: {e}")
try:
    from app.ml.model_trainer import load_training_data
    df = load_training_data(limit=500_000)
    ok.append(f"Training data: {len(df)} rows")
except Exception as e: errors.append(f"Training data: {e}")
try:
    from app.ml.inference import predict_for_upcoming
    from datetime import datetime, timezone
    pred = predict_for_upcoming("809294", "318305", "", 1.9, 1.9, datetime.now(timezone.utc))
    ok.append(f"ML analytics: p_match={pred.p_match:.3f}" if pred else "ML analytics: no prediction")
except Exception as e: errors.append(f"ML inference: {e}")
print("="*50, "\nML Pipeline Test\n" + "="*50)
for s in ok: print("[OK]", s)
for s in errors: print("[FAIL]", s)
print("="*50)
sys.exit(1 if errors else 0)
'
