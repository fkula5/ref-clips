# Do zmiany (uwagi z testów)

- [ ] **Funkcje sędziów w obsadzie: CC, U1, U2.** Pierwszy sędzia to CC (crew chief), drugi U1, opcjonalny trzeci U2. Teraz `MATCH_ROLES` w `app/models.py` ma tylko „Sędzia główny (R)” i „Sędzia pomocniczy (U)”, a formularz w `app/templates/match_form.html` ustawia je domyślnie według kolejności. Do zmiany:
  - wartości `cc` / `u1` / `u2` i etykiety CC / U1 / U2,
  - domyślne przypisanie według pozycji (1 → CC, 2 → U1, 3 → U2),
  - migracja Alembic dla istniejących wpisów (`crew_chief` → `cc`, `umpire` → `u1`/`u2` według kolejności),
  - wyświetlanie funkcji przy klipach i w filtrach.
