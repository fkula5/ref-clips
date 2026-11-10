#!/usr/bin/env bash
# Server backup: DB (SQLite backup API) + clips, without full recordings and drafts. Result:
# $BACKUP_ROOT/YYYY-MM-DD (last 14 snapshots; clips as hard links, so later days take only new clips).
# Run by the systemd timer (deploy/ref-clips-backup.timer) or by hand: sudo
# /opt/ref-clips/deploy/backup.sh
# Runs in a one-off app container: no sqlite3 or rsync needed on the host.
#
# Optional variables: REFCLIPS_DIR (directory with compose.yaml), BACKUP_ROOT, KEEP_BACKUPS,
# COMPOSE_FILE (default compose.yaml:compose.prod.yaml), COMPOSE_PROJECT_NAME.
set -euo pipefail

REFCLIPS_DIR="${REFCLIPS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/ref-clips}"
KEEP_BACKUPS="${KEEP_BACKUPS:-14}"
export COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml:compose.prod.yaml}"

cd "$REFCLIPS_DIR"
umask 077  # the backup holds recordings of players: owner only
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

echo "==> Kopia zapasowa ref-clips do $BACKUP_ROOT ($(date -u +%FT%TZ))"
# --user = current host user: backup files belong to them (root from systemd, reads the whole volume).
# --no-deps: does not start init/app, works while the app is stopped.
docker compose run --rm -T --no-deps --user "$(id -u):$(id -g)" \
  -v "$BACKUP_ROOT:/backup" app \
  python - /data /backup "$KEEP_BACKUPS" < "$REFCLIPS_DIR/deploy/backup_snapshot.py"
echo "==> Migawki:"
ls -1 "$BACKUP_ROOT" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | tail -n "$KEEP_BACKUPS"
du -sh "$BACKUP_ROOT" | sed 's/^/Zajęte miejsce: /'
