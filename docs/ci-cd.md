# Wydania i automatyczne wdrożenie (GitHub Actions)

> Stan: konfiguracja gotowa, ale **pierwsze prawdziwe wydanie jeszcze się nie odbyło** — workflow da się w pełni
> sprawdzić dopiero na GitHubie. Zanim cokolwiek zadziała, wykonaj [kroki jednorazowe](#kroki-jednorazowe-po-merge-u-ręcznie)
> (kolejność ma znaczenie). Ręczne wdrożenie z komputera (`deploy/deploy.sh`) nadal działa jako wyjście awaryjne.

## Jak to działa

1. **Praca w PR-ach.** Zmiany trafiają do `main` wyłącznie przez pull request. Na każdym PR-ze startuje `ci.yml`
   z dwoma jobami: `unit` (`pytest -q`) i `e2e` (Playwright + Chromium, `scripts/e2e.sh`). Obie nazwy są wymagane
   w ochronie `main`. Przy porażce `e2e` zrzuty ekranu i logi są w artefaktach przebiegu (`e2e-artefakty`, 7 dni).
2. **Tytuł PR-a = wpis w historii.** Przy scalaniu „squash” tytuł PR-a staje się commitem na `main`, a z commitów
   [release-please](https://github.com/googleapis/release-please-action) liczy numer wersji i listę zmian
   (Conventional Commits): `fix:` podnosi ostatnią cyfrę, `feat:` środkową, `feat!:` albo `BREAKING CHANGE:` pierwszą;
   `docs:`, `ci:`, `chore:`, `test:` same nie tworzą wydania.
3. **PR wydania.** Po każdym merge'u na `main` workflow `release.yml` uruchamia release-please. Ten otwiera
   (albo aktualizuje) PR „chore: wydanie vX.Y.Z” ze zmianą `version.txt`, `.release-please-manifest.json` i `CHANGELOG.md`.
   Nic się nie wdraża, dopóki go nie scalisz.
4. **Merge PR-a wydania** tworzy tag `vX.Y.Z` i GitHub Release, a w tym samym przebiegu kolejne joby:
   - `build` — buduje obraz na GitHubie i publikuje w GHCR: `ghcr.io/fkula5/ref-clips:vX.Y.Z` oraz `:sha-xxxxxxx`
     (numer wersji w obrazie: `--build-arg REFCLIPS_VERSION`, widoczny w stopce zalogowanym; obrazu istniejącego tagu nie
     nadpisujemy),
   - `deploy` (środowisko `production`) — jedno polecenie `ssh serwer deploy vX.Y.Z`. Serwer niczego nie buduje,
     tylko pobiera gotowy obraz.
5. **Na serwerze** polecenie trafia do wymuszonego skryptu `deploy/ci-entry.sh` (zainstalowanego jako
   `/usr/local/bin/ref-clips-ci-entry`): pobiera pliki wersji z publicznego repo, **czeka do 2 godzin, aż nic nie
   trwa** (upload, konwersja — to samo sprawdzenie `app/busy.py` co w `deploy.sh`), pobiera obraz, podmienia pliki
   i `REFCLIPS_IMAGE` w `.env`, restartuje stos i sprawdza `/health`. Jeśli nowa wersja nie wstanie, **wraca sam do
   poprzedniej**. Po 2 godzinach czekania kończy się czytelnym błędem (kod 3), a wdrożenie ponawia się jednym
   przyciskiem (patrz „Ponowienie i powrót”).

```
PR ──► ci.yml: unit + e2e ──(zielone)──► merge do main ──► release.yml: release-please
                                                           └► PR „wydanie vX.Y.Z” ──► ci.yml (dispatch) ──► merge
merge PR-a wydania ──► tag + Release ──► build (GHCR) ──► deploy: ssh … deploy vX.Y.Z ──► ci-entry.sh na serwerze
```

Dlaczego build i wdrożenie są jobami `release.yml`, a nie osobnymi workflow „na tag”: tag utworzony przez
`GITHUB_TOKEN` nie uruchamia żadnych innych workflow (zdarzenia od `GITHUB_TOKEN` nie tworzą przebiegów — wyjątek to
`workflow_dispatch` i `repository_dispatch`; tak samo opisuje to dokumentacja release-please).

### Testy na PR-ze wydania (pułapka z `GITHUB_TOKEN`)

PR otwarty przez `GITHUB_TOKEN` (czyli przez release-please bez osobistego tokena) **nie wywołuje zdarzenia
`pull_request`**, więc wymagane checki na nim by nie ruszyły. Rozwiązanie bez PAT, zastosowane w `release.yml`:
po utworzeniu lub aktualizacji PR-a wydania workflow wywołuje `ci.yml` przez `workflow_dispatch` na jego gałęzi
(`release-please--branches--main`, uprawnienie `actions: write`; `workflow_dispatch` jest wyjątkiem i tworzy przebieg
także dla `GITHUB_TOKEN`). Przebieg dotyczy dokładnie tego commita, który jest końcem PR-a.

**Zastrzeżenie (sprawdzone w dokumentacji, nie na żywo):** dokumentacja GitHuba
([Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks))
mówi wprost, że checki z jobów workflow uruchomionego przez `workflow_dispatch` na gałęzi PR-a **nie pojawiają się
w sekcji checków PR-a i nie spełniają wymaganego sprawdzenia w regułach (ruleset)**, nawet gdy przeszły; ograniczenie
dotyczy tylko checków z jobów workflow, a nie *statusów commita*. Dlatego ostatni krok każdego z jobów `unit` i `e2e`
(tylko przy `workflow_dispatch` na gałęzi `release-please--*`) **dodatkowo zapisuje status commita o tej samej nazwie**
(`unit`, `e2e`; `POST /repos/…/statuses/{sha}`, uprawnienie `statuses: write`). Status trafia na ten sam commit i spełnia
wymagane sprawdzenie o tej nazwie, o ile reguła nie wymusza źródła „GitHub Actions” (zostaw **Any source**, krok 6).
Jeśli przy pierwszym PR-ze wydania mimo to merge będzie zablokowany („Waiting for status to be reported”), opcje są
dwie: administrator scala PR wydania z pominięciem reguły (jednorazowo), albo przechodzimy na token GitHub App /
PAT dla release-please (wtedy PR wywołuje zwykłe `pull_request`; sekret `RELEASE_PLEASE_TOKEN` + `token:` w kroku
release-please, cała reszta bez zmian).

## Co może klucz CI

Klucz prywatny jest w sekrecie `DEPLOY_SSH_KEY` środowiska `production`. Na serwerze jego wpis w `authorized_keys`
ma **wymuszone polecenie i `restrict`** (bez terminala, przekierowań portów, agenta), więc niezależnie od tego, co
wyśle klient, uruchomi się tylko `ref-clips-ci-entry`. Skrypt (własność roota, poza katalogiem aplikacji, więc klucz
CI nie może go zmienić) akceptuje dokładnie dwa polecenia, ścisłymi wyrażeniami regularnymi, bez `eval` i bez
przekazywania argumentów dalej:

| Polecenie | Działanie |
|---|---|
| `deploy vX.Y.Z` | wdrożenie wersji (opis niżej) |
| `status` | wypisuje wdrożoną wersję (`.deploy-commit`) i stan usług |

Wszystko inne kończy się kodem 2. Klucz CI nie ma kanału zapisu na serwer: pliki wersji serwer pobiera sam po HTTPS
z publicznego repozytorium (`codeload.github.com/fkula5/ref-clips`), a obraz z GHCR. Skrypt podmienia tylko
`compose.yaml`, `compose.prod.yaml` i `deploy/` w `/opt/ref-clips` oraz jedną linię `REFCLIPS_IMAGE` w `.env`
(`.env` nie jest wypisywany, dane są w wolumenach). Skutek uboczny wynikający z modelu zaufania: kto może scalić kod
na `main`, kontroluje to, co wdraża się na serwer — dlatego ochrona `main` i środowisko `production` mają znaczenie.

Host key serwera jest przypięty w repozytorium (`deploy/known_hosts`, wartość publiczna), a `ssh` działa z
`StrictHostKeyChecking=yes`. Po reinstalacji serwera/zmianie klucza hosta zaktualizuj ten plik (`ssh-keygen -F
57.131.162.204`, tylko linia `ssh-ed25519`, **w formie niezahashowanej** z nazwą hosta; odcisk sprawdź na serwerze:
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).

### Kroki `deploy` na serwerze

1. blokada `flock` (`/opt/ref-clips/.deploy.lock`, ta sama co w `deploy.sh`) na czas całości;
2. pobranie plików wersji do katalogu tymczasowego (zły tag kończy się od razu, nie po 2 godzinach czekania);
3. czekanie, aż nic nie trwa: `app/busy.py` wysłany na wejście `python -` działającego kontenera `app`; zatrzymany stos
   nie blokuje, **błąd sprawdzenia blokuje** (kod 1); sprawdzanie co 60 s, łącznie do 120 min, potem kod 3 i komunikat,
   co trwa;
4. `docker pull` obrazu wersji (przed jakąkolwiek zmianą) i **ponowne sprawdzenie zajętości tuż przed restartem**;
5. kopia poprzednich plików do `.rollback/`, podmiana plików, `REFCLIPS_IMAGE=ghcr.io/fkula5/ref-clips:vX.Y.Z` w `.env`
   (nowy plik obok + `mv`, jedna linia; ten sam obraz stosuje `deploy/backup.sh`);
6. `docker compose up -d --no-build --remove-orphans --wait --wait-timeout 300`; Caddy restartuje się tylko po zmianie
   `Caddyfile`;
7. kontrola `GET /health` przez Caddy (do 150 s). Gdy `up` albo `/health` zawiodą: **powrót do poprzednich plików i
   poprzedniego `REFCLIPS_IMAGE`**, kod 4 (powrót się udał) lub 5 (nie udał się — trzeba wejść na serwer). Wyjątek:
   jeśli `/health` zwraca błąd tylko z powodu dysku (baza i worker `ok`), to nie wina wersji — zostaje nowa, z ostrzeżeniem;
8. zapis `vX.Y.Z` w `.deploy-commit` (zamiast hasha) i usunięcie starych obrazów `ghcr.io/fkula5/ref-clips` — zostają
   3 najnowsze oraz bieżący i poprzedni (obraz lokalny `ref-clips:local` i inne obrazy nietknięte; bez `prune`).

Kody wyjścia (widoczne w podsumowaniu przebiegu): 0 ok · 1 błąd przed zmianami (brak obrazu, błąd sprawdzenia…) ·
2 niedozwolone polecenie · 3 przez 2 godziny coś trwało · 4 nowa wersja nie wstała, przywrócono poprzednią ·
5 nie wstała i powrót się nie udał · 255 błąd połączenia ssh.

**Migracje bazy a powrót.** Migracje (`init` przy starcie) wykonują się przy starcie nowej wersji i **nie cofają się**
przy powrocie do starszego obrazu. Starszy obraz musi więc działać na nowszym schemacie, czyli migracje muszą być
*addytywne* (nowe tabele i kolumny dopuszczające `NULL`/z wartością domyślną; usuwanie i zmiana nazw kolumn dopiero
w kolejnym wydaniu, po tym jak żadna działająca wersja ich nie używa). Migracja niszcząca lub zmieniająca znaczenie
danych wymaga kopii (`sudo /opt/ref-clips/deploy/backup.sh`) przed scaleniem PR-a wydania i świadomego powrotu
z odtworzeniem bazy (`deploy/restore.md`).

## Kroki jednorazowe po merge'u (ręcznie)

Kolejność: kroki 1–6 wykonaj **przed** merge'em tej gałęzi, krok 7 **po** nim (workflow z ręcznym uruchomieniem musi
najpierw trafić na `main`). Gdyby `release.yml` ruszył przed krokami 3–4, jego przebieg zakończy się błędem — wystarczy
go potem uruchomić ponownie. Pierwszy PR (ten z pipeline'em) jest zarazem pierwszym testem `ci.yml`; nazwy `unit` i `e2e`
pojawią się na liście wymaganych sprawdzeń dopiero po pierwszym przebiegu.
Poniżej `fkula5/ref-clips` to repozytorium, a `57.131.162.204` / `ubuntu` — serwer i użytkownik z `docs/wdrozenie.md`.

### 1. Osobny klucz CI (nie `ref_clips_deploy`)

Na swoim komputerze (bez hasła do klucza — CI nie ma jak go wpisać):

```bash
ssh-keygen -t ed25519 -N '' -C ref-clips-ci -f ~/.ssh/ref_clips_ci
cat ~/.ssh/ref_clips_ci.pub        # jedna linia „ssh-ed25519 AAAA… ref-clips-ci” — przyda się w kroku 2
```

### 2. Serwer: skrypt wejściowy i wymuszone polecenie

Skrypt `deploy/ci-entry.sh` instalujemy jako plik roota **poza** `/opt/ref-clips`. Z komputera, z repozytorium
(po przejrzeniu skryptu), swoim dotychczasowym kluczem:

```bash
scp -i ~/.ssh/ref_clips_deploy deploy/ci-entry.sh ubuntu@57.131.162.204:/tmp/ref-clips-ci-entry.sh
ssh -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 \
  'sudo install -o root -g root -m 755 /tmp/ref-clips-ci-entry.sh /usr/local/bin/ref-clips-ci-entry && rm /tmp/ref-clips-ci-entry.sh && ls -l /usr/local/bin/ref-clips-ci-entry'
```

Na serwerze (zalogowany jak zwykle) dopisz klucz publiczny do `~ubuntu/.ssh/authorized_keys` **z wymuszonym poleceniem**
(wklej swoją linię z kroku 1 po `restrict `):

```bash
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
echo 'command="/usr/local/bin/ref-clips-ci-entry",restrict ssh-ed25519 AAAA…TWÓJ_KLUCZ… ref-clips-ci' >> ~/.ssh/authorized_keys
```

Serwer potrzebuje `curl`, `tar` i `flock` (na Ubuntu 24.04 są). Sprawdzenie **z komputera** (klucz CI ma dać tylko `status`):

```bash
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204 status     # wersja i stan usług
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204 'id'       # ma być: Niedozwolone polecenie…
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204            # bez polecenia też odmowa (kod 2), bez powłoki
```

Po zmianach w `deploy/ci-entry.sh` w repozytorium instalujesz go ponownie tą samą komendą `install` (po przejrzeniu zmian) —
wdrożenie samo tego nie robi, a przy różnicy wypisze przypomnienie. Odebranie dostępu: usuń wiersz `ref-clips-ci` z `authorized_keys`.

### 3. GitHub: środowisko `production`, sekret i zmienne

Środowisko musi istnieć, zanim ustawisz jego sekrety:

```bash
gh api --method PUT repos/fkula5/ref-clips/environments/production
gh secret set DEPLOY_SSH_KEY --env production --repo fkula5/ref-clips < ~/.ssh/ref_clips_ci
gh variable set DEPLOY_HOST --env production --repo fkula5/ref-clips --body 57.131.162.204
gh variable set DEPLOY_USER --env production --repo fkula5/ref-clips --body ubuntu
```

`DEPLOY_HOST` musi być dokładnie tym adresem, który jest w `deploy/known_hosts` (tu: IP). Klucz idzie z pliku na
standardowe wejście, nic się nie wyświetla. Po wgraniu możesz usunąć lokalny plik klucza prywatnego
(`shred -u ~/.ssh/ref_clips_ci`; w razie potrzeby wygenerujesz nowy i zamienisz wpis na serwerze).
W interfejsie (Settings → Environments → production) ustaw też **Deployment branches and tags → Selected branches → `main`**;
opcjonalnie **Required reviewers** (wtedy każde wdrożenie wymaga zatwierdzenia przyciskiem — zwiększa bezpieczeństwo, ale
zabiera „automat”).

### 4. Zezwolenie, by Actions tworzyły PR-y

Bez tego release-please nie otworzy PR-a wydania. Settings → Actions → General → Workflow permissions →
zaznacz **Allow GitHub Actions to create and approve pull requests** (domyślne uprawnienia mogą zostać „Read”, joby
deklarują własne). To samo komendą:

```bash
gh api --method PUT repos/fkula5/ref-clips/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
```

### 5. Pierwszy PR i test CI

Otwórz PR z gałęzi `ci/release-pipeline` do `main` i sprawdź, że `unit` i `e2e` ruszają i przechodzą. Dopiero wtedy
nazwy są dostępne do wyboru w ochronie `main`.

### 6. Ochrona `main`

Settings → Rules → Rulesets → New branch ruleset (albo klasyczna ochrona gałęzi), cel: `main`:

- **Require a pull request before merging** (liczba zatwierdzeń 0 — jesteś jedynym autorem; PR wydania scalasz sam);
- **Require status checks to pass**: dodaj dokładnie `unit` i `e2e`, źródło **Any source** (nie przypinaj do „GitHub Actions” —
  status PR-a wydania pochodzi spoza checków workflow, patrz wyżej);
- **Block force pushes** i **Restrict deletions**; nie dodawaj wyjątków (bypass) bez potrzeby.

### 7. Po merge'u: próba na `v1.1.0`, widoczność pakietu w GHCR, pierwsze wydanie

Pakiety GHCR tworzone przez workflow dziedziczą uprawnienia repozytorium, ale **nie jego widoczność** — nowy pakiet jest
prywatny i serwer (bez logowania do GHCR) nie pobierze obrazu. Po merge'u tej gałęzi release-please otworzy PR
„chore: wydanie v1.2.0” (od `v1.1.0` jest `feat(app)`) — **jeszcze go nie scalaj**. Najpierw „próba generalna” na wersji,
która już działa: Actions → **Wydanie** → Run workflow → tag `v1.1.0` (to samo: `gh workflow run release.yml -f tag=v1.1.0`).
Job `build` zbuduje obraz tej wersji i utworzy pakiet, a `deploy` zakończy się błędem „nie udało się pobrać obrazu”
(kod 1, nic na serwerze nie zmienione). Wtedy:

1. GitHub → profil `fkula5` → Packages → `ref-clips` → Package settings → Danger Zone → **Change visibility → Public**
   (tego nie da się zrobić przez workflow);
2. sprawdź, że obraz pobiera się anonimowo (np. na serwerze: `docker logout ghcr.io; docker pull ghcr.io/fkula5/ref-clips:v1.1.0`);
3. uruchom ten sam workflow ponownie (`v1.1.0`) — wdrożenie przełączy serwer z obrazu lokalnego na obraz z GHCR
   (krótka przerwa na restart, ale dopiero gdy nic nie trwa); sprawdź w logu kroków, `status` i `/health`;
4. dopiero teraz scal PR „wydanie v1.2.0” (po zielonych testach; sprawdź, że na jego commicie są statusy `unit` i `e2e`) —
   workflow sam zbuduje obraz i wdroży `v1.2.0`.

Jeśli wolisz zostawić pakiet prywatny: na serwerze wykonaj `docker login ghcr.io` z tokenem klasycznym z uprawnieniem
`read:packages` (to dodatkowy sekret na serwerze, więc zalecamy pakiet publiczny — w obrazie nie ma sekretów).

## Ponowienie wdrożenia i powrót do starszej wersji

Actions → **Wydanie** → **Run workflow** (gałąź `main`) → pole `tag`, np. `v1.1.0`; z wiersza poleceń:

```bash
gh workflow run release.yml -f tag=v1.1.0
gh run watch                       # podgląd
```

Workflow sprawdza format tagu (`^v\d+\.\d+\.\d+$`) i czy istnieje, buduje obraz tylko jeśli go jeszcze nie ma w GHCR,
po czym wdraża go tak samo jak świeże wydanie (z czekaniem do 2 h na wolny serwer). Tak ponawiasz wdrożenie po błędzie
(np. kod 3 po dwóch godzinach) i tak wracasz do starszej wersji — pamiętając o uwadze o migracjach powyżej. Stare obrazy
są na serwerze tylko dla 3 ostatnich wersji, resztę serwer pobierze z GHCR (obrazy w GHCR nie są usuwane).

Awaryjnie, gdy GitHub jest niedostępny, na serwerze (obraz musi być jeszcze lokalnie, sprawdź `docker image ls ghcr.io/fkula5/ref-clips`):

```bash
cd /opt/ref-clips
nano .env                          # zmień jedną linię REFCLIPS_IMAGE=ghcr.io/fkula5/ref-clips:vX.Y.Z
COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose up -d --no-build --wait
```

albo zbuduj aktualny kod na serwerze z komputera: `deploy/deploy.sh` (patrz niżej).

## Wyjście awaryjne: `deploy/deploy.sh`

Skrypt nadal wysyła commit z komputera i buduje obraz na serwerze. Ponieważ `.env` może mieć `REFCLIPS_IMAGE` z GHCR,
skrypt na czas wdrożenia **wymusza `REFCLIPS_IMAGE=ref-clips:local`** (obraz zbudowany na serwerze nie podszywa się pod
tag z GHCR) i tuż przed restartem zapisuje tę wartość w `.env`, dzięki czemu `deploy/backup.sh` używa tego samego obrazu
co działający stos. Następne wdrożenie z GitHuba zastąpi tę linię tagiem GHCR. Blokada „coś trwa” (`--wait`, `--force`)
działa jak dotąd; obie ścieżki używają tej samej blokady `.deploy.lock`, więc nie nałożą się na siebie.
Uwaga: `deploy.sh` zapisuje w `.deploy-commit` hash commita, wdrożenia z GitHuba — numer wersji.

## Pliki

| Plik | Rola |
|---|---|
| `.github/workflows/ci.yml` | testy `unit` i `e2e` na PR-ach do `main` i ręcznie |
| `.github/workflows/release.yml` | release-please, budowa obrazu, wdrożenie; ręczne ponowienie/powrót (`tag`) |
| `release-please-config.json`, `.release-please-manifest.json`, `version.txt`, `CHANGELOG.md` | konfiguracja i stan wersji (start: 1.1.0, tag bez komponentu: `v1.2.3`) |
| `deploy/ci-entry.sh` | wymuszone polecenie klucza CI na serwerze (`deploy vX.Y.Z`, `status`) |
| `deploy/known_hosts` | przypięty klucz hosta serwera dla `ssh` z Actions |
| `deploy/deploy.sh` | wdrożenie awaryjne (build na serwerze) |
| `tests/test_ci_entry.py` | test `ci-entry.sh` z podstawionymi `docker` i `curl` |

Akcje innych autorów są przypięte do pełnych SHA (komentarz przy każdej podaje wersję); aktualizuj je świadomie.
Obrazy w GHCR i wydania na GitHubie nie mają automatycznego sprzątania.
