#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$PROJECT_ROOT/../gonzarun_dashboard_app.zip}"

rm -f "$OUTPUT"
cd "$PROJECT_ROOT"
zip -r "$OUTPUT" \
  app.py \
  requirements.txt \
  README.md \
  .env.example \
  .streamlit/config.toml \
  running_dashboard \
  scripts/refresh_db.sh \
  launchers \
  -x '*/__pycache__/*' '*.pyc'

printf 'Paquete creado: %s\n' "$OUTPUT"
