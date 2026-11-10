#!/usr/bin/env bash
# Entry point for the CI key (GitHub Actions): the only thing this key can run on the server.
#
# Install (once, as root; the file lives outside the app directory so the CI key cannot change it):
#   sudo install -o root -g root -m 755 /opt/ref-clips/deploy/ci-entry.sh /usr/local/bin/ref-clips-ci-entry
# and a forced command in ~ubuntu/.ssh/authorized_keys (see docs/ci-cd.md):
#   command="/usr/local/bin/ref-clips-ci-entry",restrict ssh-ed25519 AAAA... ref-clips-ci
# After changing this file in the repository, reinstall it by hand (after reviewing the changes).
#
# Accepts ONLY (SSH_ORIGINAL_COMMAND, strict patterns, no eval, no arguments passed on):
#   deploy vX.Y.Z   deploys that version of the image ghcr.io/fkula5/ref-clips:vX.Y.Z
#   status          prints the deployed version and the state of the services
#
# deploy, in order (nothing on the server changes until the "busy -> idle" point):
#   1. flock (.deploy.lock, the same as in deploy.sh) for the whole run,
#   2. download the version's files over HTTPS from the public repo (codeload.github.com) to a temp dir
#       (the server pulls by itself; the CI key has no write channel): a bad tag fails at once, not after 2
#       h of waiting,
#   3. wait until nothing is running (app/busy.py as in deploy.sh; limit 120 min, then exit 3),
#   4. docker pull, then re-check busy right before the change,
#   5. replace compose.yaml, compose.prod.yaml and deploy/ (previous ones copied to .rollback/), write
#       REFCLIPS_IMAGE to .env (atomically, one line; .env is never printed),
#   6. docker compose up -d --no-build --remove-orphans --wait; restart Caddy only if the Caddyfile
#       changed,
#   7. check /health through Caddy; if the new version does not come up, restore the previous files and
#       image,
#   8. record the version in .deploy-commit, remove old ref-clips images (keeps the 3 newest plus the
#       current and previous).
#
# Exit codes: 0 ok; 1 error (nothing changed, or changes undone before the start); 2 command not
# allowed;
#   3 something kept running for the whole limit (nothing changed); 4 the new version did not come up,
#       the previous one was restored;
#   5 the new version did not come up and the rollback failed: manual intervention needed.
#
# The REFCLIPS_CI_* variables are for local tests only (an ssh client cannot set them: `restrict`).
set -euo pipefail

export PATH="${REFCLIPS_CI_PATH_PREFIX:+$REFCLIPS_CI_PATH_PREFIX:}/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset REFCLIPS_IMAGE COMPOSE_FILE COMPOSE_PROJECT_NAME DOCKER_HOST

DIR="${REFCLIPS_CI_DIR:-/opt/ref-clips}"
REPO="fkula5/ref-clips"
IMAGE_REPO="ghcr.io/${REPO}"
WAIT_SECONDS="${REFCLIPS_CI_WAIT_SECONDS:-7200}"
WAIT_INTERVAL="${REFCLIPS_CI_WAIT_INTERVAL:-60}"
HEALTH_TRIES="${REFCLIPS_CI_HEALTH_TRIES:-30}"
HEALTH_SLEEP="${REFCLIPS_CI_HEALTH_SLEEP:-5}"
KEEP_IMAGES=3

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
err() { printf '[%s] BŁĄD: %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
audit() { command -v logger >/dev/null 2>&1 && logger -t ref-clips-ci -- "$*" || true; }
die() { err "$*"; audit "błąd: $*"; exit 1; }

cmd="${SSH_ORIGINAL_COMMAND:-}"
TAG=""
if [ "${#cmd}" -le 40 ] && [[ "$cmd" != *$'\n'* ]] && [[ "$cmd" == "status" ]]; then
  ACTION=status
elif [ "${#cmd}" -le 40 ] && [[ "$cmd" != *$'\n'* ]] && [[ "$cmd" =~ ^deploy\ (v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4})$ ]]; then
  ACTION=deploy
  TAG="${BASH_REMATCH[1]}"
else
  printf 'Niedozwolone polecenie: %q\nDozwolone: "deploy vX.Y.Z" oraz "status".\n' "${cmd:0:40}" >&2
  audit "odrzucone polecenie: $(printf '%q' "${cmd:0:40}")"
  exit 2
fi

DOCKER=(docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n docker)
dc() { (cd "$DIR" && "${DOCKER[@]}" compose -f compose.yaml -f compose.prod.yaml "$@"); }

if [ "$ACTION" = status ]; then
  if [ -f "$DIR/.deploy-commit" ]; then
    read -r version stamp _ < "$DIR/.deploy-commit" || true
    echo "Wdrożona wersja: ${version:-nieznana} (${stamp:-brak daty})"
  else
    echo "Wdrożona wersja: nieznana (brak .deploy-commit)"
  fi
  dc ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
  exit 0
fi

[ -d "$DIR" ] || die "brak katalogu $DIR na serwerze"
cd "$DIR"
exec 9>.deploy.lock
flock -n 9 || die "inne wdrożenie trwa (blokada $DIR/.deploy.lock)"
audit "wdrożenie $TAG: start"

IMAGE="${IMAGE_REPO}:${TAG}"
STAGE=""
cleanup() { [ -z "$STAGE" ] || rm -rf "$STAGE"; }
trap cleanup EXIT

was_running=0
if [ -f compose.yaml ] && [ -f .env ]; then
  services="$(dc ps --status running --services 2>/dev/null || true)"
  ! grep -qx app <<<"$services" || was_running=1
fi
prev_line=""
if [ -f .env ]; then prev_line="$(grep -E '^REFCLIPS_IMAGE=' .env | tail -n1 || true)"; fi
prev_tag="${prev_line#REFCLIPS_IMAGE=}"; prev_tag="${prev_tag##*:}"

# Writes (or removes, when $1 is empty) the REFCLIPS_IMAGE line in .env: new file alongside, then
# rename; the rest of .env unchanged.
set_env_line() {
  local line="$1" tmp
  [ -f .env ] || die "brak pliku .env w $DIR — patrz docs/wdrozenie.md"
  tmp="$(mktemp .env.XXXXXX)"
  chmod --reference=.env "$tmp"
  { grep -v '^REFCLIPS_IMAGE=' .env || true; } > "$tmp"
  [ -z "$line" ] || printf '%s\n' "$line" >> "$tmp"
  mv -f "$tmp" .env
}

# 0 = idle (or the stack is not running), 1 = busy, 2 = check failed. Like check_busy in deploy.sh, but
# local.
check_busy() {
  local running out rc=0
  [ -f compose.yaml ] && [ -f .env ] || { log "Stos jeszcze nie był uruchamiany — nic nie trwa."; return 0; }
  running="$(dc ps --status running --services 2>&1)" \
    || { err "docker compose ps nie działa: $running"; return 2; }
  printf '%s\n' "$running" | grep -qx app || { log "Kontener app nie działa — nic nie trwa."; return 0; }
  out="$(dc exec -T app python - < "$STAGE/app/busy.py" 2>&1)" || rc=$?
  printf '%s\n' "$out" | sed 's/^/    /'
  if [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '^ZAJĘTE'; then return 1; fi
  [ "$rc" -eq 0 ] && return 0
  return 2
}

DEADLINE=$(( $(date +%s) + WAIT_SECONDS ))
wait_until_free() {
  local status
  while true; do
    status=0; check_busy || status=$?
    case "$status" in
      0) return 0 ;;
      1)
        if [ "$(date +%s)" -ge "$DEADLINE" ]; then
          err "Przez $(( WAIT_SECONDS / 60 )) min na serwerze trwało zadanie (patrz wyżej). Wdrożenie $TAG NIE zostało wykonane, nic nie zmieniono."
          err "Ponów później: GitHub → Actions → Wydanie → Run workflow, tag $TAG."
          audit "wdrożenie $TAG: przekroczono limit czekania"
          exit 3
        fi
        log "Czekam ${WAIT_INTERVAL} s i sprawdzam ponownie (limit łącznie $(( WAIT_SECONDS / 60 )) min)..."
        sleep "$WAIT_INTERVAL" ;;
      *) die "nie udało się sprawdzić, czy coś trwa (patrz wyżej) — wdrożenie wstrzymane, nic nie zmieniono" ;;
    esac
  done
}

STAGE="$(mktemp -d "$DIR/.ci-incoming.XXXXXX")"
log "Pobieram pliki wersji $TAG z GitHuba..."
curl -fsSL --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 2 --max-time 180 \
  -o "$STAGE/src.tar.gz" "https://codeload.github.com/${REPO}/tar.gz/refs/tags/${TAG}" \
  || die "nie udało się pobrać $TAG z GitHuba (czy tag istnieje i repozytorium jest publiczne?)"
tar -xzf "$STAGE/src.tar.gz" -C "$STAGE" --strip-components=1 --no-same-owner --no-same-permissions \
  || die "archiwum $TAG jest uszkodzone"
rm -f "$STAGE/src.tar.gz"
for f in compose.yaml compose.prod.yaml deploy/Caddyfile deploy/backup.sh app/busy.py; do
  [ -f "$STAGE/$f" ] && [ ! -L "$STAGE/$f" ] || die "w archiwum $TAG brak pliku $f"
done
[ -z "$(find "$STAGE/deploy" -type l)" ] || die "katalog deploy/ w $TAG zawiera dowiązania symboliczne — odmawiam"

log "Sprawdzam, czy na serwerze coś trwa (limit czekania $(( WAIT_SECONDS / 60 )) min)..."
wait_until_free

# The pull may have taken a while: check busy again right before the change.
log "Pobieram obraz $IMAGE..."
"${DOCKER[@]}" pull --quiet "$IMAGE" >/dev/null \
  || die "nie udało się pobrać obrazu $IMAGE (czy build się udał, a pakiet GHCR jest publiczny? docs/ci-cd.md)"
log "Ostatnie sprawdzenie zajętości tuż przed restartem..."
wait_until_free

install_tree() {
  local src="$1" f
  for f in compose.yaml compose.prod.yaml; do
    cp "$src/$f" ".$f.new" && mv -f ".$f.new" "$f"
  done
  rm -rf .deploy.new .deploy.old
  cp -a "$src/deploy" .deploy.new
  [ ! -d deploy ] || mv deploy .deploy.old
  mv .deploy.new deploy
  rm -rf .deploy.old
}
rm -rf .rollback && mkdir .rollback
cp -a compose.yaml compose.prod.yaml deploy .rollback/ 2>/dev/null || true
log "Podmieniam compose.yaml, compose.prod.yaml i deploy/ (kopia poprzednich: $DIR/.rollback)."
install_tree "$STAGE"
set_env_line "REFCLIPS_IMAGE=$IMAGE"

caddy_refresh() {  # The Caddyfile is mounted as a single file: after a change Caddy must be restarted (as in deploy.sh).
  local services current
  services="$(dc ps --status running --services 2>/dev/null || true)"
  grep -qx caddy <<<"$services" || return 0
  current="$(dc exec -T caddy cat /etc/caddy/Caddyfile 2>/dev/null || true)"
  if [ "$current" != "$(cat deploy/Caddyfile)" ]; then
    log "Caddyfile się zmienił, restart Caddy."
    dc restart caddy
  fi
}

HEALTH_BODY=""
health_ok() {  # 0 = /health returns 200; the body of the last response is in HEALTH_BODY
  local site code body
  site="$(sed -n 's/^REFCLIPS_SITE=//p' .env | tail -n1 | tr -d "\"' \r")"
  [ -n "$site" ] || { HEALTH_BODY="brak REFCLIPS_SITE w .env"; return 1; }
  body="$STAGE/health.json"
  code="$(curl -sS --max-time 10 -o "$body" -w '%{http_code}' --resolve "${site}:443:127.0.0.1" "https://${site}/health" 2>&1)" || true
  HEALTH_BODY="$(head -c 300 "$body" 2>/dev/null || true)"
  [ "$code" = 200 ]
}

rollback() {
  err "Wracam do poprzedniej wersji (${prev_tag:-ref-clips:local})."
  [ -d .rollback ] || { err "brak katalogu .rollback — nie ma do czego wracać"; return 1; }
  install_tree "$DIR/.rollback" || return 1
  set_env_line "$prev_line" || return 1
  if [ "$was_running" != 1 ]; then
    err "Stos nie działał przed wdrożeniem, więc nie uruchamiam go ponownie (pliki i .env przywrócone)."
    return 1
  fi
  dc up -d --no-build --remove-orphans --wait --wait-timeout 300 || return 1
  caddy_refresh || true
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do health_ok && { log "Poprzednia wersja działa (/health 200)."; return 0; }; sleep "$HEALTH_SLEEP"; done
  err "po powrocie /health nie odpowiada 200: $HEALTH_BODY"
  return 1
}

fail_and_rollback() {
  err "$1"
  err "--- logi usług (ostatnie linie):"
  dc logs --tail 30 app worker init 2>&1 | sed 's/^/    /' >&2 || true
  audit "wdrożenie $TAG: niepowodzenie ($1), powrót"
  if rollback; then
    err "Wdrożenie $TAG NIE powiodło się; serwer działa na poprzedniej wersji. Migracje bazy z $TAG zostają (patrz docs/ci-cd.md)."
    exit 4
  fi
  err "Wdrożenie $TAG NIE powiodło się, a powrót do poprzedniej wersji też. Zaloguj się na serwer i sprawdź: cd $DIR && docker compose -f compose.yaml -f compose.prod.yaml ps"
  exit 5
}

log "Uruchamiam $TAG (docker compose up --wait)..."
if ! dc up -d --no-build --remove-orphans --wait --wait-timeout 300; then
  fail_and_rollback "docker compose up nie zakończył się powodzeniem"
fi
caddy_refresh || fail_and_rollback "restart Caddy nie powiódł się"

# Missing disk space alone is not the new version's fault and does not justify a rollback.
log "Sprawdzam /health (do $(( HEALTH_TRIES * HEALTH_SLEEP )) s)..."
healthy=0
for _ in $(seq 1 "$HEALTH_TRIES"); do
  if health_ok; then healthy=1; break; fi
  sleep "$HEALTH_SLEEP"
done
if [ "$healthy" != 1 ]; then
  if printf '%s' "$HEALTH_BODY" | grep -q '"db":"ok"' && printf '%s' "$HEALTH_BODY" | grep -q '"worker":"ok"'; then
    err "UWAGA: /health nie zwraca 200, ale baza i worker działają (odpowiedź: $HEALTH_BODY) — to nie wina wersji, zostaję przy $TAG."
  else
    fail_and_rollback "/health nie zwraca 200 po starcie (odpowiedź: ${HEALTH_BODY:-brak})"
  fi
fi

printf '%s %s\n' "$TAG" "$(date -u +%FT%TZ)" > .deploy-commit.new && mv -f .deploy-commit.new .deploy-commit
rm -rf .rollback

log "Sprzątanie starych obrazów ${IMAGE_REPO} (zostają ${KEEP_IMAGES} najnowsze, bieżący i poprzedni)..."
kept=0
while read -r tag; do
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
  kept=$(( kept + 1 ))
  if [ "$kept" -le "$KEEP_IMAGES" ] || [ "$tag" = "$TAG" ] || [ "$tag" = "$prev_tag" ]; then continue; fi
  "${DOCKER[@]}" image rm "${IMAGE_REPO}:${tag}" >/dev/null 2>&1 && log "  usunięto ${IMAGE_REPO}:${tag}" || true
done < <("${DOCKER[@]}" image ls "$IMAGE_REPO" --format '{{.Tag}}')

if [ -f deploy/ci-entry.sh ] && ! cmp -s deploy/ci-entry.sh /usr/local/bin/ref-clips-ci-entry; then
  log "Uwaga: deploy/ci-entry.sh w tej wersji różni się od zainstalowanego /usr/local/bin/ref-clips-ci-entry — przejrzyj i zainstaluj ręcznie (docs/ci-cd.md)."
fi
dc ps
audit "wdrożenie $TAG: ok"
log "Gotowe: wdrożono $TAG."
