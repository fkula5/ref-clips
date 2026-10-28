# ref-clips

Lokalna aplikacja webowa do wycinania i analizy decyzji sędziowskich z meczów koszykówki.
Wgrywasz nagranie (Veo, telefon, inny plik), zaznaczasz momenty albo wklejasz notatki typu
`2:54 Filip PTS`, a aplikacja wycina z każdego wpisu klip (domyślnie ±10 s) i porządkuje je
w liście z filtrami, komentarzami i eksportem do ZIP.

Etap 1 (to repozytorium): wersja lokalna dla jednego użytkownika. Model danych jest już
przygotowany pod grupę (użytkownik z rolą, autor wpisu, widoczność klipu).

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

## Uruchomienie

```bash
./run.sh
```

Skrypt tworzy/migruje bazę, startuje worker (`python -m app.worker`) w tle oraz serwer
(`uvicorn`) na porcie 8000. Otwórz w przeglądarce (także na Windowsie przy WSL2):
**http://localhost:8000**. Ctrl+C zatrzymuje oba procesy.

Ręcznie, w dwóch terminalach:

```bash
.venv/bin/python -m app.initdb
.venv/bin/python -m uvicorn app.main:app --port 8000
.venv/bin/python -m app.worker
```

Zmienne: `PORT`, `HOST` (run.sh), `REFCLIPS_DATA_DIR` (domyślnie `./data`), `DATABASE_URL`.
Wszystko, co tworzy aplikacja (baza SQLite, wgrane pliki, wersje robocze, klipy), leży w `data/`
i jest poza gitem.

## Workflow

1. **Nowy mecz** – data, drużyny (nazwa + kolor strojów, np. „białe”/„ciemne”), poziom rozgrywek
   i obsada sędziowska. Imiona z obsady parser rozpoznaje w notatkach.
2. **Wgraj nagranie** (na stronie meczu; można kilka plików, np. osobne kwarty). Plik jest
   zapisywany strumieniowo na dysk z paskiem postępu. Worker konwertuje go do wersji roboczej
   (H.264/AAC, maks. 720p, klatka kluczowa co sekundę, `+faststart`), dzięki czemu przewijanie
   jest płynne w każdej przeglądarce. Oryginał zostaje nietknięty.
3. **Odtwarzacz** – skróty klawiszowe:

   | Klawisz | Działanie |
   |---|---|
   | Spacja | start / pauza |
   | ← / → | ±1 s (z Shift ±5 s) |
   | `,` / `.` | klatka wstecz / naprzód |
   | `[` / `]` | wolniejsze / szybsze tempo (0.25×–2×, także lista wyboru) |
   | `M` | dodaj decyzję w bieżącym czasie – wpisz np. `Filip PTS` i Enter |
   | `Q` | znacznik początku kwarty (kolejno Q1, Q2, Q3, Q4, OT1…) |

   Kwarta każdego klipu jest liczona ze znaczników początku kwart w czasie nagrania
   (ostatni znacznik nie późniejszy niż decyzja), a nie z odczytu zegara. Znaczniki można
   w każdej chwili poprawić lub usunąć – kwarty klipów przeliczą się same.
4. **Notatki** – „Wklej notatki” przy nagraniu. Jedna linia to jedna decyzja:
   ```
   2:54 Filip PTS
   3:17 Filip Dlaczego nie blok?
   1:02:15 Kasia kroki białe błąd
   ```
   Czas: `m:ss`, `mm:ss`, `h:mm:ss` (także `2.54`, `2,54`). Po czasie pierwsze słowo to sędzia
   (bez względu na wielkość liter i polskie znaki), dalej parser szuka tagów ze słownika
   (strona **Tagi**, edytowalna: nazwy + aliasy) oraz drużyny. Cała linia zostaje jako opis.
   Pokazuje się tabela podglądu z ostrzeżeniami (nieznany sędzia, nierozpoznany czas) – każdą
   linię można poprawić – i przycisk **Wytnij wszystkie zaznaczone**.
5. **Klipy** – lista z filtrami (mecz, sędzia, tag, ocena, kwarta). Na stronie klipu: odtwarzanie,
   opis, ocena (poprawna/błędna/wątpliwa/do omówienia), **korekta początku i końca** z automatycznym
   ponownym wycięciem, komentarze (opcjonalnie przypięte do sekundy klipu, z odpowiedziami),
   pobranie MP4.
6. **Eksport** – ZIP z klipami i plikiem `opisy.csv` (separator `;`, UTF-8 z BOM – otwiera się
   w polskim Excelu), dla zaznaczonych klipów albo całego filtra.

Nazwy klipów przy pobieraniu: `2026-10-28_Q2_02m54s_Filip_PTS.mp4` (bez znaków specjalnych;
gdy nie ma znacznika kwarty – `Qx`).

Klipy wycinane są dokładnie (z przekodowaniem) z wersji roboczej; margines przed/po domyślnie
10 s i jest obcinany do granic nagrania.

## Testy

```bash
.venv/bin/python -m pytest
```

Testy wideo (konwersja, wycinanie, obcięcie do granic nagrania, przepływ end-to-end) używają
prawdziwego ffmpeg i są pomijane, gdy go brak.

## Struktura

```
app/main.py            aplikacja FastAPI
app/routers/           trasy: mecze, nagrania/odtwarzacz/notatki, klipy, tagi
app/models.py          model danych (SQLAlchemy 2), migracje w alembic/
app/notes_parser.py    parser notatek (czysta funkcja)
app/video.py           ffprobe/ffmpeg: konwersja i wycinanie
app/storage.py         magazyn plików (lokalny; interfejs pod przyszłe S3)
app/worker.py          pętla zadań z tabeli jobs
app/services.py        kwarty, granice klipów, nazwy plików, kolejka
app/templates, static  interfejs (Jinja2, HTMX z CDN unpkg w wersji 2.0.4, czysty JS)
tests/                 pytest
```

Uwaga: HTMX jest ładowany z CDN (unpkg, wersja przypięta) – do odświeżania list i komentarzy
potrzebny jest dostęp do internetu w przeglądarce.

## Poza zakresem etapu 1

Konta i logowanie, role w praktyce, biblioteka szkoleniowa, pobieranie z YouTube, Docker/S3,
wykrywanie gwizdka/OCR zegara (patrz plan: etapy 2 i 3).
