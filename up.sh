#!/bin/bash
# Run sport-analyzator with Docker Compose.
#
# Usage: ./up.sh [docker compose args...]
#   ./up.sh              # up -d (default)
#   ./up.sh logs -f      # follow logs
set -e
cd "$(dirname "$0")"

COMPOSE_ARGS=("$@")
[[ ${#COMPOSE_ARGS[@]} -eq 0 ]] && COMPOSE_ARGS=(up -d)

exec docker compose "${COMPOSE_ARGS[@]}"
