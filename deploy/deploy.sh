#!/usr/bin/env bash
# Deploys ref-clips to the server; run LOCALLY from the repository.
# Sends the current commit (git archive HEAD, not the working directory) over ssh without touching .env
# or data (data lives in Docker volumes), builds the images, starts the stack (docker compose -f
# compose.yaml -f compose.prod.yaml up -d --build), waits for the app to be healthy and shows the
# status. Idempotent. Never prints .env.
#
# Before changing anything on the server it checks for an upload (activity in the last 10 min), a
# conversion/cut or queued jobs (python -m app.busy in the running container). If something is running
# it exits WITHOUT replacing files or restarting (exit code 3); --force skips the check, --wait waits.
#
# This is the emergency path (image built on the server). Normal deploys come from GitHub Actions with a
# ready GHCR image (deploy/ci-entry.sh, docs/ci-cd.md). If the last of those wrote a GHCR tag to .env
# (REFCLIPS_IMAGE), this script forces REFCLIPS_IMAGE=ref-clips:local for the deploy and writes it to
# .env (right before the restart), so the locally built image does not pose as a GHCR tag and
# deploy/backup.sh uses the same image as the running stack.
#
# Usage:   deploy/deploy.sh [-H user@host] [-i ssh_key] [-d server_dir] [--force] [--wait]
#          --force   deploy despite a running upload/conversion (interrupts it; a conversion restarts
#              from zero)
#          --wait    wait until idle (checked every minute), then deploy
# Variables: REFCLIPS_DEPLOY_HOST  (default ubuntu@57.131.162.204)
#            REFCLIPS_DEPLOY_KEY   (default ~/.ssh/ref_clips_deploy)
#            REFCLIPS_DEPLOY_DIR   (default /opt/ref-clips)
#            REFCLIPS_DEPLOY_URL   (address for the final check; default: REFCLIPS_PUBLIC_URL from the
#                server's .env, empty = skip)
#            REFCLIPS_DEPLOY_CURL_OPTS     extra curl options for the final check (e.g. -k for a test
#                with a local certificate)
#            REFCLIPS_DEPLOY_FORCE=1       same as --force
#            REFCLIPS_DEPLOY_WAIT_MINUTES  wait limit for --wait (default 120)
#            REFCLIPS_DEPLOY_WAIT_INTERVAL seconds between checks for --wait (default 60)
set -euo pipefail

HOST="${REFCLIPS_DEPLOY_HOST:-ubuntu@57.131.162.204}"
KEY="${REFCLIPS_DEPLOY_KEY:-$HOME/.ssh/ref_clips_deploy}"
DIR="${REFCLIPS_DEPLOY_DIR:-/opt/ref-clips}"
URL_FROM_ENV=1; [ -z "${REFCLIPS_DEPLOY_URL+x}" ] || URL_FROM_ENV=0
URL="${REFCLIPS_DEPLOY_URL-}"
FORCE=0; [ "${REFCLIPS_DEPLOY_FORCE:-}" = 1 ] && FORCE=1
WAIT=0
CURL_OPTS=(); [ -z "${REFCLIPS_DEPLOY_CURL_OPTS:-}" ] || read -r -a CURL_OPTS <<<"$REFCLIPS_DEPLOY_CURL_OPTS"
WAIT_MINUTES="${REFCLIPS_DEPLOY_WAIT_MINUTES:-120}"
WAIT_INTERVAL="${REFCLIPS_DEPLOY_WAIT_INTERVAL:-60}"

usage() { sed -n '2,/^set -/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "BŁĄD: $*" >&2; exit 1; }

# Long options (--force, --wait, --help) are removed before getopts, which knows only short ones.
args=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --wait) WAIT=1 ;;
    --help) args+=(-h) ;;
    *) args+=("$arg") ;;
  esac
done
set -- ${args[@]+"${args[@]}"}

while getopts "H:i:d:h" opt; do
  case "$opt" in
    H) HOST="$OPTARG" ;;
    i) KEY="$OPTARG" ;;
    d) DIR="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "to nie jest repozytorium git"
[ -f "$KEY" ] || die "brak klucza ssh: $KEY (ustaw REFCLIPS_DEPLOY_KEY albo użyj -i)"
case "$DIR" in /*) ;; *) die "katalog na serwerze musi być ścieżką bezwzględną: $DIR" ;; esac
# The upload wipes the target directory (except .env), so system directories and ones that are too
# shallow are refused.
case "${DIR%/}" in ""|/*/*) ;; *) die "katalog na serwerze musi mieć co najmniej dwa poziomy (np. /opt/ref-clips): $DIR" ;; esac
[ -n "${DIR%/}" ] || die "katalog na serwerze nie może być /"

# The commit is what gets deployed, so uncommitted changes would not be included: refuse, to avoid
# surprises.
if ! git diff-index --quiet HEAD --; then
  git status --short --untracked-files=no >&2
  die "są niezacommitowane zmiany w śledzonych plikach — zacommituj je albo schowaj (git stash)"
fi
untracked="$(git ls-files --others --exclude-standard | wc -l)"
[ "$untracked" -eq 0 ] || echo "Uwaga: $untracked nieśledzonych plików nie zostanie wysłanych (git archive bierze tylko commit)." >&2

COMMIT="$(git rev-parse --short=12 HEAD)"
SUBJECT="$(git log -1 --format=%s HEAD)"
echo "==> Wdrażam $COMMIT ($SUBJECT) na $HOST:$DIR"

SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new
     -o ConnectTimeout=15 -o ServerAliveInterval=30 "$HOST")
QDIR="$(printf '%q' "$DIR")"

# The busy check happens BEFORE replacing files, so after an abort the server directory matches the
# running version. It is app.busy from the deployed commit, piped into `python -` of the running
# container (works on images that predate the module).
BUSY_B64="$(git show HEAD:app/busy.py | base64 | tr -d '\n')"

# Returns 0 = idle (or the stack is not running), 1 = busy, 2 = check failed.
check_busy() {
  local out rc=0
  out="$("${SSH[@]}" "bash -s -- $QDIR $BUSY_B64" 2>&1 <<'CHECK'
cd "$1" 2>/dev/null || { echo "Brak katalogu na serwerze — pierwsze wdrożenie, nic nie trwa."; exit 0; }
[ -f compose.yaml ] && [ -f .env ] || { echo "Stos jeszcze nie był uruchamiany — nic nie trwa."; exit 0; }
DOCKER=(docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n docker)
export COMPOSE_FILE=compose.yaml:compose.prod.yaml
running="$("${DOCKER[@]}" compose ps --status running --services 2>&1)" \
  || { echo "BŁĄD: docker compose ps nie działa: $running"; exit 2; }
printf '%s\n' "$running" | grep -qx app || { echo "Kontener app nie działa — nic nie trwa."; exit 0; }
printf '%s' "$2" | base64 -d | "${DOCKER[@]}" compose exec -T app python -
CHECK
  )" || rc=$?
  printf '%s\n' "$out" | sed 's/^/    /'
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '^ZAJĘTE'; then return 1; fi
  [ "$rc" -eq 0 ] && return 0
  return 2
}

echo "==> Sprawdzanie, czy coś trwa na serwerze"
deadline=$(( $(date +%s) + WAIT_MINUTES * 60 ))
while true; do
  status=0; check_busy || status=$?
  case "$status" in
    0) break ;;
    1)
      if [ "$FORCE" = 1 ]; then
        echo "UWAGA: --force — wdrażam mimo trwających zadań (zostaną przerwane)." >&2
        break
      elif [ "$WAIT" = 1 ] && [ "$(date +%s)" -lt "$deadline" ]; then
        echo "    Czekam ${WAIT_INTERVAL} s i sprawdzam ponownie (limit: ${WAIT_MINUTES} min)..."
        sleep "$WAIT_INTERVAL"
      else
        [ "$WAIT" = 1 ] && echo "Przekroczono limit czekania (${WAIT_MINUTES} min)." >&2
        echo "Wdrożenie wstrzymane: na serwerze coś trwa. Nic nie zostało zmienione." >&2
        echo "Spróbuj później, użyj --wait (poczeka na koniec) albo --force (przerwie zadania)." >&2
        exit 3
      fi ;;
    *)
      if [ "$FORCE" = 1 ]; then
        echo "UWAGA: nie udało się sprawdzić zajętości, ale --force — wdrażam." >&2
        break
      fi
      die "nie udało się sprawdzić, czy coś trwa na serwerze (patrz wyżej); --force pomija sprawdzenie" ;;
  esac
done

echo "==> Wysyłanie plików (git archive)"
# Unpack to .incoming, then swap: old files go (also those deleted in the repo), but .env and technical
# deploy files stay. App data is in volumes, not here.
git archive --format=tar HEAD | "${SSH[@]}" "set -e
  cd $QDIR || { echo 'Brak katalogu $DIR na serwerze — patrz docs/wdrozenie.md' >&2; exit 1; }
  exec 9>.deploy.lock
  flock -n 9 || { echo 'BŁĄD: inne wdrożenie trwa (blokada .deploy.lock)' >&2; exit 1; }
  rm -rf .incoming && mkdir .incoming
  tar -x -C .incoming
  find . -mindepth 1 -maxdepth 1 ! -name .env ! -name .incoming ! -name .deploy.lock -exec rm -rf {} +
  find .incoming -mindepth 1 -maxdepth 1 -exec mv {} . \;
  rmdir .incoming
  printf '%s %s\\n' $COMMIT \"\$(date -u +%FT%TZ)\" > .deploy-commit"

echo "==> Budowanie i uruchamianie na serwerze"
"${SSH[@]}" "bash -s -- $QDIR $FORCE" <<'REMOTE'
set -euo pipefail
cd "$1"
exec 9>.deploy.lock
flock -n 9 || { echo "BŁĄD: inne wdrożenie trwa (blokada .deploy.lock)" >&2; exit 1; }

[ -f .env ] || { echo "BŁĄD: brak pliku .env w $1 — skopiuj deploy/env.prod.example do .env (docs/wdrozenie.md)" >&2; exit 1; }
for key in REFCLIPS_SITE REFCLIPS_COOKIE_SECURE REFCLIPS_TRUST_PROXY REFCLIPS_PUBLIC_URL; do
  grep -Eq "^${key}=." .env || { echo "BŁĄD: w .env brakuje ustawienia $key" >&2; exit 1; }
done

# The image built here is ref-clips:local regardless of REFCLIPS_IMAGE in .env (it may point to GHCR).
# The variable goes through `env` because sudo clears the environment.
DOCKER=(env REFCLIPS_IMAGE=ref-clips:local docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n env REFCLIPS_IMAGE=ref-clips:local docker)
export COMPOSE_FILE=compose.yaml:compose.prod.yaml

"${DOCKER[@]}" compose build

# A build takes minutes and someone may have started an upload meanwhile: final check right before the
# restart.
if [ "$2" != 1 ] && "${DOCKER[@]}" compose ps --status running --services | grep -qx app; then
  rc=0; out="$("${DOCKER[@]}" compose exec -T app python - < app/busy.py 2>&1)" || rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$out" | sed 's/^/    /' >&2
    echo "Pliki są już na serwerze i obrazy zbudowane, ale stos NIE został zrestartowany (działa poprzednia wersja)." >&2
    echo "Uruchom deploy/deploy.sh ponownie, gdy będzie wolne (albo z --force)." >&2
    exit 3
  fi
fi

# Only now (after the last busy check) is the local image written to .env: new file alongside, then
# rename; the rest of .env unchanged. So backup.sh and later `docker compose` use what is running.
env_tmp="$(mktemp .env.XXXXXX)"
chmod --reference=.env "$env_tmp"
{ grep -v '^REFCLIPS_IMAGE=' .env || true; echo 'REFCLIPS_IMAGE=ref-clips:local'; } > "$env_tmp"
mv -f "$env_tmp" .env

"${DOCKER[@]}" compose up -d --remove-orphans --wait --wait-timeout 300
# The Caddyfile is mounted as a single file and the upload recreates it: the running Caddy still sees
# the old content and compose does not recreate it. After a config change it must be restarted.
if ! "${DOCKER[@]}" compose exec -T caddy cat /etc/caddy/Caddyfile | cmp -s - deploy/Caddyfile; then
  echo "--- Caddyfile się zmienił, restart Caddy:"
  "${DOCKER[@]}" compose restart caddy
fi
echo "--- status:"
"${DOCKER[@]}" compose ps
echo "--- sprzątanie nieużywanych obrazów:"
"${DOCKER[@]}" image prune -f
echo "--- wdrożony commit: $(cut -d' ' -f1 .deploy-commit)"
REMOTE

if [ "$URL_FROM_ENV" = 1 ]; then
  URL="$("${SSH[@]}" "sed -n 's/^REFCLIPS_PUBLIC_URL=//p' $QDIR/.env | tail -n1" 2>/dev/null | tr -d "\"' \r" || true)"
  URL="${URL%/}"
  [ -n "$URL" ] || echo "UWAGA: nie udało się odczytać REFCLIPS_PUBLIC_URL z .env na serwerze — pomijam sprawdzenie adresu." >&2
fi
if [ -n "$URL" ]; then
  echo "==> Sprawdzanie $URL/login"
  code=000
  for _ in $(seq 1 20); do
    code="$(curl -sS ${CURL_OPTS[@]+"${CURL_OPTS[@]}"} -o /dev/null -w '%{http_code}' --max-time 10 "$URL/login" 2>/dev/null || true)"
    [ "$code" = 200 ] && break
    sleep 3  # first start: Caddy is still obtaining the certificate
  done
  [ "$code" = 200 ] || die "$URL/login odpowiada kodem $code (logi: ssh ... docker compose logs caddy app)"
  # /health: DB, worker (the heartbeat renews every 30 s, so after a restart it may take a moment) and
  # disk.
  echo "==> Sprawdzanie $URL/health"
  code=000
  for _ in $(seq 1 15); do
    code="$(curl -sS ${CURL_OPTS[@]+"${CURL_OPTS[@]}"} -o /dev/null -w '%{http_code}' --max-time 10 "$URL/health" 2>/dev/null || true)"
    [ "$code" = 200 ] && break
    sleep 4
  done
  if [ "$code" = 200 ]; then echo "    ok"; else
    echo "UWAGA: $URL/health odpowiada kodem $code — sprawdź: curl -s $URL/health (które sprawdzenie nie przechodzi)" >&2
  fi
fi
echo "==> Gotowe: $COMMIT"
