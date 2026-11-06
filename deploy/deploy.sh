#!/usr/bin/env bash
# Wdrożenie ref-clips na serwer — uruchamiane LOKALNIE, z repozytorium.
# Wysyła aktualny commit (git archive HEAD, nie katalog roboczy) przez ssh do katalogu na serwerze,
# nie ruszając pliku .env ani danych (dane są w wolumenach Dockera), buduje obrazy, uruchamia
# stos (docker compose -f compose.yaml -f compose.prod.yaml up -d --build), czeka na zdrowie
# aplikacji i pokazuje status. Można uruchamiać wielokrotnie (idempotentne). Nie wypisuje .env.
#
# Użycie:   deploy/deploy.sh [-H użytkownik@host] [-i klucz_ssh] [-d katalog_na_serwerze]
# Zmienne:  REFCLIPS_DEPLOY_HOST  (domyślnie ubuntu@57.131.162.204)
#           REFCLIPS_DEPLOY_KEY   (domyślnie ~/.ssh/ref_clips_deploy)
#           REFCLIPS_DEPLOY_DIR   (domyślnie /opt/ref-clips)
#           REFCLIPS_DEPLOY_URL   (adres do końcowego sprawdzenia; domyślnie https://57-131-162-204.sslip.io,
#                                  puste = pomiń)
set -euo pipefail

HOST="${REFCLIPS_DEPLOY_HOST:-ubuntu@57.131.162.204}"
KEY="${REFCLIPS_DEPLOY_KEY:-$HOME/.ssh/ref_clips_deploy}"
DIR="${REFCLIPS_DEPLOY_DIR:-/opt/ref-clips}"
URL="${REFCLIPS_DEPLOY_URL-https://57-131-162-204.sslip.io}"

usage() { sed -n '2,/^set -/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "BŁĄD: $*" >&2; exit 1; }

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
"${SSH[@]}" "bash -s -- $QDIR" <<'REMOTE'
set -euo pipefail
cd "$1"
exec 9>.deploy.lock
flock -n 9 || { echo "BŁĄD: inne wdrożenie trwa (blokada .deploy.lock)" >&2; exit 1; }

[ -f .env ] || { echo "BŁĄD: brak pliku .env w $1 — skopiuj deploy/env.prod.example do .env (docs/wdrozenie.md)" >&2; exit 1; }
for key in REFCLIPS_SITE REFCLIPS_COOKIE_SECURE REFCLIPS_TRUST_PROXY REFCLIPS_PUBLIC_URL; do
  grep -Eq "^${key}=." .env || { echo "BŁĄD: w .env brakuje ustawienia $key" >&2; exit 1; }
done

DOCKER=(docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n docker)
export COMPOSE_FILE=compose.yaml:compose.prod.yaml

"${DOCKER[@]}" compose up -d --build --remove-orphans --wait --wait-timeout 300
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
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$URL/login" 2>/dev/null || true)"
    [ "$code" = 200 ] && break
    sleep 3   # pierwszy start: Caddy dopiero wystawia certyfikat
  done
  [ "$code" = 200 ] || die "$URL/login odpowiada kodem $code (logi: ssh ... docker compose logs caddy app)"
fi
echo "==> Gotowe: $COMMIT"
