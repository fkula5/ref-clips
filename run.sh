#!/usr/bin/env bash
# Starts the web server (http://localhost:8000) and the background job worker. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Brak .venv — utwórz: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if ! command -v "${FFMPEG_PATH:-ffmpeg}" >/dev/null 2>&1; then
  echo "UWAGA: brak ffmpeg — uruchom: sudo apt install ffmpeg (aplikacja wystartuje, ale zadania będą czekać)" >&2
fi

PY=.venv/bin/python
$PY -m app.initdb

$PY -m app.worker &
WORKER_PID=$!
trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT INT TERM

# --host 0.0.0.0 so a browser on Windows can reach WSL at localhost:8000
$PY -m uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
