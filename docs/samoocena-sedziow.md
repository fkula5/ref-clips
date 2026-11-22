# Referee self-assessment sheet

A digital copy of the Excel sheet „Arkusz samooceny RC 2026/27”. Each referee of a match crew describes their own work: clips picked from the match and three open questions. A referee can also fill in a sheet for a match that is **not in the system** (a standalone sheet). Migrations `mvp0012` and `mvp0013`.

## Content
- **Header**, read-only, from the match (a standalone sheet has a typed header, see [Standalone sheets](#standalone-sheets)): Liga (`level`), Data meczu, Gospodarze / Goście (the team names), Sędzia główny (CC) and Sędzia pomocniczy (U1, and U2 when there is one, comma-separated).
- **Clips**, at least 3, no upper limit. The author picks them from the match's clips; one clip cannot be added twice and a clip of another match is refused. The time („Czas z nagrania”: recording, time in it and the quarter, e.g. „Całość, 8:30 (Q2 · 3:15)”) and the name („Nazwa klipu”: the category, the custom one when it has a name) fill in from the clip. The „Opis” is copied from the clip's own description **once, when the clip is added** and can then be edited freely; the edit stays in the sheet and never changes the clip. A clip with no description gives an empty field. „Wstaw opis z klipu” copies the clip's current description into the field again without saving. Each row links to the clip, so it can be played (any logged-in user may open a clip). A **manual row** („Dodaj wiersz ręcznie”, next to the picker) is for a clip that was not cut in the app: the author types the time, the name and the description; it has no playback.
- **Three questions**, with the Excel's wording: „Co uważam o swoim sędziowaniu? (ogólne opinię o swoim sędziowaniu)”, „Co było dobre w tym meczu i co chciałbym zachować na kolejne mecze?”, „Co było złe w tym meczu i co chciałbym zmienić w kolejnych meczach?”.

## Flow
1. On the match page, the **Samoocena** card offers a referee of the crew „Wypełnij samoocenę” (later „Kontynuuj szkic” / „Zobacz wysłaną”). One sheet per referee and match, enforced by the database.
2. **Zapisz szkic** can be pressed any number of times; a draft may be incomplete. Rows can be added, removed and moved up and down (each action stores the typed text first). Rows keep text snapshots of the time and name, refreshed on each save of a draft, so a sheet stays readable if a clip is deleted later (`clip_id` becomes NULL; such a row still counts). A manual row is never refreshed: its time and name are the author's own text (`is_manual`, the only thing that tells it from a deleted clip's row, since both have `clip_id` NULL).
3. **Wyślij** (with a confirmation) needs at least 3 rows (clip rows and manual rows count together), a description in every row (a manual row also needs a time and a name) and all three answers; otherwise the draft is saved and the problems are listed in Polish. A submitted sheet is read-only for the author. A standalone sheet is also checked for its header, see below.
4. An admin can use **Przywróć do edycji** to return a submitted sheet to draft; `submitted_at` is kept. Submitting again notifies again. The author can delete their own draft.

## Standalone sheets
For a match that is not in the system, a referee uses **„Nowa samoocena — mecz spoza systemu”** at the top of `/self-assessments`. It creates a draft with `match_id` NULL; it stays standalone forever (no linking to a match later), and a user can have any number of them.
- **Header**, typed by the author in the form: Liga, Data meczu (date input), Gospodarze, Goście, Sędzia główny and Sędzia pomocniczy (one optional field; two names are separated by a comma, as in a match sheet). Stored in `league`, `match_date`, `home_team`, `away_team`, `main_referee`, `assistant_referees`, which are empty for a sheet tied to a match. Each text is a single line of at most 200 characters.
- **Rows** are all manual (no picker, no playback): free text „Czas z nagrania”, „Nazwa klipu” and „Opis”, at least 3, added, removed and moved like the other rows.
- **Submitting** needs Liga, Data meczu, Gospodarze, Goście and Sędzia główny (the assistants are optional) on top of the usual rules. A draft may be incomplete.
- Visibility, the lock, „Przywróć do edycji”, deleting a draft, notifications, the report and the PDF work as for a match sheet. A standalone sheet is on no match page and does not stop a match from being deleted. The list page shows the typed teams and the date with a „spoza systemu” mark.

## Access rules (`app/permissions.py`, table in `tests/test_permissions.py`)
| Operation | Who |
|---|---|
| starting a sheet (`can_fill_self_assessment`) | a referee who is in the match's crew by account; coaches and admins only if they are also crew referees |
| starting a standalone sheet (`can_create_standalone_self_assessment`) | any referee (no crew needed); coaches and admins only if they are also referees |
| editing, submitting, deleting (`can_edit_…`, `can_delete_…`) | the author, only while it is a draft |
| viewing a draft | the author only (not other crew members, not coaches, not admins) |
| viewing a submitted sheet (`can_view_self_assessment`) | the author, every coach and every admin; not other referees, crew members included |
| returning to draft (`can_reopen_…`) | admin only, only a submitted sheet |

Whoever may not see a sheet gets **404** (not 403) on every sheet route, so nobody learns that a colleague started one; 403 only for someone who may see it but not do what they asked (a coach editing a submitted sheet). Coaches see all submitted sheets, not only those of their own groups, because groups only organise views (`TrainingGroup`); only the notifications follow the groups. A match with a submitted self-assessment can be deleted only by an admin, as with a published qualifier sheet.

## Pages
- `/self-assessments`: coaches and admins get the submitted sheets, newest first; every referee gets „Moje samooceny” (own sheets, drafts included). The menu link is „Samooceny” / „Moje samooceny”.
- `/self-assessments/<id>`: the read-only report; for the author's draft it is a preview with a „SZKIC” marker.
- `/self-assessments/<id>/edit`: the form (app-styled).
- `/self-assessments/<id>/pdf`: „Pobierz PDF”, the same permission as viewing.

## The report and the PDF
The report copies the Excel layout: A4 portrait, margins 0.25 in left/right and 0.75 in top/bottom, columns B–K at the Excel widths (in pixels), thick black borders, red `#C90012` labels with white text, cream `#F9F3EA` value cells, a `#F0E5DB` background around the sheet on screen and plain white in print. A clip is one block at least as tall as the Excel's 5 rows and an answer block at least as tall as its 8 rows; they grow with the text and are not split across pages. Descriptions are centred as in the Excel; the answers are left-aligned and top-aligned, because long centred text reads badly. Font: Calibri, with Carlito (metric-compatible) as the free substitute.

The PDF is rendered on the server by WeasyPrint from the same template and stylesheet (`app/self_assessment_pdf.py`, `app/static/self_assessment_report.css`), named `samoocena_<date>_<teams>_<crew function>.pdf`, e.g. `samoocena_2026-10-28_Legia-Wisla_CC.pdf`; a standalone sheet has no crew slot, so no function: `samoocena_2026-11-07_Slask-Zaglebie.pdf` (parts that are empty on a draft are left out). The image installs pango, harfbuzz-subset and `fonts-crosextra-carlito` (see the `Dockerfile`). „Drukuj” on the page uses the browser's print with the same stylesheet.

## Notifications
On submit the **coaches of the groups the author belongs to as a referee** get a bell notification (kind `self_assessment`, „<author>: wysłana samoocena w meczu …”) and, per the `self_assessment_submitted` switch („Wysłane samooceny sędziów z moich grup”, default on for coaches, shown to coaches and admins), a line in the daily e-mail digest ([email-digest.md](email-digest.md)). A standalone sheet notifies the same coaches (the notification has no `match_id`; the bell shows the typed teams, the digest lists it under „Mecze spoza systemu”). An author in no group notifies nobody; the sheet is still on the list page. Opening the sheet marks its notification read.

## Data
`self_assessments` (match, user, three answers, `status` draft/submitted, `created_at`, `updated_at`, `submitted_at`; unique `(match_id, user_id)`; deleted with the match) and `self_assessment_clips` (sheet, `clip_id` ON DELETE SET NULL, `position`, `description`, `time_label`, `name_label`; unique `(self_assessment_id, clip_id)`). Migration `mvp0013` makes `self_assessments.match_id` nullable (NULLs are distinct in a unique constraint on SQLite and Postgres, so several standalone sheets per user are fine; no CHECK is needed because „standalone” is simply `match_id IS NULL`), adds the typed header columns and `self_assessment_clips.is_manual` (default false). Its downgrade deletes the standalone sheets, their rows and notifications, since they have no match to return to. `notifications` gets `self_assessment_id` (CASCADE) and the new kind; `email_preferences` gets the switch. The app has no user export or user deletion, so nothing there changes; the retention job only purges recordings, and the sheet's text snapshots outlive them.
