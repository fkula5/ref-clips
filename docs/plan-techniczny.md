# Technical plan for the MVP

> Version 0.3, 2026-11-01. Responds to section 4 of the [MVP specification](specyfikacja-mvp.md) (version 0.3).
> A document for approval before writing the code.

## 1. Summary of decisions

| Area | Decision | Main reason |
|---|---|---|
| Prototype | **We develop `ref-clips`**, we do not start from zero | about 2 thousand lines of working, tested video code that would otherwise have to be written again |
| Backend | Python 3.12 + FastAPI + SQLAlchemy + Alembic | already in place, works well with ffmpeg |
| Database | **SQLite (WAL mode)** | a few dozen users on one server, zero administration, the backup is a single file |
| Frontend | Jinja2 templates + HTMX + plain JS in the player | simple forms and lists, no separate build, works on a phone |
| Upload | **tus protocol** (resumable): `tus-js-client` in the browser, a simple tus server in FastAPI | resuming after a dropped connection is a standard, not our own invention |
| Video | Conversion to 720p H.264, deleting the original, clips as **separate** MP4 files | clips must survive deleting the full match (retention) |
| Login | Own accounts: e-mail + password (argon2), session in a cookie, invitations by link | no dependence on external services; accounts are created by the admin |
| Hosting | VPS in the EU (e.g. Hetzner CX22: 2 vCPU, 4 GB, 40 GB, approx. €4–5 / month) + Docker Compose + Caddy (HTTPS) | fits the budget, automatic certificate |
| Backups | Nightly backup of the database and clips to external storage in the EU (e.g. Hetzner Storage Box, approx. €4 / month) | loss of the VPS does not mean loss of the clips |

## 2. Prototype: what stays, what changes

**Stays (with extensions):**
- `app/video.py`: probe, conversion, cutting. Change: default margin 15/15 s, and cutting right after a marker is added.
- `app/worker.py`: job queue in the `jobs` table. The `retention` and `cleanup` jobs are added.
- `app/notes_parser.py`: adds recognition of the `CC`/`U1`/`U2` functions and a category dictionary instead of tags.
- `app/storage.py`: adds disk space reservation.
- `app/static/player.js`: adds the „Zaznacz” key without stopping playback, and the marker list.

**Changes:**
- Data model (section 4): accounts, roles, crew CC/U1/U2, categories, ratings, retention.
- Upload: the raw POST is replaced by tus.
- Tags are replaced by **categories** with groups (fouls, violations, no whistle, mechanics, other) and the „własna” (custom) option.

**Removed from the interface (returns in version 2):** manual correction of clip boundaries, ZIP export, editing of the tag dictionary in its current form. The code of the correction and the export stays in the repository, only hidden.

Migration: the prototype has no production data, so we make a **new initial migration** instead of reworking the old one.

## 3. Architecture

```
przeglądarka ──HTTPS──► Caddy ──► FastAPI (uvicorn, 2 procesy) ──► SQLite (WAL)
                          │            │
                          │            └── tabela jobs ◄── worker (1 proces, ffmpeg, nice 10)
                          │
                          └── /media/*  ── forward_auth do FastAPI ──► pliki z dysku (Range)
```

- **Serving video through Caddy.** Python does not transfer gigabytes. Before each file request Caddy asks FastAPI (`/auth/media`) whether the session is valid (forward_auth). Then it serves the file itself, with seeking support (Range).
- **Worker** processes one job at a time with lowered priority (`nice`), so that conversion does not block the site on 2 vCPU. Clip cutting jobs have priority over conversion, because they are short.
- **SQLite:** `journal_mode=WAL`, `busy_timeout=5000`, writes in short transactions. SQLAlchemy leaves the option to move to Postgres without changes in the application code.

## 4. Data model

| Table | Most important fields | Notes |
|---|---|---|
| `users` | e-mail, first and last name, password hash, active | |
| `user_roles` | user_id, role (`admin` / `coach` / `referee`) | several roles at once |
| `sessions` | token (hash), user_id, validity | logging out invalidates the session |
| `invites` | token (hash), user_id, purpose (`activate` / `reset`), validity 7 days | link for setting a password |
| `matches` | date, league, teams (name, colour), author | |
| `match_officials` | match_id, function (`CC`/`U1`/`U2`), user_id **or** a typed first and last name | the check "was in the crew" by user_id |
| `videos` | match_id, content (`full` / list of quarters), proxy path, duration, status, `expires_at`, `purged_at` | the original only during conversion |
| `upload_sessions` | tus: id, user_id, size, offset, reserved bytes, metadata | cleaned after 24 h of inactivity |
| `period_marks` | video_id, period (Q1–Q4, OT1–OT3), time in the recording | |
| `categories` | group, name, aliases, active, order | edited by the admin |
| `clips` | video_id, marker time, start/end, file, cutting status, official_id or "whole team", category_id or custom name, description, author, `described_at` | `described_at = null` means "undescribed" |
| `ratings` | clip_id, coach_id, rating (`correct` / `incorrect` / `debatable`), comment | unique (clip_id, coach_id) |
| `comments` | match_id **or** clip_id, author, text, `edited_at` | |
| `jobs` | type, video_id / clip_id, status, progress, error | as in the prototype |
| `settings` | key, value | e.g. `retention_days = 30` |

**Quarter and clip time** are calculated when read from `period_marks` (as in the prototype), so changing a marker immediately corrects all clips. A recording with one quarter and no marker has a default start of 0:00 for the declared quarter.

## 5. Permissions

- All rules are in one module, `app/permissions.py`, as pure functions, e.g. `can_create_clip(user, match)`, `can_rate(user)`, `can_delete(user, obj)`. Routes call them, and templates use them only to hide buttons.
- **The server always checks.** Every write route has the FastAPI dependency `require(...)`. Tests cover every row of the permissions table from the specification, calling the API without the interface.
- **"Was in the crew"** means the existence of a `match_officials` row with `user_id = user`.
- **Upload by a referee:** the form inserts the referee into the crew, and the server rejects saving a match in whose crew they are not (this applies to a user who is only a referee).

## 6. Video

### 6.1 Upload (tus)

- Browser: `tus-js-client` (a JS file pinned in the repository, no CDN), chunks of 50 MB, automatic retrying and resuming after a page refresh (file fingerprint).
- Server: a minimal implementation of tus 1.0.0 in FastAPI (`app/routers/uploads.py`, logic in `app/uploads.py`): extensions `creation`, `termination` and `expiration`, i.e. `POST` to create, `HEAD` for the offset, `PATCH` to append, `DELETE` to cancel. The data goes in a stream to `uploads/tus-<id>.part`, and the state to `upload_sessions` (the offset is saved every 4 MB and when the connection breaks).
- **Space reservation:** with `POST` we know the file size. The server accepts the upload only if the disk has free space for `size + 1.5 GB (proxy) + 3 GB of margin`, counting uploads already reserved. Otherwise the user gets the message „brak miejsca, spróbuj później” ("no space, try again later"), and the admin gets a warning in the panel.
- Limit: one active upload per user, at most 8 GB per file.

### 6.2 Conversion

- Settings as in the prototype: H.264 `veryfast` CRF 23, AAC, max 720p, max 30 fps, a keyframe every 1 s, `+faststart`.
- **The original is deleted** right after a successful conversion and checking the result (ffprobe: the duration of the video track matches the original within a tolerance of max(2 s, 1% of the length); phone recordings have audio longer than the video, edit lists and start_time ≠ 0, so we compare the video tracks, not the formats).
- Estimated time on 2 vCPU: a 2-hour match from a 1080p phone takes approx. 45–90 min, and 4K/HEVC may take 2–3 h. The interface shows the position in the queue and the progress.
- **Local measurement (stone 3, 2026-11-01).** A synthetic 1080p recording, 30 fps, 3 min (ffmpeg `testsrc2` with motion + a sine, H.264 at approx. 10 Mb/s, 227 MB), conversion with the full command from `app/video.py` (veryfast, CRF 23, 720p, +faststart):

  | Conditions | Time for 3 min | Multiple of real time | Extrapolation to 2 h |
  |---|---|---|---|
  | `taskset -c 0,1` (2 cores), 2 measurements | 50.7 s and 50.2 s | approx. 0.28× | approx. 34 min |
  | no limit (16 cores) | 31.7 s | approx. 0.18× | approx. 21 min |

  The result for 2 h on 2 cores is well below 2 h, so the `superfast` preset is not needed (for comparison: 41.3 s, approx. 28 min for 2 h, but a file more than 2× larger). The 3-min proxy had 32 MB, so 2 h is approx. 1.3 GB. **Caveat:** the synthetic image differs from a real recording (different motion and noise complexity, no blur and camera compression), and linear extrapolation does not cover 4K/HEVC, where decoding alone is several times more expensive. The cores of this computer are also faster than the vCPUs of a typical VPS. We treat the figures as a lower bound; **the measurement must be repeated on a real VPS and a real recording** (after buying the server, segment 8). If it is too slow, the `superfast` preset or a stronger VPS during the conversion is possible.
- **Frame limit:** we add the filter `fps=30` up to 30 fps only when the source (average or nominal frame count) has more than 30 fps; a lower frame count is not raised.
- **Priority:** the worker runs ffmpeg via `nice -n 10` (variable `REFCLIPS_FFMPEG_NICE`).
- Space: a 2 h proxy takes approx. 1–1.5 GB.

### 6.3 Clips

- A clip is created right after a marker is added, i.e. a `cut` job from the proxy: 15 s before and 15 s after, trimmed to the file boundaries.
- Cutting is exact (re-encoding), CRF 20, 720p. A 30 s clip is approx. 6–10 MB. 30 s on 2 vCPU is cut in a few seconds.
- Deleting a marker also deletes the clip file.
- Markers from notes on upload wait for the conversion to finish, then they are cut automatically.

### 6.4 Retention

- `videos.expires_at = upload + retention_days` (default 30, an administrator setting).
- The daily `retention` job deletes the proxies after their deadline and sets `purged_at`. The clips stay.
- 7 days before the deadline the match carries a mark in the interface: „pełne nagranie dostępne jeszcze X dni” ("full recording available for X more days").
- The admin panel shows disk usage (full recordings, clips, free space) and allows deleting a full recording earlier.
- **Implementation in segment 7 (deviations from the plan):**
  - the `retention` job is not a row in the `jobs` table, but a cleanup step of the worker (it checks every hour whether a day has passed since `settings.retention_last_run`); the time is saved by an atomic `UPDATE`, so neither a restart nor a second worker runs it twice;
  - recordings in conversion and recordings with clips waiting to be cut are skipped (by retention and by manual deletion) and come back in the next run; after deletion the write routes return 409;
  - a change of `retention_days` applies to new recordings, and the admin may deliberately recalculate the existing ones (upload + N days);
  - the proxy size is kept in the column `videos.proxy_bytes` (migration `mvp0004`), so the panel does not check files;
  - a clip with an undetermined quarter can be described after the full recording is deleted (the quarter stays "undetermined");
  - an upload rejected for lack of space is saved in `upload_rejections` and gives a banner in the admin panel (plan 6.1).

**Disk budget (40 GB):** the system and Docker take approx. 8 GB, a reserve for an active upload approx. 8 GB, so about 24 GB remains for full recordings and clips. That is about 12–15 full matches at once plus several hundred clips. With more traffic we first shorten the retention, then move the clips to object storage (the `storage` layer is prepared for this).

## 7. Login and accounts

- Passwords: `argon2-cffi`. Login with e-mail + password, with an attempt limit (5 per 15 minutes per account and IP).
- Session: a random token in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie, valid for 30 days with refreshing. Only the token hash is kept in the database.
- CSRF: `SameSite=Lax` + a CSRF token in the forms and in the HTMX header.
- **Creating an account:** the admin enters the e-mail, first and last name and the roles, and the system generates an **invitation link** (valid 7 days). The admin sends it themselves, e.g. via Messenger or SMS. In the MVP the application does not send e-mails, so it does not need an SMTP server.
- Password reset: the admin generates a reset link in the same way. Self-service reset by e-mail is in version 2.
- The first admin is created with the command `python -m app.create_admin`.

## 8. Interface

- Templates + HTMX (the file pinned in `static/`, no CDN).
- Responsive layout: the views of the clip list, clip, ratings and comments are designed for a phone first. The match player and the marker describing screen are designed for a computer.
- The most important screens:
  1. **Login and setting a password from an invitation**
  2. **Match list** with a filter and status: conversion / ready / no quarter markers / full recording deleted
  3. **New match:** data, crew CC/U1/U2 (choosing an account or typing), file or files with the content declaration, optional notes with a preview
  4. **Quarter markers** (a step required for a file with several quarters)
  5. **Player:** `Z` = mark, list of markers on the side, shortcuts as in the prototype
  6. **Describing:** list of undescribed markers, with a clip preview for each, referee, category and description, save and move to the next
  7. **Match clips** (tab) with filters: referee / category / quarter
  8. **Clip:** player, description, coaches' ratings, comments
  9. **Admin:** users and roles, categories, retention, disk usage

## 9. Deployment

- **Server:** Ubuntu 24.04 LTS. Firewall `ufw` (only 22, 80, 443 open), SSH login with a key only, `unattended-upgrades` for security patches.
- **Docker Compose:** services `app` (uvicorn), `worker` and `caddy`. The `data/` volume for the database, video and clips.
- **Domain:** needed for HTTPS, e.g. a subdomain of a domain you own or a cheap `.pl` domain. Caddy issues and renews the Let's Encrypt certificate by itself.
- **Application update:** `git pull && docker compose up -d --build`. The Alembic migrations run at start.
- **Backups** (cron, nightly):
  - database: `sqlite3 .backup`, sent via `rclone` to the Storage Box, kept for 14 days,
  - clips: `rclone sync` to the Storage Box,
  - full recordings are **not** copied, because they are temporary.
  - Once a quarter we run a test restore.
- **Monitoring:** a simple `/health` endpoint (database, worker, free space) and a free external ping (e.g. UptimeRobot) that raises an alarm when the site does not respond.

## 10. Deployment process

We split the work into segments (milestones below). Each segment goes through the loop:

```
wdrożenie ──► review ──► są uwagi? ──tak──► poprawa błędów ──► review ──► …
                            │
                            nie
                            ▼
                      segment zamknięty ──► następny segment
```

- **Deployment:** implementation of the segment together with its tests (agent Sonnet 5.5, effort high), on a separate branch `segment-N`.
- **Review:** an independent review of the changes (Opus 5.5): compliance with the specification and the plan, logic errors, permissions and security, tests. Each comment gets a weight: **blocking** (must be fixed) or **minor**.
- **Fixing errors:** removal of all blocking comments (minor ones at discretion), followed by another review. The loop continues until the review returns no blocking comment and all tests pass.
- **Closing the segment:** a short report (what was done, the test result, the list of minor comments postponed for later) and merging the branch into `master`.
- **Tests before review:** each segment passes the full `pytest` before review, as well as `scripts/e2e.sh` (UI tests in a real browser, segment 4a) and — from segment 2a — `scripts/docker-smoke.sh` (smoke test of the Docker image). The new interface (JS, templates, HTMX) gets scenarios in `tests/e2e/`.
- Postponed minor comments and ideas go to `TODO.md`.

## 11. Milestones

Each milestone ends with a working version with tests.

1. **Foundation:** the new data model + migration, accounts, login, invitations, roles, `permissions.py` with tests of the permissions table.
2. **Matches and crew:** the match form, CC/U1/U2 (account or typed name), the rule "a referee uploads only their own matches".
2a. **Docker locally (for testing by other people):** a `Dockerfile` (Python 3.12 slim + ffmpeg from Debian packages) and a `compose.yaml` with the `app` and `worker` services on a shared data volume. Starting with one command, `docker compose up`, and the first admin via `docker compose run --rm app python -m app.create_admin`. Instructions in the README for Windows (Docker Desktop), macOS and Linux. The same image will later serve in segment 8, where only Caddy, backups and the production configuration are added.
3. **Upload and conversion:** tus, space reservation, the file content declaration, deleting the original. Measuring the conversion time locally, limited to 2 cores (`taskset -c 0,1`) as an approximation of the VPS.
4. **Markers:** quarter markers, the player with the „Zaznacz” key, notes on upload (parser with CC/U1/U2 and categories).
5. **Clips:** 15/15 cutting, the describing screen, the match clips tab with filters, the clip view.
6. **Ratings and comments:** coach ratings, match and clip comments, editing and deleting according to permissions, mobile views.
7. **Admin and retention:** the panel for users, categories, retention and disk, the `retention` job.
8. **Deployment (postponed until the VPS is bought):** the image and Compose from segment 2a extended with Caddy, backups, monitoring, and passing the acceptance criteria from the specification on the server.

Milestones 1–7 are built and tested locally in WSL; from segment 2a every segment must also work in Docker. After the VPS is bought, the conversion time measurement from step 3 is repeated on the server.

## 12. Risks

| Risk | Effect | What we do |
|---|---|---|
| Conversion on 2 vCPU too slow (4K/HEVC) | a match available only after several hours | measurement in milestone 3, faster presets, possibly a temporarily stronger VPS |
| Slow upload from home (4 GB at 20 Mb/s takes approx. 30 min) | frustration when uploading | tus with resuming, a recommendation to upload over Wi-Fi / from a computer |
| A full disk | uploads rejected | space reservation, retention, disk panel, alarm in `/health` |
| Loss of the VPS | loss of clips and descriptions | nightly backups to external storage |
| Safari on an iPhone and playback | clips do not play on the phone | H.264 + AAC + faststart (compatible), a test in the acceptance criteria |

## 13. Monthly costs (estimate)

| Item | Cost |
|---|---|
| VPS 2 vCPU / 4 GB / 40 GB (EU) | approx. €4–5 |
| Storage Box 1 TB for backups (EU) | approx. €4 |
| `.pl` domain | approx. 1–5 PLN / month converted (the first year may be cheaper) |
| **Total** | **approx. 40–50 PLN / month** |
