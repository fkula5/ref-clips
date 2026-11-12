# Restoring ref-clips from a backup

Backups are in `/var/backups/ref-clips/RRRR-MM-DD` (the database `ref-clips.db`, the `clips/` directory and, if the matches have scoresheets, `scoresheets/`; see `docs/wdrozenie.md`).
Restore on the server, in `/opt/ref-clips`. **Full recordings are not in the backup** — after restoring on a new server
the clips and descriptions are there, but recordings for re-watching must be uploaded again (retention deletes them anyway).

## 1. Choosing a snapshot and checking it

```bash
cd /opt/ref-clips
export COMPOSE_FILE=compose.yaml:compose.prod.yaml
sudo ls /var/backups/ref-clips                      # dostępne dni
SNAP=/var/backups/ref-clips/2026-11-05              # wybrany dzień
sudo cat "$SNAP/INFO.txt"
```

## 2. Restoring on the same server

```bash
docker compose stop app worker                      # Caddy zostaje, pokaże błąd 502 do końca

docker compose run --rm --no-deps --user root -v "$SNAP:/backup:ro" app sh -c '
  set -e
  rm -f /data/ref-clips.db-wal /data/ref-clips.db-shm        # stary dziennik WAL nie pasuje do kopii
  [ -f /data/ref-clips.db ] && mv /data/ref-clips.db /data/przed-odtworzeniem.db
  cp /backup/ref-clips.db /data/ref-clips.db
  rm -rf /data/clips.przed-odtworzeniem
  [ -d /data/clips ] && mv /data/clips /data/clips.przed-odtworzeniem
  cp -a /backup/clips /data/clips
  rm -rf /data/scoresheets.przed-odtworzeniem
  if [ -d /data/scoresheets ]; then mv /data/scoresheets /data/scoresheets.przed-odtworzeniem; fi
  if [ -d /backup/scoresheets ]; then cp -a /backup/scoresheets /data/scoresheets; fi
  chown -R app:app /data/ref-clips.db /data/clips
  if [ -d /data/scoresheets ]; then chown -R app:app /data/scoresheets; fi
'
docker compose up -d --wait                         # init zastosuje migracje, jeśli kopia jest starsza od kodu
```

Log in and check the match list and clip playback. When everything works, free the space:

```bash
docker compose run --rm --no-deps --user root app sh -c 'rm -rf /data/przed-odtworzeniem.db /data/clips.przed-odtworzeniem /data/scoresheets.przed-odtworzeniem'
```

If the restore failed, go back to the state before (`przed-odtworzeniem.db`, `clips.przed-odtworzeniem`, `scoresheets.przed-odtworzeniem`) with the analogous `mv`.

## 3. Restoring on a new server

1. Prepare the server and deploy the application according to `docs/wdrozenie.md` (without creating an administrator).
2. Copy the snapshot to the server, e.g. `scp -r` to `/var/backups/ref-clips/RRRR-MM-DD` (directory permissions unchanged, owned by root).
3. Perform step 2. Accounts, roles, ratings and comments come back together with the database, so there is no need to create an administrator.
   If the address has changed, set the new one in `.env` (`REFCLIPS_SITE`, `REFCLIPS_PUBLIC_URL`).

## 4. Test restore (once a quarter)

On a separate stack, so as not to touch production: make a copy of the repository in another directory, run it with another project
(`COMPOSE_PROJECT_NAME=ref-clips-test`, other ports `REFCLIPS_HTTP_PORT`/`REFCLIPS_HTTPS_PORT`, `REFCLIPS_SITE=localhost`),
perform step 2 and check login and clip playback. At the end run `docker compose down -v` for **this** project.
