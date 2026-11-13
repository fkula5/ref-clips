# Qualifier assessment sheet

Template: the two-sided „Arkusz oceny sędziów” (referee assessment sheet) of the Podkarpacki Związek Koszykówki (Podkarpackie Basketball Association). The assessment is descriptive, without points or a grade. Implemented on branch `feat/qualifier-sheet` (migration `mvp0006`).

## Content
- **Header.** Taken from the match data: match, date, category (league), crew. Stored in the sheet: the result (short text, up to 50 characters, e.g. „78:65”) and the difficulty level (easy / normal / hard). The qualifier is filled in automatically from the logged-in account.
- **Assessment items.** For each referee in the crew (CC, U1, U2) a separate comment per item. Items from the migration, in order: Obowiązki przedmeczowe, Przygotowanie fizyczne, Mechanika, Sygnalizacja, Ocena kontaktów, Ocena błędów, Współpraca, Kontrola gry, Przywództwo, Jakość pracy. The list is editable by a coach or admin in the admin panel (the „Arkusz oceny” tab): adding, renaming, ordering, deactivating, and deleting only unused items.
- **Overall assessment.** For each referee a description and a crew recommendation (e.g. „Może sędziować każde zawody jako sędzia główny” — "Can referee any game as chief referee"), plus one shared note about the pair.
- The sheet **does not contain a list of moments** or points. Moments follow the existing route (markers, notes, clips); the sheet and the clips are linked by the match page (the „Arkusz oceny” card).

## Access rules (`app/permissions.py`, table in `tests/test_permissions.py`)
| Operation | Who |
|---|---|
| creating | only the coach role (the admin alone is not enough, as with rating a clip); one sheet per pair (match, coach) enforced by the database, reopening edits the existing one |
| editing and publishing | only the author, also after publication |
| deleting | the author, as long as it is a draft; the admin always; with confirmation |
| viewing a draft | only the author |
| viewing a published sheet | the author, referees from the crew who have accounts, coaches, administrators |

Anyone who may not see the sheet gets **404** (not 403) on every sheet route, identical to a non-existent number; on the match page the „Arkusz oceny” card is not shown at all. This applies to a logged-in referee outside the crew who can see the match and its clips. Access for a referee in the crew is checked against the current crew of the match (a referee removed from the crew loses access).

## Flow
- Draft → published; there is no undoing publication. The same form has „Zapisz szkic” („Save draft”) and „Opublikuj” („Publish”). Publishing requires a difficulty level; empty fields are allowed, and the confirmation (browser dialog) states how many there are; after publication the message repeats the number of empty fields.
- The author may correct a published sheet (the „Zapisz zmiany” („Save changes”) button; the difficulty level must remain). When the edit happened after publication, „zmieniono <data>” („changed <date>”) is shown; re-saving identical content is not a change.
- Limits: each text field 5000 characters (`config.TEXT_MAX_CHARS`), result 50 (`config.SHEET_RESULT_MAX_CHARS`). A validation error shows the form (422) with everything that was entered and a list of errors; success is a 303 to the page with a one-time message (cookie `refclips_notice`, `app/flash.py`). A field that was not in the submitted form stays unchanged, so an outdated form does not wipe text.
- Script `static/sheet.js`: a `beforeunload` warning for unsaved changes (no false alarm on saving; after a validation error the form starts as „unsaved”) and a confirmation of publication with the number of empty fields.

## Copies (snapshots)
When a sheet is created, the names of the items (rows) and the function and surname of each referee (columns) are saved. Renaming, deactivating and deleting an item, and changing the match crew, do not change existing sheets; a new sheet takes the current dictionary and crew. The header (teams, date, league) is read from the match live. `SheetRow.element_id` is used only to check whether an item is in use.

**Refreshing the crew of a draft.** When the match crew differs from the columns of the draft, the form shows the differences and a „Odśwież obsadę” („Refresh crew”) button: it saves the typed text, adds empty columns for new referees, updates the function of a person who changed it, and removes a column of a referee who is no longer in the crew only if it is empty; columns with text stay (with a message). People are recognised by surname. For a published sheet the crew is frozen.

## Printing and PDF
The „Drukuj / zapisz jako PDF” („Print / save as PDF”) button calls `window.print()`. The sheet prints from the `@media print` stylesheet (A4 via a named page `sheet`, without navigation, buttons, messages and footer; rows are not split between pages). No new dependencies and no server-side PDF; no association logos.

## Data
Tables: `sheet_elements`, `sheets`, `sheet_columns` (referee, overall assessment and recommendation), `sheet_rows` (item), `sheet_cells` (comment). Deleting a match deletes its sheets (ON DELETE CASCADE); the author key has no cascade, as with ratings. The migration adds ten items; `app/seed.py` does not re-seed them, so deleting all of them does not come back after a restart.
