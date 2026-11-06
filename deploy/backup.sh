#!/usr/bin/env bash
# Kopia zapasowa ref-clips na serwerze: baza (API kopii zapasowej SQLite) + klipy, bez pełnych
# nagrań i wersji roboczych. Wynik: $BACKUP_ROOT/RRRR-MM-DD (14 ostatnich migawek; klipy jako
# twarde dowiązania, więc kolejne dni zajmują tylko nowe klipy). Uruchamia go systemd timer
# (deploy/ref-clips-backup.timer), można też ręcznie: sudo /opt/ref-clips/deploy/backup.sh
# Praca idzie w jednorazowym kontenerze aplikacji — na hoście nie trzeba sqlite3 ani rsync.
#
# Zmienne (opcjonalne): REFCLIPS_DIR (katalog z compose.yaml), BACKUP_ROOT, KEEP_BACKUPS,
# COMPOSE_FILE (domyślnie compose.yaml:compose.prod.yaml), COMPOSE_PROJECT_NAME.
set -euo pipefail

REFCLIPS_DIR="${REFCLIPS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/ref-clips}"
KEEP_BACKUPS="${KEEP_BACKUPS:-14}"
export COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml:compose.prod.yaml}"

cd "$REFCLIPS_DIR"
umask 077   # w kopii są nagrania z wizerunkiem zawodników — tylko dla właściciela
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

echo "==> Kopia zapasowa ref-clips do $BACKUP_ROOT ($(date -u +%FT%TZ))"
# --user = bieżący użytkownik hosta: pliki kopii należą do niego (root z systemd, czyta cały wolumin).
# --no-deps: nie startuje init/app, działa także przy zatrzymanej aplikacji.
docker compose run --rm -T --no-deps --user "$(id -u):$(id -g)" \
  -v "$BACKUP_ROOT:/backup" app \
  python - /data /backup "$KEEP_BACKUPS" < "$REFCLIPS_DIR/deploy/backup_snapshot.py"
echo "==> Migawki:"
ls -1 "$BACKUP_ROOT" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | tail -n "$KEEP_BACKUPS"
du -sh "$BACKUP_ROOT" | sed 's/^/Zajęte miejsce: /'
