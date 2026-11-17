#!/usr/bin/env bash
# Delivers the ref-clips site file to the shared edge proxy (github.com/fkula5/vps-edge) and reloads it.
# Renders TEMPLATE with deploy/render-site.sh, writes it next to the destination and renames it into
# ${REFCLIPS_EDGE_DIR:-/opt/edge}/conf/sites/ref-clips.caddy, then runs the edge's reload.sh. When the
# validation or reload fails, the previous file is restored and the edge reloaded again; exit code 1.
#
# Usage: deploy/install-site.sh [--check] TEMPLATE ENV_FILE
#   --check   only verify that the edge stack is there and that the template renders; change nothing
set -euo pipefail

EDGE_DIR="${REFCLIPS_EDGE_DIR:-/opt/edge}"
SITES="$EDGE_DIR/conf/sites"
DEST="$SITES/ref-clips.caddy"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "BŁĄD: $*" >&2; exit 1; }

CHECK=0
if [ "${1:-}" = --check ]; then CHECK=1; shift; fi
[ "$#" -eq 2 ] || { echo "Użycie: $0 [--check] SZABLON PLIK_ENV" >&2; exit 2; }
TEMPLATE="$1"; ENV_FILE="$2"

DOCKER=(docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo -n docker)
RELOAD=("$EDGE_DIR/reload.sh")
[ "${DOCKER[0]}" != sudo ] || RELOAD=(sudo -n "$EDGE_DIR/reload.sh")

HINT="patrz docs/wdrozenie.md, „Moving from the bundled Caddy to the shared edge proxy” (https://github.com/fkula5/vps-edge)"
[ -d "$SITES" ] || die "brak katalogu $SITES — stos edge nie jest zainstalowany ($HINT)"
[ -x "$EDGE_DIR/reload.sh" ] || die "brak wykonywalnego $EDGE_DIR/reload.sh ($HINT)"
[ "$("${DOCKER[@]}" inspect -f '{{.State.Running}}' edge-caddy 2>/dev/null || true)" = true ] \
  || die "kontener edge-caddy nie działa ($HINT)"

tmp="$(mktemp "$SITES/.ref-clips.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
bash "$HERE/render-site.sh" "$TEMPLATE" "$ENV_FILE" > "$tmp" || die "nie udało się wygenerować ref-clips.caddy z .env"
[ "$CHECK" = 0 ] || { echo "Edge gotowy, ref-clips.caddy się generuje."; exit 0; }
chmod 644 "$tmp"

if [ -f "$DEST" ] && cmp -s "$tmp" "$DEST"; then
  echo "ref-clips.caddy bez zmian — pomijam przeładowanie edge."
  exit 0
fi

backup="$SITES/.ref-clips.caddy.bak"
rm -f "$backup"
[ ! -f "$DEST" ] || cp -p "$DEST" "$backup"
mv -f "$tmp" "$DEST"

echo "Przeładowuję edge-caddy (walidacja całej konfiguracji, potem reload)..."
if ! "${RELOAD[@]}"; then
  echo "BŁĄD: walidacja lub przeładowanie edge nie powiodły się — przywracam poprzedni ref-clips.caddy." >&2
  if [ -f "$backup" ]; then mv -f "$backup" "$DEST"; else rm -f "$DEST"; fi
  "${RELOAD[@]}" >/dev/null 2>&1 || echo "UWAGA: ponowne przeładowanie po przywróceniu też zawiodło — sprawdź: docker logs edge-caddy" >&2
  exit 1
fi
rm -f "$backup"
echo "ref-clips.caddy zainstalowany w $SITES."
