#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${LEARNNOTE_PYTHON:-python3}"
PORT="${LEARNNOTE_PORT:-8765}"
VENV_DIR="${LEARNNOTE_VENV_DIR:-${ROOT}/.venv}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT}/backend/requirements.desktop.txt"
export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"
export LEARNNOTE_DATA_DIR="${LEARNNOTE_DATA_DIR:-${HOME}/Library/Application Support/LearnNote}"
exec "${VENV_DIR}/bin/python" "${ROOT}/desktop/main.py" --port "${PORT}" "$@"
