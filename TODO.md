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
- [ ] Cały mecz wymaga znaczników Q1–Q4 (dogrywki opcjonalne); po wprowadzeniu deklaracji zawartości w segmencie 3 sprawdzić, czy `services.missing_periods` zgadza się z formatem pola `Video.content`.
- [ ] Lista klipów na stronie meczu nie ma własnych filtrów (sędzia/kategoria/kwarta) — odsyła do `/clips?match_id=...`; zakładka z filtrami to segment 5.
