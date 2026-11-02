# Do zmiany (uwagi z testów)

- [x] **Funkcje sędziów w obsadzie: CC, U1, U2.** *(zrobione w segmencie 1: tabela `match_officials`, nowa migracja początkowa zamiast przeróbki starej)* Pierwszy sędzia to CC (crew chief), drugi U1, opcjonalny trzeci U2. Teraz `MATCH_ROLES` w `app/models.py` ma tylko „Sędzia główny (R)” i „Sędzia pomocniczy (U)”, a formularz w `app/templates/match_form.html` ustawia je domyślnie według kolejności. Do zmiany:
  - wartości `cc` / `u1` / `u2` i etykiety CC / U1 / U2,
  - domyślne przypisanie według pozycji (1 → CC, 2 → U1, 3 → U2),
  - migracja Alembic dla istniejących wpisów (`crew_chief` → `cc`, `umpire` → `u1`/`u2` według kolejności),
  - wyświetlanie funkcji przy klipach i w filtrach.

## Uwagi z segmentu 1 (drobne, odłożone)

- [x] HTMX przypięty lokalnie: `app/static/vendor/htmx-2.0.4.min.js` (bez CDN).
- [x] Błędy 403/404/422 przy wysyłce formularza pokazują prostą stronę błędu; warto je zamienić na komunikaty w formularzach. *(segment 2: formularz meczu i panel admina pokazują błąd z zachowanymi wartościami; `error.html` zostaje dla 403/404/422 przy nawigacji, z tekstem i linkiem powrotu)*
- [x] Komentarze do meczu (tabela gotowa, brak trasy i widoku) oraz edycja komentarza (reguła `can_edit_comment` gotowa) — segment 6. *(segment 6: komentarze do meczu i klipu z edycją inline, usuwaniem i testami uprawnień; trasy `/matches/{id}/comments…` i `/clips/{id}/comments…`)*
- [ ] Sędzia usunięty z obsady przestaje mieć dostęp do meczu, ale jego klipy zostają bez powiązania z pozycją (`official_id` = NULL).
- [x] Obsada: to samo ręcznie wpisane imię i nazwisko na dwóch pozycjach jest po cichu scalane w jedną pozycję (`set_officials` indeksuje po tożsamości). Formularz powinien odrzucić duplikat, tak jak robi to dla kont. *(segment 2; także konto i wpisane nazwisko tej samej osoby)*
- [x] Obsada: zamiana wpisanego nazwiska na konto tej samej osoby (np. sędzia założył konto później) jest traktowana jako nowa osoba, więc jej klipy tracą przypisanie. Warto dopasowywać też po nazwisku konta. *(segment 2: dopasowanie w obie strony po znormalizowanym nazwisku konta; przy dwóch kontach o tej samej nazwie nie łączymy)*

## Uwagi z segmentu 2 (drobne, odłożone)

- [ ] Lista meczów nie odświeża się sama podczas konwersji (stan i pozycja w kolejce aktualizują się po odświeżeniu lub zmianie filtra); strona meczu odświeża panel nagrań co 3 s.
- [ ] Filtr „liga” to dokładne dopasowanie nazwy (ligi różniące się wielkością liter są osobnymi pozycjami); ewentualne scalanie wariantów pisowni to osobna decyzja.
- [x] Cały mecz wymaga znaczników Q1–Q4 (dogrywki opcjonalne); po wprowadzeniu deklaracji zawartości w segmencie 3 sprawdzić, czy `services.missing_periods` zgadza się z formatem pola `Video.content`. *(segment 3: format bez zmian — `full` albo kwarty po przecinku, zapis przez `services.normalize_content`; testy w `tests/test_uploads.py`)*
- [x] Lista klipów na stronie meczu nie ma własnych filtrów (sędzia/kategoria/kwarta) — odsyła do `/clips?match_id=...`; zakładka z filtrami to segment 5. *(segment 5: sekcja „Klipy” meczu z filtrami w adresie, HTMX i bez JS; /clips ma te same filtry)*

## Uwagi z segmentu 3 (drobne, odłożone)

- [x] Znaczniki kwart w UI i klawisz „Zaznacz” (segment 4): `services.next_period` nie zna deklaracji zawartości. *(segment 4: `next_period(marks, content)` wg deklaracji — cały mecz Q1→…→OT1, kilka kwart tylko zadeklarowane, jedna kwarta przesuwa swój znacznik)*
- [x] Zmiana deklaracji zawartości na jedną kwartę zostawia tylko najwcześniejszy znacznik — ostrzeżenie w formularzu edycji, gdy znaczniki są usuwane. *(segment 4: lista usuwanych znaczników i potwierdzenie; zostaje znacznik tej kwarty, jeśli istnieje, inaczej najwcześniejszy przemianowany)*
- [ ] Po zmianie deklaracji wznowionego uploadu obowiązuje deklaracja z pierwszego POST (metadane zapisane po stronie serwera); poprawka przez „Edytuj” przy nagraniu.
- [ ] Wgrywanie wznowione bez zapamiętanego adresu (np. inna przeglądarka): ten sam plik (mecz, nazwa, rozmiar) startuje od zera, stary niedokończony upload jest wtedy usuwany.
- [x] Panel admina: ostrzeżenie o odrzuconych uploadach z braku miejsca (plan 6.1) — na razie tylko wpis w logu serwera (segment 7). *(segment 7: zapis w tabeli `upload_rejections` + baner na zakładkach panelu i lista na „Retencja i dysk”; wpis w logu zostaje)*
- [ ] Pomiar czasu konwersji powtórzyć na prawdziwym VPS i na prawdziwym nagraniu (4K/HEVC), patrz plan 6.2 (segment 8).
- [x] Wgrywanie w przeglądarce (`app/static/upload.js`) nie ma testów automatycznych. *(segment 4a: `tests/e2e/test_upload.py` — pasek postępu, notatki z podglądem, przerwanie i wznowienie, Przerwij, konflikt uploadów, dwa pliki)*

## Uwagi z segmentu 4 (drobne, odłożone)

- [x] Interfejs odtwarzacza (`app/static/player.js`) i podglądu notatek w formularzu wgrywania (`upload.js`) nie ma testów automatycznych w przeglądarce. *(segment 4a: `tests/e2e/test_player.py`; w Chromium sprawdzone `Z`/`Backspace`/`M`/`Q`/`F`/`?`, błysk i API pełnego ekranu; zostaje ręczne przejrzenie w Safari/iPhonie)*
- [ ] Pełny ekran działa przez kontener `.video-wrap` (własny przycisk i klawisz `F`; natywny przycisk pełnego ekranu jest ukryty przez `controlsList="nofullscreen"`, co obsługuje Chrome). W Safari natywny pełny ekran wideo nie pokazuje błysku ani toastów.
- [ ] „Cofnij ostatni znacznik” (Backspace) usuwa ostatni własny nieopisany klip w nagraniu, także utworzony z notatek przy wgrywaniu lub klawiszem `M`; rozważyć ograniczenie do znaczników z bieżącej sesji odtwarzacza.
- [ ] Ochrona przed podwójnym kliknięciem używa blokady w procesie (`services.MARKER_LOCK`); przy kilku procesach uvicorn wystarcza sprawdzenie czasu w bazie, ale dwa żądania w tej samej milisekundzie do różnych procesów mogłyby oba przejść.
- [x] Usunięcie znacznika w trakcie cięcia go przez worker może zostawić osierocony plik klipu (jak przy usuwaniu klipu na jego stronie); posprzątać w zadaniu `cleanup` (segment 7). *(segment 7: `retention.cleanup_orphan_clips` w sprzątaniu workera — pliki `.mp4` w `clips/` bez klipu o takim `clip_path`, starsze niż godzina)*
- [ ] Notatki przy wgrywaniu: podgląd nie zna długości nagrania, więc „moment poza nagraniem” wychodzi dopiero po konwersji (klip w stanie błędu, „Spróbuj ponownie” nie pomoże — usuń klip).

## Uwagi z segmentu 4a (drobne, odłożone)

- [ ] Testy E2E działają tylko w Chromium (Playwright) i na pliku H.264/AAC; Safari/iPhone (kryterium akceptacji: odtwarzanie klipów na telefonie) wymaga ręcznego sprawdzenia na prawdziwym urządzeniu. Prawdziwy pełny ekran na monitorze (wygląd błysku) też tylko ręcznie.
- [x] Filtry listy meczów (HTMX) wysyłają w adresie puste parametry (`?date_from=&date_to=&level=X&person=`); działa, ale adres jest brzydki — `hx-params` albo skrypt usuwający puste pola. *(segment 5: `static/filters.js`, atrybut `data-clean-params` na formularzach filtrów)*
- [ ] Przy zerwanym połączeniu (`navigator.onLine === false`, np. tryb offline) wgrywanie nie ponawia się samo, tylko pokazuje komunikat i prosi o ponowny wybór pliku; ponawianie działa przy błędach sieci i serwera, gdy przeglądarka uważa się za online.
- [ ] Lista klipów na stronie meczu i stan meczu odświeżają się razem z panelem nagrań co 3 s (także podczas cięcia klipów); jeśli worker nie działa, strona meczu odpytuje serwer w nieskończoność, dopóki są klipy „w kolejce” — ewentualnie wydłużyć odstęp po minucie.
- [ ] Testy E2E uruchamiają jeden serwer na całą sesję i dzielą bazę (każdy test zakłada własny mecz); równoległe uruchamianie (pytest-xdist) wymaga osobnych serwerów.

## Uwagi z segmentu 5 (drobne, odłożone)

- [x] Oceny szkoleniowców: na stronie klipu i w tabeli klipów jest tylko miejsce (kolumna „Oceny”, karta „Oceny szkoleniowców”) — segment 6. *(segment 6: karta ocen z formularzem dla szkoleniowca, podsumowanie w tabeli klipów i filtr „Oceny” w adresie)*
- [ ] Sędzia wpisany ręcznie i usunięty z obsady: klipy tracą przypisanie (`official_id` = NULL) i trzeba je opisać od nowa — ekran opisywania ich nie wyłapuje, bo mają `described_at`.
- [ ] Klip z kwartą nieustaloną jest blokowany także, gdy znaczniki kwart są niekompletne, a sam klip leży w ustawionej kwarcie (zgodnie ze specyfikacją: do czasu kompletu kwart klipy z pliku mają kwartę nieustaloną). Lista znaczników w odtwarzaczu i tabela klipów pokazują w tym stanie najlepszą znaną kwartę, a ekran opisywania „kwarta nieustalona”.
- [x] Po usunięciu pełnego nagrania (retencja, segment 7) klipu z nieustaloną kwartą nie da się już opisać (nie ma gdzie ustawić kwart) — rozważyć, czy panel admina ma dawać wyjście. *(segment 7: po usunięciu pełnego nagrania blokada opisu znika — klip opisuje się z kwartą „nieustaloną”; ręczne wpisywanie kwart bez nagrania odłożone, patrz niżej)*
- [ ] Podgląd klipu w kolejce używa wersji roboczej (zakres klipu, zatrzymanie na końcu robi `describe.js`); strona ekranu nie przełącza się sama na plik klipu po wycięciu — wystarczy odświeżyć.
- [ ] `Enter` na liście kategorii zapisuje formularz tylko przy zamkniętej liście (otwarta lista zużywa Enter na wybór opcji).
- [ ] Opis (`description`) klipów ze znacznika `M` zawiera całą linię notatki (np. „2:54 CC kroki”), więc propozycja opisu bywa powtórzeniem sędziego i kategorii — warto zapisywać tylko resztę linii po rozpoznaniu.

## Uwagi z segmentu 6 (drobne, odłożone)

- [ ] Użytkowników nie da się usunąć (panel tylko dezaktywuje konta), więc `ratings.coach_id` i `comments.author_id` nie mają `ON DELETE`; baza odrzuci usunięcie konta z ocenami lub komentarzami (test w `tests/test_feedback.py`). Ewentualne usuwanie kont wymaga decyzji (anonimizacja autora vs kaskada).
- [ ] Komentarze nie mają wątków ani powiadomień; nie ma paginacji (sekcja pokazuje wszystkie komentarze meczu lub klipu).
- [ ] Wynik zapisu przez HTMX po błędzie innym niż walidacja (403/404) to krótki komunikat (toast) bez odświeżenia listy; widok poprawia się dopiero po przeładowaniu strony. Nie ma też odświeżania komentarzy dodanych przez innych w czasie, gdy strona jest otwarta.
- [ ] Przy dodaniu komentarza bez JavaScriptu na stronie klipu filtry listy, z której przyszedł użytkownik (poprzedni/następny klip), nie są zachowywane w adresie po przekierowaniu.
- [ ] Usunięcie komentarza i oceny bez JavaScriptu nie pyta o potwierdzenie (przycisk w zwykłym formularzu); z JavaScriptem jest `confirm`.
- [ ] Znacznik „zmieniona” przy ocenie i „edytowano” przy komentarzu opierają się na porównaniu `updated_at`/`edited_at`; ponowny zapis identycznej treści nie jest uznawany za zmianę. Daty pokazywane są w UTC, jak w reszcie aplikacji.
- [ ] Filtr ocen „ma ocenę: X” oznacza „co najmniej jedna ocena X” (klip z oceną prawidłową i dyskusyjną pasuje do obu); brak filtru „oceny sprzeczne” czy „zgodne”.
- [ ] Indeksy dodano tylko dla `comments.clip_id` i `comments.match_id` (migracja `mvp0003`); `ratings.clip_id` pokrywa unikalność (clip_id, coach_id), a `ratings.coach_id` bez indeksu (tylko kontrola kluczy obcych).
- [ ] Widoki mobilne sprawdzone w Chromium 375×740, nie na prawdziwym iPhonie/Safari (pole `<details>` do zmiany cudzej oceny i `confirm` w przycisku warto obejrzeć ręcznie).
- [ ] Test E2E `test_player.py::test_podwojne_z_to_jeden_znacznik_a_backspace_cofa` raz nie przeszedł podczas prac nad segmentem 6; zależy od czasu (blokada podwójnego `Z` przez 1 s), może być niestabilny przy obciążonej maszynie — obserwować. W review segmentu 7 jeden z czterech pełnych przebiegów E2E miał 1 porażkę (nazwa testu nie została zapisana, kolejne przebiegi i 8× sam `test_player.py` zielone) — przy następnym wystąpieniu uruchamiać z `-rf` i ustabilizować ten test.

## Uwagi z segmentu 7 (drobne, odłożone)

- [ ] Klip z nieustaloną kwartą po usunięciu pełnego nagrania zostaje z kwartą „nieustaloną” na zawsze — admin nie może wpisać początków kwart ręcznie (bez nagrania nie ma jak ich odczytać). Ewentualny ekran „wpisz czas początku kwarty” dla usuniętych nagrań to osobna decyzja.
- [ ] Zadanie retencji działa raz na dobę (sprawdzane co godzinę): nagranie po terminie może poczekać do ok. doby; nagranie pominięte (konwersja, klipy w kolejce) wraca dopiero w następnym przebiegu. Brak przycisku „uruchom sprzątanie teraz” w panelu.
- [ ] Nagranie, z którego czekają klipy na cięcie, nie wygasa i nie da się go usunąć ręcznie; gdy worker nie działa (brak ffmpeg), klipy wiszą „w kolejce”, a retencja i przycisk usuwania czekają razem z nimi.
- [ ] Nagranie w stanie błędu konwersji po terminie jest usuwane razem z oryginałem (nie da się go już ponowić); klipy czekające w jego kolejce dostają stan błędu „usunięte przed wycięciem”.
- [ ] Zajętość dysku liczy tylko pliki znane aplikacji (wersje robocze z bazy, oryginały, uploady, katalog klipów); baza SQLite, pliki tymczasowe (`tmp/`) i inne dane na tym samym dysku nie są pokazywane osobno (widać je tylko w „wolnym miejscu”).
- [ ] Panel kategorii używa zwykłych formularzy (pełne przeładowanie strony po każdej akcji, bez HTMX i przeciągania); grupy to stała lista pięciu grup ze specyfikacji — dodawanie nowych grup nie jest możliwe.
- [ ] Konflikty aliasów wykrywamy tylko na równość znormalizowanych napisów; aliasy będące fragmentem innych (np. „blok” i „blok / szarża”) rozstrzyga parser (dłuższy alias wygrywa), bez ostrzeżenia w panelu.
- [ ] Zmiana `retention_days` z przeliczeniem nadaje termin także nagraniom bez terminu (`expires_at` NULL, np. sprzed wprowadzenia retencji); bez przeliczenia takie nagrania nigdy nie wygasają.
- [ ] Daty w panelu retencji są w UTC, jak w reszcie aplikacji; „dostępne jeszcze X dni” zaokrągla w górę do pełnych dni.
- [ ] `retention.purge_video` usuwa pliki przed zapisem `purged_at` w bazie; jeśli commit się nie uda (np. zajęta baza), nagranie zostaje „gotowe” bez pliku do najbliższego przebiegu retencji. Bezpieczniejsza kolejność: najpierw `purged_at` (commit), potem pliki, a nieudane usunięcie pliku zostawić sprzątaniu.
- [ ] Formularze panelu admina (kategorie, retencja, usunięcie nagrania) odpowiadają stroną zamiast przekierowania 303 — odświeżenie strony po zapisie wysyła formularz ponownie (tak jak dotychczasowa strona kont).

## Uwagi z testów UI (2026-11-03)

- [ ] Strona klipu: odtwarzacz nie jest wyrównany do bocznego panelu („Opis klipu”, „Oceny szkoleniowców”) — górne krawędzie wideo i pierwszej karty powinny być w jednej linii.
- [ ] Strona klipu: „Pobierz MP4” przylega do odtwarzacza (brak odstępu) i jest słabo umiejscowiony — dodać odstęp i przemyśleć miejsce (np. pasek akcji pod wideo razem z nazwą pliku, wyrównany do krawędzi odtwarzacza).
- [ ] Wszystkie tabele (m.in. panel kategorii, użytkownicy): kolumna z przyciskami akcji rozjeżdża się względem wierszy danych — linie wierszy w kolumnie akcji nie pokrywają się z resztą, wysokości komórek są różne. Ujednolicić wyrównanie pionowe i wysokość wierszy we wszystkich tabelach.
