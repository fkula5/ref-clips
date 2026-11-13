# ref-clips

A web application for cutting out and analysing referee decisions from basketball games, for referees
and coaches of one district. You upload a recording, mark moments or paste notes such as
`2:54 Filip kroki`, and the app cuts a clip from each entry (15 s before and 15 s after) and organises
the clips with descriptions, comments and coach ratings.

Project documentation: [MVP specification](docs/specyfikacja-mvp.md),
[technical plan](docs/plan-techniczny.md), [deployment to the server](docs/wdrozenie.md),
[releases and automatic deployment (GitHub Actions)](docs/ci-cd.md). Status of the work: segment 1 („Fundament” — "Foundation") — accounts,
login, roles, crew CC/U1/U2, new data model; segment 2 („Mecze i obsada” — "Matches and crew") — match list
with filters and status, match page, errors in forms; segment 3 („Wgrywanie i konwersja” — "Upload and conversion") —
resumable upload (tus), declaration of the file contents, deleting the original after conversion;
segment 2a („Docker lokalnie” — "Docker locally") — image and Compose for testing on other computers;
segment 4 („Znaczniki” — "Markers") — the „Zaznacz” key, quarter starts from the file declaration, notes on upload;
segment 4a („Testy interfejsu” — "UI tests") — automated browser tests (Playwright, Chromium);
segment 5 („Klipy” — "Clips") — the marker description screen, the „Klipy” tab of a match with filters, the clip view;
segment 6 („Oceny i komentarze” — "Ratings and comments") — coach ratings, match and clip comments, mobile views;
segment 7 („Admin i retencja” — "Admin and retention") — category, retention and disk panel, the `retention` job in the worker.
The next segment (deployment to a VPS) is described in the plan.

## Requirements and installation

- Python 3.12 (with the `venv` module), ffmpeg + ffprobe.

```bash
sudo apt install ffmpeg            # konwersja i wycinanie wideo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

For tests: `.venv/bin/pip install -r requirements-dev.txt`.

Without ffmpeg the application starts, but the interface shows the message
„Brak ffmpeg — uruchom: sudo apt install ffmpeg”, and jobs wait in the queue
(the worker picks them up by itself after installation). Paths can be given with the environment variables
`FFMPEG_PATH` and `FFPROBE_PATH` (default: taken from `PATH`).

### First administrator

There is no public registration — you create the first account with a command (it asks for e-mail, first and last name
and password; the password has at least 10 characters):

```bash
.venv/bin/python -m app.create_admin
# albo bez pytań:
.venv/bin/python -m app.create_admin --email szef@example.com --name "Jan Kowalski" --password '...'
```

The command creates the database if it does not exist. Run for an existing e-mail, it grants the administrator
role and sets a new password — this is also the way to regain access to the admin account.

> **Old prototype data.** The data model and migration have been replaced with new ones (the prototype had
> no production data). If you have a `data/` directory from the previous version, delete it
> (`rm -rf data`) before the first start — otherwise the migration will report an unknown revision.

## Running

```bash
./run.sh
```

The script creates/migrates the database, starts the worker (`python -m app.worker`) in the background and the server
(`uvicorn`) on port 8000. Open it in a browser (also on Windows with WSL2):
**http://localhost:8000** and log in with the administrator account. Ctrl+C stops both processes.

Manually, in two terminals:

```bash
.venv/bin/python -m app.initdb
.venv/bin/python -m uvicorn app.main:app --port 8000
.venv/bin/python -m app.worker
```

Environment variables:

| Variable | Meaning |
|---|---|
| `PORT`, `HOST` | server address in `run.sh` |
| `REFCLIPS_DATA_DIR` | data directory (default `./data`): SQLite database, uploaded files, proxies, clips |
| `DATABASE_URL` | database address (default: SQLite in the data directory) |
| `REFCLIPS_COOKIE_SECURE` | `1` sets cookies with the `Secure` flag — enable over HTTPS; leave off locally over `http://` |
| `REFCLIPS_PUBLIC_URL` | application address in invitation links and share links (e.g. `https://refclips.pl`); default: from the request |
| `REFCLIPS_TRUST_PROXY` | `1` takes the client address (login attempt limit) from `X-Forwarded-For` — only behind a trusted proxy |
| `REFCLIPS_UPLOAD_MAX_GB` | max size of one uploaded file (default 8) |
| `REFCLIPS_DRAFT_RESERVE_GB` | space reserved for a proxy when an upload is accepted (default 1.5) |
| `REFCLIPS_DISK_SAFETY_GB` | free-space margin that an upload may not take (default 3) |
| `REFCLIPS_TIMEZONE` | time zone in which the application shows dates and times (default `Europe/Warsaw`; the database always stores UTC) |
| `REFCLIPS_FFMPEG_NICE` | priority (`nice`) of ffmpeg in the worker (default 10, `0` = no change) |
| `REFCLIPS_FFMPEG_STALL_SECONDS` | after how many seconds without progress a stalled ffmpeg is killed and the job ends with an error (default 900, `0` = no watchdog) |
| `REFCLIPS_TEST_UPLOAD_CHUNK_KB` | **UI tests only:** size of a tus chunk in KB (default 50 MB); do not set in production |
| `REFCLIPS_V2_FEATURES` | `1` enables the hidden version 2 features (clip boundary correction, ZIP export) |

## Running in Docker (local tests)

This is for someone who only wants to try the application on their own computer: you do not need to
install Python or ffmpeg — everything is in the image.

**Requirements**

- Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 enabled
  (the installer offers this by itself); macOS: Docker Desktop; Linux: Docker Engine with the Compose plugin
  (`docker compose version` must work). You need Docker Compose **version 2.24 or newer** (Docker Desktop from 2024 or
  later) — check with `docker compose version`; an older Compose will report an error about an unknown `required` field in `compose.yaml`.
- Git and access to the private repository: accept the invitation on GitHub (an e-mail from the owner),
  then log in to GitHub in Git (on Windows a login window will open).
- About 2 GB of free space for the image, plus space for the recordings.

**First start** (in a terminal; on Windows PowerShell):

```bash
git clone https://github.com/fkula5/ref-clips.git
cd ref-clips
docker compose up -d --build
```

The first build takes a few minutes (it downloads the Python image and ffmpeg). When it finishes,
`docker compose ps` shows the `app` service as `healthy`. Then create the administrator account
(it asks for e-mail, first and last name and password, at least 10 characters):

```bash
docker compose run --rm app python -m app.create_admin
```

(or without questions: `docker compose run --rm -T app python -m app.create_admin --email szef@example.com --name "Jan Kowalski" --password '...'`).
Open **http://localhost:8000** and log in.

**Access from this computer only.** The application listens only on `127.0.0.1`, so it is not
visible to other devices on the network (Wi-Fi, dormitory, work). To reach it from a phone on your home network,
you must change this deliberately: set `REFCLIPS_BIND=0.0.0.0` in `.env`, run `docker compose up -d`
and open `http://<computer's address on the network>:8000` on the phone. Note: this is plain HTTP, without
encryption, and the application holds recordings showing players (including minors) —
enable this only on a trusted network and go back to `127.0.0.1` after the test.

**Inviting other people.** In the application: *Użytkownicy* → add an account → copy the
invitation link. Note: the link starts with `http://localhost:8000`, so it only works on this
computer (the other person would have to run their own copy). Real sharing is done with
deployment on a server with HTTPS (a separate stage).

**Day to day**

| What | Command |
|---|---|
| View logs (Ctrl+C ends the view) | `docker compose logs -f` (separately: `logs -f worker`) |
| Stop (data is kept) | `docker compose stop` |
| Start again | `docker compose up -d` |
| Restart the application and the worker | `docker compose restart app worker` |
| Update to a new version | `git pull`, then `docker compose up -d --build` (the database migrates by itself) |
| Stop and remove the containers (data is kept) | `docker compose down` |
| **Delete all data** (database, recordings, clips) | `docker compose down -v` — **irreversible** |

You change settings (port, upload limits, etc.) in the `.env` file: `cp .env.example .env`
(on Windows `copy .env.example .env`), edit, then `docker compose up -d`. Without `.env` the
default values apply. `.env.example` describes all options.

**Where the data is.** In the named Docker volume `ref-clips_dane` (in the containers the directory
`/data`: SQLite database, uploaded recordings, proxies, clips). It survives a computer restart,
`docker compose down` and an update; it disappears after `down -v`. Database backup: `docker compose cp app:/data/ref-clips.db .`.

**Common problems**

- *„port is already allocated” / port 8000 in use* — set a different port in `.env` (`REFCLIPS_PORT=8001`)
  and open `http://localhost:8001`.
- *„Cannot connect to the Docker daemon” / no connection to Docker* — start Docker Desktop
  and wait until it shows „Running”.
- *No space for large recordings* — Docker Desktop keeps data on a virtual disk of limited size
  (Settings → Resources); the application refuses an upload when there is not enough space
  (message „Brak miejsca na serwerze”). Increase the disk limit in Docker Desktop or
  remove unneeded images (`docker system prune`).
- *Conversion takes a long time* — the worker deliberately runs at low priority, and Docker Desktop by default
  gets some of the computer's processors (Settings → Resources). A one-hour match may take
  a dozen minutes or more to convert; the status is shown on the match page.
- *I cannot log in at http://localhost* — `.env` must contain `REFCLIPS_COOKIE_SECURE=0`.
- Data on a plain directory instead of a volume (`./dane:/data`) requires the directory to belong to the
  user with UID 1000 (the container does not run as root); the simplest is to keep the volume.

Smoke test of the whole set (build, start, creating the admin, uploading a video, conversion):
`scripts/docker-smoke.sh` — runs on a separate Compose project and port 8123, and cleans up after itself at the end.

## Deployment to the server (production)

The production configuration (Caddy with HTTPS, backups, deployment script run from the local computer) is
described in [docs/wdrozenie.md](docs/wdrozenie.md): `compose.prod.yaml` (overlay on `compose.yaml`),
`deploy/Caddyfile`, `deploy/env.prod.example`, `deploy/deploy.sh`, `deploy/backup.sh`. Restoring
from a backup: [deploy/restore.md](deploy/restore.md).

Releases and deployment are automated (GitHub Actions): tests on every PR, a PR „wydanie vX.Y.Z” ("release vX.Y.Z") created by
release-please, the Docker image in GHCR and deployment after it is merged, with automatic rollback when the start fails.
How it works, one-time steps and rolling back to an older version: [docs/ci-cd.md](docs/ci-cd.md). The version number is shown
in the footer of the site after logging in.

## Accounts, roles and inviting users

1. The administrator goes to **Użytkownicy** („Users”, in the menu at the top) and adds an account: first and last name, e-mail
   (this is the login) and roles. The application shows an **invitation link** to copy — send it to the
   person yourself (Messenger, SMS). The application does not send e-mails.
2. The person opens the link, sets a password and logs in. The link is valid for 7 days and works only once;
   after the page is closed it cannot be read again, a new one must be generated.
3. Forgotten password: the administrator clicks **Link resetu hasła** („Password reset link”) next to the account and sends the new link.
   A reset logs the account out of all devices.
4. Roles can be changed at any time; an account can be deactivated (the user is logged out
   and cannot log in, but their entries remain). There must always be at least one active administrator.

Roles (several at once, permissions add up):

| Permission | Administrator | Coach | Referee |
|---|---|---|---|
| Managing accounts and roles, retention and disk | yes | no | no |
| Managing the category dictionary and the assessment sheet elements | yes | yes | no |
| Viewing all matches and clips, commenting | yes | yes | yes |
| Uploading matches and crew, creating and describing clips | every match | every match | only matches in which they are in the crew (by account) |
| Rating a clip | no (unless they also have the coach role) | yes, own | no |
| Editing and deleting | everything | own | own |

The rules are in one place, `app/permissions.py` (pure functions), and every write route checks
them on the server side (`auth.require(...)`); the interface only hides unavailable buttons.

Security: passwords hashed with argon2; session in an `HttpOnly`, `SameSite=Lax` cookie
(`Secure` via `REFCLIPS_COOKIE_SECURE`), valid for 30 days with renewal, only the token hash in the database;
limit of 5 failed login attempts per 15 minutes, separately per account and per IP address; a CSRF token
in every form and in the `X-CSRF-Token` header of HTMX/fetch requests. Every page except login
and setting a password requires logging in (pages redirect to `/login`, the API returns 401).

## Administrator panel (segment 7)

The **Administracja** („Administration”) menu is shown to everyone who may open at least one of its tabs and leads to the first
one they may open. The server checks the role on every route: **Użytkownicy** and **Retencja i dysk** are for administrators only,
**Kategorie** and **Arkusz oceny** are also open to coaches; other roles get 403, logged-out users get 401/a redirect to login,
and writes require a CSRF token. A user sees only the tabs they may open (the out-of-space banner is shown to administrators only).

**Użytkownicy** („Users”) — accounts, roles, invitation links (described above).

**Kategorie** („Categories”, `/admin/categories`) — the dictionary in the groups Faule („Fouls”) / Naruszenia („Violations”) / Bez gwizdka („No whistle”) / Mechanika („Mechanics”) / Inne („Other”):
- adding, renaming, groups and aliases (comma-separated), order (↑/↓ within a group), activation and deactivation;
- names and aliases are compared regardless of letter case and Polish diacritics, as in the note parser. A name must be
  unique, and an alias cannot repeat the name or an alias of another category (including an inactive one) or the CC/U1/U2 functions —
  the parser could not then decide which category to choose, so the save is rejected with a clear error;
- **a category used in clips can only be deactivated** (not deleted). An inactive one disappears from the choice in describe forms,
  from the note preview and from recognition in the parser, but clips that have it still show it (with the note
  „nieaktywna” — "inactive" — in the form), and saving a description without changes keeps the category; clip filters still know it. An unused
  category can be deleted;
- the „własna” („custom”) category (a name typed in for the clip) cannot be deactivated or deleted.

**Retencja i dysk** („Retention and disk”, `/admin/retention`):
- *Retention of full recordings:* number of days (1–365, default 30) after which the proxy of the full recording is deleted.
  A change applies to **new** recordings; the deadline of existing ones stays, unless you tick „przelicz termin dla istniejących
  nagrań” („recalculate the deadline for existing recordings”) — then it becomes the upload date + N days (a warning before saving; recordings older than N days will disappear at the
  next worker cleanup, clips stay). Next to it you see the time and result of the last run of the retention job.
- *Disk usage:* full recordings (proxies), originals awaiting conversion and unfinished uploads, clips, free space,
  space reserved for ongoing uploads and conversions, and the largest file a new upload can now take.
  The sizes come from the database (`videos.proxy_bytes`, `videos.size_bytes`, `upload_sessions.offset_bytes`); only the clips
  directory is read from disk (one pass over the directory), so the page does not query each file. The proxy size of
  older recordings is filled in the first time the page is opened.
- *Recording list* (match, recording, upload date, deletion deadline, size, number of clips), from the nearest deadline.
  **Delete the full recording now** (with confirmation) removes the proxy (and the original, if it was left after a conversion error)
  and sets `purged_at`; the clips stay. There is no button (and the server responds with 409) when the recording is being uploaded or
  converted, or when clips from it are waiting to be cut (status „nowy” — "new" / „w kolejce do cięcia” — "queued for cutting") — deleting it
  would leave them in the queue forever; you have to wait until the worker cuts them.
- *Out-of-space warning:* an upload rejected with code 507 is recorded (time, user, file, size, free space, in the
  `upload_rejections` table; entries older than 30 days are deleted). Rejections from the last 7 days are shown by a banner on
  all panel tabs and by a table on the „Retencja i dysk” tab.

### Retention of full recordings

- A full recording gets a deadline (`videos.expires_at`) = upload + `retention_days` (default 30). **7 days before the
  deadline** the match list, the match page, the recordings panel and the player show „pełne nagranie dostępne jeszcze X dni”
  („full recording available for X more days”) (after the deadline, and before cleanup: „zostanie usunięte w najbliższym sprzątaniu” — "it will be deleted at the next cleanup"). Earlier, the match page shows
  only the date in the recordings panel.
- **After deletion** the recording has no player, and every write route that needs the proxy (the `Z` marker, undo, the `M` marker with a note, notes, quarter starts, re-cutting, boundary correction in version 2) returns 409
  with the message „Pełne nagranie zostało usunięte…” („The full recording has been deleted…”) instead of a server error. Quarter markers and the content declaration are
  frozen („Edytuj” — "Edit" next to the recording only changes the label now), so clip quarters stay as they were. Clips
  cut earlier play normally.
- **A clip with an undetermined quarter** (no quarter markers) can **now be described** after the full recording is deleted: quarters
  cannot be set, so the description block no longer applies, and the clip still shows „kwarta nieustalona” — "quarter undetermined" (the quarter is
  calculated from the `period_marks` markers; their absence means exactly that).

### What the worker does besides conversion and cutting

Once an hour (and right after start) `python -m app.worker` performs cleanup; each step is independent (an error in one
does not stop the others):
1. inactive uploads (> 24 h) and orphaned `.part` files;
2. entries about rejected uploads older than 30 days;
3. **the `retention` job** — once a day deletes the proxies of recordings past their deadline (`expires_at` in the past),
   sets `purged_at` and logs the result; it skips recordings being converted and those with clips waiting to be cut
   (they will be handled in the next run). The time of the last run is saved with an atomic `UPDATE` in the `settings` table
   (`retention_last_run`), so neither a worker restart within the same day nor two workers running at once runs the job a second time,
   and after a longer break it catches up at start;
4. orphaned clip files: `.mp4` files in `clips/` that no `clip_path` of any clip points to (e.g. after
   deleting a marker during cutting), older than an hour;
5. leftovers of ZIP packages in `tmp/` (after a crash or an interrupted download), older than an hour.

## Sharing clips with a link (no account)

On the clip page („Udostępnij linkiem” — "Share with a link") or on the clip list („Udostępnij zaznaczone” — "Share selected"), the administrator, the coach
and the marker's author create a link `https://…/s/<kod>` (validity 1, 7 or 30 days, default 7). A person without an account can view
the clips and download them (one clip: MP4, several: one ZIP). The link can be revoked on the clip page (by its creator or the administrator),
where the active links and the number of visits are also shown. The full address is shown only once, after creation; the database holds a hash of the code.

Publicly only the video, the league and the decision category are visible — no names, teams, dates, descriptions, ratings or comments
(file name: `III-liga_blok-szarza.mp4`). Text typed manually as a „własna” category is also public. The `/s/*` pages have `noindex`, `no-referrer` and `no-store`, and the code does not get into the logs (`/s/[ukryty]` — "/s/[hidden]"). Clips cut before this feature was introduced may carry metadata of the source file (title, GPS): after deployment run
`python -m app.strip_metadata` once (see `docs/wdrozenie.md`). Limits: `SHARE_MAX_CLIPS` (30 clips per link),
`SHARE_ZIP_MAX_PARALLEL` (2 parallel ZIP packages) in `app/config.py`.

## Workflow

1. **New match** — date, league, teams (name + kit colour) and the crew **CC / U1 / U2**
   (U2 optional). You fill in each position by choosing an account with the referee role or typing a first and last name
   (a referee without an account). The referee who creates the match is placed in the first
   position (they may change their function), and the server rejects a match in whose crew they are not
   (this applies to a user who is neither an administrator nor a coach). The same person cannot
   take two positions (the same account or the same typed name; a typed name matching
   an account's name is the same person). The „Liga” („League”) field suggests leagues used earlier. Errors are shown
   in the form with the values kept.
   When a referee entered by hand later gets an account, it is enough to pick the account in the crew
   (match editing): their clips stay with them, provided the account's first and last name is the same
   (after normalising letter case and Polish diacritics) and there is no second account with that name.
   **The match list** (home page) has filters in the address (dates from–to, league, referee, „tylko moje” — "only mine"),
   pagination by 25 and a match status calculated from the recordings: no recording, conversion (with its place
   in the queue), conversion error, no quarter markers, ready, full recording deleted. A file without a
   content declaration counts as a whole match (requires markers Q1–Q4); a file with one quarter
   does not require markers. On a phone the table turns into cards. **The match page** shows the
   crew (who has an account), the recordings and clips of the match; deleting a match is preceded by a
   confirmation page with the number of recordings and clips.
2. **Upload a recording** (on the match page; several files are possible, e.g. separate quarters). For each
   file, state **what it contains**: the whole match, one quarter (Q1–Q4, OT1–OT3) or several quarters.
   Uploading is **resumable** (tus 1.0.0 protocol, `tus-js-client` pinned in
   `static/vendor`): chunks of 50 MB, automatic retrying after a dropped connection, and after a
   page refresh or closing the tab it is enough to choose the same file and click „Wgraj” („Upload”) —
   the upload continues from where it stopped. „Przerwij” („Cancel”) cancels the upload and deletes the data.
   The file is streamed to disk (`uploads/`); after the last byte a recording and a conversion job are created.
   Limits: max 8 GB per file, one unfinished upload per user (another one returns a clear error with the option to cancel
   the previous one), an inactive upload older than 24 h is deleted by the worker (every hour). **Space reservation:** an upload is accepted only
   when the free disk space is ≥ the file size + 1.5 GB (proxy) + 3 GB of margin, counting the reservations of other uploads and originals waiting for conversion; otherwise error 507
   „Brak miejsca na serwerze, spróbuj później.” („No space on the server, try again later.”). The same people who create clips may upload to a match
   (administrator, coach, referee from the crew); nobody can touch someone else's upload.
   The content declaration can be corrected after the upload (**Edytuj** — "Edit" next to the recording). A file with one
   quarter automatically gets a quarter-start marker at 0:00 (it can be moved), so it does not
   need manual markers; a whole match and several quarters require quarter-start markers
   (match status „brak znaczników kwart” — "no quarter markers").
   The worker converts the file to a proxy (H.264 veryfast CRF 23, AAC, max 720p, max 30
   fps — a higher frame rate is limited, a lower one is not raised — a keyframe every second,
   `+faststart`; ffmpeg runs with `nice 10`, and clip cutting has priority over
   conversion). After conversion it checks the result (ffprobe: a video stream is present, the duration matches the
   original to max(2 s, 1% of the length); the video track is compared) and **deletes the original**. On a mismatch the recording gets an error and the original
   stays — „Ponów konwersję” („Retry conversion”) works only as long as the original exists. The full recording gets a
   validity deadline (`retention_days`, default 30). For the conversion time estimate see
   [technical plan](docs/plan-techniczny.md), chapter 6.2.
3. **Player** — you browse the recording and mark moments, describing them later. Shortcuts
   (help under the `?` key on the page):

   | Key | Action |
   |---|---|
   | `Z` (the „Zaznacz” button — "Mark") | **marker at the current time, without stopping playback** — an undescribed clip (15 s before and after), immediately in the cutting queue; a flash on the picture and a marker counter |
   | `Backspace` | undo your last undescribed marker (also deletes the clip file) |
   | `M` | marker with a note: pause and a text field (referee, category, description as in the notes) |
   | `Q` | set the start of the next missing quarter at the current time |
   | `F` | full screen (the video container — markers, the flash and the „Zaznacz” button also work in full screen) |
   | Space | start / pause |
   | ← / → | ±1 s (with Shift ±5 s) |
   | `,` / `.` | frame back / forward |
   | `[` / `]` | slower / faster speed (0.25×–2×, also the selection list) |
   | `?` | help with shortcuts |

   **Markers** are shown in the list next to the player: the time in the recording (clicking seeks),
   the quarter and the time since its start or „kwarta nieustalona” („quarter undetermined”), the cutting state, described/undescribed and
   deletion (×; an already described clip requires confirmation). Two markers by the same author in the
   same recording less than a second apart are a double click — the server ignores the second one.
   The „Zaznacz” button can be seen and used by the administrator, the coach and the referee from the match crew
   (the server enforces this also for requests bypassing the interface). A recording whose full version
   has been deleted (retention) has no player or markers — the page shows a message, and the cut clips stay.
   Note: in browsers without `requestFullscreen` on the container (e.g. Safari on an iPhone) the full screen
   of the native player does not show the flash — the `Z` key still works, but the confirmation is visible only after exiting.

   **Quarter starts.** The „Początki kwart” („Quarter starts”) panel lists the quarters from the file declaration: the whole match
   Q1–Q4 (required) and OT1–OT3 (optional), several quarters — only the declared ones, one quarter —
   only that one (its 0:00 marker is created automatically and can be moved, but not deleted). Next to each quarter there is
   „Ustaw tutaj” („Set here”) / „Ustaw ponownie tutaj” („Set again here”) (the current time of the recording) and deletion; `Q` sets the next
   missing one in the order of the declaration. The server rejects quarters outside the declaration and an order
   inconsistent with chronology (Q2 cannot start before Q1; one quarter = one marker).
   As long as a file with several quarters does not have a complete set of markers, the match page and the player show a banner
   „Ustaw początki kwart, żeby klipy miały kwartę i czas” („Set the quarter starts so the clips have a quarter and time”) with a link; the clips then have the
   „nieustaloną” („undetermined”) quarter, and cutting works. Changing the declaration in „Edytuj” next to the recording that would delete
   quarter markers first shows their list and requires confirmation.

   The quarter of each clip is calculated from the quarter-start markers in the recording time
   (the last marker not later than the clip), not from a clock reading. The clip description shows it
   directly, e.g. „Q2 · 4:12 od początku kwarty (czas nagrania)” („4:12 since the start of the quarter (recording time)”). Markers can be corrected or deleted at any time —
   the clip quarters recalculate by themselves.
4. **Notes** — when uploading or later („Wklej notatki” — "Paste notes" for a ready recording). One line is one moment:
   ```
   2:54 Filip kroki
   3:17 U1 dlaczego nie blok?
   1:02:15 CC faul techniczny
   ```
   Time: `m:ss`, `mm:ss`, `h:mm:ss` (also `2.54`, `2,54`). After the time, the first word is the referee:
   a first name, a last name or the function **CC/U1/U2** (regardless of letter case and Polish diacritics).
   The category is recognised from the category dictionary and its aliases; the rest of the line goes into the
   description. A preview table with warnings is shown (unknown referee, unrecognised time,
   several categories) — each line can be corrected — and the **Wytnij wszystkie zaznaczone** („Cut all selected”) button.

   **Notes on upload.** In the upload form each file has an optional field „Notatki do tego pliku” („Notes for this file”) and a **Podgląd** („Preview”) button (a table with the match crew and the category dictionary and warnings,
   before sending; the text can be corrected and the preview repeated). The notes are sent to the server in a separate request
   `POST /uploads/{id}/notes` right after the tus session is created (saved in `upload_sessions.notes`, not in the
   `Upload-Metadata` header; limit 20,000 characters and 300 lines) and do not depend on the order relative to
   the last byte. After the upload finishes, lines with a valid time create **undescribed clips**
   (referee and category set if the parser recognised them; the description is approved later), and cutting
   waits for the finished proxy. The length of the recording is known only after conversion, so a clip with a
   moment outside the recording gets the error state „Moment poza nagraniem” („Moment outside the recording”) instead of being silently truncated.
   Until quarter markers are set, the clips have the „nieustalona” („undetermined”) quarter.
5. **Describing markers** — after watching the recording you describe the markers in one place. Entry:
   the **Opisz znaczniki (N)** („Describe markers (N)”) button on the match page (all recordings, in the order recording → time) or
   in the player (only that recording; the counter N grows with each „Zaznacz”). The screen shows on the side a list of
   undescribed markers (time, quarter or „kwarta nieustalona”, author, cutting state), and in the main part
   the clip preview and the description fields:
   - **preview:** the clip file, once cut; while the clip waits in the queue — the proxy from the start to the end
     of the clip (playback stops at the end of the range);
   - **referee** (CC / U1 / U2 from the match crew or „cały zespół” — "whole team"), **category** (a list grouped by the dictionary
     groups; „własna” („custom”) requires a name, up to 100 characters) and **description** (optional, up to 2000 characters). The referee and category are
     required for approval;
   - **proposals from notes:** clips from notes (on upload, „Wklej notatki”, `M` in the player) already have the
     recognised referee and category — they are preselected, marked „propozycja” („proposal”), and are saved only after
     approval;
   - **Zapisz i dalej** („Save and next”) sets `described_at` and `described_by_id` (the first approval; editing does not change them) and moves on to the
     next undescribed one (after the last it returns to the first skipped one; when nothing is left — the message
     „Wszystkie znaczniki są opisane” („All markers are described”)); **Pomiń** („Skip”) moves on without saving; **Usuń znacznik** („Delete marker”) asks for confirmation
     and also deletes the clip file;
   - **undetermined quarter:** a clip from a recording that requires quarter markers (whole match, several quarters) and has no complete set — or from a moment before the start of the first quarter — **cannot be described** (the server refuses too).
     The screen shows a message with a link to the „Początki kwart” panel in the player. Exception: when the full recording
     has been deleted (retention), quarters can no longer be set, so the clip can be described with the „nieustalona” („undetermined”) quarter.

   Shortcuts on the describing screen (they do not work in text fields):

   | Key | Action |
   |---|---|
   | `1` / `2` / `3` / `0` | referee CC / U1 / U2 / whole team |
   | `K` | move to the category list (typing the start of a name selects a category) |
   | `D` | move to the description field |
   | Space / `R` | play–pause the preview / from the start of the clip |
   | `Enter` (in the form, also in the category list) | save and next |
   | `Ctrl+Enter` (in the description) | save and next |

   Administrators and coaches can describe in every match, and a referee in the matches in whose crew they are
   (`can_describe_clip`; the server refuses others with code 403 on the screen and on all write routes).
6. **Clips of the match** — on the match page a „Klipy” („Clips”) section with filters: **referee** (match crew or „cały zespół”),
   **category**, **quarter** (also „nieustalona”), **ratings** (with any rating, „ma ocenę: prawidłowa / nieprawidłowa / dyskusyjna” — "has rating: correct / incorrect / debatable", without ratings) and **described / undescribed**. The filters are in the address
   (`?person=…&category_id=…&period=Q2&rating=none&described=0`), work without JavaScript (a plain GET form), and HTMX
   only swaps the list and writes the filters to the address. A row: referee (function + last name), category,
   „kwarta · czas od początku kwarty” („quarter · time since quarter start”) (recording time, not the match clock), time in the recording, description excerpt, state,
   rating summary (e.g. „2× prawidłowa”, „1× dyskusyjna”) with the number of comments and a link to the clip; on a phone
   the rows are cards.
   The global list `/clips` has the same filters (plus match).
7. **Clip** — the clip player, the description (referee, category, „Q2 · 4:12 od początku kwarty (czas nagrania)” with the note
   „czas nagrania – nie zegar meczowy” („recording time – not the match clock”), description, who added the marker and when, when it was described), MP4 download (file name
   `kategoria-rozgrywek_nazwisko_decyzja.mp4`, e.g. `III-liga_Kowalski_blok-szarza.mp4`; calculated on the fly,
   so after changing the description the downloaded file has a new name; only ASCII characters, the name of a custom category shortened to 40 characters),
   coach ratings, comments, a link to that moment in the full recording (only when the full recording has not been deleted), an edit form
   for the description (the same fields and validation as on the describing screen) and **previous / next clip of the match**
   according to the filters the user came from (the filters pass in the address; without filters — by time). A clip in the error state shows the cause; authorised users have „Wytnij ponownie” („Recut”) (not when the moment is outside the recording
   or the full recording no longer exists) and „Usuń klip” („Delete clip”). A clip without a description is marked „nieopisany” („undescribed”).
8. **Ratings and comments** (segment 6).
   - **Ratings:** on the clip page each coach (role `coach`; the administrator role alone is not enough) gives their own
     rating — correct / incorrect / debatable — with an optional comment. There is one rating per pair (clip, coach): saving again updates it (the page shows „zmieniona” — "changed" with the date). All
     ratings are visible with the author and date; a referee sees them without the form. Only the author or the administrator can change or delete a rating; the administrator changes someone else's rating, but the coach remains the author.
   - **Comments** on the match (match page) and the clip (clip page): every logged-in user can comment; the author edits their own
     (a comment shows „edytowano” — "edited" with the date), the author or the administrator deletes (the administrator does not edit others' comments). The content is plain text (up to 5000 characters, line breaks kept), no HTML. Adding, inline editing
     (with „Anuluj” — "Cancel") and deleting (with confirmation) work via HTMX without reloading the page, and without JavaScript as
     plain forms with a redirect. The match comments section is outside the area refreshed every 3 s, so
     the text being typed and an open edit survive the refresh of the recordings panel.
   - **Phone:** the clip page, the clip table (cards) and the comments are readable at about 375 px width without
     horizontal scrolling; the match player and the describing screen remain designed for a computer.

The category dictionary (groups Faule, Naruszenia, Bez gwizdka, Mechanika, Inne) is created
on the first start (`app/seed.py`); the administrator edits it in the panel (the „Kategorie” tab). Clips
are cut exactly (with re-encoding) from the proxy; the margin before/after is by default
15 s, clipped to the boundaries of the recording.

Hidden in the MVP (the code stays in the repository, returns in version 2): correction of the clip start and end and the
ZIP export (`app/routers/clips_v2.py`, enabled with `REFCLIPS_V2_FEATURES=1`), the old tags page (replaced by
categories).

## Tests

```bash
.venv/bin/python -m pytest
```

The video tests (conversion, frame limiting, deleting the original, cutting, clipping to the recording
boundaries, the tus → worker → ready recording flow) use real ffmpeg and are skipped when it is missing. The permission tests (`tests/test_permissions.py`)
cover every row of the permissions table from the specification for each role and their combinations, and
requests sent directly to the API that the server must reject (403).

## UI tests (E2E)

Tests in a real browser (Chromium driven by [Playwright](https://playwright.dev/python/)):
login, accounts and invitations, the match form, uploading (tus, interruption and resume, notes
with preview), the player and keyboard shortcuts, markers, permissions in the interface, the clip page
with ratings and comments (HTMX, also without JavaScript; refreshing the match page vs. a comment being typed; views 375×740), the describing screen (keyboard shortcuts, proposals from notes, undetermined quarter),
the clips tab of a match (HTMX and non-JS filters, cards on a phone), previous/next navigation, the match list
(filters, pagination, mobile view) and error pages, the admin panel (categories, retention, disk, manual deletion of the full recording, the out-of-space banner).
The test starts a real server (uvicorn) and the worker on a free port with a temporary data directory,
creates accounts with the application code, and generates the test video with ffmpeg. Each test fails
when a JavaScript error appears in the browser console (except explicitly allowed ones).

```bash
.venv/bin/pip install -r requirements-dev.txt      # także playwright i pytest-playwright
.venv/bin/playwright install chromium              # jednorazowo: przeglądarka (ok. 120 MB w ~/.cache/ms-playwright)
scripts/e2e.sh                                     # albo: .venv/bin/python -m pytest -m e2e
scripts/e2e.sh -k upload                           # wybrane testy; E2E_KEEP=1 zostawia katalog danych
```

The whole run takes about 1.5 minutes. A plain `pytest` skips the `e2e` tests (they are slow), so the quick unit tests
stay quick. On failure, a screenshot, the browser console log and the server and worker logs are saved
in `/tmp/refclips-e2e-artifacts/<date>/<test>/`, and the path is in the error message. If Chromium does not
start because of missing system libraries, install them: `sudo .venv/bin/playwright install-deps chromium`.
Full screen „on a real monitor”, Safari and iPhone cannot be checked this way (headless Chromium
checks only the full-screen API and the layout in a narrow 390×844 window).

## Structure

```
app/main.py            aplikacja FastAPI, dołączanie tras z wymogiem logowania i CSRF
app/auth.py            sesja, CSRF, zależność require(...) dla tras
app/accounts.py        logowanie z limitem prób, sesje, zaproszenia, zarządzanie kontami
app/permissions.py     uprawnienia (czyste funkcje, jedno miejsce)
app/create_admin.py    polecenie zakładające pierwszego administratora
app/routers/           trasy: logowanie, panel admina, mecze, nagrania/odtwarzacz/notatki, klipy, ekran opisywania
app/clip_list.py       filtry klipów z adresu (zakładka meczu, /clips, poprzedni/następny), podsumowanie ocen
app/feedback.py        oceny i komentarze: walidacja, zapis oceny (upsert), liczniki; trasy: app/routers/feedback.py
app/models.py          model danych (SQLAlchemy 2), migracje w alembic/
app/seed.py            słownik kategorii i ustawienia domyślne
app/notes_parser.py    parser notatek (czysta funkcja)
app/routers/uploads.py protokół tus (wgrywanie wznawialne); logika sesji, rezerwacji miejsca i sprzątania: app/uploads.py
app/video.py           ffprobe/ffmpeg: konwersja, weryfikacja wyniku i wycinanie
app/storage.py         magazyn plików (lokalny; interfejs pod przyszłe S3)
app/worker.py          pętla zadań z tabeli jobs, sprzątanie okresowe
app/retention.py       retencja pełnych nagrań (termin, usuwanie, zadanie dobowe), osierocone pliki klipów
app/disk.py            zajętość dysku i lista nagrań dla panelu, odrzucone uploady
app/share.py           linki udostępniające klipy bez konta: tworzenie, ważność, paczka ZIP; strony: app/routers/share.py,
                       zarządzanie: app/routers/share_links.py, nagłówki prywatności: app/privacy.py
app/categories.py      słownik kategorii: walidacja nazw i aliasów, kolejność, aktywacja
Dockerfile, compose.yaml, .env.example   obraz i uruchomienie w Dockerze (app, worker, init)
compose.prod.yaml, deploy/               produkcja: Caddy, wdrożenie (deploy.sh), kopie zapasowe; docs/wdrozenie.md
scripts/docker-smoke.sh                  test dymny Dockera
.github/workflows/, release-please-config.json   CI (testy), wydania i wdrożenie; docs/ci-cd.md
scripts/e2e.sh, tests/e2e/               testy interfejsu w przeglądarce (Playwright)
app/services.py        obsada, kwarty, granice klipów, nazwy plików, kolejka
app/templates, static  interfejs (Jinja2, HTMX 2.0.4 w static/vendor, czysty JS)
tests/                 pytest (testy jednostkowe i API; interfejs: tests/e2e)
```
