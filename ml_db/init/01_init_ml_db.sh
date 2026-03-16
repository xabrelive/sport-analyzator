#!/bin/bash
set -e
# Создаём базу pingwin_ml при первом запуске postgres.
# Подключаемся к postgres (системная БД), т.к. CREATE DATABASE нельзя из транзакции другой БД.
PGPORT="${PGPORT:-11002}"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -p "$PGPORT" -tc "SELECT 1 FROM pg_database WHERE datname = 'pingwin_ml'" | grep -q 1 || \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -p "$PGPORT" -c "CREATE DATABASE pingwin_ml;"
for f in /docker-entrypoint-initdb.d/schema/02_ml_schema.sql \
         /docker-entrypoint-initdb.d/schema/03_ml_features_v2.sql \
         /docker-entrypoint-initdb.d/schema/04_suspicious_matches_v2.sql \
         /docker-entrypoint-initdb.d/schema/05_league_performance.sql \
         /docker-entrypoint-initdb.d/schema/06_player_daily_stats.sql \
         /docker-entrypoint-initdb.d/schema/07_player_style.sql \
         /docker-entrypoint-initdb.d/schema/08_player_elo_history.sql \
         /docker-entrypoint-initdb.d/schema/09_add_duration_to_matches.sql \
         /docker-entrypoint-initdb.d/schema/10_ml_features_v3_strong.sql \
         /docker-entrypoint-initdb.d/schema/11_ml_features_h2h_sample_league.sql; do
  [ -f "$f" ] && psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d pingwin_ml -p "$PGPORT" -f "$f"
done
