# Arkusz oceny kwalifikatora

Wzór: dwustronny „Arkusz oceny sędziów” Podkarpackiego Związku Koszykówki. Ocena jest opisowa, bez punktów i noty. Wdrożone na gałęzi `feat/qualifier-sheet` (migracja `mvp0006`).

## Zawartość
- **Nagłówek.** Z danych meczu: mecz, data, kategoria (liga), obsada. Zapisane w arkuszu: wynik (krótki tekst, do 50 znaków, np. „78:65”) i stopień trudności (łatwy / normalny / trudny). Kwalifikator wpisuje się sam na podstawie zalogowanego konta.
- **Elementy oceny.** Dla każdego sędziego z obsady (CC, U1, U2) osobny komentarz do elementu. Elementy z migracji, w kolejności: Obowiązki przedmeczowe, Przygotowanie fizyczne, Mechanika, Sygnalizacja, Ocena kontaktów, Ocena błędów, Współpraca, Kontrola gry, Przywództwo, Jakość pracy. Lista jest edytowalna w panelu admina (zakładka „Arkusz oceny”): dodawanie, zmiana nazwy, kolejność, dezaktywacja, usuwanie tylko nieużywanych.
- **Ocena ogólna.** Dla każdego sędziego opis i rekomendacja obsadowa (np. „Może sędziować każde zawody jako sędzia główny”), a do tego jedna wspólna uwaga o parze.
- Arkusz **nie zawiera listy momentów** ani punktów. Momenty idą dotychczasową drogą (znaczniki, notatki, klipy); arkusz i klipy łączy strona meczu (karta „Arkusz oceny”).

## Zasady dostępu (`app/permissions.py`, tabela w `tests/test_permissions.py`)
| Operacja | Kto |
|---|---|
| założenie | tylko rola szkoleniowca (sam admin nie wystarcza, jak przy ocenie klipu); jeden arkusz na parę (mecz, szkoleniowiec) wymuszony przez bazę, ponowne otwarcie edytuje istniejący |
| edycja i publikacja | tylko autor, także po publikacji |
| usunięcie | autor, dopóki to szkic; admin zawsze; z potwierdzeniem |
| podgląd szkicu | tylko autor |
| podgląd opublikowanego | autor, sędziowie z obsady mający konta, szkoleniowcy, administratorzy |

Kto nie może zobaczyć arkusza, dostaje **404** (nie 403) na każdej trasie arkusza, identyczne jak dla nieistniejącego numeru; na stronie meczu karta „Arkusz oceny” w ogóle się nie pokazuje. Dotyczy to zalogowanego sędziego spoza obsady, który mecz i klipy widzi. Dostęp sędziego z obsady liczy się według bieżącej obsady meczu (sędzia usunięty z obsady traci dostęp).

## Przebieg
- Szkic → opublikowany; brak cofania publikacji. Ten sam formularz ma „Zapisz szkic” i „Opublikuj”. Publikacja wymaga stopnia trudności; puste pola są dozwolone, a potwierdzenie (okno przeglądarki) podaje, ile ich jest; po publikacji komunikat powtarza liczbę pustych pól.
- Autor może poprawiać opublikowany arkusz (przycisk „Zapisz zmiany”; stopień trudności musi zostać). Gdy edycja nastąpiła po publikacji, widać „zmieniono <data>”; ponowny zapis identycznej treści nie jest zmianą.
- Limity: każde pole tekstowe 5000 znaków (`config.TEXT_MAX_CHARS`), wynik 50 (`config.SHEET_RESULT_MAX_CHARS`). Błąd walidacji pokazuje formularz (422) ze wszystkim, co wpisano, i listą błędów; sukces to 303 na stronę z jednorazowym komunikatem (ciasteczko `refclips_notice`, `app/flash.py`). Pole, którego nie było w wysłanym formularzu, zostaje bez zmian, więc nieaktualny formularz nie skasuje tekstu.
- Skrypt `static/sheet.js`: ostrzeżenie `beforeunload` przy niezapisanych zmianach (bez fałszywego alarmu przy zapisie; po błędzie walidacji formularz startuje jako „niezapisany”) i potwierdzenie publikacji z liczbą pustych pól.

## Kopie (snapshoty)
Przy założeniu arkusza zapisujemy nazwy elementów (wiersze) oraz funkcję i nazwisko każdego sędziego (kolumny). Zmiana nazwy, dezaktywacja i usunięcie elementu oraz zmiana obsady meczu nie zmieniają istniejących arkuszy; nowy arkusz bierze aktualny słownik i obsadę. Nagłówek (drużyny, data, liga) jest czytany z meczu na żywo. `SheetRow.element_id` służy tylko do sprawdzenia, czy element jest używany.

**Odświeżenie obsady szkicu.** Gdy obsada meczu różni się od kolumn szkicu, formularz pokazuje różnice i przycisk „Odśwież obsadę”: zapisuje wpisany tekst, dodaje puste kolumny nowych sędziów, aktualizuje funkcję osoby, która ją zmieniła, i usuwa kolumnę sędziego spoza obsady tylko wtedy, gdy jest pusta; kolumny z tekstem zostają (z komunikatem). Osoby rozpoznajemy po nazwisku. Dla opublikowanego arkusza obsada jest zamrożona.

## Wydruk i PDF
Przycisk „Drukuj / zapisz jako PDF” wywołuje `window.print()`. Arkusz drukuje się z arkusza stylów `@media print` (A4 przez nazwaną stronę `sheet`, bez nawigacji, przycisków, komunikatów i stopki; wiersze nie są dzielone między strony). Bez nowych zależności i bez PDF po stronie serwera; bez logotypów związku.

## Dane
Tabele: `sheet_elements`, `sheets`, `sheet_columns` (sędzia, ocena ogólna i rekomendacja), `sheet_rows` (element), `sheet_cells` (komentarz). Usunięcie meczu kasuje arkusze (ON DELETE CASCADE); klucz autora bez kaskady, jak przy ocenach. Migracja dodaje dziesięć elementów; `app/seed.py` ich nie dosiewa, więc usunięcie wszystkich nie wraca po restarcie.
