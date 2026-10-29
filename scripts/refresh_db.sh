#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "No se encuentra el Python del entorno virtual: ${PYTHON_BIN}" >&2
  echo "Crea el entorno con: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" -m running_dashboard.ingest
