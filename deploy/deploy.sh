#!/usr/bin/env bash
# Wdrożenie ref-clips na serwer — uruchamiane LOKALNIE, z repozytorium.
# Wysyła aktualny commit (git archive HEAD, nie katalog roboczy) przez ssh do katalogu na serwerze,
# nie ruszając pliku .env ani danych (dane są w wolumenach Dockera), buduje obrazy, uruchamia
# stos (docker compose -f compose.yaml -f compose.prod.yaml up -d --build), czeka na zdrowie
# aplikacji i pokazuje status. Można uruchamiać wielokrotnie (idempotentne). Nie wypisuje .env.
#
# Zanim cokolwiek zmieni na serwerze, sprawdza, czy nie trwa upload (aktywność w ostatnich 10 min),
# konwersja/cięcie ani zadania w kolejce (python -m app.busy w działającym kontenerze). Jeśli coś trwa,
# kończy BEZ podmiany plików i restartu (kod wyjścia 3); --force pomija blokadę, --wait czeka.
#
# To wyjście awaryjne (obraz budowany na serwerze). Zwykłe wdrożenia robi GitHub Actions z gotowego obrazu z GHCR
# (deploy/ci-entry.sh, docs/ci-cd.md); jeśli ostatnie z nich zapisało w .env tag GHCR (REFCLIPS_IMAGE), ten skrypt na
# czas wdrożenia wymusza REFCLIPS_IMAGE=ref-clips:local i zapisuje to w .env (tuż przed restartem), więc zbudowany
# lokalnie obraz nie podszywa się pod tag z GHCR, a deploy/backup.sh używa tego samego obrazu co działający stos.
#
# Użycie:   deploy/deploy.sh [-H użytkownik@host] [-i klucz_ssh] [-d katalog_na_serwerze] [--force] [--wait]
#           --force   wdróż mimo trwającego uploadu/konwersji (przerwie je; konwersja zacznie od zera)
#           --wait    poczekaj, aż będzie wolne (sprawdzanie co minutę), potem wdróż
# Zmienne:  REFCLIPS_DEPLOY_HOST  (domyślnie ubuntu@57.131.162.204)
#           REFCLIPS_DEPLOY_KEY   (domyślnie ~/.ssh/ref_clips_deploy)
#           REFCLIPS_DEPLOY_DIR   (domyślnie /opt/ref-clips)
#           REFCLIPS_DEPLOY_URL   (adres do końcowego sprawdzenia; domyślnie https://57-131-162-204.sslip.io,
#                                  puste = pomiń)
#           REFCLIPS_DEPLOY_CURL_OPTS          dodatkowe opcje curl do końcowego sprawdzenia (np. -k dla testu z certyfikatem lokalnym)
#           REFCLIPS_DEPLOY_FORCE=1            to samo co --force
#           REFCLIPS_DEPLOY_WAIT_MINUTES       limit czekania przy --wait (domyślnie 120)
#           REFCLIPS_DEPLOY_WAIT_INTERVAL      odstęp między sprawdzeniami przy --wait, w sekundach (domyślnie 60)
set -euo pipefail

HOST="${REFCLIPS_DEPLOY_HOST:-ubuntu@57.131.162.204}"
KEY="${REFCLIPS_DEPLOY_KEY:-$HOME/.ssh/ref_clips_deploy}"
DIR="${REFCLIPS_DEPLOY_DIR:-/opt/ref-clips}"
URL="${REFCLIPS_DEPLOY_URL-https://57-131-162-204.sslip.io}"
FORCE=0; [ "${REFCLIPS_DEPLOY_FORCE:-}" = 1 ] && FORCE=1
WAIT=0
CURL_OPTS=(); [ -z "${REFCLIPS_DEPLOY_CURL_OPTS:-}" ] || read -r -a CURL_OPTS <<<"$REFCLIPS_DEPLOY_CURL_OPTS"
WAIT_MINUTES="${REFCLIPS_DEPLOY_WAIT_MINUTES:-120}"
WAIT_INTERVAL="${REFCLIPS_DEPLOY_WAIT_INTERVAL:-60}"

usage() { sed -n '2,/^set -/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "BŁĄD: $*" >&2; exit 1; }

# Opcje długie (--force, --wait, --help) wyjmujemy przed getopts, który zna tylko krótkie.
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
# Wysyłka czyści katalog docelowy (poza .env), więc nie pozwalamy na katalog systemowy ani zbyt płytki.
case "${DIR%/}" in ""|/*/*) ;; *) die "katalog na serwerze musi mieć co najmniej dwa poziomy (np. /opt/ref-clips): $DIR" ;; esac
[ -n "${DIR%/}" ] || die "katalog na serwerze nie może być /"

# Wdrażamy commit, więc zmiany niezacommitowane do niego nie trafią — odmawiamy, żeby nie było niespodzianek.
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

# --- czy coś trwa? Sprawdzamy PRZED podmianą plików, żeby po przerwaniu stan katalogu na serwerze
# zgadzał się z działającą wersją. Sprawdzenie robi moduł app.busy z wdrażanego commitu, wysłany na
# wejście `python -` działającego kontenera (działa też na obrazie sprzed dodania tego modułu).
BUSY_B64="$(git show HEAD:app/busy.py | base64 | tr -d '\n')"

# Zwraca 0 = wolne (albo stos nie działa), 1 = zajęte, 2 = nie udało się sprawdzić.
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
# Rozpakowanie do .incoming, potem podmiana: usuwamy stare pliki (także te skasowane w repo),
# ale zostaje .env i pliki techniczne wdrożenia. Dane aplikacji leżą w wolumenach, nie tutaj.
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

# Obraz budowany tu nazywa się ref-clips:local — niezależnie od REFCLIPS_IMAGE w .env (może wskazywać na GHCR).
# Zmienna idzie przez `env`, bo sudo czyści środowisko.
DOCKER=(env REFCLIPS_IMAGE=ref-clips:local docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n env REFCLIPS_IMAGE=ref-clips:local docker)
export COMPOSE_FILE=compose.yaml:compose.prod.yaml

"${DOCKER[@]}" compose build

# Budowanie trwa minuty — w tym czasie ktoś mógł zacząć wgrywać plik. Ostatnie sprawdzenie tuż przed restartem.
if [ "$2" != 1 ] && "${DOCKER[@]}" compose ps --status running --services | grep -qx app; then
  rc=0; out="$("${DOCKER[@]}" compose exec -T app python - < app/busy.py 2>&1)" || rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$out" | sed 's/^/    /' >&2
    echo "Pliki są już na serwerze i obrazy zbudowane, ale stos NIE został zrestartowany (działa poprzednia wersja)." >&2
    echo "Uruchom deploy/deploy.sh ponownie, gdy będzie wolne (albo z --force)." >&2
    exit 3
  fi
fi

# Dopiero teraz (po ostatnim sprawdzeniu zajętości) zapisujemy obraz lokalny w .env: nowy plik obok i rename,
# reszta .env bez zmian. Dzięki temu backup.sh i kolejne `docker compose` używają tego, co właśnie działa.
env_tmp="$(mktemp .env.XXXXXX)"
chmod --reference=.env "$env_tmp"
{ grep -v '^REFCLIPS_IMAGE=' .env || true; echo 'REFCLIPS_IMAGE=ref-clips:local'; } > "$env_tmp"
mv -f "$env_tmp" .env

"${DOCKER[@]}" compose up -d --remove-orphans --wait --wait-timeout 300
# Caddyfile jest zamontowany jako pojedynczy plik, a wysyłka tworzy go na nowo: działający Caddy dalej
# widzi starą treść i compose go nie odtwarza. Po zmianie konfiguracji trzeba go zrestartować.
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

if [ -n "$URL" ]; then
  echo "==> Sprawdzanie $URL/login"
  code=000
  for _ in $(seq 1 20); do
    code="$(curl -sS ${CURL_OPTS[@]+"${CURL_OPTS[@]}"} -o /dev/null -w '%{http_code}' --max-time 10 "$URL/login" 2>/dev/null || true)"
    [ "$code" = 200 ] && break
    sleep 3   # pierwszy start: Caddy dopiero wystawia certyfikat
  done
  [ "$code" = 200 ] || die "$URL/login odpowiada kodem $code (logi: ssh ... docker compose logs caddy app)"
  # /health: baza, worker (znacznik życia odnawia się co 30 s, więc po restarcie może chwilę potrwać) i dysk.
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
