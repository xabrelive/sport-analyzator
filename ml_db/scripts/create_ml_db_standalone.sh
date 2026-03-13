#!/bin/bash
# Создание БД pingwin_ml на уже запущенном postgres (без пересоздания volume).
# Использование: ./create_ml_db_standalone.sh
# Или: PGPASSWORD=pingwin ./create_ml_db_standalone.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ML_INIT_DIR="$(dirname "$SCRIPT_DIR")/init"
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-11002}"
export PGUSER="${PGUSER:-pingwin}"
export PGPASSWORD="${PGPASSWORD:-pingwin}"

psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'pingwin_ml'" | grep -q 1 || \
  psql -d postgres -c "CREATE DATABASE pingwin_ml;"
for f in 02_ml_schema 03_ml_features_v2 04_suspicious_matches_v2 05_league_performance \
         06_player_daily_stats 07_player_style 08_player_elo_history 09_add_duration_to_matches \
         10_ml_features_v3_strong; do
  [ -f "$ML_INIT_DIR/schema/${f}.sql" ] && psql -d pingwin_ml -f "$ML_INIT_DIR/schema/${f}.sql" || true
done
echo "OK: pingwin_ml created and schema applied."
