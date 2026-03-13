#!/usr/bin/env python3
"""Скрипт обучения ML-моделей (XGBoost/LightGBM) с GPU."""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.ml.model_trainer import (
    FEATURE_COLS,
    load_training_data,
    save_models,
    train_match_model,
    train_set1_model,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100_000, help="Max rows for training")
    parser.add_argument("--version", type=str, default="v1", help="Model version")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU")
    args = parser.parse_args()

    logger.info("Loading training data (limit=%s)...", args.limit)
    df = load_training_data(limit=args.limit)
    if df.empty or len(df) < 100:
        logger.error("Not enough data: %s rows. Need at least 100.", len(df))
        sys.exit(1)

    logger.info("Training match model (GPU=%s)...", not args.no_gpu)
    match_model = train_match_model(df, use_gpu=not args.no_gpu)
    logger.info("Training set1 model...")
    set1_model = train_set1_model(df, use_gpu=not args.no_gpu)

    path = save_models(match_model, set1_model, version=args.version)
    logger.info("Models saved to %s", path)


if __name__ == "__main__":
    main()
