# ref-clips

Aplikacja webowa do wycinania i analizy decyzji sędziowskich z meczów koszykówki, dla sędziów
i szkoleniowców jednego okręgu. Wgrywasz nagranie, zaznaczasz momenty albo wklejasz notatki typu
`2:54 Filip kroki`, a aplikacja wycina z każdego wpisu klip (15 s przed i 15 s po) i porządkuje
klipy z opisem, komentarzami i ocenami szkoleniowców.

Dokumentacja projektu: [specyfikacja MVP](docs/specyfikacja-mvp.md),
[plan techniczny](docs/plan-techniczny.md). Stan prac: segment 1 („Fundament”) — konta,
logowanie, role, obsada CC/U1/U2, nowy model danych; segment 2 („Mecze i obsada”) — lista meczów
z filtrami i stanem, strona meczu, błędy w formularzach; segment 3 („Wgrywanie i konwersja”) —
wznawialne wgrywanie (tus), deklaracja zawartości pliku, usuwanie oryginału po konwersji;
segment 2a („Docker lokalnie”) — obraz i Compose do testów na innych komputerach;
segment 4 („Znaczniki”) — klawisz „Zaznacz”, początki kwart wg deklaracji pliku, notatki przy wgrywaniu;
segment 4a („Testy interfejsu”) — automatyczne testy w przeglądarce (Playwright, Chromium);
segment 5 („Klipy”) — ekran opisywania znaczników, zakładka „Klipy” meczu z filtrami, widok klipu;
segment 6 („Oceny i komentarze”) — oceny szkoleniowców, komentarze do meczu i klipu, widoki mobilne;
segment 7 („Admin i retencja”) — panel kategorii, retencji i dysku, zadanie `retention` w workerze.
Kolejny segment (wdrożenie na VPS) opisuje plan.

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
| `REFCLIPS_TEST_UPLOAD_CHUNK_KB` | **tylko testy interfejsu:** rozmiar kawałka tus w KB (domyślnie 50 MB); nie ustawiaj w produkcji |
| `REFCLIPS_V2_FEATURES` | `1` włącza ukryte funkcje wersji 2 (korekta granic klipu, eksport ZIP) |

## Uruchomienie w Dockerze (testy lokalne)

Sposób dla osoby, która chce tylko wypróbować aplikację na swoim komputerze: nie trzeba
instalować Pythona ani ffmpeg — wszystko jest w obrazie.

**Wymagania**

- Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/) z włączonym WSL2
  (instalator sam to proponuje); macOS: Docker Desktop; Linux: Docker Engine z wtyczką
  Compose (`docker compose version` musi działać). Potrzebny Docker Compose w wersji
  **2.24 lub nowszej** (Docker Desktop z 2024 r. lub nowszy) — sprawdź poleceniem
  `docker compose version`; starszy Compose zgłosi błąd o nieznanym polu `required` w `compose.yaml`.
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

**Dostęp tylko z tego komputera.** Aplikacja nasłuchuje wyłącznie na `127.0.0.1`, więc nie jest
widoczna dla innych urządzeń w sieci (Wi-Fi, akademik, praca). Żeby wejść z telefonu w domowej sieci,
trzeba to zmienić świadomie: w `.env` ustaw `REFCLIPS_BIND=0.0.0.0`, wykonaj `docker compose up -d`
i otwórz `http://<adres komputera w sieci>:8000` na telefonie. Uwaga: to zwykłe HTTP, bez
szyfrowania, a w aplikacji są nagrania z wizerunkiem zawodników (także niepełnoletnich) —
włączaj tylko w zaufanej sieci i po teście wróć do `127.0.0.1`.

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

## Wdrożenie na serwerze (produkcja)

Konfiguracja produkcyjna (Caddy z HTTPS, kopie zapasowe, skrypt wdrożenia z komputera lokalnego) jest
opisana w [docs/wdrozenie.md](docs/wdrozenie.md): `compose.prod.yaml` (nakładka na `compose.yaml`),
`deploy/Caddyfile`, `deploy/env.prod.example`, `deploy/deploy.sh`, `deploy/backup.sh`. Odtwarzanie
z kopii: [deploy/restore.md](deploy/restore.md).

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

## Panel administratora (segment 7)

Menu **Administracja** (tylko rola administratora; serwer sprawdza to na każdej trasie, pozostałe role dostają 403,
niezalogowani 401/przekierowanie na logowanie, a zapisy wymagają tokenu CSRF) ma trzy zakładki.

**Użytkownicy** — konta, role, linki zaproszeń (opisane wyżej).

**Kategorie** (`/admin/categories`) — słownik w grupach Faule / Naruszenia / Bez gwizdka / Mechanika / Inne:
- dodawanie, zmiana nazwy, grupy i aliasów (po przecinku), kolejność (↑/↓ w obrębie grupy), aktywacja i dezaktywacja;
- nazwa i aliasy są porównywane bez względu na wielkość liter i polskie znaki, tak jak w parserze notatek. Nazwa musi być
  unikalna, a alias nie może powtarzać nazwy ani aliasu innej kategorii (także nieaktywnej) ani funkcji CC/U1/U2 —
  parser nie umiałby wtedy rozstrzygnąć, którą kategorię wybrać, więc zapis jest odrzucany z czytelnym błędem;
- **kategorię użytą w klipach można tylko dezaktywować** (nie usunąć). Nieaktywna znika z wyboru w formularzach opisu,
  w podglądzie notatek i z rozpoznawania w parserze, ale klipy, które ją mają, dalej ją pokazują (z dopiskiem
  „nieaktywna” w formularzu), a zapis opisu bez zmian zachowuje kategorię; filtry klipów nadal ją znają. Kategorię
  nieużywaną można usunąć;
- kategorii „własna” (nazwa wpisywana przy klipie) nie można dezaktywować ani usunąć.

**Retencja i dysk** (`/admin/retention`):
- *Retencja pełnych nagrań:* liczba dni (1–365, domyślnie 30), po których usuwana jest wersja robocza pełnego nagrania.
  Zmiana dotyczy **nowych** nagrań; termin istniejących zostaje, chyba że zaznaczysz „przelicz termin dla istniejących
  nagrań” — wtedy staje się on datą wgrania + N dni (ostrzeżenie przed zapisem; nagrania starsze niż N dni znikną przy
  najbliższym sprzątaniu workera, klipy zostają). Obok widać czas i wynik ostatniego uruchomienia zadania retencji.
- *Zajętość dysku:* pełne nagrania (wersje robocze), oryginały w konwersji i niedokończone uploady, klipy, wolne miejsce,
  miejsce zarezerwowane dla trwających uploadów i konwersji oraz największy plik, jaki nowy upload może teraz zająć.
  Rozmiary pochodzą z bazy (`videos.proxy_bytes`, `videos.size_bytes`, `upload_sessions.offset_bytes`); jedynie katalog
  klipów jest czytany z dysku (jedno przejście po katalogu), więc strona nie robi zapytań o każdy plik. Rozmiar wersji
  roboczej starszych nagrań jest uzupełniany przy pierwszym otwarciu strony.
- *Lista nagrań* (mecz, nagranie, data wgrania, termin usunięcia, rozmiar, liczba klipów), od najbliższego terminu.
  **Usuń pełne nagranie teraz** (z potwierdzeniem) kasuje wersję roboczą (i oryginał, jeśli został po błędzie konwersji)
  oraz ustawia `purged_at`; klipy zostają. Przycisku nie ma (a serwer odpowiada 409), gdy nagranie jest wgrywane lub
  konwertowane albo gdy klipy z niego czekają na wycięcie (status „nowy” / „w kolejce do cięcia”) — usunięcie
  zostawiłoby je w kolejce na zawsze; trzeba poczekać, aż worker je wytnie.
- *Ostrzeżenie o braku miejsca:* upload odrzucony kodem 507 zapisuje się (czas, użytkownik, plik, rozmiar, wolne miejsce,
  tabela `upload_rejections`, wpisy starsze niż 30 dni są usuwane). Odrzucenia z ostatnich 7 dni pokazuje baner na
  wszystkich zakładkach panelu i tabela na zakładce „Retencja i dysk”.

### Retencja pełnych nagrań

- Pełne nagranie dostaje termin (`videos.expires_at`) = wgranie + `retention_days` (domyślnie 30). Na **7 dni przed
  terminem** lista meczów, strona meczu, panel nagrań i odtwarzacz pokazują „pełne nagranie dostępne jeszcze X dni”
  (po terminie, a przed sprzątaniem: „zostanie usunięte w najbliższym sprzątaniu”). Wcześniej strona meczu pokazuje
  tylko datę w panelu nagrań.
- **Po usunięciu** nagranie nie ma odtwarzacza, a każda trasa zapisu, która potrzebuje wersji roboczej (znacznik `Z`,
  cofnięcie, znacznik z notatką `M`, notatki, początki kwart, ponowne cięcie, korekta granic w wersji 2), zwraca 409
  z komunikatem „Pełne nagranie zostało usunięte…” zamiast błędu serwera. Znaczniki kwart i deklaracja zawartości są
  zamrożone („Edytuj” przy nagraniu zmienia już tylko etykietę), więc kwarty klipów zostają takie, jakie były. Klipy
  wycięte wcześniej odtwarzają się normalnie.
- **Klip z nieustaloną kwartą** (brak znaczników kwart) po usunięciu pełnego nagrania **można już opisać**: kwart nie da
  się ustawić, więc blokada opisu przestaje obowiązywać, a klip dalej pokazuje „kwarta nieustalona” (kwarta jest
  liczona ze znaczników `period_marks`; ich brak oznacza właśnie to).

### Co robi worker poza konwersją i cięciem

Raz na godzinę (i zaraz po starcie) `python -m app.worker` wykonuje sprzątanie; każdy krok jest niezależny (błąd jednego
nie wstrzymuje pozostałych):
1. nieaktywne uploady (> 24 h) i osierocone pliki `.part`;
2. wpisy o odrzuconych uploadach starsze niż 30 dni;
3. **zadanie `retention`** — raz na dobę usuwa wersje robocze nagrań po terminie (`expires_at` w przeszłości),
   ustawia `purged_at` i loguje wynik; pomija nagrania w konwersji i takie, z których czekają klipy na cięcie
   (wrócą w następnym przebiegu). Czas ostatniego uruchomienia zapisywany jest atomowym `UPDATE` w tabeli `settings`
   (`retention_last_run`), więc restart workera w ciągu doby ani dwa workery naraz nie uruchomią zadania drugi raz,
   a po dłuższej przerwie nadrobi się przy starcie;
4. osierocone pliki klipów: pliki `.mp4` w `clips/`, do których nie prowadzi `clip_path` żadnego klipu (np. po
   usunięciu znacznika w trakcie cięcia), starsze niż godzina.

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
3. **Odtwarzacz** — przeglądasz nagranie i zaznaczasz momenty, opisujesz je później. Skróty
   (pomoc pod klawiszem `?` na stronie):

   | Klawisz | Działanie |
   |---|---|
   | `Z` (przycisk „Zaznacz”) | **znacznik w bieżącym czasie, bez zatrzymywania odtwarzania** — nieopisany klip (po 15 s przed i po), od razu w kolejce do cięcia; błysk na obrazie i licznik znaczników |
   | `Backspace` | cofnij swój ostatni nieopisany znacznik (usuwa też plik klipu) |
   | `M` | znacznik z notatką: pauza i pole tekstowe (sędzia, kategoria, opis jak w notatkach) |
   | `Q` | ustaw początek następnej brakującej kwarty w bieżącym czasie |
   | `F` | pełny ekran (kontener z wideo — znaczniki, błysk i przycisk „Zaznacz” działają także w pełnym ekranie) |
   | Spacja | start / pauza |
   | ← / → | ±1 s (z Shift ±5 s) |
   | `,` / `.` | klatka wstecz / naprzód |
   | `[` / `]` | wolniejsze / szybsze tempo (0.25×–2×, także lista wyboru) |
   | `?` | pomoc ze skrótami |

   **Znaczniki** są widoczne na liście obok odtwarzacza: czas w nagraniu (kliknięcie przewija),
   kwarta i czas od jej początku albo „kwarta nieustalona”, stan cięcia, opisany/nieopisany i
   usunięcie (×; klip już opisany wymaga potwierdzenia). Dwa znaczniki tego samego autora w
   tym samym nagraniu w odstępie krótszym niż sekunda to podwójne kliknięcie — serwer ignoruje drugi.
   Przycisk „Zaznacz” widzą i mogą używać administrator, szkoleniowiec oraz sędzia z obsady meczu
   (serwer egzekwuje to także dla żądań z pominięciem interfejsu). Nagranie, którego pełną wersję
   usunięto (retencja), nie ma odtwarzacza ani znaczników — strona pokazuje komunikat, a wycięte klipy zostają.
   Uwaga: w przeglądarkach bez `requestFullscreen` na kontenerze (np. Safari na iPhonie) pełny ekran
   natywnego odtwarzacza nie pokazuje błysku — klawisz `Z` nadal działa, ale potwierdzenie widać dopiero po wyjściu.

   **Początki kwart.** Panel „Początki kwart” wypisuje kwarty z deklaracji pliku: cały mecz
   Q1–Q4 (wymagane) i OT1–OT3 (opcjonalne), kilka kwart — tylko zadeklarowane, jedna kwarta —
   tylko ta (jej znacznik 0:00 powstaje sam i można go przesunąć, ale nie usunąć). Przy każdej kwarcie jest
   „Ustaw tutaj” / „Ustaw ponownie tutaj” (bieżący czas nagrania) i usunięcie; `Q` ustawia następną
   brakującą w kolejności deklaracji. Serwer odrzuca kwarty spoza deklaracji i kolejność
   niezgodną z chronologią (Q2 nie może zaczynać się przed Q1; jedna kwarta = jeden znacznik).
   Dopóki plik z wieloma kwartami nie ma kompletu znaczników, strona meczu i odtwarzacz pokazują baner
   „Ustaw początki kwart, żeby klipy miały kwartę i czas” z linkiem; klipy mają wtedy kwartę
   „nieustaloną”, a wycinanie działa. Zmiana deklaracji w „Edytuj” przy nagraniu, która usunęłaby
   znaczniki kwart, najpierw pokazuje ich listę i wymaga potwierdzenia.

   Kwarta każdego klipu jest liczona ze znaczników początku kwart w czasie nagrania
   (ostatni znacznik nie późniejszy niż klip), a nie z odczytu zegara. W opisie klipu widać ją
   wprost, np. „Q2 · 4:12 od początku kwarty (czas nagrania)”. Znaczniki można w każdej chwili
   poprawić lub usunąć — kwarty klipów przeliczą się same.
4. **Notatki** — przy wgrywaniu albo później („Wklej notatki” przy gotowym nagraniu). Jedna linia to jeden moment:
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

   **Notatki przy wgrywaniu.** W formularzu wgrywania każdy plik ma opcjonalne pole „Notatki do tego
   pliku” i przycisk **Podgląd** (tabela z obsadą meczu i słownikiem kategorii oraz ostrzeżeniami,
   przed wysłaniem; tekst można poprawić i ponowić podgląd). Notatki jadą na serwer osobnym żądaniem
   `POST /uploads/{id}/notes` zaraz po utworzeniu sesji tus (zapis w `upload_sessions.notes`, nie w
   nagłówku `Upload-Metadata`; limit 20 000 znaków i 300 linii) i nie zależą od kolejności względem
   ostatniego bajtu. Po zakończeniu wgrywania z linii z poprawnym czasem powstają **nieopisane klipy**
   (sędzia i kategoria ustawione, jeśli parser je rozpoznał; opis zatwierdza się później), a cięcie
   czeka na gotową wersję roboczą. Długość nagrania jest znana dopiero po konwersji, więc klip z
   momentem poza nagraniem dostaje stan błędu „Moment poza nagraniem” zamiast cichego obcięcia.
   Do czasu ustawienia znaczników kwart klipy mają kwartę „nieustaloną”.
5. **Opisywanie znaczników** — po obejrzeniu nagrania opisujesz znaczniki w jednym miejscu. Wejście:
   przycisk **Opisz znaczniki (N)** na stronie meczu (wszystkie nagrania, w kolejności nagranie → czas) albo
   w odtwarzaczu (tylko to nagranie; licznik N rośnie przy każdym „Zaznacz”). Ekran pokazuje z boku listę
   nieopisanych znaczników (czas, kwarta albo „kwarta nieustalona”, autor, stan cięcia), a w głównej części
   podgląd klipu i pola opisu:
   - **podgląd:** plik klipu, gdy już wycięty; gdy klip czeka w kolejce — wersja robocza od startu do końca
     klipu (odtwarzanie zatrzymuje się na końcu zakresu);
   - **sędzia** (CC / U1 / U2 z obsady meczu albo „cały zespół”), **kategoria** (lista pogrupowana wg grup
     słownika; „własna” wymaga nazwy, do 100 znaków) i **opis** (opcjonalny, do 2000 znaków). Sędzia i kategoria są
     wymagane do zatwierdzenia;
   - **propozycje z notatek:** klipy z notatek (przy wgrywaniu, „Wklej notatki”, `M` w odtwarzaczu) mają już
     rozpoznanego sędziego i kategorię — są wstępnie wybrane, oznaczone „propozycja” i zapisują się dopiero po
     zatwierdzeniu;
   - **Zapisz i dalej** ustawia `described_at` (pierwsze zatwierdzenie; edycja go nie zmienia) i przechodzi do
     następnego nieopisanego (po ostatnim wraca do pierwszego z pominiętych; gdy nic nie zostało — komunikat
     „Wszystkie znaczniki są opisane”); **Pomiń** przechodzi dalej bez zapisu; **Usuń znacznik** pyta o potwierdzenie
     i usuwa też plik klipu;
   - **kwarta nieustalona:** klipu z nagrania, które wymaga znaczników kwart (cały mecz, kilka kwart), a nie ma
     kompletu — albo z momentu przed początkiem pierwszej kwarty — **nie da się opisać** (serwer też odmawia).
     Ekran pokazuje komunikat z linkiem do panelu „Początki kwart” w odtwarzaczu. Wyjątek: gdy pełne nagranie
     zostało usunięte (retencja), kwart nie da się już ustawić, więc klip można opisać z kwartą „nieustaloną”.

   Skróty w ekranie opisywania (nie działają w polach tekstowych):

   | Klawisz | Działanie |
   |---|---|
   | `1` / `2` / `3` / `0` | sędzia CC / U1 / U2 / cały zespół |
   | `K` | przejście do listy kategorii (wpisanie początku nazwy wybiera kategorię) |
   | `D` | przejście do pola opisu |
   | Spacja / `R` | odtwórz–pauza podglądu / od początku klipu |
   | `Enter` (w formularzu, także na liście kategorii) | zapisz i dalej |
   | `Ctrl+Enter` (w opisie) | zapisz i dalej |

   Opisywać mogą administrator i szkoleniowiec w każdym meczu oraz sędzia w meczach, w których jest w obsadzie
   (`can_describe_clip`; serwer odmawia pozostałym kodem 403 na ekranie i wszystkich trasach zapisu).
6. **Klipy meczu** — na stronie meczu sekcja „Klipy” z filtrami: **sędzia** (obsada meczu albo „cały zespół”),
   **kategoria**, **kwarta** (także „nieustalona”), **oceny** (z dowolną oceną, „ma ocenę: prawidłowa /
   nieprawidłowa / dyskusyjna”, bez ocen) i **opisane / nieopisane**. Filtry są w adresie
   (`?person=…&category_id=…&period=Q2&rating=none&described=0`), działają bez JavaScriptu (zwykły formularz GET), a HTMX
   podmienia tylko listę i wpisuje filtry do adresu. Wiersz: sędzia (funkcja + nazwisko), kategoria,
   „kwarta · czas od początku kwarty” (czas nagrania, nie zegar meczowy), czas w nagraniu, skrót opisu, stan,
   podsumowanie ocen (np. „2× prawidłowa”, „1× dyskusyjna”) z liczbą komentarzy i link do klipu; na telefonie
   wiersze to karty.
   Globalna lista `/clips` ma te same filtry (plus mecz).
7. **Klip** — odtwarzacz klipu, opis (sędzia, kategoria, „Q2 · 4:12 od początku kwarty (czas nagrania)” z dopiskiem
   „czas nagrania – nie zegar meczowy”, opis, kto dodał znacznik i kiedy, kiedy opisano), pobranie MP4 (nazwa
   pliku `kategoria-rozgrywek_nazwisko_decyzja.mp4`, np. `III-liga_Kowalski_blok-szarza.mp4`; liczona na bieżąco,
   więc po zmianie opisu pobrany plik ma nową nazwę; tylko znaki ASCII, nazwa własnej kategorii skrócona do 40 znaków),
   oceny szkoleniowców, komentarze, link do tego momentu w pełnym nagraniu (tylko gdy pełne nagranie nie zostało usunięte), formularz
   edycji opisu (te same pola i walidacja co na ekranie opisywania) i **poprzedni / następny klip meczu**
   według filtrów, z których użytkownik przyszedł (filtry przechodzą w adresie; bez filtrów — wg czasu).
   Klip w stanie błędu pokazuje przyczynę; uprawnieni mają „Wytnij ponownie” (nie, gdy moment jest poza nagraniem
   albo pełnego nagrania już nie ma) i „Usuń klip”. Klip bez opisu jest oznaczony „nieopisany”.
8. **Oceny i komentarze** (segment 6).
   - **Oceny:** na stronie klipu każdy szkoleniowiec (rola `coach`; sama rola administratora nie wystarcza)
     wystawia własną ocenę — prawidłowa / nieprawidłowa / dyskusyjna — z opcjonalnym komentarzem. Ocena jest jedna
     na parę (klip, szkoleniowiec): ponowny zapis ją aktualizuje (strona pokazuje „zmieniona” z datą). Widać
     wszystkie oceny z autorem i datą; sędzia widzi je bez formularza. Zmienić lub usunąć ocenę może jej autor
     albo administrator; administrator zmienia cudzą ocenę, ale autorem zostaje szkoleniowiec.
   - **Komentarze** do meczu (strona meczu) i klipu (strona klipu): komentuje każdy zalogowany; autor edytuje swój
     (przy komentarzu „edytowano” z datą), autor albo administrator usuwa (administrator nie edytuje cudzych).
     Treść to zwykły tekst (do 5000 znaków, łamania linii zachowane), bez HTML. Dodawanie, edycja inline
     (z „Anuluj”) i usuwanie (z potwierdzeniem) działają przez HTMX bez przeładowania strony, a bez JavaScriptu jako
     zwykłe formularze z przekierowaniem. Sekcja komentarzy meczu jest poza obszarem odświeżanym co 3 s, więc
     wpisywany tekst i otwarta edycja przeżywają odświeżanie panelu nagrań.
   - **Telefon:** strona klipu, tabela klipów (karty) i komentarze są czytelne na szerokości ok. 375 px bez
     poziomego przewijania; odtwarzacz meczu i ekran opisywania zostają pod komputer.

Słownik kategorii (grupy Faule, Naruszenia, Bez gwizdka, Mechanika, Inne) jest zakładany
przy pierwszym uruchomieniu (`app/seed.py`); edytuje go administrator w panelu (zakładka „Kategorie”). Klipy
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

## Testy interfejsu (E2E)

Testy w prawdziwej przeglądarce (Chromium sterowany przez [Playwright](https://playwright.dev/python/)):
logowanie, konta i zaproszenia, formularz meczu, wgrywanie (tus, przerwanie i wznowienie, notatki
z podglądem), odtwarzacz i skróty klawiszowe, znaczniki, uprawnienia w interfejsie, strona klipu
z ocenami i komentarzami (HTMX, także bez JavaScriptu; odświeżanie strony meczu a wpisywany komentarz; widoki 375×740), ekran opisywania (skróty klawiszowe, propozycje z notatek, kwarta nieustalona),
zakładka klipów meczu (filtry HTMX i bez JS, karty na telefonie), nawigacja poprzedni/następny, lista meczów
(filtry, paginacja, widok mobilny) i strony błędów, panel admina (kategorie, retencja, dysk, ręczne usunięcie pełnego nagrania, baner o braku miejsca).
Test uruchamia prawdziwy serwer (uvicorn) i worker na wolnym porcie z tymczasowym katalogiem danych,
konta zakłada kodem aplikacji, a wideo próbne generuje ffmpeg-iem. Każdy test kończy się porażką,
gdy w konsoli przeglądarki pojawi się błąd JavaScript (poza jawnie dopuszczonymi).

```bash
.venv/bin/pip install -r requirements-dev.txt      # także playwright i pytest-playwright
.venv/bin/playwright install chromium              # jednorazowo: przeglądarka (ok. 120 MB w ~/.cache/ms-playwright)
scripts/e2e.sh                                     # albo: .venv/bin/python -m pytest -m e2e
scripts/e2e.sh -k upload                           # wybrane testy; E2E_KEEP=1 zostawia katalog danych
```

Całość trwa ok. 1,5 minuty. Zwykłe `pytest` pomija testy `e2e` (są wolne), więc szybkie testy jednostkowe
zostają szybkie. Przy porażce zrzut ekranu, log konsoli przeglądarki i logi serwera i workera zapisują się
w `/tmp/refclips-e2e-artifacts/<data>/<test>/`, a ścieżka jest w komunikacie błędu. Jeśli Chromium nie
startuje z powodu brakujących bibliotek systemowych, doinstaluj je: `sudo .venv/bin/playwright install-deps chromium`.
Pełnego ekranu „na prawdziwym monitorze”, Safari i iPhone'a w ten sposób nie sprawdzimy (Chromium headless
sprawdza tylko API pełnego ekranu i układ w wąskim oknie 390×844).

## Struktura

```
app/main.py            aplikacja FastAPI, dołączanie tras z wymogiem logowania i CSRF
app/auth.py            sesja, CSRF, zależność require(...) dla tras
app/accounts.py        logowanie z limitem prób, sesje, zaproszenia, zarządzanie kontami
app/permissions.py     uprawnienia (czyste funkcje, jedno miejsce)
app/create_admin.py    polecenie zakładające pierwszego administratora
app/routers/           trasy: logowanie, panel admina, mecze, nagrania/odtwarzacz/notatki, klipy, ekran opisywania
app/clip_list.py       filtry klipów z adresu (zakładka meczu, /clips, poprzedni/następny), podsumowanie ocen
app/feedback.py        oceny i komentarze: walidacja, zapis oceny (upsert), liczniki; trasy: app/routers/feedback.py
app/models.py          model danych (SQLAlchemy 2), migracje w alembic/
app/seed.py            słownik kategorii i ustawienia domyślne
app/notes_parser.py    parser notatek (czysta funkcja)
app/routers/uploads.py protokół tus (wgrywanie wznawialne); logika sesji, rezerwacji miejsca i sprzątania: app/uploads.py
app/video.py           ffprobe/ffmpeg: konwersja, weryfikacja wyniku i wycinanie
app/storage.py         magazyn plików (lokalny; interfejs pod przyszłe S3)
app/worker.py          pętla zadań z tabeli jobs, sprzątanie okresowe
app/retention.py       retencja pełnych nagrań (termin, usuwanie, zadanie dobowe), osierocone pliki klipów
app/disk.py            zajętość dysku i lista nagrań dla panelu, odrzucone uploady
app/categories.py      słownik kategorii: walidacja nazw i aliasów, kolejność, aktywacja
Dockerfile, compose.yaml, .env.example   obraz i uruchomienie w Dockerze (app, worker, init)
compose.prod.yaml, deploy/               produkcja: Caddy, wdrożenie (deploy.sh), kopie zapasowe; docs/wdrozenie.md
scripts/docker-smoke.sh                  test dymny Dockera
scripts/e2e.sh, tests/e2e/               testy interfejsu w przeglądarce (Playwright)
app/services.py        obsada, kwarty, granice klipów, nazwy plików, kolejka
app/templates, static  interfejs (Jinja2, HTMX 2.0.4 w static/vendor, czysty JS)
tests/                 pytest (testy jednostkowe i API; interfejs: tests/e2e)
```
