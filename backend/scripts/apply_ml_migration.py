#!/usr/bin/env python3
"""Применяет миграцию 10_ml_features_v3_strong к pingwin_ml."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.config import settings

def main():
    engine = create_engine(settings.database_url_ml)
    path = os.path.join(os.path.dirname(__file__), "..", "..", "ml_db", "init", "schema", "10_ml_features_v3_strong.sql")
    with open(path) as f:
        sql = f.read()
    with engine.connect() as conn:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                conn.execute(text(stmt))
        conn.commit()
    print("OK: migration 10_ml_features_v3_strong applied")

if __name__ == "__main__":
    main()
