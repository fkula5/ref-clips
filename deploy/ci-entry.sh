#!/usr/bin/env bash
# Wejście dla klucza CI (GitHub Actions) — jedyna rzecz, którą ten klucz może uruchomić na serwerze.
#
# Instalacja (raz, root; plik poza katalogiem aplikacji, żeby klucz CI nie mógł go zmienić):
#   sudo install -o root -g root -m 755 /opt/ref-clips/deploy/ci-entry.sh /usr/local/bin/ref-clips-ci-entry
# oraz wymuszone polecenie w ~ubuntu/.ssh/authorized_keys (opis: docs/ci-cd.md):
#   command="/usr/local/bin/ref-clips-ci-entry",restrict ssh-ed25519 AAAA... ref-clips-ci
# Po zmianie tego pliku w repozytorium zainstaluj go ponownie ręcznie (po przejrzeniu zmian).
#
# Akceptuje WYŁĄCZNIE (SSH_ORIGINAL_COMMAND, ścisłe wyrażenia, bez eval, bez przekazywania argumentów dalej):
#   deploy vX.Y.Z   wdrożenie wersji z obrazu ghcr.io/fkula5/ref-clips:vX.Y.Z
#   status          wypisuje wdrożoną wersję i stan usług
#
# deploy — kolejność kroków (do chwili „zajęte → wolne” nic na serwerze się nie zmienia):
#   1. blokada flock (.deploy.lock — ta sama co w deploy.sh) na czas całości,
#   2. pobranie plików wersji po HTTPS z publicznego repo (codeload.github.com) do katalogu tymczasowego
#      (serwer pobiera sam; klucz CI nie ma kanału zapisu) — zły tag wychodzi od razu, nie po 2 h czekania,
#   3. czekanie, aż nic nie trwa (app/busy.py jak w deploy.sh; limit 120 min, potem kod 3),
#   4. pobranie obrazu (docker pull), ponowne sprawdzenie zajętości tuż przed zmianą,
#   5. podmiana compose.yaml, compose.prod.yaml i deploy/ (kopia poprzednich w .rollback/), zapis
#      REFCLIPS_IMAGE w .env (atomowo, jedna linia; .env nie jest wypisywany),
#   6. docker compose up -d --no-build --remove-orphans --wait; restart Caddy tylko po zmianie Caddyfile,
#   7. kontrola /health przez Caddy; gdy nowa wersja nie wstanie — powrót do poprzednich plików i obrazu,
#   8. zapis wersji w .deploy-commit, usunięcie starych obrazów ref-clips (zostaje 3 ostatnie + bieżący i poprzedni).
#
# Kody wyjścia: 0 ok; 1 błąd (nic nie zmienione albo zmiany cofnięte przed startem); 2 niedozwolone polecenie;
#   3 przez cały limit coś trwało (nic nie zmienione); 4 nowa wersja nie wstała, przywrócono poprzednią;
#   5 nowa wersja nie wstała i powrót się nie udał — potrzebna ręczna interwencja.
#
# Zmienne REFCLIPS_CI_* służą wyłącznie testom lokalnym (klient ssh ich nie ustawi: `restrict`).
set -euo pipefail

export PATH="${REFCLIPS_CI_PATH_PREFIX:+$REFCLIPS_CI_PATH_PREFIX:}/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset REFCLIPS_IMAGE COMPOSE_FILE COMPOSE_PROJECT_NAME DOCKER_HOST

DIR="${REFCLIPS_CI_DIR:-/opt/ref-clips}"
REPO="fkula5/ref-clips"
IMAGE_REPO="ghcr.io/${REPO}"
WAIT_SECONDS="${REFCLIPS_CI_WAIT_SECONDS:-7200}"   # limit czekania: 120 min
WAIT_INTERVAL="${REFCLIPS_CI_WAIT_INTERVAL:-60}"
HEALTH_TRIES="${REFCLIPS_CI_HEALTH_TRIES:-30}"
HEALTH_SLEEP="${REFCLIPS_CI_HEALTH_SLEEP:-5}"
KEEP_IMAGES=3

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
err() { printf '[%s] BŁĄD: %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
audit() { command -v logger >/dev/null 2>&1 && logger -t ref-clips-ci -- "$*" || true; }
die() { err "$*"; audit "błąd: $*"; exit 1; }

# --- polecenie z klienta: ścisłe dopasowanie, nic nie jest wykonywane ani rozwijane -------------------
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

# --- status -----------------------------------------------------------------------------------------
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

# --- deploy -----------------------------------------------------------------------------------------
[ -d "$DIR" ] || die "brak katalogu $DIR na serwerze"
cd "$DIR"
exec 9>.deploy.lock
flock -n 9 || die "inne wdrożenie trwa (blokada $DIR/.deploy.lock)"
audit "wdrożenie $TAG: start"

IMAGE="${IMAGE_REPO}:${TAG}"
STAGE=""
cleanup() { [ -z "$STAGE" ] || rm -rf "$STAGE"; }
trap cleanup EXIT

# Stan sprzed zmian — do powrotu.
was_running=0
if [ -f compose.yaml ] && [ -f .env ]; then
  services="$(dc ps --status running --services 2>/dev/null || true)"
  ! grep -qx app <<<"$services" || was_running=1
fi
prev_line=""
if [ -f .env ]; then prev_line="$(grep -E '^REFCLIPS_IMAGE=' .env | tail -n1 || true)"; fi
prev_tag="${prev_line#REFCLIPS_IMAGE=}"; prev_tag="${prev_tag##*:}"

# Zapis (albo usunięcie, gdy $1 puste) linii REFCLIPS_IMAGE w .env: nowy plik obok, potem rename; reszta .env bez zmian.
set_env_line() {
  local line="$1" tmp
  [ -f .env ] || die "brak pliku .env w $DIR — patrz docs/wdrozenie.md"
  tmp="$(mktemp .env.XXXXXX)"
  chmod --reference=.env "$tmp"
  { grep -v '^REFCLIPS_IMAGE=' .env || true; } > "$tmp"
  [ -z "$line" ] || printf '%s\n' "$line" >> "$tmp"
  mv -f "$tmp" .env
}

# 0 = wolne (albo stos nie działa), 1 = zajęte, 2 = nie udało się sprawdzić. Jak check_busy w deploy.sh, ale lokalnie.
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

# 2. Pliki wersji z publicznego repo.
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

# 3. Czekanie, aż będzie wolne.
log "Sprawdzam, czy na serwerze coś trwa (limit czekania $(( WAIT_SECONDS / 60 )) min)..."
wait_until_free

# 4. Obraz (przed jakąkolwiek zmianą), potem ostatnie sprawdzenie zajętości — pobieranie mogło potrwać.
log "Pobieram obraz $IMAGE..."
"${DOCKER[@]}" pull --quiet "$IMAGE" >/dev/null \
  || die "nie udało się pobrać obrazu $IMAGE (czy build się udał, a pakiet GHCR jest publiczny? docs/ci-cd.md)"
log "Ostatnie sprawdzenie zajętości tuż przed restartem..."
wait_until_free

# 5. Podmiana plików (z kopią do powrotu) i zapis obrazu w .env.
install_tree() {   # $1 = katalog źródłowy z compose.yaml, compose.prod.yaml i deploy/
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

caddy_refresh() {   # Caddyfile jest montowany jako pojedynczy plik: po zmianie trzeba zrestartować Caddy (jak w deploy.sh)
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
health_ok() {   # 0 = /health zwraca 200; treść ostatniej odpowiedzi w HEALTH_BODY
  local site code body
  site="$(sed -n 's/^REFCLIPS_SITE=//p' .env | tail -n1 | tr -d "\"' \r")"
  [ -n "$site" ] || { HEALTH_BODY="brak REFCLIPS_SITE w .env"; return 1; }
  body="$STAGE/health.json"
  code="$(curl -sS --max-time 10 -o "$body" -w '%{http_code}' --resolve "${site}:443:127.0.0.1" "https://${site}/health" 2>&1)" || true
  HEALTH_BODY="$(head -c 300 "$body" 2>/dev/null || true)"
  [ "$code" = 200 ]
}

# 7 (powrót): poprzednie pliki i poprzednia linia REFCLIPS_IMAGE.
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

fail_and_rollback() {   # $1 = powód
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

# 6. Start.
log "Uruchamiam $TAG (docker compose up --wait)..."
if ! dc up -d --no-build --remove-orphans --wait --wait-timeout 300; then
  fail_and_rollback "docker compose up nie zakończył się powodzeniem"
fi
caddy_refresh || fail_and_rollback "restart Caddy nie powiódł się"

# 7. /health przez Caddy. Sam brak miejsca na dysku nie jest winą nowej wersji i nie uzasadnia powrotu.
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

# 8. Zapis wersji i sprzątanie starych obrazów.
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
