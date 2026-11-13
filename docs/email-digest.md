# E-mail digest

One e-mail per account per day at 07:00 Warsaw time, grouped by match, sent only when there is something to report. The in-app bell is unchanged. Setup on the server: [docs/wdrozenie.md](wdrozenie.md#e-mail-digest-smtp).

## What goes in

Five events, each a switch on **Ustawienia powiadomień** (`/settings/notifications`, linked in the header), plus a master switch „Wysyłaj maile”.

| Event | Source | Who | Default for |
|---|---|---|---|
| `new_clips_in_groups` | clips with `described_at` in the window, in a match whose crew includes a referee of a group the recipient coaches; one line per match: „5 nowych klipów (3× faul, 2× kroki)” | coaches of that group, never for clips they described themselves | coach |
| `new_match_in_groups` | matches created in the window with such a crew: date, teams, crew | same, never for a match they created | coach |
| `comments_and_ratings` | `Notification` rows of kind comment/rating created in the window, read or not, so the recipients are the bell's; „2 komentarze, 1 ocena” with the first 12 words of each comment and links | the bell's recipients | coach, referee |
| `sheet_published` | `Notification` rows of kind `sheet_published` | the crew | referee |
| `group_added` | `Notification` rows of kind `group_added`: „Dodano Cię do grupy Y (szkoleniowiec: Z)” | the person added | coach, referee |

Events 1-2 are computed when the digest is built and are not in the bell. Defaults apply while the account has not touched a switch (the column is NULL), so they follow later role changes; the admin role gives nothing by itself, and a switch the page does not show (group events for a plain referee) is never changed by saving. Nobody is told about their own actions. Accounts that are inactive or have no password get nothing.

## When it runs

A thread in the worker (`app/worker.py: digest_loop`) calls `digest.run_due` every 5 minutes, separate from the job loop so a long conversion cannot delay it. An account is due when local time is at least 07:00 (`REFCLIPS_TIMEZONE`, Europe/Warsaw by default, DST included) and its `last_digest_until` is older than today's 07:00.

- Window: `(last_digest_until, now]`; the first run covers 24 h, and any run at most 48 h, so downtime or a long-off account never floods anyone.
- `last_digest_until` is stored after every run, also when nothing was sent. After a failed send it is not, so the next check retries with the same start and nothing is lost. A crash between the SMTP delivery and that write could repeat one message; there is one worker, so this is the only duplicate path.
- A failing account does not block the others; after 3 failed sends in a row the rest of the run waits for the next check, so a dead SMTP server is not hit for every account.
- A comment's text is found by matching its notification to the nearest comment by the same author on the same target; a deleted comment is counted without text.

## Sending

Standard library only (`smtplib`, `email`); multipart plain text and inline-styled HTML in Polish, user text escaped, body quoted-printable. Configuration is by environment (`app/config.py`); without `REFCLIPS_SMTP_HOST` (and a sender address, and `REFCLIPS_PUBLIC_URL` for the links) the digest is off and logs that once. `REFCLIPS_MAIL_MODE=file` writes `.eml` files to `DATA_DIR/outbox` instead of sending (development); tests use an in-memory outbox (`mail.OUTBOX`).

Administrators get **Wyślij mi testowe podsumowanie** on the settings page: the last 24 h to their own address now, ignoring the schedule and the master switch, without moving `last_digest_until`, and sent even when empty. SMTP errors are shown on the page.

## Unsubscribing

Every mail has the footer links „Zmień ustawienia” (login needed) and „Wyłącz wszystkie maile”, and the headers `List-Unsubscribe: <https://…/unsubscribe/<token>>` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.

`/unsubscribe/<token>` needs no session and no CSRF token. GET (and HEAD) only show a confirmation page, so a mail scanner that opens links unsubscribes nobody; POST (the page's button, or a mail client's one-click request) clears the master switch and keeps the event choices. The token is 256 random bits stored per account (`email_preferences.unsubscribe_token`), in plain text because every mail has to carry it again; it can do nothing but switch the digest off. A wrong token gets the same 404 page whatever the mistake. The token path is replaced with `[ukryty]` in the application log (`app/logfilter.py`) and in the Caddy access log and Referer (`deploy/Caddyfile`), and the page sends `no-store`, `no-referrer` and `noindex`.

## Data

Migration `mvp0011` adds one table, `email_preferences` (one row per account, created on first use): `digest_enabled` (default on), five nullable event switches, `unsubscribe_token`, `last_digest_until`. No existing table changes; downgrade drops it.
