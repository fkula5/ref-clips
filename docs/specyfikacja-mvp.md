# Narzędzie do wycinania klipów meczowych dla sędziów koszykówki

> Specyfikacja dla Claude Code. **Budujemy tylko MVP** (sekcja 1). Pozostałe sekcje opisują docelową wizję – traktuj je jako kontekst, nie jako zakres pracy.
> Wersja 0.3, 2026-11-01. Uwzględnia decyzje z przeglądu specyfikacji.

## 0. Kontekst

Aplikacja webowa, w której sędziowie i szkoleniowcy koszykówki wgrywają nagrania meczów, zaznaczają momenty do analizy (decyzje, sytuacje bez gwizdka, poruszanie się sędziów), a narzędzie automatycznie wycina z nich klipy do analizy, komentowania i oceny.

**Problem:** po meczu ktoś przegląda 1,5–2 h nagrania, notuje czasy na kartce i ręcznie wycina fragmenty w ogólnym edytorze wideo. Trwa to godzinami, a klipy lądują w folderach bez opisu.

**Założenia:**
- Na własny użytek, dla sędziów jednego okręgu (kilkudziesięciu użytkowników, nie tysiące)
- Bezpłatne – brak płatności i subskrypcji
- Tylko online – bez trybu offline
- Interfejs po polsku
- Nagrania pochodzą z dowolnego źródła (telefon sędziego, kamera Veo itp.) – zawsze jako plik wgrywany do systemu (MP4, MOV); pliki mogą być duże (kilka GB)
- Istnieje prototyp `ref-clips` (FastAPI + SQLite + ffmpeg, bez logowania): konwersja nagrań, znaczniki kwart, parser notatek, cięcie klipów, strumieniowanie wideo. Plan techniczny ma uzasadnić, czy go rozwijamy, czy zastępujemy.

## 1. MVP – zakres do zbudowania

### Happy path

1. Użytkownik loguje się na platformę.
2. Wgrywa mecz, wpisuje obsadę sędziowską (CC, U1, opcjonalnie U2) i opcjonalnie wkleja notatki z momentami do wycięcia.
3. Jeśli plik zawiera więcej niż jedną kwartę, ustawia znaczniki początku kwart.
4. Ogląda mecz i zaznacza kolejne momenty (bez przerywania oglądania). Opisuje je później, w jednym miejscu.
5. Z każdego znacznika powstaje klip 30 s: 15 s przed i 15 s po.
6. Klipy meczu pojawiają się pod nagraniem lub w osobnej zakładce. Każdy ma opis: sędzia, kategoria, kwarta i czas od początku kwarty.
7. Po wejściu w klip widać jego opis, komentarze i oceny szkoleniowców.

### Role i uprawnienia

Użytkownik może mieć **kilka ról naraz** (np. administrator + szkoleniowiec). Uprawnienia sumują się.

| Uprawnienie | Administrator | Szkoleniowiec | Sędzia |
| --- | --- | --- | --- |
| Zarządzanie kontami i przypisywanie ról | Tak | Nie | Nie |
| Zarządzanie słownikiem kategorii | Tak | Nie | Nie |
| Przeglądanie wszystkich meczów i klipów | Tak | Tak | Tak |
| Wgrywanie meczów i wpisanie obsady | Tak | Tak | Tak, tylko mecze, w których był w obsadzie |
| Tworzenie i opisywanie klipów | Tak, każdy mecz | Tak, każdy mecz | Tylko mecze, w których był w obsadzie |
| Ocena klipu | Nie (chyba że ma też rolę szkoleniowca) | Tak, każdy własną | Nie |
| Komentowanie meczów i klipów | Tak | Tak | Tak |
| Edycja i usuwanie | Wszystko | Własne mecze, klipy, oceny, komentarze | Własne mecze, klipy, komentarze |

**Widoczność w MVP:** każdy zalogowany użytkownik widzi wszystkie mecze i klipy. Ograniczenia widoczności (zakresy, „scopes”) są poza MVP.

### Obsada sędziowska

- Funkcje: **CC** (pierwszy sędzia), **U1** (drugi), **U2** (trzeci, opcjonalny).
- Każdą pozycję w obsadzie wypełnia się **wyborem użytkownika** z listy albo **wpisaniem imienia i nazwiska** (sędzia bez konta). Uprawnienia „był w obsadzie” działają tylko dla pozycji powiązanych z kontem.
- Sędzia, który wgrywa mecz, musi być w jego obsadzie. Formularz wstawia go automatycznie na pierwszą wolną pozycję, a funkcję może zmienić.

### Wgrywanie meczu

- Mecz wgrywany w całości (jeden plik) albo podzielony na kwarty (osobne pliki).
- Przy wgrywaniu użytkownik określa, co zawiera plik: cały mecz, jedną kwartę (którą) lub kilka kwart (które).
- Dane meczu: data, liga, drużyny (nazwa + kolor stroju), obsada sędziowska.
- **Notatki przy wgrywaniu (opcjonalne):** pole tekstowe, jedna linia to jeden moment, np. `2:54 Filip PTS`, `3:17 U1 dlaczego nie blok?`.
  - Czas oznacza **czas nagrania** w formacie `m:ss` / `h:mm:ss`, dopuszczalne `2.54` i `2,54`.
  - Sędziego rozpoznajemy po imieniu, nazwisku lub funkcji (CC/U1/U2), bez względu na wielkość liter i polskie znaki.
  - Kategorię rozpoznajemy ze słownika i jego aliasów. Reszta linii trafia do opisu.
  - Przed zapisem użytkownik widzi tabelę podglądu z ostrzeżeniami i może ją poprawić.
  - Z notatek powstają znaczniki, a z nich klipy, gdy nagranie jest gotowe.
- **Znaczniki kwart:** jeśli plik zawiera więcej niż jedną kwartę, po wgraniu użytkownik ustawia początek każdej kwarty. Do tego czasu klipy z tego pliku mają kwartę „nieustaloną” i nie da się ich opisać. Wycinanie może już ruszyć.
  - Plik z jedną kwartą: znacznik startu jest opcjonalny, domyślnie 0:00. Można go przesunąć, np. gdy na początku nagrania jest rozgrzewka.

### Odtwarzacz i znaczniki

- Odtwarzacz wideo z przewijaniem, zwolnionym tempem (0,25×–2×), klatka po klatce i skrótami klawiszowymi.
- Przycisk / klawisz „Zaznacz” dodaje znacznik w bieżącym czasie nagrania **bez zatrzymywania odtwarzania**.
- Znaczniki są widoczne na liście obok odtwarzacza (czas, kwarta). Kliknięcie przenosi do momentu, a znacznik można usunąć.
- Opisywanie odbywa się **po obejrzeniu**: lista nieopisanych znaczników, przy każdym podgląd klipu i pola opisu.

### Klipy

- Z każdego znacznika powstaje klip 30 s: 15 s przed i 15 s po (przycięty do granic nagrania).
- Opis klipu:
  - **sędzia** z obsady meczu, którego dotyczy sytuacja (wybór z CC/U1/U2) albo „cały zespół”,
  - **kategoria** ze słownika (lista niżej) albo „własna” z krótką nazwą wpisaną ręcznie,
  - **kwarta i czas od początku kwarty w nagraniu**, wyliczone automatycznie ze znaczników kwart. W interfejsie podpisane wprost, np. „Q2 · 4:12 od początku kwarty (czas nagrania)”. **To nie jest zegar meczowy.**
  - opcjonalny opis tekstowy.
- Słownik kategorii na start (edytowalny przez administratora, z aliasami do rozpoznawania w notatkach):
  - **Faule:** osobisty, w akcji rzutowej, blok / szarża, niesportowy, techniczny, dyskwalifikujący.
  - **Naruszenia:** kroki, podwójny kozioł, 3 s, 5 s, 8 s, 24 s, aut, goaltending / interferencja.
  - **Bez gwizdka:** brak gwizdka (powinien być), gwizdek niepotrzebny.
  - **Mechanika:** pozycja / poruszanie się, rotacja, współpraca w zespole, sygnalizacja.
  - **Inne:** inne, własna.
- Lista klipów meczu pod nagraniem lub w osobnej zakładce, z filtrem po sędzi, kategorii i kwarcie.
- Widok klipu: odtwarzacz, opis, oceny szkoleniowców, komentarze użytkowników.

### Ocena szkoleniowca

- Każdy szkoleniowiec może wystawić **własną** ocenę klipu: prawidłowa / nieprawidłowa / dyskusyjna, plus komentarz.
- Ocenę może zmienić lub usunąć jej autor lub administrator. Przy klipie widać wszystkie oceny z autorem.

### Komentarze

- Każdy zalogowany użytkownik może komentować mecz i każdy klip.
- Autor może edytować i usuwać swój komentarz. Administrator może usunąć każdy.

### Retencja danych

- Oryginalny plik jest usuwany po udanej konwersji do wersji roboczej. Zostaje tylko wersja robocza.
- Wersja robocza pełnego meczu jest usuwana po **N dniach** od wgrania. N ustawia administrator, domyślnie 30. Klipy zostają na stałe.
- Przed usunięciem mecz jest oznaczony w interfejsie („pełne nagranie dostępne jeszcze X dni”). Po usunięciu nie da się dodawać nowych znaczników.
- Administrator widzi zajętość dysku i może ręcznie usunąć pełne nagranie wcześniej.

## 2. Wymagania niefunkcjonalne

- Przeglądarka na komputerze. Przeglądanie klipów i komentowanie wygodne także na telefonie.
- Płynne przewijanie nagrań do 2 h. Wgrywanie dużych plików odporne na przerwanie (wznowienie od miejsca przerwania).
- RODO: nagrania zawierają wizerunek zawodników, w tym niepełnoletnich. Dostęp tylko dla zalogowanych użytkowników, dane przechowywane w UE.
- Logowanie kontem, role i uprawnienia sprawdzane po stronie serwera.
- Konta zakłada administrator (brak publicznej rejestracji).
- **Infrastruktura startowa:** VPS 2 vCPU, 4 GB RAM, 40 GB dysku, w UE. Rozwiązanie musi się w nim zmieścić, łącznie z kolejką konwersji (jedno zadanie naraz) i retencją. Musi też dać się później przenieść pliki do magazynu obiektowego (S3) bez przebudowy.

## 3. Poza zakresem MVP (wizja na później)

- **Wersja 2:**
  - ręczna korekta granic klipu, rysowanie na stopklatce,
  - biblioteka klipów z wyszukiwaniem (kategoria, sędzia, liga, ocena, data), zestawy szkoleniowe,
  - kilka ujęć tego samego meczu,
  - udostępnianie linkiem z datą ważności, eksport klipów,
  - zakresy widoczności („scopes”) dla ról i meczów.
- **Wersja 3:** statystyki sędziów, raporty PDF, aplikacja mobilna, integracja z systemem obsady meczów.

## 4. Do ustalenia w planie technicznym

Zaproponuj i uzasadnij przed pisaniem kodu:
- Stos technologiczny (frontend, backend, baza danych), z uwzględnieniem prototypu `ref-clips`
- Przechowywanie plików wideo przy 40 GB dysku i retencji z sekcji 1, wgrywanie odporne na przerwanie
- Wycinanie klipów: przy usuwaniu pełnych nagrań klipy muszą istnieć jako osobne pliki. Uzasadnij sposób cięcia i jakość.
- Logowanie i zarządzanie kontami (zakładane przez administratora)
- Wdrożenie na wskazanym VPS: kopie zapasowe bazy, HTTPS, aktualizacje

## 5. Kryteria akceptacji MVP

- Plik 4 GB wgrywa się do końca mimo zerwania połączenia w połowie.
- Po wgraniu pliku z dwiema kwartami i ustawieniu znaczników każdy klip ma poprawną kwartę i czas od początku kwarty.
- Notatki wklejone przy wgrywaniu tworzą klipy w podanych momentach, a nierozpoznane linie są pokazane z ostrzeżeniem.
- Klip ma 30 s (krócej tylko przy granicy nagrania) i odtwarza się w Chrome na komputerze i w Safari/Chrome na telefonie.
- Sędzia spoza obsady nie może tworzyć klipów z meczu. Serwer odrzuca takie żądanie także wysłane z pominięciem interfejsu.
- Po upływie retencji pełne nagranie znika z dysku, a jego klipy dalej się odtwarzają.
