# ref-clips

Aplikacja webowa do wycinania i analizy decyzji sędziowskich z meczów koszykówki, dla sędziów
i szkoleniowców jednego okręgu. Wgrywasz nagranie, zaznaczasz momenty albo wklejasz notatki typu
`2:54 Filip kroki`, a aplikacja wycina z każdego wpisu klip (15 s przed i 15 s po) i porządkuje
klipy z opisem, komentarzami i (docelowo) ocenami szkoleniowców.

Dokumentacja projektu: [specyfikacja MVP](docs/specyfikacja-mvp.md),
[plan techniczny](docs/plan-techniczny.md). Stan prac: segment 1 („Fundament”) — konta,
logowanie, role, obsada CC/U1/U2, nowy model danych; segment 2 („Mecze i obsada”) — lista meczów
z filtrami i stanem, strona meczu, błędy w formularzach; segment 3 („Wgrywanie i konwersja”) —
wznawialne wgrywanie (tus), deklaracja zawartości pliku, usuwanie oryginału po konwersji;
segment 2a („Docker lokalnie”) — obraz i Compose do testów na innych komputerach.
Kolejne segmenty (znaczniki „Zaznacz”, ekran opisywania, oceny, retencja, wdrożenie) opisuje plan.

## Wymagania i instalacja

- Python 3.12 (z modułem `venv`), ffmpeg + ffprobe.

```bash
sudo apt install ffmpeg            # konwersja i wycinanie wideo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Do testów: `.venv/bin/pip install -r requirements-dev.txt`.

Bez ffmpeg aplikacja startuje, ale w interfejsie widać komunikat
„Brak ffmpeg — uruchom: sudo apt install ffmpeg”, a zadania czekają w kolejce
(worker podejmie je sam po instalacji). Ścieżki można podać zmiennymi środowiskowymi
`FFMPEG_PATH` i `FFPROBE_PATH` (domyślnie z `PATH`).

### Pierwszy administrator

Nie ma publicznej rejestracji — pierwsze konto zakładasz poleceniem (pyta o e-mail, imię
i nazwisko oraz hasło; hasło min. 10 znaków):

```bash
.venv/bin/python -m app.create_admin
# albo bez pytań:
.venv/bin/python -m app.create_admin --email szef@example.com --name "Jan Kowalski" --password '...'
```

Polecenie tworzy bazę, jeśli jej nie ma. Uruchomione dla istniejącego e-maila nadaje rolę
administratora i ustawia nowe hasło — to też sposób na odzyskanie dostępu do konta admina.

> **Stare dane z prototypu.** Model danych i migracja zostały zastąpione nowymi (prototyp nie
> miał danych produkcyjnych). Jeśli masz katalog `data/` z poprzedniej wersji, usuń go
> (`rm -rf data`) przed pierwszym uruchomieniem — inaczej migracja zgłosi nieznaną rewizję.

## Uruchomienie

```bash
./run.sh
```

Skrypt tworzy/migruje bazę, startuje worker (`python -m app.worker`) w tle oraz serwer
(`uvicorn`) na porcie 8000. Otwórz w przeglądarce (także na Windowsie przy WSL2):
**http://localhost:8000** i zaloguj się kontem administratora. Ctrl+C zatrzymuje oba procesy.

Ręcznie, w dwóch terminalach:

```bash
.venv/bin/python -m app.initdb
.venv/bin/python -m uvicorn app.main:app --port 8000
.venv/bin/python -m app.worker
```

Zmienne środowiskowe:

| Zmienna | Znaczenie |
|---|---|
| `PORT`, `HOST` | adres serwera w `run.sh` |
| `REFCLIPS_DATA_DIR` | katalog danych (domyślnie `./data`): baza SQLite, wgrane pliki, wersje robocze, klipy |
| `DATABASE_URL` | adres bazy (domyślnie SQLite w katalogu danych) |
| `REFCLIPS_COOKIE_SECURE` | `1` ustawia ciasteczka z flagą `Secure` — włącz za HTTPS; lokalnie po `http://` zostaw wyłączone |
| `REFCLIPS_PUBLIC_URL` | adres aplikacji w linkach zaproszeń (np. `https://klipy.example.pl`); domyślnie z żądania |
| `REFCLIPS_TRUST_PROXY` | `1` bierze adres klienta (limit prób logowania) z `X-Forwarded-For` — tylko za zaufanym proxy |
| `REFCLIPS_UPLOAD_MAX_GB` | maks. rozmiar jednego wgrywanego pliku (domyślnie 8) |
| `REFCLIPS_DRAFT_RESERVE_GB` | miejsce rezerwowane na wersję roboczą przy przyjmowaniu uploadu (domyślnie 1,5) |
| `REFCLIPS_DISK_SAFETY_GB` | zapas wolnego miejsca, którego upload nie może zająć (domyślnie 3) |
| `REFCLIPS_FFMPEG_NICE` | priorytet (`nice`) ffmpeg w workerze (domyślnie 10, `0` = bez zmiany) |
| `REFCLIPS_V2_FEATURES` | `1` włącza ukryte funkcje wersji 2 (korekta granic klipu, eksport ZIP) |

## Uruchomienie w Dockerze (testy lokalne)

Sposób dla osoby, która chce tylko wypróbować aplikację na swoim komputerze: nie trzeba
instalować Pythona ani ffmpeg — wszystko jest w obrazie.

**Wymagania**

- Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/) z włączonym WSL2
  (instalator sam to proponuje); macOS: Docker Desktop; Linux: Docker Engine z wtyczką
  Compose (`docker compose version` musi działać).
- Git oraz dostęp do prywatnego repozytorium: przyjmij zaproszenie na GitHubie (mail od
  właściciela), a potem zaloguj się do GitHuba w Git (na Windowsie otworzy się okno logowania).
- Ok. 2 GB wolnego miejsca na obraz, plus miejsce na nagrania.

**Pierwsze uruchomienie** (w terminalu; na Windowsie PowerShell):

```bash
git clone https://github.com/fkula5/ref-clips.git
cd ref-clips
docker compose up -d --build
```

Pierwsze budowanie trwa kilka minut (pobiera się obraz Pythona i ffmpeg). Gdy skończy,
`docker compose ps` pokazuje usługę `app` jako `healthy`. Potem załóż konto administratora
(zapyta o e-mail, imię i nazwisko oraz hasło, min. 10 znaków):

```bash
docker compose run --rm app python -m app.create_admin
```

(albo bez pytań: `docker compose run --rm -T app python -m app.create_admin --email szef@example.com --name "Jan Kowalski" --password '...'`).
Otwórz **http://localhost:8000** i zaloguj się.

**Zapraszanie kolejnych osób.** W aplikacji: *Użytkownicy* → dodaj konto → skopiuj link
zaproszenia. Uwaga: link zaczyna się od `http://localhost:8000`, więc działa tylko na tym
komputerze (inna osoba musiałaby uruchomić własną kopię). Do prawdziwego udostępniania służy
wdrożenie na serwerze z HTTPS (osobny etap).

**Na co dzień**

| Co | Polecenie |
|---|---|
| Podgląd logów (Ctrl+C kończy podgląd) | `docker compose logs -f` (osobno: `logs -f worker`) |
| Zatrzymanie (dane zostają) | `docker compose stop` |
| Ponowne uruchomienie | `docker compose up -d` |
| Restart aplikacji i workera | `docker compose restart app worker` |
| Aktualizacja do nowej wersji | `git pull`, potem `docker compose up -d --build` (baza migruje się sama) |
| Wyłączenie i usunięcie kontenerów (dane zostają) | `docker compose down` |
| **Skasowanie wszystkich danych** (baza, nagrania, klipy) | `docker compose down -v` — **nieodwracalne** |

Ustawienia (port, limity wgrywania, itp.) zmieniasz w pliku `.env`: `cp .env.example .env`
(na Windowsie `copy .env.example .env`), edycja, `docker compose up -d`. Bez `.env` działają
wartości domyślne. Wszystkie opcje opisuje `.env.example`.

**Gdzie są dane.** W nazwanym woluminie Dockera `ref-clips_dane` (w kontenerach katalog
`/data`: baza SQLite, wgrane nagrania, wersje robocze, klipy). Przeżywa restart komputera,
`docker compose down` i aktualizację; znika po `down -v`. Kopia bazy: `docker compose cp app:/data/ref-clips.db .`.

**Typowe problemy**

- *„port is already allocated” / zajęty port 8000* — ustaw w `.env` inny port (`REFCLIPS_PORT=8001`)
  i otwórz `http://localhost:8001`.
- *„Cannot connect to the Docker daemon” / brak połączenia z Dockerem* — uruchom Docker Desktop
  i poczekaj, aż będzie „Running”.
- *Brak miejsca przy dużych nagraniach* — Docker Desktop trzyma dane na dysku wirtualnym
  o ograniczonym rozmiarze (Settings → Resources); aplikacja odmawia wgrania pliku, gdy miejsca
  brakuje (komunikat „Brak miejsca na serwerze”). Zwiększ limit dysku w Docker Desktop albo
  usuń niepotrzebne obrazy (`docker system prune`).
- *Konwersja trwa długo* — worker celowo działa z niskim priorytetem, a Docker Desktop domyślnie
  dostaje część procesorów komputera (Settings → Resources). Godzinny mecz może konwertować się
  kilkanaście minut lub dłużej; status widać na stronie meczu.
- *Nie mogę się zalogować na http://localhost* — w `.env` musi być `REFCLIPS_COOKIE_SECURE=0`.
- Dane na zwykłym katalogu zamiast woluminu (`./dane:/data`) wymagają, by katalog należał do
  użytkownika o UID 1000 (kontener nie działa jako root); najprościej zostać przy woluminie.

Test dymny całego zestawu (budowanie, start, założenie admina, wgranie wideo, konwersja):
`scripts/docker-smoke.sh` — działa na osobnym projekcie Compose i porcie 8123, na końcu po sobie sprząta.

## Konta, role i zapraszanie użytkowników

1. Administrator wchodzi w **Użytkownicy** (menu na górze) i dodaje konto: imię i nazwisko, e-mail
   (to login) oraz role. Aplikacja pokazuje **link zaproszenia** do skopiowania — wyślij go
   osobie sam (Messenger, SMS). Aplikacja nie wysyła e-maili.
2. Osoba otwiera link, ustawia hasło i loguje się. Link jest ważny 7 dni i działa tylko raz;
   po zamknięciu strony nie da się go odczytać, trzeba wygenerować nowy.
3. Zapomniane hasło: administrator klika przy koncie **Link resetu hasła** i wysyła nowy link.
   Reset wylogowuje konto ze wszystkich urządzeń.
4. Role można zmienić w każdej chwili; konto można dezaktywować (użytkownik zostaje wylogowany
   i nie zaloguje się, ale jego wpisy zostają). Zawsze musi zostać jeden aktywny administrator.

Role (kilka naraz, uprawnienia sumują się):

| Uprawnienie | Administrator | Szkoleniowiec | Sędzia |
|---|---|---|---|
| Zarządzanie kontami i rolami, słownikiem kategorii | tak | nie | nie |
| Przeglądanie wszystkich meczów i klipów, komentowanie | tak | tak | tak |
| Wgrywanie meczów i obsada, tworzenie i opisywanie klipów | każdy mecz | każdy mecz | tylko mecze, w których jest w obsadzie (po koncie) |
| Ocena klipu | nie (chyba że ma też rolę szkoleniowca) | tak, własna | nie |
| Edycja i usuwanie | wszystko | własne | własne |

Reguły są w jednym miejscu, `app/permissions.py` (czyste funkcje), a każda trasa zapisu sprawdza
je po stronie serwera (`auth.require(...)`); interfejs tylko ukrywa niedostępne przyciski.

Bezpieczeństwo: hasła hashowane argon2; sesja w ciasteczku `HttpOnly`, `SameSite=Lax`
(`Secure` przez `REFCLIPS_COOKIE_SECURE`), ważna 30 dni z odnawianiem, w bazie tylko hash tokenu;
limit 5 nieudanych prób logowania na 15 minut osobno na konto i na adres IP; token CSRF
w każdym formularzu i w nagłówku `X-CSRF-Token` zapytań HTMX/fetch. Każda strona poza logowaniem
i ustawieniem hasła wymaga zalogowania (strony przekierowują na `/login`, API zwraca 401).

## Workflow

1. **Nowy mecz** — data, liga, drużyny (nazwa + kolor strojów) i obsada **CC / U1 / U2**
   (U2 opcjonalnie). Każdą pozycję wypełniasz wyborem konta z rolą sędziego albo wpisaniem imienia
   i nazwiska (sędzia bez konta). Sędzia, który zakłada mecz, jest wstawiony na pierwszą
   pozycję (może zmienić funkcję), a serwer odrzuca mecz, w którego obsadzie go nie ma
   (dotyczy użytkownika, który nie jest administratorem ani szkoleniowcem). Ta sama osoba nie
   zajmie dwóch pozycji (to samo konto albo to samo wpisane nazwisko; wpisane nazwisko zgodne z
   nazwą konta to ta sama osoba). Pole „Liga” podpowiada ligi użyte wcześniej. Błędy pokazują
   się w formularzu z zachowanymi wartościami.
   Gdy sędzia wpisany ręcznie dostanie później konto, wystarczy wybrać konto w obsadzie
   (edycja meczu): jego klipy zostają przy nim, o ile imię i nazwisko konta jest takie samo
   (po normalizacji wielkości liter i polskich znaków) i nie ma drugiego konta o tej nazwie.
   **Lista meczów** (strona główna) ma filtry w adresie (daty od–do, liga, sędzia, „tylko moje”),
   paginację po 25 i stan meczu wyliczany z nagrań: brak nagrania, konwersja (z pozycją w
   kolejce), błąd konwersji, brak znaczników kwart, gotowy, pełne nagranie usunięte. Plik bez
   deklaracji zawartości liczy się jak cały mecz (wymaga znaczników Q1–Q4); plik z jedną kwartą
   znaczników nie wymaga. Na telefonie tabela zamienia się w karty. **Strona meczu** pokazuje
   obsadę (kto ma konto), nagrania i klipy meczu; usunięcie meczu poprzedza strona
   potwierdzenia z liczbą nagrań i klipów.
2. **Wgraj nagranie** (na stronie meczu; można kilka plików, np. osobne kwarty). Przy każdym
   pliku wskaż, **co zawiera**: cały mecz, jedną kwartę (Q1–Q4, OT1–OT3) albo kilka kwart.
   Wgrywanie jest **wznawialne** (protokół tus 1.0.0, `tus-js-client` przypięty w
   `static/vendor`): kawałki po 50 MB, automatyczne ponawianie po zerwaniu połączenia, a po
   odświeżeniu strony lub zamknięciu karty wystarczy wybrać ten sam plik i kliknąć „Wgraj” —
   wgrywanie pójdzie dalej od miejsca przerwania. „Przerwij” anuluje wgrywanie i usuwa dane.
   Plik trafia strumieniowo na dysk (`uploads/`), po ostatnim bajcie powstaje nagranie i zadanie
   konwersji. Limity: maks. 8 GB na plik, jedno niedokończone wgrywanie na użytkownika
   (kolejne zwraca czytelny błąd z możliwością przerwania poprzedniego), nieaktywne dłużej niż
   24 h jest usuwane przez worker (co godzinę). **Rezerwacja miejsca:** upload jest przyjmowany tylko
   wtedy, gdy wolne miejsce na dysku ≥ rozmiar pliku + 1,5 GB (wersja robocza) + 3 GB zapasu, licząc
   rezerwacje innych uploadów i oryginałów czekających na konwersję; inaczej błąd 507
   „Brak miejsca na serwerze, spróbuj później.”. Wgrywać do meczu mogą ci sami, co zakładają klipy
   (administrator, szkoleniowiec, sędzia z obsady); cudzego uploadu nie da się dotknąć.
   Deklarację zawartości można poprawić po wgraniu (**Edytuj** przy nagraniu). Plik z jedną
   kwartą dostaje automatycznie znacznik początku kwarty 0:00 (można go przesunąć), więc nie
   wymaga ręcznych znaczników; cały mecz i kilka kwart wymagają znaczników początku kwart
   (stan meczu „brak znaczników kwart”).
   Worker konwertuje plik do wersji roboczej (H.264 veryfast CRF 23, AAC, maks. 720p, maks. 30
   kl./s — wyższą liczbę klatek ograniczamy, niższej nie podnosimy — klatka kluczowa co sekundę,
   `+faststart`; ffmpeg działa z priorytetem `nice 10`, a cięcie klipów ma pierwszeństwo przed
   konwersją). Po konwersji sprawdza wynik (ffprobe: jest wideo, czas trwania zgodny z
   oryginałem do max(2 s, 1% długości); porównywana jest ścieżka wideo) i **usuwa oryginał**. Przy niezgodności nagranie dostaje błąd, a oryginał
   zostaje — „Ponów konwersję” działa tylko dopóki oryginał istnieje. Pełne nagranie dostaje
   termin ważności (`retention_days`, domyślnie 30). Szacunek czasu konwersji: patrz
   [plan techniczny](docs/plan-techniczny.md), rozdz. 6.2.
3. **Odtwarzacz** — skróty klawiszowe:

   | Klawisz | Działanie |
   |---|---|
   | Spacja | start / pauza |
   | ← / → | ±1 s (z Shift ±5 s) |
   | `,` / `.` | klatka wstecz / naprzód |
   | `[` / `]` | wolniejsze / szybsze tempo (0.25×–2×, także lista wyboru) |
   | `M` | dodaj klip w bieżącym czasie — wpisz np. `Filip kroki` i Enter |
   | `Q` | znacznik początku kwarty (kolejno Q1, Q2, Q3, Q4, OT1…) |

   Kwarta każdego klipu jest liczona ze znaczników początku kwart w czasie nagrania
   (ostatni znacznik nie późniejszy niż klip), a nie z odczytu zegara. W opisie klipu widać ją
   wprost, np. „Q2 · 4:12 od początku kwarty (czas nagrania)”. Znaczniki można w każdej chwili
   poprawić lub usunąć — kwarty klipów przeliczą się same.
4. **Notatki** — „Wklej notatki” przy nagraniu. Jedna linia to jeden moment:
   ```
   2:54 Filip kroki
   3:17 U1 dlaczego nie blok?
   1:02:15 CC faul techniczny
   ```
   Czas: `m:ss`, `mm:ss`, `h:mm:ss` (także `2.54`, `2,54`). Po czasie pierwsze słowo to sędzia:
   imię, nazwisko albo funkcja **CC/U1/U2** (bez względu na wielkość liter i polskie znaki).
   Kategoria jest rozpoznawana ze słownika kategorii i jego aliasów; reszta linii trafia do
   opisu. Pokazuje się tabela podglądu z ostrzeżeniami (nieznany sędzia, nierozpoznany czas,
   kilka kategorii) — każdą linię można poprawić — i przycisk **Wytnij wszystkie zaznaczone**.
5. **Klipy** — lista z filtrami (mecz, sędzia, kategoria, kwarta). Na stronie klipu: odtwarzanie,
   opis (sędzia z obsady albo „cały zespół”, kategoria ze słownika lub „własna”, tekst),
   komentarze, pobranie MP4. Klip bez opisu jest oznaczony jako „nieopisany”.

Słownik kategorii (grupy Faule, Naruszenia, Bez gwizdka, Mechanika, Inne) jest zakładany
przy pierwszym uruchomieniu (`app/seed.py`); edycja z poziomu panelu to segment 7. Klipy
wycinane są dokładnie (z przekodowaniem) z wersji roboczej; margines przed/po to domyślnie
15 s, obcinany do granic nagrania.

Ukryte w MVP (kod zostaje w repozytorium, wraca w wersji 2): korekta początku i końca klipu oraz
eksport ZIP (`app/routers/clips_v2.py`, włączane `REFCLIPS_V2_FEATURES=1`), stara strona tagów
(zastąpiona kategoriami).

## Testy

```bash
.venv/bin/python -m pytest
```

Testy wideo (konwersja, ograniczenie klatek, usuwanie oryginału, wycinanie, obcięcie do granic
nagrania, przepływ tus → worker → gotowe nagranie) używają
prawdziwego ffmpeg i są pomijane, gdy go brak. Testy uprawnień (`tests/test_permissions.py`)
obejmują każdy wiersz tabeli uprawnień ze specyfikacji dla każdej roli i ich kombinacji oraz
żądania wysyłane wprost do API, które serwer ma odrzucić (403).

## Struktura

```
app/main.py            aplikacja FastAPI, dołączanie tras z wymogiem logowania i CSRF
app/auth.py            sesja, CSRF, zależność require(...) dla tras
app/accounts.py        logowanie z limitem prób, sesje, zaproszenia, zarządzanie kontami
app/permissions.py     uprawnienia (czyste funkcje, jedno miejsce)
app/create_admin.py    polecenie zakładające pierwszego administratora
app/routers/           trasy: logowanie, panel admina, mecze, nagrania/odtwarzacz/notatki, klipy
app/models.py          model danych (SQLAlchemy 2), migracje w alembic/
app/seed.py            słownik kategorii i ustawienia domyślne
app/notes_parser.py    parser notatek (czysta funkcja)
app/routers/uploads.py protokół tus (wgrywanie wznawialne); logika sesji, rezerwacji miejsca i sprzątania: app/uploads.py
app/video.py           ffprobe/ffmpeg: konwersja, weryfikacja wyniku i wycinanie
app/storage.py         magazyn plików (lokalny; interfejs pod przyszłe S3)
app/worker.py          pętla zadań z tabeli jobs
Dockerfile, compose.yaml, .env.example   obraz i uruchomienie w Dockerze (app, worker, init)
scripts/docker-smoke.sh                  test dymny Dockera
app/services.py        obsada, kwarty, granice klipów, nazwy plików, kolejka
app/templates, static  interfejs (Jinja2, HTMX 2.0.4 w static/vendor, czysty JS)
tests/                 pytest
```
