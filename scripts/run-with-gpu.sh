#!/bin/bash
# Wrapper: use ./up.sh in project root instead.
cd "$(dirname "$0")/.."
exec ./up.sh "$@"
