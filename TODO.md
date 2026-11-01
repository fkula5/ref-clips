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

- [ ] Znaczniki kwart w UI i klawisz „Zaznacz” (segment 4): `services.next_period` nie zna deklaracji zawartości — dla pliku z jedną kwartą (np. Q3, automatyczny znacznik Q3@0:00) „następną kwartą” wyjdzie Q1; przy dodawaniu znaczników uwzględnić `Video.content`.
- [ ] Zmiana deklaracji zawartości na jedną kwartę zostawia tylko najwcześniejszy znacznik (pozostałe są usuwane, kwarty klipów się przeliczają) — rozważyć ostrzeżenie w formularzu edycji, gdy znaczniki są usuwane.
- [ ] Po zmianie deklaracji wznowionego uploadu obowiązuje deklaracja z pierwszego POST (metadane zapisane po stronie serwera); poprawka przez „Edytuj” przy nagraniu.
- [ ] Wgrywanie wznowione bez zapamiętanego adresu (np. inna przeglądarka): ten sam plik (mecz, nazwa, rozmiar) startuje od zera, stary niedokończony upload jest wtedy usuwany.
- [ ] Panel admina: ostrzeżenie o odrzuconych uploadach z braku miejsca (plan 6.1) — na razie tylko wpis w logu serwera (segment 7).
- [ ] Pomiar czasu konwersji powtórzyć na prawdziwym VPS i na prawdziwym nagraniu (4K/HEVC), patrz plan 6.2 (segment 8).
- [ ] Wgrywanie w przeglądarce (`app/static/upload.js`) nie ma testów automatycznych: sprawdzono zgodność `tus-js-client` z serwerem skryptem w Node z podstawionym XHR (wznowienie, przerwanie), ale formularz z paskiem postępu wymaga ręcznego przejrzenia w przeglądarce.
