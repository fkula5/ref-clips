# Match scoresheet ("Protokół")

Scanned or photographed scoresheets attached to a match. Migration `mvp0010` only adds the table `match_scoresheets`.

## Rules

- A match has up to 10 files (`SCORESHEET_MAX_FILES`), each up to 20 MB (`SCORESHEET_MAX_BYTES`), both in `app/config.py`.
- Allowed: PDF, JPEG, PNG, WebP, HEIC/HEIF (iPhone). Anything else, SVG included, is refused with a Polish message.
- Upload and delete: referees in the match crew (accounts only, as for recordings), every coach, admin. Everybody logged in views and downloads. Deleting asks for confirmation.
- Shown only on the match page („Protokół”), plus a document icon with the label „Protokół” in the match list. Never in public share links (`/s/...`) or training sets.
- Deleting a match deletes its files from disk and its rows (`ON DELETE CASCADE`).

## How it works

- The upload form is a plain multipart `POST /matches/{id}/scoresheets` with `accept` for the allowed types and no `capture`, so an iPhone offers camera, library and files. The small script `static/scoresheet.js` only gives early feedback; the server validates again.
- The type is detected from the first bytes (`app/scoresheets.py`), not from the extension or the browser's Content-Type. All or nothing: one rejected file rejects the batch.
- Free space uses the same check as recordings (`uploads.check_space`, so a rejection also shows in the admin panel).
- Files are stored as `scoresheets/<random 32 hex>.<ext>` under `DATA_DIR`. The user's file name is sanitized (no directories or control characters, at most 150 characters, extension matched to the real type) and kept only for display and for the download name.
- `GET .../scoresheets/{id}/file` is `inline`, `.../download` is `attachment`. Both send the stored `Content-Type`, `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-cache`.
- HEIC is shown as a file tile with a download link: only Safari displays it, and there is no server-side conversion. Photos are served at full size (no thumbnails are generated), so the page loads them lazily.
- The worker's hourly cleanup removes files in `scoresheets/` that have no row (older than an hour), e.g. after a crash between writing and saving.
- `deploy/Caddyfile` gives this one route a 220 MB request body limit (the rest of the site stays at 10 MB). Keep it above `SCORESHEET_MAX_FILES * SCORESHEET_MAX_BYTES` if the limits change.

- The nightly backup copies `scoresheets/` next to `clips/` (`deploy/backup_snapshot.py`; restore steps in `deploy/restore.md`).

## Known limits

- Photos keep their EXIF metadata (e.g. GPS); nothing is stripped.
- Two simultaneous uploads to one match could exceed the file limit by a few files.
