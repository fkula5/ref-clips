#!/usr/bin/env bash
# Browser UI tests (Playwright + Chromium) against a real server and worker.
# Usage: scripts/e2e.sh [pytest args, e.g. -k upload]   (E2E_KEEP=1 keeps the data directory)
# On failure screenshots, the console log and server logs go to /tmp/refclips-e2e-artifacts/.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Brak .venv — utwórz: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi
if ! "$PY" -c "import playwright" 2>/dev/null; then
  echo "Brak playwright — uruchom: .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi
for tool in ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Brak $tool — uruchom: sudo apt install ffmpeg" >&2; exit 1; }
done
if ! "$PY" - <<'PYEOF' 2>/dev/null
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    assert os.path.exists(p.chromium.executable_path)
PYEOF
then
  echo "Brak przeglądarki Chromium — uruchom: .venv/bin/playwright install chromium" >&2
  exit 1
fi

exec "$PY" -m pytest -m e2e "$@"
