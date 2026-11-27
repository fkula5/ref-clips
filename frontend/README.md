# Ref Clips — Vue + Quasar + TypeScript

Interfejs Vue obejmuje mecze, nagrania, wspólne oglądanie, kolejkę opisywania i bibliotekę klipów,
grupy i zestawy szkoleniowe, profile sędziów, arkusze ocen, samooceny, protokoły,
powiadomienia, administrację oraz strony publiczne. Dane i walidacja pochodzą z FastAPI.

## Struktura frontendu

```text
src/
  App.vue                 RouterView i ekran startowego ładowania
  main.ts                 rejestracja Vue, Quasara i routera
  router/                 trasy, ochrona sesji, tytuły stron
  layouts/                wspólny układ aplikacji
  views/                  widoki logowania, meczów i błędów
  components/
    common/               elementy współdzielone
    layout/               nagłówek i menu
    matches/              filtry i element listy meczów
  composables/            sesja oraz pobieranie i filtrowanie meczów
  api/                    klient HTTP oraz endpointy logowania i meczów
  types/                  typy danych i odpowiedzi API
```

Nowe widoki dodawaj do `views/` i rejestruj w `router/index.ts`.
Widoki wymagające sesji umieszczaj jako dzieci `MainLayout`.
Podczas pobierania danych widoki korzystają ze wspólnego komponentu
`components/common/LoadingSkeleton.vue`. Dobierz wariant do układu widoku.
Logowanie Vue ma adres `/auth/login`, lista meczów `/matches`, a szczegóły `/matches/:id`.
Biblioteka klipów ma adres `/clips`, a szczegóły `/clips/:id`.
Analiza nagrania ma adres `/recordings/:id`, a zestawy szkoleniowe `/training-sets`.
Dotychczasowe polskie adresy przekierowują do nowych tras z zachowaniem filtrów i fragmentu URL.
Vue Router używa historii przeglądarki; filtry i strona listy są w query string.
Gdy adres widoku pokrywa się z endpointem FastAPI, żądania dokumentu HTML
otwierają Vue, a żądania API trafiają do FastAPI. Odnośniki do poprzedniego
interfejsu używają parametru `?view=classic`.
Ochrona tras w przeglądarce uzupełnia uprawnienia sprawdzane przez backend.

## Uruchomienie lokalne

Najprościej uruchomić całość w Docker Desktop, z katalogu głównego repozytorium:

```powershell
docker compose -f compose.yaml -f compose.frontend.yaml up -d --build
```

Nowy frontend: **http://127.0.0.1:5173**. Dotychczasowy interfejs:
**http://127.0.0.1:8000**. Edycje `frontend/src` są widoczne automatycznie.
Po zmianach zależności lub konfiguracji Vite ponownie wykonaj powyższe polecenie.
Ten wariant nie wymaga Node.js ani Pythona zainstalowanych w Windows.

### Dane demonstracyjne

Do lokalnej bazy Docker można dodać fikcyjne mecze, animowane nagranie MP4, klipy,
grupę, zestaw szkoleniowy, protokół i oceny. Podaj adres istniejącego konta testowego
z rolą sędziego. Polecenie nie uruchamia się automatycznie i nie duplikuje meczu demo.

```powershell
Get-Content -Raw -Encoding utf8 scripts/seed_demo.py | docker compose -f compose.yaml -f compose.frontend.yaml exec -T app python - --referee sedzia@example.test
```

Po zalogowaniu na to konto wyszukaj mecz „Sokoły DEMO – Wilki DEMO” w bibliotece.
Skrypt wypisuje również adresy nagrania i klipów dla użytej bazy.

### Uruchomienie bez kontenera frontendu

Alternatywnie można uruchomić frontend przez Node.js na komputerze:

W katalogu głównym repozytorium uruchom backend:

```powershell
docker compose up -d --build
```

Jeżeli nie masz jeszcze konta, utwórz administratora (polecenie pyta o dane):

```powershell
docker compose run --rm app python -m app.create_admin
```

W drugim terminalu:

```powershell
cd frontend
npm ci
npm run dev
```

Otwórz **http://127.0.0.1:5173**. Wymagany Node.js 22.12+ (lub nowsza wersja LTS).
Backend powinien działać na porcie 8000. Jeżeli zmienisz port backendu,
zmień `target` w `vite.config.ts` lub ustaw `FRONTEND_API_TARGET`.

Proxy Vite obsługuje API i dotychczasowe strony na jednym adresie, dzięki czemu
działają ciasteczka sesji, odnośniki i ochrona CSRF. Hasła i tokeny sesji nie są
zapisywane w localStorage. Frontend pobiera token CSRF z API i przesyła go
w nagłówku przy logowaniu oraz wylogowaniu.

## Weryfikacja

W wariancie Docker, z katalogu głównego repozytorium:

```powershell
docker compose -f compose.yaml -f compose.frontend.yaml exec frontend npm run build
```

W wariancie Node.js, z katalogu `frontend/`:

```powershell
npm run build
```

Build sprawdza typy TypeScripta i szablony Vue, a następnie tworzy pliki produkcyjne.
Samo sprawdzenie typów: `npm run typecheck`.

Testy API z katalogu głównego, w środowisku z zależnościami `requirements-dev.txt`:

```text
python -m pytest tests/test_frontend_api.py tests/test_auth.py tests/test_match_list.py
```

## Wdrożenie

Obraz aplikacji zawiera kompilację Vue w `app/frontend_dist`. Ustaw
`REFCLIPS_VUE_FRONTEND=1` w konfiguracji kontenera, aby serwować Vue na głównym
adresie aplikacji. Lokalnie można dodać tę zmienną do `.env` i uruchomić
`docker compose up -d --build`.

FastAPI serwuje kompilację, trasy Vue oraz API pod tym samym adresem. Publiczne
linki i ustawianie hasła zachowują dotychczasowe adresy. Włączenie trybu Vue
jest opcjonalne, co pozwala w razie potrzeby wrócić do dotychczasowej strony
głównej przez wyłączenie zmiennej. Pliki wideo, pobrania i klient WebSocket
korzystają z tych samych adresów serwera.

`npm run preview` służy do samodzielnego podglądu plików kompilacji.

Integracja Quasara korzysta z oficjalnego pluginu Vite:
https://quasar.dev/start/vite-plugin/
