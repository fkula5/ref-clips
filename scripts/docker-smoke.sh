#!/usr/bin/env bash
# Test dymny wdrożenia w Dockerze: buduje obraz, startuje osobny projekt Compose (inny port,
# osobny wolumin), zakłada admina, loguje się, wgrywa małe wideo (tus), czeka na konwersję
# przez workera, sprawdza restart i na końcu usuwa wszystko (down -v + obraz testowy).
# Użycie: scripts/docker-smoke.sh   (opcjonalnie SMOKE_PORT=8123)
set -euo pipefail
cd "$(dirname "$0")/.."

export REFCLIPS_PORT="${SMOKE_PORT:-8123}"
export REFCLIPS_IMAGE="ref-clips-smoke:test"
export COMPOSE_PROJECT_NAME="ref-clips-smoke"
EMAIL="smoke@example.com"
PASSWORD="smoke-test-password-123"
URL="http://localhost:${REFCLIPS_PORT}"
DC="docker compose"
COOKIES="$(mktemp)"
TMPVIDEO="$(mktemp -d)"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- BŁĄD (kod $status); logi: ---" >&2
    $DC logs --tail 40 >&2 || true
  fi
  $DC down -v --remove-orphans >/dev/null 2>&1 || true
  docker rmi "$REFCLIPS_IMAGE" >/dev/null 2>&1 || true
  rm -rf "$COOKIES" "$TMPVIDEO"
  exit "$status"
}
trap cleanup EXIT

step() { echo "==> $*"; }

step "Budowanie obrazu i start (pusty wolumin)"
$DC up -d --build --wait --wait-timeout 180

step "ffmpeg w kontenerze"
$DC exec -T app ffmpeg -version | head -1
$DC exec -T app sh -c 'test "$(id -u)" != 0 && echo "użytkownik bez roota: $(id -un)"'

step "Worker działa"
$DC ps --status running --services | grep -qx worker
$DC logs worker | grep -q "Worker uruchomiony"

step "Strona logowania bez sesji"
test "$(curl -s -o /dev/null -w '%{http_code}' "$URL/login")" = 200
test "$(curl -s -o /dev/null -w '%{http_code}' "$URL/")" = 303   # przekierowanie na logowanie

step "Założenie administratora (z argumentami)"
$DC run --rm -T app python -m app.create_admin --email "$EMAIL" --name "Smoke Test" --password "$PASSWORD"

step "Logowanie curl-em (z CSRF) i strona główna"
CSRF="$(curl -s -c "$COOKIES" "$URL/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)"
test -n "$CSRF"
test "$(curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" -c "$COOKIES" \
  --data-urlencode "email=$EMAIL" --data-urlencode "password=$PASSWORD" \
  --data-urlencode "csrf_token=$CSRF" "$URL/login")" = 303
test "$(curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" "$URL/")" = 200

step "Wgranie wideo (tus) i konwersja przez workera"
$DC exec -T app ffmpeg -loglevel error -f lavfi -i testsrc=duration=5:size=640x360:rate=25 \
  -f lavfi -i sine=frequency=440:duration=5 -c:v libx264 -c:a aac -shortest -y /tmp/smoke.mp4
$DC exec -T app python - "$EMAIL" "$PASSWORD" /tmp/smoke.mp4 < scripts/docker_smoke_upload.py

step "Restart kontenerów — dane zostają"
$DC restart app worker
$DC up -d --wait --wait-timeout 120
CSRF="$(curl -s -c "$COOKIES" "$URL/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)"
test "$(curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" -c "$COOKIES" \
  --data-urlencode "email=$EMAIL" --data-urlencode "password=$PASSWORD" \
  --data-urlencode "csrf_token=$CSRF" "$URL/login")" = 303
curl -s -b "$COOKIES" "$URL/" | grep -q "A – B"

echo "==> SMOKE TEST: OK"
