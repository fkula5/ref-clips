# Do zmiany (uwagi z testów)

- [x] **Funkcje sędziów w obsadzie: CC, U1, U2.** *(zrobione w segmencie 1: tabela `match_officials`, nowa migracja początkowa zamiast przeróbki starej)* Pierwszy sędzia to CC (crew chief), drugi U1, opcjonalny trzeci U2. Teraz `MATCH_ROLES` w `app/models.py` ma tylko „Sędzia główny (R)” i „Sędzia pomocniczy (U)”, a formularz w `app/templates/match_form.html` ustawia je domyślnie według kolejności. Do zmiany:
  - wartości `cc` / `u1` / `u2` i etykiety CC / U1 / U2,
  - domyślne przypisanie według pozycji (1 → CC, 2 → U1, 3 → U2),
  - migracja Alembic dla istniejących wpisów (`crew_chief` → `cc`, `umpire` → `u1`/`u2` według kolejności),
  - wyświetlanie funkcji przy klipach i w filtrach.

## Uwagi z segmentu 1 (drobne, odłożone)

- [x] HTMX przypięty lokalnie: `app/static/vendor/htmx-2.0.4.min.js` (bez CDN).
- [ ] Błędy 403/404/422 przy wysyłce formularza pokazują prostą stronę błędu; warto je zamienić na komunikaty w formularzach.
- [ ] Komentarze do meczu (tabela gotowa, brak trasy i widoku) oraz edycja komentarza (reguła `can_edit_comment` gotowa) — segment 6.
- [ ] Sędzia usunięty z obsady przestaje mieć dostęp do meczu, ale jego klipy zostają bez powiązania z pozycją (`official_id` = NULL).
