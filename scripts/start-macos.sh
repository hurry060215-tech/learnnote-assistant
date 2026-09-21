#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${LEARNNOTE_PYTHON:-python3}"
PORT="${LEARNNOTE_PORT:-8765}"
VENV_DIR="${LEARNNOTE_VENV_DIR:-${ROOT}/.venv}"
DATA_DIR="${LEARNNOTE_DATA_DIR:-${HOME}/Library/Application Support/LearnNote}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT}/backend/requirements.txt"
export PYTHONPATH="${ROOT}:${ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"
export LEARNNOTE_DATA_DIR="${DATA_DIR}"
export LEARNNOTE_BACKEND_ORIGIN="http://127.0.0.1:${PORT}"
mkdir -p "${LEARNNOTE_DATA_DIR}/logs"

URL="http://127.0.0.1:${PORT}"
OUT_LOG="${LEARNNOTE_DATA_DIR}/logs/backend-${PORT}.out.log"
ERR_LOG="${LEARNNOTE_DATA_DIR}/logs/backend-${PORT}.err.log"

"${VENV_DIR}/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" >"${OUT_LOG}" 2>"${ERR_LOG}" &
BACKEND_PID=$!

cleanup() {
  if kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

deadline=$((SECONDS + 120))
until curl --fail --silent --show-error "${URL}/health" >/dev/null 2>&1; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "LearnNote backend stopped before becoming ready. Check ${ERR_LOG}." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "LearnNote backend did not become ready within 120 seconds. Check ${ERR_LOG}." >&2
    exit 1
  fi
  sleep 1
done

open "${URL}"
echo "LearnNote browser workspace: ${URL}"
echo "Backend logs: ${OUT_LOG}"
echo "              ${ERR_LOG}"
echo "Keep this Terminal window open. Press Ctrl+C to stop LearnNote."
wait "${BACKEND_PID}"
