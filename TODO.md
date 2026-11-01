# Do zmiany (uwagi z testów)

- [x] **Funkcje sędziów w obsadzie: CC, U1, U2.** *(zrobione w segmencie 1: tabela `match_officials`, nowa migracja początkowa zamiast przeróbki starej)* Pierwszy sędzia to CC (crew chief), drugi U1, opcjonalny trzeci U2. Teraz `MATCH_ROLES` w `app/models.py` ma tylko „Sędzia główny (R)” i „Sędzia pomocniczy (U)”, a formularz w `app/templates/match_form.html` ustawia je domyślnie według kolejności. Do zmiany:
  - wartości `cc` / `u1` / `u2` i etykiety CC / U1 / U2,
  - domyślne przypisanie według pozycji (1 → CC, 2 → U1, 3 → U2),
  - migracja Alembic dla istniejących wpisów (`crew_chief` → `cc`, `umpire` → `u1`/`u2` według kolejności),
  - wyświetlanie funkcji przy klipach i w filtrach.

## Uwagi z segmentu 1 (drobne, odłożone)

- [x] HTMX przypięty lokalnie: `app/static/vendor/htmx-2.0.4.min.js` (bez CDN).
- [x] Błędy 403/404/422 przy wysyłce formularza pokazują prostą stronę błędu; warto je zamienić na komunikaty w formularzach. *(segment 2: formularz meczu i panel admina pokazują błąd z zachowanymi wartościami; `error.html` zostaje dla 403/404/422 przy nawigacji, z tekstem i linkiem powrotu)*
- [ ] Komentarze do meczu (tabela gotowa, brak trasy i widoku) oraz edycja komentarza (reguła `can_edit_comment` gotowa) — segment 6.
- [ ] Sędzia usunięty z obsady przestaje mieć dostęp do meczu, ale jego klipy zostają bez powiązania z pozycją (`official_id` = NULL).
- [x] Obsada: to samo ręcznie wpisane imię i nazwisko na dwóch pozycjach jest po cichu scalane w jedną pozycję (`set_officials` indeksuje po tożsamości). Formularz powinien odrzucić duplikat, tak jak robi to dla kont. *(segment 2; także konto i wpisane nazwisko tej samej osoby)*
- [x] Obsada: zamiana wpisanego nazwiska na konto tej samej osoby (np. sędzia założył konto później) jest traktowana jako nowa osoba, więc jej klipy tracą przypisanie. Warto dopasowywać też po nazwisku konta. *(segment 2: dopasowanie w obie strony po znormalizowanym nazwisku konta; przy dwóch kontach o tej samej nazwie nie łączymy)*

## Uwagi z segmentu 2 (drobne, odłożone)

- [ ] Lista meczów nie odświeża się sama podczas konwersji (stan i pozycja w kolejce aktualizują się po odświeżeniu lub zmianie filtra); strona meczu odświeża panel nagrań co 3 s.
- [ ] Filtr „liga” to dokładne dopasowanie nazwy (ligi różniące się wielkością liter są osobnymi pozycjami); ewentualne scalanie wariantów pisowni to osobna decyzja.
- [x] Cały mecz wymaga znaczników Q1–Q4 (dogrywki opcjonalne); po wprowadzeniu deklaracji zawartości w segmencie 3 sprawdzić, czy `services.missing_periods` zgadza się z formatem pola `Video.content`. *(segment 3: format bez zmian — `full` albo kwarty po przecinku, zapis przez `services.normalize_content`; testy w `tests/test_uploads.py`)*
- [ ] Lista klipów na stronie meczu nie ma własnych filtrów (sędzia/kategoria/kwarta) — odsyła do `/clips?match_id=...`; zakładka z filtrami to segment 5.

## Uwagi z segmentu 3 (drobne, odłożone)

- [x] Znaczniki kwart w UI i klawisz „Zaznacz” (segment 4): `services.next_period` nie zna deklaracji zawartości. *(segment 4: `next_period(marks, content)` wg deklaracji — cały mecz Q1→…→OT1, kilka kwart tylko zadeklarowane, jedna kwarta przesuwa swój znacznik)*
- [x] Zmiana deklaracji zawartości na jedną kwartę zostawia tylko najwcześniejszy znacznik — ostrzeżenie w formularzu edycji, gdy znaczniki są usuwane. *(segment 4: lista usuwanych znaczników i potwierdzenie; zostaje znacznik tej kwarty, jeśli istnieje, inaczej najwcześniejszy przemianowany)*
- [ ] Po zmianie deklaracji wznowionego uploadu obowiązuje deklaracja z pierwszego POST (metadane zapisane po stronie serwera); poprawka przez „Edytuj” przy nagraniu.
- [ ] Wgrywanie wznowione bez zapamiętanego adresu (np. inna przeglądarka): ten sam plik (mecz, nazwa, rozmiar) startuje od zera, stary niedokończony upload jest wtedy usuwany.
- [ ] Panel admina: ostrzeżenie o odrzuconych uploadach z braku miejsca (plan 6.1) — na razie tylko wpis w logu serwera (segment 7).
- [ ] Pomiar czasu konwersji powtórzyć na prawdziwym VPS i na prawdziwym nagraniu (4K/HEVC), patrz plan 6.2 (segment 8).
- [x] Wgrywanie w przeglądarce (`app/static/upload.js`) nie ma testów automatycznych. *(segment 4a: `tests/e2e/test_upload.py` — pasek postępu, notatki z podglądem, przerwanie i wznowienie, Przerwij, konflikt uploadów, dwa pliki)*

## Uwagi z segmentu 4 (drobne, odłożone)

- [x] Interfejs odtwarzacza (`app/static/player.js`) i podglądu notatek w formularzu wgrywania (`upload.js`) nie ma testów automatycznych w przeglądarce. *(segment 4a: `tests/e2e/test_player.py`; w Chromium sprawdzone `Z`/`Backspace`/`M`/`Q`/`F`/`?`, błysk i API pełnego ekranu; zostaje ręczne przejrzenie w Safari/iPhonie)*
- [ ] Pełny ekran działa przez kontener `.video-wrap` (własny przycisk i klawisz `F`; natywny przycisk pełnego ekranu jest ukryty przez `controlsList="nofullscreen"`, co obsługuje Chrome). W Safari natywny pełny ekran wideo nie pokazuje błysku ani toastów.
- [ ] „Cofnij ostatni znacznik” (Backspace) usuwa ostatni własny nieopisany klip w nagraniu, także utworzony z notatek przy wgrywaniu lub klawiszem `M`; rozważyć ograniczenie do znaczników z bieżącej sesji odtwarzacza.
- [ ] Ochrona przed podwójnym kliknięciem używa blokady w procesie (`services.MARKER_LOCK`); przy kilku procesach uvicorn wystarcza sprawdzenie czasu w bazie, ale dwa żądania w tej samej milisekundzie do różnych procesów mogłyby oba przejść.
- [ ] Usunięcie znacznika w trakcie cięcia go przez worker może zostawić osierocony plik klipu (jak przy usuwaniu klipu na jego stronie); posprzątać w zadaniu `cleanup` (segment 7).
- [ ] Notatki przy wgrywaniu: podgląd nie zna długości nagrania, więc „moment poza nagraniem” wychodzi dopiero po konwersji (klip w stanie błędu, „Spróbuj ponownie” nie pomoże — usuń klip).

## Uwagi z segmentu 4a (drobne, odłożone)

- [ ] Testy E2E działają tylko w Chromium (Playwright) i na pliku H.264/AAC; Safari/iPhone (kryterium akceptacji: odtwarzanie klipów na telefonie) wymaga ręcznego sprawdzenia na prawdziwym urządzeniu. Prawdziwy pełny ekran na monitorze (wygląd błysku) też tylko ręcznie.
- [ ] Filtry listy meczów (HTMX) wysyłają w adresie puste parametry (`?date_from=&date_to=&level=X&person=`); działa, ale adres jest brzydki — `hx-params` albo skrypt usuwający puste pola.
- [ ] Przy zerwanym połączeniu (`navigator.onLine === false`, np. tryb offline) wgrywanie nie ponawia się samo, tylko pokazuje komunikat i prosi o ponowny wybór pliku; ponawianie działa przy błędach sieci i serwera, gdy przeglądarka uważa się za online.
- [ ] Lista klipów na stronie meczu i stan meczu odświeżają się razem z panelem nagrań co 3 s (także podczas cięcia klipów); jeśli worker nie działa, strona meczu odpytuje serwer w nieskończoność, dopóki są klipy „w kolejce” — ewentualnie wydłużyć odstęp po minucie.
- [ ] Testy E2E uruchamiają jeden serwer na całą sesję i dzielą bazę (każdy test zakłada własny mecz); równoległe uruchamianie (pytest-xdist) wymaga osobnych serwerów.
