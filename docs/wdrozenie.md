# Wdrożenie na serwer (produkcja)

> Segment 8. Stan: konfiguracja gotowa i przetestowana lokalnie; przygotowanie serwera i pierwsze
> wdrożenie wykonuje osoba z dostępem do VPS.

Docelowo: OVH VPS (Ubuntu 24.04, 2 vCPU, ok. 3,7 GB RAM, 38 GB dysku), Docker Engine z wtyczką Compose,
`ufw` z otwartymi portami 22/80/443. Bez własnej domeny adres to `https://57-131-162-204.sslip.io`
(sslip.io zamienia nazwę z IP na ten adres IP; Caddy dostaje certyfikat Let's Encrypt).

## Jak to jest zbudowane

```
przeglądarka ──HTTPS──► Caddy (80, 443, 443/udp) ──sieć compose──► app:8000 ──► SQLite (WAL, wolumin „dane”)
                                                                    worker ──► ffmpeg (ten sam wolumin)
```

| Plik | Do czego |
|---|---|
| `compose.yaml` | usługi `init`, `app`, `worker` (jak w testach lokalnych) |
| `compose.prod.yaml` | **nakładka** na `compose.yaml`: usuwa port aplikacji z hosta, dodaje `caddy`, rotację logów |
| `deploy/Caddyfile` | HTTPS, nagłówki bezpieczeństwa, kompresja, `reverse_proxy` do aplikacji |
| `deploy/env.prod.example` | wzór pliku `.env` na serwerze (bez sekretów) |
| `deploy/deploy.sh` | wdrożenie z komputera lokalnego przez ssh |
| `deploy/backup.sh`, `backup_snapshot.py`, `ref-clips-backup.service/.timer` | nocna kopia zapasowa |
| `deploy/restore.md` | odtwarzanie z kopii |

Nakładka zamiast osobnego pliku: usługi `init`/`app`/`worker` są zdefiniowane w jednym miejscu, więc test
dymny (`scripts/docker-smoke.sh`) i produkcja nie rozjadą się. Cena: zawsze podajemy oba pliki
(`-f compose.yaml -f compose.prod.yaml`) albo ustawiamy `COMPOSE_FILE=compose.yaml:compose.prod.yaml`
(deploy.sh i backup.sh robią to same).

Aplikacja **nie ma żadnego sekretu** (klucza podpisu itp.): sesje i zaproszenia to losowe tokeny
w bazie, hasła są hashowane (argon2). W `.env` są tylko ustawienia, a hasło administratora wpisujesz
interaktywnie. Wszystkie dane (baza, nagrania, klipy) są w wolumenie Dockera `ref-clips_dane`,
certyfikaty Caddy w `ref-clips_caddy_data`.

Uwaga o `ufw`: porty publikowane przez Dockera omijają reguły `ufw`. Tu publikuje je tylko Caddy
(80, 443, 443/udp), a aplikacja nie ma portu na hoście — nie zmieniaj tego (np. nie dodawaj `ports:` do `app`).

## Pierwsze wdrożenie

Na serwerze (jednorazowo, z `sudo`):

```bash
sudo install -d -o ubuntu -g ubuntu -m 755 /opt/ref-clips
docker compose version     # użytkownik ubuntu musi móc uruchamiać docker (grupa docker) albo mieć sudo bez hasła
```

Na komputerze lokalnym, w repozytorium (wszystko zacommitowane na gałęzi, którą wdrażasz):

```bash
deploy/deploy.sh            # domyślnie ubuntu@57.131.162.204, klucz ~/.ssh/ref_clips_deploy
```

Przy pierwszym uruchomieniu skrypt wyśle pliki, po czym zatrzyma się z komunikatem o braku `.env` — to
oczekiwane. Na serwerze:

```bash
cd /opt/ref-clips
cp deploy/env.prod.example .env && chmod 600 .env
nano .env        # sprawdź REFCLIPS_SITE i REFCLIPS_PUBLIC_URL; limity dopasowane do dysku 38 GB
```

Potem ponownie `deploy/deploy.sh` (lokalnie). Pierwsze budowanie obrazu trwa kilka minut, a Caddy potrzebuje
chwili na certyfikat. Skrypt czeka, aż `app` będzie zdrowa, i sprawdza `https://57-131-162-204.sslip.io/login`.

**Konto administratora** (interaktywnie, hasło min. 10 znaków; `-t` potrzebne, by hasło nie było widoczne):

```bash
ssh -t -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 \
  'cd /opt/ref-clips && COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose run --rm app python -m app.create_admin'
```

(albo na serwerze: `docker compose -f compose.yaml -f compose.prod.yaml run --rm app python -m app.create_admin`).
Nie podawaj hasła w parametrze `--password`: trafiłoby do historii poleceń.

**Kopie zapasowe** — włączenie timera (raz, na serwerze):

```bash
cd /opt/ref-clips
sudo cp deploy/ref-clips-backup.service deploy/ref-clips-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ref-clips-backup.timer
systemctl list-timers ref-clips-backup.timer     # następne uruchomienie ok. 03:30 UTC
sudo systemctl start ref-clips-backup.service    # próba od razu
journalctl -u ref-clips-backup.service -n 20 --no-pager
ls -la /var/backups/ref-clips/
```

Po zmianie plików `.service`/`.timer` w repozytorium skopiuj je ponownie i wykonaj `daemon-reload`.

**Sprawdzenie końcowe:** otwórz `https://57-131-162-204.sslip.io`, zaloguj się, utwórz zaproszenie
(link musi zaczynać się od `https://57-131-162-204.sslip.io`), wgraj krótkie wideo. Pomiar czasu konwersji
2-godzinnego nagrania na tym VPS jest nadal do zrobienia (patrz `TODO.md`).

## Kolejne wdrożenia

```bash
git commit ...              # deploy.sh wdraża commit (HEAD), nie katalog roboczy; odmawia przy niezacommitowanych zmianach
deploy/deploy.sh
```

Skrypt: wysyła `git archive HEAD` do `/opt/ref-clips` (usuwa pliki skasowane w repozytorium, **zostawia `.env`**;
dane są w wolumenach, więc nie są ruszane), uruchamia `docker compose up -d --build --wait`, pokazuje status
i usuwa nieużywane obrazy (`docker image prune -f`). Migracje bazy wykonuje usługa `init` przy starcie.
Podczas przebudowy aplikacja jest niedostępna przez kilkanaście sekund; trwające wgrywanie tus wznowi się samo.
Przed ryzykowną zmianą bazy: `sudo /opt/ref-clips/deploy/backup.sh`.

Inny serwer lub klucz: `deploy/deploy.sh -H user@host -i ~/.ssh/klucz -d /opt/ref-clips` albo zmienne
`REFCLIPS_DEPLOY_HOST`, `REFCLIPS_DEPLOY_KEY`, `REFCLIPS_DEPLOY_DIR`, `REFCLIPS_DEPLOY_URL` (adres do końcowego
sprawdzenia, puste = pomiń). Skrypt używa `StrictHostKeyChecking=accept-new`: pierwsze połączenie zapamiętuje klucz
serwera, późniejsza zmiana klucza zatrzyma wdrożenie.

## Codzienna obsługa

Na serwerze, w `/opt/ref-clips` (jednorazowo `export COMPOSE_FILE=compose.yaml:compose.prod.yaml`):

| Co | Polecenie |
|---|---|
| Status | `docker compose ps` |
| Logi aplikacji / workera / Caddy | `docker compose logs -f --tail 100 app` (`worker`, `caddy`) |
| Restart | `docker compose restart app worker` |
| Wersja na serwerze | `cat .deploy-commit` |
| Miejsce na dysku | `df -h /`, `docker system df`, panel admina → „Retencja i dysk” |
| Zatrzymanie (dane zostają) | `docker compose stop` |

Logi kontenerów rotują się same (5 plików po 20 MB na usługę). Dziennik dostępu Caddy (`docker compose logs caddy`)
zawiera adresy żądań, w tym linki zaproszeń; ciasteczek i nagłówka Authorization Caddy nie zapisuje.
**Nie wykonuj `docker compose down -v`** — usuwa wolumin z danymi i certyfikatami.

## Kopie zapasowe

`deploy/backup.sh` (timer: codziennie ok. 03:30 UTC) tworzy migawkę `/var/backups/ref-clips/RRRR-MM-DD`:

- `ref-clips.db` — baza przez API kopii zapasowej SQLite (spójna przy działającej aplikacji), sprawdzona `integrity_check`,
- `clips/` — klipy; niezmienione pliki są twardymi dowiązaniami do poprzedniej migawki, więc dzień kosztuje tylko nowe klipy,
- `INFO.txt` — podsumowanie.

Pełne nagrania (wersje robocze), oryginały i niedokończone uploady **nie** są kopiowane — są tymczasowe (retencja).
Zostaje 14 ostatnich migawek. Praca idzie w jednorazowym kontenerze aplikacji, więc na hoście nie trzeba `sqlite3` ani `rsync`.
Katalog kopii ma uprawnienia 700 (w klipach jest wizerunek zawodników, w tym niepełnoletnich).

**Ważne:** kopia leży na tym samym dysku co dane, więc chroni przed pomyłką i uszkodzeniem bazy, ale **nie** przed
utratą serwera. Kopia poza serwerem jest w `TODO.md` (OVH Object Storage lub Hetzner Storage Box + rclone).
Do czasu jej wdrożenia warto okresowo pobierać najnowszą migawkę na swój komputer, np.:
`ssh -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 'sudo tar -C /var/backups/ref-clips -cf - "$(sudo ls /var/backups/ref-clips | tail -1)"' > ref-clips-kopia.tar`.

Miejsce: 38 GB dysku to mało na obrazy Dockera (ok. 2 GB), kopie i nagrania. Obserwuj `df -h /`; limity wgrywania w `.env`
(`REFCLIPS_UPLOAD_MAX_GB`, `REFCLIPS_DISK_SAFETY_GB`) chronią przed zapełnieniem dysku uploadem, ale nie przed kopiami.

## Odtwarzanie z kopii

Patrz [deploy/restore.md](../deploy/restore.md). Zalecane jest próbne odtworzenie raz na kwartał (na osobnym stosie Compose).

## Zmiana adresu na własną domenę

1. U rejestratora ustaw rekord `A` (i ewentualnie `AAAA`) domeny, np. `klipy.example.pl`, na `57.131.162.204`. Poczekaj, aż `dig +short klipy.example.pl` pokaże ten adres.
2. W `/opt/ref-clips/.env` zmień:
   `REFCLIPS_SITE=klipy.example.pl` i `REFCLIPS_PUBLIC_URL=https://klipy.example.pl`.
3. `docker compose -f compose.yaml -f compose.prod.yaml up -d` (Caddy wystawi nowy certyfikat; porty 80/443 muszą być osiągalne z internetu).
4. Lokalnie ustaw `REFCLIPS_DEPLOY_URL=https://klipy.example.pl` (deploy.sh sprawdza ten adres).
5. Zaproszenia wysłane wcześniej mają stary adres w treści linku; wystaw je ponownie. Stare ciasteczka sesji
   dotyczą starej nazwy hosta — użytkownicy zalogują się ponownie.

## Odebranie dostępu kluczowi `claude-deploy-ref-clips`

Klucz jest w `~ubuntu/.ssh/authorized_keys` (komentarz `claude-deploy-ref-clips`). Na serwerze, po zalogowaniu własnym kluczem:

```bash
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
sed -i '/claude-deploy-ref-clips/d' ~/.ssh/authorized_keys
grep -c claude-deploy-ref-clips ~/.ssh/authorized_keys     # ma być 0
```

Sprawdź z komputera, na którym jest ten klucz, że `ssh -i ~/.ssh/ref_clips_deploy -o IdentitiesOnly=yes ubuntu@57.131.162.204 true`
kończy się odmową, a potem usuń `authorized_keys.bak` i lokalny plik klucza (`~/.ssh/ref_clips_deploy*`).
Jeśli klucz miał wpis w `sudoers` lub inny sposób dostępu, usuń go także (`sudo grep -r claude /etc/sudoers /etc/sudoers.d`).

## Rozwiązywanie problemów

- **Brak certyfikatu / błąd TLS po pierwszym starcie:** `docker compose logs caddy`. Adres musi wskazywać na ten serwer, a porty 80 i 443
  muszą być osiągalne (ufw, firewall OVH). `sslip.io` to wspólna domena wielu osób i Let's Encrypt potrafi zwrócić limit zapytań —
  Caddy próbuje wtedy automatycznie innego wystawcy (ZeroSSL); gdyby się nie udało, użyj własnej domeny.
- **`deploy.sh`: „brak pliku .env”:** patrz „Pierwsze wdrożenie”. **„permission denied” przy docker:** dodaj użytkownika do grupy `docker` albo skonfiguruj `sudo` bez hasła.
- **Wgrywanie dużych plików się zrywa:** Caddy nie ma limitu czasu ciała żądania, a kawałek tus ma 50 MB (limit w Caddy to 64 MB); sprawdź
  `docker compose logs app caddy` i wolne miejsce na dysku.
- **Zaproszenie ma adres `http://...`:** brak `REFCLIPS_PUBLIC_URL` w `.env`.
- **Limit prób logowania blokuje wszystkich naraz:** `REFCLIPS_TRUST_PROXY=1` musi być ustawione, inaczej każdy użytkownik ma adres kontenera Caddy.
