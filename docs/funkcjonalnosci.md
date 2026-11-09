# ref-clips: katalog funkcjonalności (MVP)

> Wersja robocza 0.1, 2026-10-29. Dokument służy do zaprojektowania MVP od nowa: każdą funkcję możemy zostawić, zmienić albo wyrzucić.
> Kolumna **Stan** opisuje, co już działa w obecnym prototypie (etap 1). Nie przesądza o tym, co znajdzie się w MVP.

## 1. Cel produktu

Narzędzie dla sędziów koszykówki i szkoleniowców do **analizy decyzji sędziowskich na nagraniach meczów**:
- szybkie oznaczanie sytuacji na nagraniu (z gwizdkiem i bez),
- automatyczne wycinanie klipów wokół tych sytuacji,
- opis, ocena i dyskusja nad klipem,
- docelowo wspólna biblioteka klipów szkoleniowych dla grupy sędziowskiej.

**Czego produkt nie robi:** nie ocenia decyzji sam. Automatyka może co najwyżej *podpowiadać* momenty (np. gwizdek), decyzję zawsze ocenia człowiek.

## 2. Użytkownicy i role

| Rola | Kto to | Co robi |
|---|---|---|
| **Sędzia** | członek grupy szkoleniowej | wgrywa mecze, oznacza i opisuje swoje sytuacje, odpowiada na uwagi, ogląda bibliotekę |
| **Szkoleniowiec** | obserwator / instruktor | wskazuje sytuacje do opisania, ocenia, komentuje, publikuje klipy do biblioteki |
| **Admin** | prowadzący grupę | zarządza kontami, słownikami (tagi, poziomy rozgrywek), ustawieniami |

Funkcje sędziowskie w obsadzie meczu: **CC** (pierwszy sędzia), **U1** (drugi), **U2** (opcjonalny trzeci).

## 3. Słownik pojęć

- **Mecz:** data, drużyny (nazwa + kolor stroju), poziom rozgrywek, obsada (CC/U1/U2).
- **Nagranie:** plik wideo przypisany do meczu. Mecz może mieć kilka nagrań, np. osobne kwarty albo różne kamery.
- **Wersja robocza:** kopia nagrania przekonwertowana do formatu wygodnego w przeglądarce (H.264/AAC MP4, max 720p, klatka kluczowa co 1 s). Oryginał zostaje bez zmian.
- **Znacznik okresu:** moment w nagraniu, w którym zaczyna się Q1–Q4 lub dogrywka. Z tych znaczników liczy się kwarta każdej decyzji, bez odczytu zegara z obrazu.
- **Decyzja (klip):** sytuacja w konkretnym momencie nagrania. Ma sędziego, tagi, opis, ocenę i plik klipu (domyślnie ±10 s).
- **Notatka:** linia tekstu w formacie `czas sędzia opis`, np. `2:54 Filip PTS`, z której powstaje decyzja.
- **Tag:** kategoria sytuacji (PTS, blok/szarża, kroki, aut, brak gwizdka…) z aliasami w słowniku.
- **Ocena:** poprawna / błędna / wątpliwa / do omówienia.

## 4. Funkcjonalności

Legenda stanu: ✅ jest w prototypie · 🔧 jest, ale do zmiany · ⬜ brak.
Priorytet: **M** = musi być w MVP · **S** = warto mieć · **P** = później (poza MVP). Kolumnę priorytetu uzupełniamy razem.

### 4.1 Mecze

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| M-01 | Utworzenie meczu: data, poziom, drużyny (nazwa + kolor) | ✅ | |
| M-02 | Obsada meczu z funkcjami CC / U1 / U2, przypisanie domyślne według kolejności | 🔧 obecnie „R” i „U” | |
| M-03 | Edycja i usunięcie meczu (z nagraniami i klipami) | ✅ | |
| M-04 | Lista meczów na stronie głównej | ✅ | |
| M-05 | Słownik sędziów (osoby wielokrotnie wybierane do obsad) | ✅ (tworzony automatycznie) | |
| M-06 | Słownik poziomów rozgrywek (lista zamiast wolnego tekstu) | ⬜ | |

### 4.2 Nagrania

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| N-01 | Wgranie pliku (także 2–6 GB) z paskiem postępu, zapis strumieniowy | ✅ (niesprawdzone na dużych plikach) | |
| N-02 | Kilka nagrań w jednym meczu, z etykietą (np. „Q1–Q2”) i źródłem (Veo / telefon / YouTube / plik) | ✅ | |
| N-03 | Automatyczna konwersja do wersji roboczej w tle, ze statusem i postępem | ✅ | |
| N-04 | Ponowienie konwersji po błędzie | ✅ | |
| N-05 | Wybór jakości wersji roboczej (720p / 1080p) albo cięcie klipów z oryginału | ⬜ | |
| N-06 | Pobranie nagrania z linku YouTube | ⬜ | |
| N-07 | Synchronizacja kilku nagrań tego samego meczu (np. kamera Veo + telefon) | ⬜ | |

### 4.3 Odtwarzacz

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| O-01 | Odtwarzanie z przewijaniem (HTTP Range) | ✅ | |
| O-02 | Skróty: spacja, ←/→ ±1 s, Shift ±5 s, `,`/`.` klatka po klatce | ✅ (niesprawdzone w przeglądarce) | |
| O-03 | Tempo 0,25×–2× | ✅ | |
| O-04 | `M` dodaje decyzję w bieżącym momencie (szybki wpis tekstem) | ✅ | |
| O-05 | `Q` dodaje znacznik kolejnej kwarty, z możliwością edycji i usuwania | ✅ | |
| O-06 | Oś czasu ze znacznikami kwart i decyzji (kliknięcie przenosi do momentu) | ⬜ | |
| O-07 | Powiększenie fragmentu obrazu (zoom), np. przy dalekim ujęciu z Veo | ⬜ | |

### 4.4 Notatki i tworzenie decyzji

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| D-01 | Wklejenie bloku notatek, w którym jedna linia to jedna decyzja | ✅ | |
| D-02 | Czas w formatach `m:ss`, `h:mm:ss`, także `2.54` / `2,54` | ✅ | |
| D-03 | Rozpoznanie sędziego z obsady (bez względu na wielkość liter i polskie znaki) | ✅ | |
| D-04 | Rozpoznanie sędziego po funkcji (`CC`, `U1`, `U2`) i po zdrobnieniach / ksywkach | ⬜ | |
| D-05 | Rozpoznanie tagów i drużyny z tekstu | ✅ | |
| D-06 | Tabela podglądu z możliwością poprawy przed zapisem i ostrzeżeniami | ✅ | |
| D-07 | „Wytnij wszystkie”: masowe wycięcie klipów ±10 s | ✅ | |
| D-08 | Domyślne marginesy klipu ustawiane per użytkownik lub per tag | ⬜ | |

### 4.5 Klipy

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| K-01 | Lista klipów z filtrami: mecz, sędzia, tag, ocena, kwarta | ✅ | |
| K-02 | Strona klipu: odtwarzanie, edycja opisu, tagów, oceny | ✅ | |
| K-03 | Korekta początku i końca klipu z automatycznym ponownym wycięciem | ✅ | |
| K-04 | Pobranie klipu MP4 z czytelną nazwą (`kategoria-rozgrywek_nazwisko_decyzja.mp4`) | ✅ | |
| K-05 | Eksport ZIP: wybrane klipy + `opisy.csv` | ✅ | |
| K-06 | Usunięcie klipu | ✅ | |
| K-07 | Playlista: zestaw klipów do omówienia (kolejność, tytuł) | ⬜ | |

### 4.6 Komentarze i ocena

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| C-01 | Komentarze do klipu z odpowiedziami (wątki) | ✅ | |
| C-02 | Komentarz przypięty do sekundy klipu (kliknięcie przenosi do momentu) | ✅ | |
| C-03 | Rysowanie na stopklatce (strzałki, linie, pozycje) przy komentarzu | ⬜ | |
| C-04 | Ocena szkoleniowca odrębna od samooceny sędziego | ⬜ | |
| C-05 | Odniesienie do przepisu / interpretacji FIBA przy klipie | ⬜ | |

### 4.7 Słowniki i ustawienia

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| S-01 | Słownik tagów z aliasami, edytowalny | ✅ | |
| S-02 | Znaczenie skrótów w słowniku (np. co dokładnie oznacza „PTS”) | ⬜ | |

### 4.8 Praca w grupie (etap 2)

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| G-01 | Konta, logowanie, zaproszenia od admina | ⬜ (model danych gotowy) | |
| G-02 | Role sędzia / szkoleniowiec / admin i uprawnienia | ⬜ | |
| G-03 | Widoczność klipu: prywatny / grupa / biblioteka | ⬜ (pole w bazie jest) | |
| G-04 | Zadania od szkoleniowca („opisz sytuację 3:17”) i lista zadań sędziego | ⬜ | |
| G-05 | Powiadomienia w aplikacji (nowy komentarz, nowe zadanie) | ⬜ | |
| G-06 | Biblioteka szkoleniowa: wyszukiwanie po tagach, ocena wzorcowa, opcja ukrycia nazwisk | ⬜ | |

### 4.9 Wdrożenie i automatyzacja (etap 3)

| ID | Funkcja | Stan | Priorytet |
|---|---|---|---|
| W-01 | Hosting na serwerze (Docker, Postgres, magazyn plików S3) | ⬜ | |
| W-02 | API JSON obok stron, pod przyszły frontend lub aplikację mobilną | ⬜ | |
| W-03 | Podpowiedzi gwizdka z audio (znaczniki na osi czasu) | ⬜ | |
| W-04 | Odczyt zegara meczowego z obrazu (OCR), gdy jest widoczny | ⬜ | |

## 5. Wymagania niefunkcjonalne

- **Interfejs po polsku**, czytelny także dla osób nietechnicznych.
- **Przeglądarki:** Chrome i Edge na Windowsie. Docelowo również telefon do oglądania i komentowania.
- **Źródła wideo:** Veo, telefon (w tym HEVC/.mov z iPhone), YouTube.
- **Skala (szacunek):** ~25 nagranych meczów na sędziego na sezon, 2–6 GB na mecz.
- **Dane:** nagrania mogą pokazywać zawodników, w tym niepełnoletnich. Dostęp do nich musi być ograniczony do grupy (ważne przy etapie 2/3, RODO).

## 6. Decyzje architektoniczne (na teraz)

- Backend w Pythonie (FastAPI, SQLAlchemy, ffmpeg) zostaje na stałe.
- Frontend: szablony + HTMX. Najbardziej interaktywne elementy (oś czasu, rysowanie) mogą powstać jako osobne komponenty (np. Svelte/React). Pełna aplikacja SPA dopiero przy potrzebie aplikacji mobilnej.
- Przy etapie 2 dodajemy API JSON (W-02).

## 7. Otwarte pytania do MVP

1. **Zakres MVP:** czy MVP to wersja dla jednej osoby (etap 1), czy ma już zawierać pracę w grupie (G-01…G-04)?
2. **Kto wgrywa nagrania:** każdy sędzia sam, czy np. tylko szkoleniowiec lub admin?
3. **„PTS” i inne skróty:** jaka jest lista skrótów używanych w Waszej grupie? (do słownika S-01/S-02)
4. **Ocena:** czy cztery stany (poprawna / błędna / wątpliwa / do omówienia) wystarczą? Czy potrzebna jest skala, kategoria błędu (np. pozycja, interpretacja, mechanika) albo podział na samoocenę i ocenę szkoleniowca (C-04)?
5. **Jakość obrazu:** czy 720p wystarczy do oceny, czy potrzeba 1080p lub cięcia z oryginału (N-05)?
6. **Marginesy klipu:** czy ±10 s zawsze pasuje, czy np. faul w akcji rzutowej potrzebuje więcej „przed”?
7. **Telefon:** czy w MVP trzeba wygodnie oglądać i komentować klipy na telefonie?
