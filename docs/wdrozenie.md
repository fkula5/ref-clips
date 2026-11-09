# Wdrożenie na serwer (produkcja)

> Segmenty 8–9. Stan: konfiguracja gotowa i przetestowana lokalnie; przygotowanie serwera i pierwsze
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
| `deploy/deploy.sh` | wdrożenie z komputera lokalnego przez ssh (z blokadą, gdy coś trwa: `app/busy.py`) |
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

Skrypt: **najpierw sprawdza, czy coś trwa** (patrz niżej), potem wysyła `git archive HEAD` do `/opt/ref-clips`
(usuwa pliki skasowane w repozytorium, **zostawia `.env`**; dane są w wolumenach, więc nie są ruszane), buduje obrazy,
uruchamia `docker compose up -d --wait`, pokazuje status i usuwa nieużywane obrazy (`docker image prune -f`),
a na końcu sprawdza `/login` i `/health`. Migracje bazy wykonuje usługa `init` przy starcie (nowe tabele i kolumny
dochodzą same; wdrożenie bez migracji nie wymaga żadnych dodatkowych kroków).
Podczas przebudowy aplikacja jest niedostępna przez kilkanaście sekund; trwające wgrywanie tus wznowi się samo, ale
konwersja w toku zaczyna od początku (dla 2-godzinnego nagrania to ponad godzina straty), dlatego:

**Blokada „coś trwa”.** Przed jakąkolwiek zmianą na serwerze skrypt uruchamia w działającym kontenerze `app`
sprawdzenie `app/busy.py` (jego treść wysyła na wejście `python -`, więc działa też na obrazie sprzed dodania tego
modułu). Za „trwające” uznaje: upload tus z aktywnością w ostatnich 10 minutach, zadanie w stanie `running`
(konwersja, wycinanie klipu) oraz zadania czekające w kolejce. Jeśli coś trwa, wypisuje co (np. `konwersja nagrania #1
(mecz.mp4) — 43%`, `upload IMG_2056.MOV — 1,6 GB/2,7 GB, ostatnia aktywność 2 min temu`) i kończy z kodem 3
**bez podmiany plików i bez restartu** — stan katalogu na serwerze zgadza się wtedy z działającą wersją. Niedokończone
uploady bez aktywności od ponad 10 minut nie blokują (wznowią się po wdrożeniu). Gdy stos nie działa (pierwsze
wdrożenie, brak `.env`, kontener `app` zatrzymany), nic nie blokuje. Jeśli samo sprawdzenie się nie uda (np. błąd
dockera), skrypt też się zatrzymuje, żeby nie wdrażać „na ślepo”.

| Opcja | Działanie |
|---|---|
| (brak) | zajęte → komunikat i koniec, nic nie zmienione; ponów później |
| `--wait` | czeka na koniec zajętości (sprawdza co 60 s, maks. 120 min: `REFCLIPS_DEPLOY_WAIT_INTERVAL`, `REFCLIPS_DEPLOY_WAIT_MINUTES`), potem wdraża |
| `--force` lub `REFCLIPS_DEPLOY_FORCE=1` | wdraża mimo to, z ostrzeżeniem (przerwie konwersję i wgrywanie) |

Budowanie obrazu trwa minuty, więc tuż przed `up` sprawdzenie jest powtarzane na serwerze. Jeśli w międzyczasie ktoś
zaczął wgrywać plik, skrypt kończy się (kod 3) z komunikatem, że pliki są już wysłane i obrazy zbudowane, ale stos
działa dalej na poprzedniej wersji — wystarczy uruchomić `deploy/deploy.sh` ponownie, gdy będzie wolne (szybko, bo
obrazy są w pamięci podręcznej). Ręczne sprawdzenie bez wdrażania:
`ssh ... 'cd /opt/ref-clips && COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose exec -T app python -m app.busy'`
(kod wyjścia 0 = wolne, 1 = zajęte, 2 = błąd sprawdzania).

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
zawiera adresy żądań, ale token z linku zaproszenia jest w nim zastąpiony napisem `[ukryty]`
(`/set-password/[ukryty]`; filtr w `deploy/Caddyfile` obejmuje adres żądania i nagłówek Referer), tak samo w dzienniku
dostępu aplikacji (`app/logfilter.py`); ciasteczek i nagłówka Authorization Caddy nie zapisuje. Strona ustawiania
hasła odpowiada z `Referrer-Policy: no-referrer` i `Cache-Control: no-store`.
**Nie wykonuj `docker compose down -v`** — usuwa wolumin z danymi i certyfikatami.

## Monitoring (`/health`)

`GET /health` (także `HEAD`) jest publiczny: bez logowania, bez ciasteczek, bez cache (`Cache-Control: no-store`),
odpowiada w kilka milisekund i sprawdza trzy rzeczy:

| Sprawdzenie | Zdrowe, gdy | Stany w odpowiedzi |
|---|---|---|
| `db` | proste zapytanie do bazy się udaje | `ok`, `error` |
| `worker` | worker odnowił znacznik życia w ciągu ostatnich 3 minut (`settings.worker_heartbeat`, zapis co 30 s w osobnym wątku, więc bije także podczas godzinnej konwersji) | `ok`, `stale` (za stary), `missing` (nigdy nie zapisany), `unknown` (baza niedostępna) |
| `disk` | wolne miejsce na dysku danych (`statvfs`, bez przeglądania katalogów) jest co najmniej równe `REFCLIPS_DISK_SAFETY_GB` — poniżej tego aplikacja i tak odrzuca każdy upload | `ok`, `low`, `error` |

Odpowiedź: `200 {"status":"ok"}` albo `503 {"status":"error","checks":{"db":"ok","worker":"stale","disk":"ok"}}` — wyłącznie
nazwy i stany, bez ścieżek, rozmiarów, wersji ani treści wyjątków (szczegóły są w logach: `docker compose logs app worker`).
Próby można zmienić w `.env`: `REFCLIPS_HEALTH_WORKER_STALE_SECONDS` (domyślnie 180), `REFCLIPS_HEALTH_DISK_MIN_GB`.

**Zewnętrzny ping** (np. UptimeRobot, plan darmowy): monitor HTTP(s) na `https://57-131-162-204.sslip.io/health`, interwał
5 min, alert e-mail przy kodzie innym niż 200 (sprawdzanie słowa kluczowego `"ok"` nie jest potrzebne). Przy 503 odczytaj
które sprawdzenie nie przechodzi: `curl -s https://57-131-162-204.sslip.io/health`.

**Healthchecki Dockera.** `app` zostaje na `/login` — tylko „czy serwer odpowiada”. Celowo nie `/health`: 503 z powodu
workera albo pełnego dysku nie jest awarią serwera WWW i restart aplikacji niczego by nie naprawił, a zablokowałby
`up --wait` (wdrożenie) i start Caddy (`depends_on`). `worker` ma własny healthcheck (`python -m app.health worker`:
znacznik życia młodszy niż 3 minuty); `docker compose ps` pokaże `unhealthy`, ale Docker sam go nie zrestartuje —
`docker compose restart worker`. Znacznik bije wątek, nie pętla zadań, więc wiszący (zablokowany) ffmpeg go nie
przeterminuje; takie zadanie widać w panelu jako konwersję bez postępu.

## Linki do klipów bez konta (`/s/<kod>`)

Pierwsza funkcja dostępna bez logowania: osoba z linkiem ogląda i pobiera klipy. Domyślnie pokazujemy jak najmniej.

- **Co widać publicznie:** wideo, liga (`Match.level`) i kategoria decyzji (`Clip.category_label`). Nie ma nazwisk
  sędziów, drużyn, daty i godziny meczu, opisów, ocen, komentarzy, nawigacji ani nazwy użytkownika, który udostępnił
  (także w nazwach plików i w ZIP-ie). **Uwaga:** tekst wpisany ręcznie jako kategoria „własna” oraz liga są wolnym
  tekstem i też są publiczne; przy tworzeniu linku strona pokazuje, co zobaczy odbiorca.
- **Kod poza logami:** kod (256 bitów losowości) jest tylko w adresie. Filtr dziennika Caddy (`deploy/Caddyfile`, adres
  żądania i Referer) oraz dziennika aplikacji (`app/logfilter.py`) zamienia go na `/s/[ukryty]`, reszta ścieżki zostaje.
  W bazie jest wyłącznie skrót SHA-256. Zmiana `Caddyfile` wymaga restartu Caddy: `deploy/deploy.sh` robi to sam.
  Sprawdzenie po wdrożeniu: `docker compose logs caddy | grep '"/s/'` nie może pokazać kodu.
- **Nagłówki:** na `/s/*` aplikacja ustawia `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store` (plik wideo: `private, no-store`, Range działa). Caddy nie nadpisuje `Referrer-Policy` na tej ścieżce.
- **Ważność i unieważnianie:** 1, 7 albo 30 dni, bez linków bezterminowych; unieważnia twórca albo administrator.
  Unieważnienie nie cofa plików już pobranych. Wygasłe i unieważnione linki zostają w bazie (bez czyszczenia).
- **ZIP:** budowany w `DATA_DIR/tmp`, usuwany po wysłaniu; najwyżej `SHARE_ZIP_MAX_PARALLEL` (2) naraz, kolejne dostają
  503, tak samo przy braku wolnego miejsca. Pozostałości po awarii sprząta worker (pliki `.zip` w `tmp/` starsze niż godzina).
- **Przy pierwszym wdrożeniu tej funkcji:** migracja `mvp0005` wykonuje się sama (usługa `init`). Klipy wycięte wcześniej mogą
  mieć metadane pliku źródłowego (tytuł, lokalizacja GPS, data nagrania); nowe już ich nie mają. Jednorazowo wyczyść stare
  (bez przekodowania, idempotentne):
  `COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose exec -T app python -m app.strip_metadata`.
- **Podgląd przez komunikatory:** roboty podglądu linków (np. Messenger) mogą otworzyć stronę i zwiększyć licznik wejść.

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
- **`deploy.sh` kończy z kodem 3 („na serwerze coś trwa”):** to blokada ochronna, nic nie zostało zmienione. Poczekaj,
  użyj `--wait` albo `--force` (patrz „Kolejne wdrożenia”). Jeśli blokuje „konwersja nagrania #N — 0%” od wielu godzin,
  a `docker compose ps` pokazuje worker `unhealthy`: `docker compose restart worker` (zadania wracają do kolejki).
- **`/health` zwraca 503:** `curl -s .../health` pokazuje, które sprawdzenie. `worker: stale/missing` — `docker compose
  logs --tail 50 worker`, `docker compose restart worker`; `disk: low` — `df -h /`, panel admina → „Retencja i dysk”.
- **Zaproszenie ma adres `http://...`:** brak `REFCLIPS_PUBLIC_URL` w `.env`.
- **Limit prób logowania blokuje wszystkich naraz:** `REFCLIPS_TRUST_PROXY=1` musi być ustawione, inaczej każdy użytkownik ma adres kontenera Caddy.
