# ref-clips

Aplikacja webowa do wycinania i analizy decyzji sędziowskich z meczów koszykówki, dla sędziów
i szkoleniowców jednego okręgu. Wgrywasz nagranie, zaznaczasz momenty albo wklejasz notatki typu
`2:54 Filip kroki`, a aplikacja wycina z każdego wpisu klip (15 s przed i 15 s po) i porządkuje
klipy z opisem, komentarzami i (docelowo) ocenami szkoleniowców.

Dokumentacja projektu: [specyfikacja MVP](docs/specyfikacja-mvp.md),
[plan techniczny](docs/plan-techniczny.md). Stan prac: segment 1 („Fundament”) — konta,
logowanie, role, obsada CC/U1/U2, nowy model danych. Kolejne segmenty (tus, znaczniki „Zaznacz”,
ekran opisywania, oceny, retencja, wdrożenie) opisuje plan.

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
| `REFCLIPS_V2_FEATURES` | `1` włącza ukryte funkcje wersji 2 (korekta granic klipu, eksport ZIP) |

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
   (dotyczy użytkownika, który nie jest administratorem ani szkoleniowcem).
2. **Wgraj nagranie** (na stronie meczu; można kilka plików, np. osobne kwarty). Plik jest
   zapisywany strumieniowo na dysk z paskiem postępu (wznawialne wgrywanie przez tus to
   segment 3). Worker konwertuje go do wersji roboczej (H.264/AAC, maks. 720p, klatka kluczowa
   co sekundę, `+faststart`). Pełne nagranie dostaje termin ważności (`retention_days`, domyślnie 30).
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

Testy wideo (konwersja, wycinanie, obcięcie do granic nagrania, przepływ end-to-end) używają
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
app/video.py           ffprobe/ffmpeg: konwersja i wycinanie
app/storage.py         magazyn plików (lokalny; interfejs pod przyszłe S3)
app/worker.py          pętla zadań z tabeli jobs
app/services.py        obsada, kwarty, granice klipów, nazwy plików, kolejka
app/templates, static  interfejs (Jinja2, HTMX z CDN unpkg w wersji 2.0.4, czysty JS)
tests/                 pytest
```

Uwaga: HTMX jest ładowany z CDN (unpkg, wersja przypięta) — do odświeżania list i komentarzy
potrzebny jest dostęp do internetu w przeglądarce (przypięcie pliku w `static/` zaplanowano w planie).
