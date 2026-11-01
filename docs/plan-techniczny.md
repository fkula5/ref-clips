# Plan techniczny MVP

> Wersja 0.3, 2026-11-01. Odpowiada na sekcję 4 [specyfikacji MVP](specyfikacja-mvp.md) (wersja 0.3).
> Dokument do akceptacji przed pisaniem kodu.

## 1. Podsumowanie decyzji

| Obszar | Decyzja | Najważniejszy powód |
|---|---|---|
| Prototyp | **Rozwijamy `ref-clips`**, a nie zaczynamy od zera | ok. 2 tys. linii działającego, przetestowanego kodu wideo, który i tak trzeba by napisać od nowa |
| Backend | Python 3.12 + FastAPI + SQLAlchemy + Alembic | już jest, dobrze współpracuje z ffmpeg |
| Baza | **SQLite (tryb WAL)** | kilkudziesięciu użytkowników na jednym serwerze, zero administracji, kopia zapasowa to jeden plik |
| Frontend | Szablony Jinja2 + HTMX + czysty JS w odtwarzaczu | proste formularze i listy, brak osobnego builda, działa na telefonie |
| Wgrywanie | **Protokół tus** (wznawialny): `tus-js-client` w przeglądarce, prosty serwer tus w FastAPI | wznowienie po zerwaniu połączenia to standard, nie własny wynalazek |
| Wideo | Konwersja do 720p H.264, usunięcie oryginału, klipy jako **osobne pliki** MP4 | klipy muszą przetrwać usunięcie pełnego meczu (retencja) |
| Logowanie | Własne konta: e-mail + hasło (argon2), sesja w cookie, zaproszenia linkiem | brak zależności od zewnętrznych usług, konta zakłada admin |
| Hosting | VPS w UE (np. Hetzner CX22: 2 vCPU, 4 GB, 40 GB, ok. 4–5 € / mies.) + Docker Compose + Caddy (HTTPS) | mieści się w budżecie, automatyczny certyfikat |
| Kopie | Nocna kopia bazy i klipów na zewnętrzny magazyn w UE (np. Hetzner Storage Box, ok. 4 € / mies.) | utrata VPS nie oznacza utraty klipów |

## 2. Prototyp: co zostaje, co się zmienia

**Zostaje (z rozbudową):**
- `app/video.py`: probe, konwersja, cięcie. Zmiana: domyślny margines 15/15 s, a cięcie od razu po dodaniu znacznika.
- `app/worker.py`: kolejka zadań w tabeli `jobs`. Dochodzą zadania `retention` i `cleanup`.
- `app/notes_parser.py`: dochodzi rozpoznawanie funkcji `CC`/`U1`/`U2` i słownik kategorii zamiast tagów.
- `app/storage.py`: dochodzi rezerwacja miejsca na dysku.
- `app/static/player.js`: dochodzi klawisz „Zaznacz” bez zatrzymywania odtwarzania i lista znaczników.

**Zmienia się:**
- Model danych (rozdział 4): konta, role, obsada CC/U1/U2, kategorie, oceny, retencja.
- Upload: surowy POST zastępuje tus.
- Tagi zastępują **kategorie** z grupami (faule, naruszenia, bez gwizdka, mechanika, inne) i opcją „własna”.

**Usuwamy z interfejsu (wraca w wersji 2):** korekta granic klipu, eksport ZIP, edycja słownika tagów w obecnej formie. Kod korekty i eksportu zostaje w repozytorium, tylko jest ukryty.

Migracja: prototyp nie ma danych produkcyjnych, więc robimy **nową migrację początkową** zamiast przerabiania starej.

## 3. Architektura

```
przeglądarka ──HTTPS──► Caddy ──► FastAPI (uvicorn, 2 procesy) ──► SQLite (WAL)
                          │            │
                          │            └── tabela jobs ◄── worker (1 proces, ffmpeg, nice 10)
                          │
                          └── /media/*  ── forward_auth do FastAPI ──► pliki z dysku (Range)
```

- **Serwowanie wideo przez Caddy.** Python nie przesyła gigabajtów. Caddy przed każdym żądaniem pliku pyta FastAPI (`/auth/media`), czy sesja jest ważna (forward_auth). Potem sam serwuje plik z obsługą przewijania (Range).
- **Worker** przetwarza jedno zadanie naraz z obniżonym priorytetem (`nice`), żeby konwersja nie blokowała strony na 2 vCPU. Zadania cięcia klipów mają pierwszeństwo przed konwersją, bo są krótkie.
- **SQLite:** `journal_mode=WAL`, `busy_timeout=5000`, zapis w krótkich transakcjach. SQLAlchemy zostawia możliwość przejścia na Postgres bez zmian w kodzie aplikacji.

## 4. Model danych

| Tabela | Najważniejsze pola | Uwagi |
|---|---|---|
| `users` | e-mail, imię i nazwisko, hash hasła, aktywny | |
| `user_roles` | user_id, rola (`admin` / `coach` / `referee`) | kilka ról naraz |
| `sessions` | token (hash), user_id, ważność | wylogowanie unieważnia sesję |
| `invites` | token (hash), user_id, cel (`activate` / `reset`), ważność 7 dni | link do ustawienia hasła |
| `matches` | data, liga, drużyny (nazwa, kolor), autor | |
| `match_officials` | match_id, funkcja (`CC`/`U1`/`U2`), user_id **lub** wpisane imię i nazwisko | sprawdzenie „czy był w obsadzie” po user_id |
| `videos` | match_id, zawartość (`full` / lista kwart), ścieżka wersji roboczej, czas trwania, status, `expires_at`, `purged_at` | oryginał tylko w trakcie konwersji |
| `upload_sessions` | tus: id, user_id, rozmiar, offset, zarezerwowane bajty, metadane | sprzątane po 24 h bezczynności |
| `period_marks` | video_id, okres (Q1–Q4, OT1–OT3), czas w nagraniu | |
| `categories` | grupa, nazwa, aliasy, aktywna, kolejność | edytuje admin |
| `clips` | video_id, czas znacznika, start/koniec, plik, status cięcia, official_id lub „cały zespół”, category_id lub nazwa własna, opis, autor, `described_at` | `described_at = null` oznacza „nieopisany” |
| `ratings` | clip_id, coach_id, ocena (`correct` / `incorrect` / `debatable`), komentarz | unikalne (clip_id, coach_id) |
| `comments` | match_id **lub** clip_id, autor, treść, `edited_at` | |
| `jobs` | typ, video_id / clip_id, status, postęp, błąd | jak w prototypie |
| `settings` | klucz, wartość | np. `retention_days = 30` |

**Kwarta i czas klipu** są wyliczane przy odczycie z `period_marks` (jak w prototypie), więc zmiana znacznika od razu poprawia wszystkie klipy. Nagranie z jedną kwartą bez znacznika ma domyślny start 0:00 dla zadeklarowanej kwarty.

## 5. Uprawnienia

- Wszystkie reguły są w jednym module, `app/permissions.py`, jako czyste funkcje, np. `can_create_clip(user, match)`, `can_rate(user)`, `can_delete(user, obj)`. Wywołują je trasy, a szablony używają ich tylko do ukrywania przycisków.
- **Serwer zawsze sprawdza.** Każda trasa zapisu ma zależność FastAPI `require(...)`. Testy obejmują każdy wiersz tabeli uprawnień ze specyfikacji, wywołując API bez interfejsu.
- **„Był w obsadzie”** oznacza istnienie wiersza `match_officials` z `user_id = użytkownik`.
- **Wgrywanie przez sędziego:** formularz wstawia go do obsady, a serwer odrzuca zapis meczu, w którego obsadzie go nie ma (dotyczy użytkownika, który jest tylko sędzią).

## 6. Wideo

### 6.1 Wgrywanie (tus)
- Przeglądarka: `tus-js-client` (plik JS przypięty w repozytorium, bez CDN), kawałki po 50 MB, automatyczne ponawianie i wznowienie po odświeżeniu strony (fingerprint pliku).
- Serwer: minimalna implementacja tus 1.0 w FastAPI (`POST` utworzenie, `HEAD` offset, `PATCH` dopisanie). To ok. 150 linii zamiast osobnej usługi.
- **Rezerwacja miejsca:** przy `POST` znamy rozmiar pliku. Serwer przyjmuje upload tylko wtedy, gdy na dysku jest wolne miejsce na `rozmiar + 1,5 GB (wersja robocza) + 3 GB zapasu`, licząc już zarezerwowane uploady. W przeciwnym razie użytkownik dostaje komunikat „brak miejsca, spróbuj później”, a admin dostaje ostrzeżenie w panelu.
- Limit: jeden aktywny upload na użytkownika, maksymalnie 8 GB na plik.

### 6.2 Konwersja
- Ustawienia jak w prototypie: H.264 `veryfast` CRF 23, AAC, maks. 720p, maks. 30 kl./s, klatka kluczowa co 1 s, `+faststart`.
- **Oryginał jest usuwany** zaraz po udanej konwersji i sprawdzeniu wyniku (ffprobe: czas trwania zgodny z oryginałem ±1 s).
- Szacowany czas na 2 vCPU: mecz 2 h z telefonu 1080p trwa ok. 45–90 min, a 4K/HEVC może zająć 2–3 h. W interfejsie widać pozycję w kolejce i postęp. **Do sprawdzenia na prawdziwym VPS w pierwszym kamieniu milowym.** Jeśli będzie za wolno, możliwy jest preset `superfast` albo mocniejszy VPS na czas konwersji.
- Zajętość: wersja robocza 2 h zajmuje ok. 1–1,5 GB.

### 6.3 Klipy
- Klip powstaje od razu po dodaniu znacznika, czyli zadanie `cut` z wersji roboczej: 15 s przed i 15 s po, obcięte do granic pliku.
- Cięcie jest dokładne (przekodowanie), CRF 20, 720p. Klip 30 s ma ok. 6–10 MB. 30 s na 2 vCPU tnie się w kilka sekund.
- Usunięcie znacznika usuwa też plik klipu.
- Znaczniki z notatek przy wgrywaniu czekają na zakończenie konwersji, potem są cięte automatycznie.

### 6.4 Retencja
- `videos.expires_at = wgranie + retention_days` (domyślnie 30, ustawienie admina).
- Codzienne zadanie `retention` usuwa wersje robocze po terminie i ustawia `purged_at`. Klipy zostają.
- Na 7 dni przed terminem mecz ma w interfejsie oznaczenie „pełne nagranie dostępne jeszcze X dni”.
- Panel admina pokazuje zajętość dysku (pełne nagrania, klipy, wolne miejsce) i pozwala usunąć pełne nagranie wcześniej.

**Budżet dysku (40 GB):** system i Docker ok. 8 GB, rezerwa na aktywny upload ok. 8 GB, więc na pełne nagrania i klipy zostaje ok. 24 GB. To ok. 12–15 pełnych meczów naraz plus kilkaset klipów. Przy większym ruchu najpierw skracamy retencję, potem przenosimy klipy do magazynu obiektowego (warstwa `storage` jest na to przygotowana).

## 7. Logowanie i konta

- Hasła: `argon2-cffi`. Logowanie e-mail + hasło, limit prób (5 na 15 minut na konto i IP).
- Sesja: losowy token w cookie `HttpOnly`, `Secure`, `SameSite=Lax`, ważność 30 dni z odświeżaniem. W bazie trzymamy tylko hash tokenu.
- CSRF: `SameSite=Lax` + token CSRF w formularzach i nagłówku HTMX.
- **Zakładanie konta:** admin wpisuje e-mail, imię i nazwisko oraz role, a system generuje **link zaproszenia** (ważny 7 dni). Admin wysyła go sam, np. przez Messenger czy SMS. W MVP aplikacja nie wysyła e-maili, więc nie potrzebuje serwera SMTP.
- Reset hasła: admin generuje link resetu tak samo. Samodzielny reset przez e-mail jest w wersji 2.
- Pierwszy admin powstaje poleceniem `python -m app.create_admin`.

## 8. Interfejs

- Szablony + HTMX (plik przypięty w `static/`, bez CDN).
- Responsywny układ: widoki listy klipów, klipu, ocen i komentarzy projektowane najpierw pod telefon. Odtwarzacz meczu i opisywanie znaczników projektujemy pod komputer.
- Najważniejsze ekrany:
  1. **Logowanie i ustawienie hasła z zaproszenia**
  2. **Lista meczów** z filtrem i stanem: konwersja / gotowy / brak znaczników kwart / pełne nagranie usunięte
  3. **Nowy mecz:** dane, obsada CC/U1/U2 (wybór konta lub wpisanie), plik lub pliki z deklaracją zawartości, opcjonalne notatki z podglądem
  4. **Znaczniki kwart** (krok wymagany przy pliku z kilkoma kwartami)
  5. **Odtwarzacz:** `Z` = zaznacz, lista znaczników z boku, skróty jak w prototypie
  6. **Opisywanie:** lista nieopisanych znaczników, przy każdym podgląd klipu, sędzia, kategoria i opis, zapis i przejście do następnego
  7. **Klipy meczu** (zakładka) z filtrami sędzia / kategoria / kwarta
  8. **Klip:** odtwarzacz, opis, oceny szkoleniowców, komentarze
  9. **Admin:** użytkownicy i role, kategorie, retencja, zajętość dysku

## 9. Wdrożenie

- **Serwer:** Ubuntu 24.04 LTS. Firewall `ufw` (otwarte tylko 22, 80, 443), logowanie SSH tylko kluczem, `unattended-upgrades` dla poprawek bezpieczeństwa.
- **Docker Compose:** usługi `app` (uvicorn), `worker` i `caddy`. Wolumin `data/` na baza, wideo i klipy.
- **Domena:** potrzebna do HTTPS, np. subdomena na posiadanej domenie lub tania domena `.pl`. Caddy sam wystawia i odnawia certyfikat Let's Encrypt.
- **Aktualizacja aplikacji:** `git pull && docker compose up -d --build`. Migracje Alembic uruchamiają się przy starcie.
- **Kopie zapasowe** (cron, codziennie w nocy):
  - baza: `sqlite3 .backup`, wysyłka przez `rclone` na Storage Box, przechowywane 14 dni,
  - klipy: `rclone sync` na Storage Box,
  - pełnych nagrań **nie** kopiujemy, bo są tymczasowe.
  - Raz na kwartał robimy próbne odtworzenie.
- **Monitoring:** prosty endpoint `/health` (baza, worker, wolne miejsce) i darmowy zewnętrzny ping (np. UptimeRobot), który alarmuje, gdy strona nie odpowiada.

## 10. Proces wdrożenia

Pracę dzielimy na segmenty (kamienie milowe niżej). Każdy segment przechodzi pętlę:

```
wdrożenie ──► review ──► są uwagi? ──tak──► poprawa błędów ──► review ──► …
                            │
                            nie
                            ▼
                      segment zamknięty ──► następny segment
```

- **Wdrożenie:** implementacja segmentu razem z testami (agent Sonnet 5.5, effort high), na osobnej gałęzi `segment-N`.
- **Review:** niezależny przegląd zmian (Opus 5.5): zgodność ze specyfikacją i planem, błędy logiczne, uprawnienia i bezpieczeństwo, testy. Każda uwaga dostaje wagę: **blokująca** (musi być poprawiona) lub **drobna**.
- **Poprawa błędów:** usunięcie wszystkich uwag blokujących (drobne według uznania), po czym kolejne review. Pętla trwa, dopóki review nie zwróci żadnej uwagi blokującej, a wszystkie testy przechodzą.
- **Zamknięcie segmentu:** krótki raport (co zrobiono, wynik testów, lista drobnych uwag odłożonych na później) i scalenie gałęzi do `master`.
- Odłożone drobne uwagi i pomysły trafiają do `TODO.md`.

## 11. Kamienie milowe

Każdy kamień milowy kończy się działającą wersją z testami.

1. **Fundament:** nowy model danych + migracja, konta, logowanie, zaproszenia, role, `permissions.py` z testami tabeli uprawnień.
2. **Mecze i obsada:** formularz meczu, CC/U1/U2 (konto lub wpisane), reguła „sędzia wgrywa tylko swoje mecze”.
2a. **Docker lokalnie (do testów u innych osób):** `Dockerfile` (Python 3.12 slim + ffmpeg z pakietów Debiana) i `compose.yaml` z usługami `app` i `worker` na wspólnym woluminie danych. Uruchomienie jednym poleceniem `docker compose up`, a pierwszy admin przez `docker compose run --rm app python -m app.create_admin`. Instrukcja w README dla Windows (Docker Desktop), macOS i Linuksa. Ten sam obraz posłuży potem w segmencie 8, gdzie dochodzi tylko Caddy, kopie zapasowe i konfiguracja produkcyjna.
3. **Wgrywanie i konwersja:** tus, rezerwacja miejsca, deklaracja zawartości pliku, usuwanie oryginału. Pomiar czasu konwersji lokalnie z ograniczeniem do 2 rdzeni (`taskset -c 0,1`) jako przybliżenie VPS.
4. **Znaczniki:** znaczniki kwart, odtwarzacz z klawiszem „Zaznacz”, notatki przy wgrywaniu (parser z CC/U1/U2 i kategoriami).
5. **Klipy:** cięcie 15/15, ekran opisywania, zakładka klipów z filtrami, widok klipu.
6. **Oceny i komentarze:** oceny szkoleniowców, komentarze do meczu i klipu, edycja i usuwanie według uprawnień, widoki mobilne.
7. **Admin i retencja:** panel użytkowników, kategorii, retencji i dysku, zadanie `retention`.
8. **Wdrożenie (odłożone, do czasu zakupu VPS):** obraz i Compose z segmentu 2a rozszerzone o Caddy, kopie zapasowe, monitoring, przejście kryteriów akceptacji ze specyfikacji na serwerze.

Kamienie 1–7 robimy i testujemy lokalnie w WSL; od segmentu 2a każdy segment musi też działać w Dockerze. Po zakupie VPS pomiar czasu konwersji z kroku 3 powtarzamy na serwerze.

## 12. Ryzyka

| Ryzyko | Skutek | Co robimy |
|---|---|---|
| Konwersja na 2 vCPU za wolna (4K/HEVC) | mecz dostępny po kilku godzinach | pomiar w kamieniu 3, presety szybsze, ew. czasowo mocniejszy VPS |
| Wolny upload z domu (4 GB przy 20 Mb/s to ok. 30 min) | frustracja przy wgrywaniu | tus z wznawianiem, zalecenie wgrywania z Wi-Fi / komputera |
| Zapełnienie dysku | odrzucone uploady | rezerwacja miejsca, retencja, panel dysku, alarm w `/health` |
| Utrata VPS | utrata klipów i opisów | nocne kopie na zewnętrzny magazyn |
| Safari na iPhonie a odtwarzanie | klipy nie grają na telefonie | H.264 + AAC + faststart (zgodne), test w kryteriach akceptacji |

## 13. Koszty miesięczne (szacunek)

| Pozycja | Koszt |
|---|---|
| VPS 2 vCPU / 4 GB / 40 GB (UE) | ok. 4–5 € |
| Storage Box 1 TB na kopie (UE) | ok. 4 € |
| Domena `.pl` | ok. 1–5 zł / mies. w przeliczeniu (pierwszy rok bywa tańszy) |
| **Razem** | **ok. 40–50 zł / mies.** |
