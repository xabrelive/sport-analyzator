#!/usr/bin/env bash
set -euo pipefail

# Simple Postgres dump helper for sport_analyzator.
# Uses the same default credentials/ports as docker-compose and .env.
#
# Usage:
#   cd backend
#   chmod +x scripts/dump_db.sh
#   ./scripts/dump_db.sh                # dump to db_dump_YYYYmmdd_HHMMSS.sql
#   ./scripts/dump_db.sh my_dump.dump   # dump to custom file
#
# Env vars you can override:
#   DB_HOST (default: localhost)
#   DB_PORT (default: 11002)
#   POSTGRES_USER (default: sport)
#   POSTGRES_PASSWORD (default: sport)
#   POSTGRES_DB (default: sport_analyzator)

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-11002}"
DB_USER="${POSTGRES_USER:-sport}"
DB_PASS="${POSTGRES_PASSWORD:-sport}"
DB_NAME="${POSTGRES_DB:-sport_analyzator}"

OUT_FILE="${1:-db_dump_$(date +%Y%m%d_%H%M%S).dump}"

echo "Creating PostgreSQL dump:"
echo "  host:     ${DB_HOST}"
echo "  port:     ${DB_PORT}"
echo "  database: ${DB_NAME}"
echo "  user:     ${DB_USER}"
echo "  file:     ${OUT_FILE}"

export PGPASSWORD="${DB_PASS}"
pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  -Fc \
  > "${OUT_FILE}"

echo "Done. Dump written to ${OUT_FILE}"

