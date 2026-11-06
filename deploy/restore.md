# Odtwarzanie ref-clips z kopii zapasowej

Kopie leżą w `/var/backups/ref-clips/RRRR-MM-DD` (baza `ref-clips.db` i katalog `clips/`; patrz `docs/wdrozenie.md`).
Odtwarzamy na serwerze, w `/opt/ref-clips`. **Pełnych nagrań nie ma w kopii** — po odtworzeniu na nowym serwerze
klipy i opisy są, a nagrań do ponownego oglądania trzeba wgrać od nowa (retencja i tak je usuwa).

## 1. Wybór migawki i sprawdzenie

```bash
cd /opt/ref-clips
export COMPOSE_FILE=compose.yaml:compose.prod.yaml
sudo ls /var/backups/ref-clips                      # dostępne dni
SNAP=/var/backups/ref-clips/2026-11-05              # wybrany dzień
sudo cat "$SNAP/INFO.txt"
```

## 2. Odtworzenie na tym samym serwerze

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
  chown -R app:app /data/ref-clips.db /data/clips
'
docker compose up -d --wait                         # init zastosuje migracje, jeśli kopia jest starsza od kodu
```

Zaloguj się i sprawdź listę meczów i odtwarzanie klipu. Gdy wszystko gra, zwolnij miejsce:

```bash
docker compose run --rm --no-deps --user root app sh -c 'rm -rf /data/przed-odtworzeniem.db /data/clips.przed-odtworzeniem'
```

Jeśli odtworzenie się nie udało, wróć do stanu sprzed (`przed-odtworzeniem.db`, `clips.przed-odtworzeniem`) analogicznym `mv`.

## 3. Odtworzenie na nowym serwerze

1. Przygotuj serwer i wdróż aplikację według `docs/wdrozenie.md` (bez zakładania administratora).
2. Skopiuj migawkę na serwer, np. `scp -r` do `/var/backups/ref-clips/RRRR-MM-DD` (uprawnienia katalogu bez zmian, własność roota).
3. Wykonaj krok 2. Konta, role, oceny i komentarze wracają razem z bazą, więc administratora nie trzeba zakładać.
   Jeśli adres się zmienił, ustaw nowy w `.env` (`REFCLIPS_SITE`, `REFCLIPS_PUBLIC_URL`).

## 4. Próbne odtworzenie (raz na kwartał)

Na osobnym stosie, żeby nie dotykać produkcji: zrób kopię repozytorium w innym katalogu, uruchom z innym projektem
(`COMPOSE_PROJECT_NAME=ref-clips-test`, inne porty `REFCLIPS_HTTP_PORT`/`REFCLIPS_HTTPS_PORT`, `REFCLIPS_SITE=localhost`),
wykonaj krok 2 i sprawdź logowanie oraz odtwarzanie klipu. Na końcu `docker compose down -v` **tego** projektu.
