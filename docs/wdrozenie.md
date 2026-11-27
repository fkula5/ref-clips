# Deployment to the server (production)

> Segments 8–9. Status: the configuration is ready and tested locally; preparing the server and the first deployment is done by a person with access to the VPS.

**Regular deployments are done by GitHub Actions** after merging the release PR (image from GHCR, a CI key with a forced command, automatic rollback when the start fails): [docs/ci-cd.md](ci-cd.md). This document describes the server, the first deployment and the manual emergency exit (`deploy/deploy.sh`).

Planned: an OVH VPS (Ubuntu 24.04, 2 vCPU, approx. 3.7 GB RAM, 38 GB disk), Docker Engine with the Compose plugin, and `ufw` with ports 22/80/443 open. The address is the domain from `REFCLIPS_SITE` (production: `https://refclips.pl`; see "Own domain" below). Without a domain, a name like `203-0-113-7.sslip.io` works (sslip.io turns the IP written with dashes into a name that points to that IP; Caddy gets a Let's Encrypt certificate).

**HTTPS and ports 80/443 are not part of this repository.** They belong to the separate, application-independent proxy stack [vps-edge](https://github.com/fkula5/vps-edge) (a private repository), installed at `/opt/edge` on the server: container `edge-caddy`, external Docker network `edge`, one site file per application in `/opt/edge/conf/sites/`. ref-clips only delivers its own site file (`ref-clips.caddy`) to it on every deploy. The edge stack must be installed **before** the first deployment (see "Installing the edge proxy" below); deploying, restarting or breaking ref-clips no longer touches the proxy or the other sites on the server.

## How it is built

```
przeglądarka ──HTTPS──► edge-caddy (80, 443, 443/udp) ──sieć „edge”──► ref-clips-app:8000 ──► SQLite (WAL, wolumin „dane”)
   (osobny stos /opt/edge, vps-edge)                                    worker ──► ffmpeg (ten sam wolumin)
```

| File | What for |
|---|---|
| `compose.yaml` | services `init`, `app`, `worker` (as in the local tests) |
| `compose.prod.yaml` | **overlay** on `compose.yaml`: removes the application port from the host, joins `app` to the external network `edge` (alias `ref-clips-app`), log rotation |
| `deploy/ref-clips.caddy` | the site block for the edge proxy: redirects, security headers, compression, body limits, log filter, `reverse_proxy ref-clips-app:8000`; a template with two placeholders |
| `deploy/render-site.sh`, `deploy/install-site.sh` | fill the placeholders from `.env` (validating the host names) and deliver the result to `/opt/edge/conf/sites/`, then reload the edge (see "How the site file reaches the edge") |
| `deploy/env.prod.example` | template of the `.env` file on the server (no secrets) |
| `deploy/deploy.sh` | emergency deployment from the local computer via ssh (build on the server; with a lock when something is running: `app/busy.py`) |
| `deploy/ci-entry.sh`, `deploy/known_hosts` | the entry point of the CI key on the server (`deploy vX.Y.Z`, `status`) and the pinned host key — [docs/ci-cd.md](ci-cd.md) |
| `deploy/backup.sh`, `backup_snapshot.py`, `ref-clips-backup.service/.timer` | nightly backup |
| `deploy/restore.md` | restoring from a backup |

An overlay instead of a separate file: the services `init`/`app`/`worker` are defined in one place, so the smoke test (`scripts/docker-smoke.sh`) and production do not drift apart. The price: we always give both files (`-f compose.yaml -f compose.prod.yaml`) or set `COMPOSE_FILE=compose.yaml:compose.prod.yaml` (deploy.sh and backup.sh do this themselves).

The application has **no signing key**: sessions and invitations are random tokens in the database, and passwords are hashed (argon2). The `.env` holds settings and, if you turn on the e-mail digest, the SMTP password (see [E-mail digest](#e-mail-digest-smtp)); you enter the administrator password interactively. All data (database, recordings, clips) is in the Docker volume `ref-clips_dane`; the certificates are in the edge stack's volume `edge_caddy_data`.

A note on `ufw`: ports published by Docker bypass the `ufw` rules. Here only the edge stack's Caddy publishes ports (80, 443, 443/udp), and the application has no port on the host — do not change this (e.g. do not add `ports:` to `app`).

### How the site file reaches the edge

Caddy's `{$VAR}` placeholders would read the environment of the `edge-caddy` container, which does not have ref-clips' variables, so the site file is **rendered on the server** at every deploy (`deploy/deploy.sh` and `deploy/ci-entry.sh` both call `deploy/install-site.sh`):

1. `deploy/render-site.sh` replaces `{$REFCLIPS_SITE}` and `{$REFCLIPS_REDIRECT_HOSTS}` in `deploy/ref-clips.caddy` with the values from `/opt/ref-clips/.env` (the second may be empty). `.env` is parsed, never sourced. `REFCLIPS_SITE` and every redirect host must be a plain host name (letters, digits, hyphens and dots, labels up to 63 characters); anything else (`a{b`, spaces, newlines, `*`) stops the deploy, so a wrong `.env` value cannot inject Caddy configuration;
2. the result is written to a temporary dotfile in `/opt/edge/conf/sites/` and renamed to `ref-clips.caddy`; the previous file is kept as a backup until the reload succeeds;
3. `/opt/edge/reload.sh` validates the whole edge configuration and reloads it gracefully. When validation or reload fails, the previous `ref-clips.caddy` is put back, the edge is reloaded again and the deploy fails. An unchanged file skips the reload;
4. before any change the deploy checks that `/opt/edge/conf/sites` and the running `edge-caddy` container exist; otherwise it stops with a pointer to this document. `REFCLIPS_EDGE_DIR` overrides `/opt/edge` (on the server for `ci-entry.sh`, in the local environment for `deploy.sh`).

## Installing the edge proxy

Once per server, **before the first ref-clips deployment**, from a copy of [vps-edge](https://github.com/fkula5/vps-edge) (private; its README has the details). `ubuntu` must be able to write to `/opt/edge/conf/sites` (the deploy scripts put `ref-clips.caddy` there):

```bash
sudo install -d -o ubuntu -g ubuntu -m 755 /opt/edge
docker network create edge                  # the same name the compose files use (`external: true`)
rsync -a --exclude .git --exclude conf/sites ./ ubuntu@<vps>:/opt/edge/     # from the vps-edge checkout
ssh ubuntu@<vps> 'mkdir -p /opt/edge/conf/sites && cd /opt/edge && docker compose up -d'
```

Ports 80/443 must be free (on a server that still runs the old bundled Caddy follow "Moving from the bundled Caddy to the shared edge proxy" instead).

## First deployment

On the server (one-off, with `sudo`):

```bash
sudo install -d -o ubuntu -g ubuntu -m 755 /opt/ref-clips
docker compose version     # użytkownik ubuntu musi móc uruchamiać docker (grupa docker) albo mieć sudo bez hasła
```

On the local computer, in the repository (everything committed on the branch you are deploying):

```bash
deploy/deploy.sh            # domyślnie ubuntu@57.131.162.204, klucz ~/.ssh/ref_clips_deploy
```

On the first run the script sends the files and then stops with a message about the missing `.env` — this is expected. On the server:

```bash
cd /opt/ref-clips
cp deploy/env.prod.example .env && chmod 600 .env
nano .env        # sprawdź REFCLIPS_SITE i REFCLIPS_PUBLIC_URL; limity dopasowane do dysku 38 GB
```

Then `deploy/deploy.sh` again (locally). The first image build takes several minutes, and the edge Caddy needs a moment for the certificate. The script waits until `app` is healthy, delivers `ref-clips.caddy` to the edge and checks `<REFCLIPS_PUBLIC_URL>/login`.

**Administrator account** (interactively, the password at least 10 characters; `-t` is needed so the password is not visible):

```bash
ssh -t -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 \
  'cd /opt/ref-clips && COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose run --rm app python -m app.create_admin'
```

(or on the server: `docker compose -f compose.yaml -f compose.prod.yaml run --rm app python -m app.create_admin`).
Do not pass the password in the `--password` parameter: it would end up in the command history.

**Backups** — enabling the timer (once, on the server):

```bash
cd /opt/ref-clips
sudo cp deploy/ref-clips-backup.service deploy/ref-clips-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ref-clips-backup.timer
systemctl list-timers ref-clips-backup.timer     # następne uruchomienie ok. 03:30 UTC
sudo systemctl start ref-clips-backup.service    # próba od razu
journalctl -u ref-clips-backup.service -n 20 --no-pager
ls -la /var/backups/ref-clips/
```

After changing the `.service`/`.timer` files in the repository, copy them again and run `daemon-reload`.

**Final check:** open the site address (`REFCLIPS_PUBLIC_URL`), log in, create an invitation (the link must start with that address), and upload a short video. Measuring the conversion time of a 2-hour recording on this VPS is still to be done (see `TODO.md`).

## Subsequent deployments

Normally: merge the release PR on GitHub ([docs/ci-cd.md](ci-cd.md)). Below is deployment from the computer, for when GitHub is unavailable or code from outside `main` has to be deployed. If `.env` has a `REFCLIPS_IMAGE` from GHCR (written by a deployment from GitHub), `deploy.sh` forces `REFCLIPS_IMAGE=ref-clips:local` (the image built on the server) for the duration of the deployment and writes this to `.env` just before the restart, so that `backup.sh` uses the same image as the running stack.

```bash
git commit ...              # deploy.sh wdraża commit (HEAD), nie katalog roboczy; odmawia przy niezacommitowanych zmianach
deploy/deploy.sh
```

The script **first checks whether anything is running** (see below), then sends `git archive HEAD` to `/opt/ref-clips` (it deletes files removed from the repository and **keeps `.env`**; the data is in volumes, so it is not touched), builds the images, runs `docker compose up -d --remove-orphans --wait`, delivers `ref-clips.caddy` to the edge proxy (reload; see "How the site file reaches the edge"), shows the status and removes unused images (`docker image prune -f`), and at the end checks `/login` and `/health`. Database migrations are run by the `init` service at start (new tables and columns come by themselves; a deployment without migrations requires no extra steps).
During the rebuild the application is unavailable for a dozen seconds or so; an ongoing tus upload resumes by itself, but a conversion in progress starts from the beginning (for a 2-hour recording that is over an hour lost), therefore:

**The "something is running" lock.** Before any change on the server, the script runs the check `app/busy.py` in the running `app` container (its content is sent to the input of `python -`, so it also works on an image from before this module was added). It counts as "running": a tus upload with activity in the last 10 minutes, a job in the `running` state (conversion, clip cutting) and jobs waiting in the queue. If something is running, it lists what (e.g. `konwersja nagrania #1
(mecz.mp4) — 43%`, `upload IMG_2056.MOV — 1,6 GB/2,7 GB, ostatnia aktywność 2 min temu`) and ends with code 3
**without replacing files and without restarting** — the state of the directory on the server then matches the running version. Unfinished uploads with no activity for more than 10 minutes do not block (they resume after the deployment). When the stack is not running (first deployment, no `.env`, the `app` container stopped), nothing blocks. If the check itself fails (e.g. a Docker error), the script also stops, so as not to deploy "blind".

| Option | Action |
|---|---|
| (none) | busy → a message and an end, nothing changed; retry later |
| `--wait` | waits for the end of the busy state (checks every 60 s, max 120 min: `REFCLIPS_DEPLOY_WAIT_INTERVAL`, `REFCLIPS_DEPLOY_WAIT_MINUTES`), then deploys |
| `--force` or `REFCLIPS_DEPLOY_FORCE=1` | deploys anyway, with a warning (it interrupts the conversion and uploads) |

Building the image takes minutes, so right before `up` the check is repeated on the server. If in the meantime someone started uploading a file, the script ends (code 3) with a message that the files are already sent and the images built, but the stack keeps running the previous version — just run `deploy/deploy.sh` again when it is free (it is quick, because the images are in the cache). A manual check without deploying:
`ssh ... 'cd /opt/ref-clips && COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose exec -T app python -m app.busy'`
(exit code 0 = free, 1 = busy, 2 = check error).

Before a risky database change: `sudo /opt/ref-clips/deploy/backup.sh`.

Another server or key: `deploy/deploy.sh -H user@host -i ~/.ssh/klucz -d /opt/ref-clips`, or the variables `REFCLIPS_DEPLOY_HOST`, `REFCLIPS_DEPLOY_KEY`, `REFCLIPS_DEPLOY_DIR`, `REFCLIPS_DEPLOY_URL` (the address for the final check; default `REFCLIPS_PUBLIC_URL` read from the server's `.env`; empty = skip). The script uses `StrictHostKeyChecking=accept-new`: the first connection remembers the server's key, and a later change of the key stops the deployment.

## Day-to-day operation

On the server, in `/opt/ref-clips` (once: `export COMPOSE_FILE=compose.yaml:compose.prod.yaml`):

| What | Command |
|---|---|
| Status | `docker compose ps` |
| Logs of the application / worker | `docker compose logs -f --tail 100 app` (`worker`) |
| Logs of the proxy (any site, from anywhere) | `docker logs -f --tail 100 edge-caddy` |
| Restart | `docker compose restart app worker` |
| Version on the server | `cat .deploy-commit` (the number `vX.Y.Z` after a deployment from GitHub, the commit hash after `deploy.sh`) |
| Disk space | `df -h /`, `docker system df`, admin panel → „Retencja i dysk” |
| Stop (data is kept) | `docker compose stop` |

Container logs rotate by themselves (5 files of 20 MB per service). The Caddy access log (`docker logs edge-caddy`, shared with the other sites) contains request addresses, but the token from an invitation link is replaced in it with `[ukryty]` (`/set-password/[ukryty]`; the filter in `deploy/ref-clips.caddy` covers the request address, the Referer header and the Location response header). That filter only wraps the access log (stdout of `edge-caddy`); reverse_proxy warnings (e.g. a viewer leaving a video mid-stream) and the site's error log go to Caddy's default logger (stderr), which the edge masks with the same pattern (`log default` in the vps-edge `conf/Caddyfile`), and the same in the application's access log (`app/logfilter.py`); Caddy does not record cookies or the Authorization header. The set-password page responds with `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.
**Do not run `docker compose down -v`** — it removes the volume with the data and the certificates.

## Monitoring (`/health`)

`GET /health` (also `HEAD`) is public: no login, no cookies, no cache (`Cache-Control: no-store`). It answers in a few milliseconds and checks three things:

| Check | Healthy when | States in the response |
|---|---|---|
| `db` | a simple query to the database succeeds | `ok`, `error` |
| `worker` | the worker has renewed its liveness marker in the last 3 minutes (`settings.worker_heartbeat`, written every 30 s in a separate thread, so it beats also during an hour-long conversion) | `ok`, `stale` (too old), `missing` (never written), `unknown` (database unavailable) |
| `disk` | free space on the data disk (`statvfs`, without browsing directories) is at least `REFCLIPS_DISK_SAFETY_GB` — below this the application rejects every upload anyway | `ok`, `low`, `error` |

The response is `200 {"status":"ok"}` or `503 {"status":"error","checks":{"db":"ok","worker":"stale","disk":"ok"}}` — only names and states, with no paths, sizes, versions or exception contents (the details are in the logs: `docker compose logs app worker`).
The thresholds can be changed in `.env`: `REFCLIPS_HEALTH_WORKER_STALE_SECONDS` (default 180), `REFCLIPS_HEALTH_DISK_MIN_GB`.

**External ping** (e.g. UptimeRobot, free plan): an HTTP(S) monitor on `<REFCLIPS_PUBLIC_URL>/health`, interval 5 min, an e-mail alert for a code other than 200 (checking the keyword `"ok"` is not needed). On a 503, read which check fails: `curl -s <REFCLIPS_PUBLIC_URL>/health`.

**Docker healthchecks.** `app` stays on `/login` — it only answers "does the web server respond". Deliberately not `/health`: a 503 caused by the worker or a full disk is not a web server failure, restarting the application would fix nothing, and it would block `up --wait` (deployment). `worker` has its own healthcheck (`python -m app.health worker`: a liveness marker younger than 3 minutes); `docker compose ps` will show `unhealthy`, but Docker does not restart it by itself — use `docker compose restart worker`. The marker is beaten by a thread, not by the job loop, so a hung (blocked) ffmpeg does not let it expire; such a job is visible in the panel as a conversion without progress.

## E-mail digest (SMTP)

The daily digest ([docs/email-digest.md](email-digest.md)) is off until the server can send mail. Create a mail account at a provider (a transactional service or any SMTP mailbox) and put its settings in `/opt/ref-clips/.env` on the server; `app` and `worker` both read that file (`compose.yaml` passes the whole `.env`), and the credentials never go to git, the compose files or the image.

| Variable | Meaning |
|---|---|
| `REFCLIPS_SMTP_HOST` | SMTP server; **without it the digest stays off** (one log line in `app` and `worker`) |
| `REFCLIPS_SMTP_PORT` | default 587 (465 with `ssl`) |
| `REFCLIPS_SMTP_SECURITY` | `starttls` (default), `ssl` or `none` (only for a trusted local relay) |
| `REFCLIPS_SMTP_USER`, `REFCLIPS_SMTP_PASSWORD` | login; leave both empty for a relay without authentication |
| `REFCLIPS_MAIL_FROM` | sender address; defaults to `REFCLIPS_SMTP_USER` when that is an address |
| `REFCLIPS_MAIL_FROM_NAME` | sender name, default `ref-clips` |
| `REFCLIPS_PUBLIC_URL` | already set for invitations; the links in the mails are built from it, and **without it the digest stays off** |

The same SMTP settings send the password-reset mails („Nie pamiętasz hasła?” on the login page). They are subject to their own limits (3 per address per hour, 50 per hour in total, so a flood cannot use up the provider's daily quota, about 300 mails on Brevo's free plan); without SMTP or `REFCLIPS_PUBLIC_URL` no reset mail is sent and the page answers as usual. Switch off link click tracking at the provider for this sender. The details are in the README („Password reset by e-mail”).

After editing `.env`: `docker compose -f compose.yaml -f compose.prod.yaml up -d`. Check it as an administrator: **Ustawienia powiadomień** → „Wyślij mi testowe podsumowanie”. A connection or login error is shown on the page and in `docker compose logs app`. For a sender address on your own domain add the SPF and DKIM records the provider asks for, otherwise the mail lands in spam. The unsubscribe links (`/unsubscribe/<token>`) are kept out of the Caddy and application logs like the other token links.

## Links to clips without an account (`/s/<kod>`)

The first feature available without logging in: a person with the link can view and download clips. By default we show as little as possible.

- **What is visible publicly:** the video, the league (`Match.level`) and the decision category (`Clip.category_label`). There are no referees' surnames, teams, the date and time of the match, descriptions, ratings, comments, navigation or the name of the user who shared it (also in file names and in the ZIP). **Caution:** text typed by hand as the „własna” (custom) category and the league are free text and are public too; when creating a link, the page shows what the recipient will see.
- **Code outside the logs:** the code (256 bits of randomness) is only in the address. The Caddy log filter (`deploy/ref-clips.caddy`, request address and Referer) and the application log (`app/logfilter.py`) replace it with `/s/[ukryty]`; the rest of the path stays. The database holds only a SHA-256 hash. A change to `ref-clips.caddy` reaches the edge with the next deploy (both deploy paths reload it). A check on the server after deployment: `bash /opt/ref-clips/deploy/check-log-leaks.sh 24h` reads both log streams (a plain `docker logs edge-caddy | grep` sees only stdout and misses the reverse_proxy warnings on stderr) and prints only counts per logger, never the code; exit code 1 means a leak.
- **Headers:** on `/s/*` the application sets `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` (the video file: `private, no-store`, Range works). Caddy does not override `Referrer-Policy` on this path.
- **Validity and revoking:** 1, 7 or 30 days, no open-ended links; revoked by the creator or the administrator. Revoking does not undo files already downloaded. Expired and revoked links stay in the database (no cleanup).
- **ZIP:** built in `DATA_DIR/tmp`, deleted after sending; at most `SHARE_ZIP_MAX_PARALLEL` (2) at once, the others get a 503, as does a request when there is no free space. Leftovers after a crash are cleaned by the worker (`.zip` files in `tmp/` older than an hour).
- **At the first deployment of this feature:** migration `mvp0005` runs by itself (the `init` service). Clips cut earlier may carry metadata of the source file (title, GPS location, recording date); new ones no longer do. Clear the old ones once (without re-encoding, idempotent):
  `COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose exec -T app python -m app.strip_metadata`.
- **Preview by messengers:** link preview bots (e.g. Messenger) may open the page and increase the visit counter.

## Backups

`deploy/backup.sh` (timer: daily at approx. 03:30 UTC) creates a snapshot `/var/backups/ref-clips/RRRR-MM-DD`:

- `ref-clips.db` — the database via the SQLite backup API (consistent while the application is running), checked with `integrity_check`,
- `clips/` — the clips; unchanged files are hard links to the previous snapshot, so a day costs only the new clips,
- `scoresheets/` — match scoresheet files (`docs/match-scoresheet.md`), copied the same way (the directory exists only once there is one),
- `INFO.txt` — a summary.

Full recordings (proxies), originals and unfinished uploads are **not** copied — they are temporary (retention).
The last 14 snapshots are kept. The work runs in a one-off container of the application, so no `sqlite3` or `rsync` is needed on the host.
The backup directory has permissions 700 (the clips show images of players, including minors).

**Important:** the backup is on the same disk as the data, so it protects against mistakes and database corruption, but **not** against loss of the server. An off-server backup is in `TODO.md` (OVH Object Storage or a Hetzner Storage Box + rclone). Until it is set up, it is worth periodically downloading the latest snapshot to your computer, e.g.:
`ssh -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 'sudo tar -C /var/backups/ref-clips -cf - "$(sudo ls /var/backups/ref-clips | tail -1)"' > ref-clips-kopia.tar`.

Space: 38 GB of disk is little for Docker images (approx. 2 GB), backups and recordings. Watch `df -h /`; the upload limits in `.env` (`REFCLIPS_UPLOAD_MAX_GB`, `REFCLIPS_DISK_SAFETY_GB`) protect against filling the disk with an upload, but not against the backups.

## Restoring from a backup

See [deploy/restore.md](../deploy/restore.md). A test restore once a quarter (on a separate Compose stack) is recommended.

## Own domain

Production runs on `https://refclips.pl`; the apex is the canonical address and everything else redirects to it. The same steps apply to any other domain (replace `refclips.pl`). The edge Caddy keeps certificates for the extra hosts and answers them with a permanent redirect (`308`, path and query kept), so links shared before the switch (`/s/<kod>`, invitations) keep working.

1. **DNS** at the registrar (OVH): `A` records for the apex `refclips.pl` and for `www` pointing to the server IP (`57.131.162.204`). Delete OVH's default `A`/`AAAA` records of the apex (they point to OVH's parking page; a leftover `AAAA` makes Let's Encrypt validate the wrong host). Wait until `dig +short refclips.pl` and `dig +short www.refclips.pl` show the server IP and `dig +short AAAA refclips.pl` is empty.
2. **`/opt/ref-clips/.env`** on the server:

   ```
   REFCLIPS_SITE=refclips.pl
   REFCLIPS_PUBLIC_URL=https://refclips.pl
   REFCLIPS_REDIRECT_HOSTS="www.refclips.pl 57-131-162-204.sslip.io"
   ```

   `REFCLIPS_REDIRECT_HOSTS` is optional (space-separated, in quotes); without it only `REFCLIPS_SITE` is served. Every host in it needs a DNS record to this server, otherwise Caddy cannot get its certificate (it keeps retrying in the background and the other hosts are not affected).
3. **Apply.** Edit `.env` as above, then re-render the site file and recreate the containers (the app and worker read `.env` only when created; data and certificates are in volumes and stay):

   ```bash
   cd /opt/ref-clips
   export COMPOSE_FILE=compose.yaml:compose.prod.yaml
   bash deploy/install-site.sh deploy/ref-clips.caddy .env   # validates the hosts, renders, reloads the edge
   docker compose up -d        # recreates app and worker if their environment changed
   docker logs --tail 50 edge-caddy    # certificate obtained for each host
   ```

   Ports 80/443 must be reachable from the internet. The next deploy renders the site file again from `.env` by itself, but never re-reads `.env` for the running containers: after any `.env` edit run `docker compose up -d`.
4. **Check** (the full list is in the PR that introduced this): `curl -sI https://refclips.pl/health` gives `200`; `curl -sI "https://www.refclips.pl/s/abc?x=1"` and `curl -sI "https://57-131-162-204.sslip.io/s/abc?x=1"` give `308` with `location: https://refclips.pl/s/abc?x=1`.
5. **What changes elsewhere:**
   - **Monitoring:** change the UptimeRobot monitor URL to `https://refclips.pl/health`.
   - **Links in e-mails and invitations** use `REFCLIPS_PUBLIC_URL`, so new ones point to the new domain. E-mails and invitations sent earlier keep the old address and still work through the redirect.
   - **Sessions:** cookies are per host, so after the switch everyone has to log in again on the new domain (the old session cookie never reaches `refclips.pl`). A watch room (`/watch/<id>`) opened before the switch has to be reopened.
   - **Deploy:** `deploy.sh` reads `REFCLIPS_PUBLIC_URL` from the server's `.env`; `REFCLIPS_DEPLOY_HOST`, `DEPLOY_HOST` in CI and `deploy/known_hosts` keep using the server IP.
   - The permanent redirect is cached by browsers: to undo it, users would need to clear the cache, so keep the old hosts in `REFCLIPS_REDIRECT_HOSTS` only as long as you want them redirected.

## Other sites on this server

Other applications on this VPS (e.g. the quiz in `/opt/quiz`) use the same edge proxy and need nothing from this repository:

- one file per site in `/opt/edge/conf/sites/<name>.caddy` (e.g. `quiz.caddy`), imported by the edge Caddyfile; ref-clips only ever writes `ref-clips.caddy`,
- the site's container joins the external network `edge` (`external: true` in its compose file) with a unique alias, and its `.caddy` file proxies to that alias, e.g. `reverse_proxy quiz:3000`; `app` is the only ref-clips container on that network, `worker` and the database stay private,
- after adding or changing a file: `/opt/edge/reload.sh` (validates the whole configuration, then reloads gracefully; a broken file is rejected and the old config keeps running).

Do not reuse the hosts from `REFCLIPS_SITE` / `REFCLIPS_REDIRECT_HOSTS` in another site file. The edge stack itself (Caddy version, global timeouts): [vps-edge](https://github.com/fkula5/vps-edge).

## Moving from the bundled Caddy to the shared edge proxy

One-time, for a server that still runs the old layout (a `caddy` service in ref-clips' compose project, `/opt/caddy-sites`, certificates in `ref-clips_caddy_data`). Expect a short interruption in step 5, when ports 80/443 change hands; nothing else is touched, and the app stays up throughout. Do it before the first release without the `caddy` service is deployed, and install the matching `deploy/ci-entry.sh` first (it is reinstalled by hand: [docs/ci-cd.md](ci-cd.md), step 2), because the new release no longer contains `deploy/Caddyfile`, which the old script requires.

1. **Install `/opt/edge` and create the network** (as in "Installing the edge proxy", but do not start it yet: the old Caddy still holds ports 80/443):

   ```bash
   sudo install -d -o ubuntu -g ubuntu -m 755 /opt/edge
   docker network create edge
   # copy vps-edge to /opt/edge (rsync as in its README), then:
   mkdir -p /opt/edge/conf/sites
   ```

2. **Copy the certificates** so the edge does not have to issue them again (Let's Encrypt rate limits):

   ```bash
   docker run --rm -v ref-clips_caddy_data:/from -v edge_caddy_data:/to alpine cp -a /from/. /to/
   ```

   (The volume is created by `docker run`; Compose later only warns that it did not create it.)
3. **Render and place `ref-clips.caddy`, and move `quiz.caddy`:**

   ```bash
   # deploy/ of this release is not on the server yet: copy it next to the running version first
   scp -r deploy ubuntu@<vps>:/tmp/ref-clips-deploy
   ssh ubuntu@<vps>
   bash /tmp/ref-clips-deploy/render-site.sh /tmp/ref-clips-deploy/ref-clips.caddy /opt/ref-clips/.env > /opt/edge/conf/sites/ref-clips.caddy
   mv /opt/caddy-sites/quiz.caddy /opt/edge/conf/sites/quiz.caddy
   ```

   The quiz container must also join the network `edge` (its compose file: `external: true`, `name: edge`) with an alias matching the `reverse_proxy` target in `quiz.caddy`; the old network `caddy-sites` is no longer used.
4. **Connect the running app to the new network** under the alias the site file proxies to (the next deploy makes this permanent through `compose.prod.yaml`):

   ```bash
   docker network connect --alias ref-clips-app edge ref-clips-app-1
   ```

5. **Stop the old Caddy, then start the edge:**

   ```bash
   cd /opt/ref-clips && COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose stop caddy
   cd /opt/edge && docker compose up -d
   ```

6. **Verify:** `docker logs --tail 50 edge-caddy` (no errors, certificates found rather than requested), `curl -sI https://refclips.pl/health` gives `200`, `curl -sI "https://www.refclips.pl/s/abc?x=1"` gives `308`, and the quiz answers. If something is wrong: `cd /opt/edge && docker compose stop`, then `cd /opt/ref-clips && docker compose start caddy` brings the old layout back (nothing was deleted yet).
7. **The next ref-clips deploy** (GitHub or `deploy/deploy.sh`) runs `docker compose up -d --remove-orphans`, which removes the stopped old `caddy` container, recreates `app` on the `edge` network and re-renders `ref-clips.caddy`. Afterwards the leftovers can be deleted: `docker volume rm ref-clips_caddy_data ref-clips_caddy_config`, `docker network rm caddy-sites` (once nothing uses it) and `/opt/caddy-sites`. Remove `REFCLIPS_CADDY_SITES_DIR`, `REFCLIPS_HTTP_PORT` and `REFCLIPS_HTTPS_PORT` from `.env` if they were set (they are ignored now).

Rolling back ref-clips to a release from before this change is not possible afterwards (that release brings its own Caddy back and the two would fight over ports 80/443).

## Revoking the access of the key `claude-deploy-ref-clips`

The key is in `~ubuntu/.ssh/authorized_keys` (comment `claude-deploy-ref-clips`). On the server, after logging in with your own key:

```bash
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
sed -i '/claude-deploy-ref-clips/d' ~/.ssh/authorized_keys
grep -c claude-deploy-ref-clips ~/.ssh/authorized_keys     # ma być 0
```

Check from the computer that has this key that `ssh -i ~/.ssh/ref_clips_deploy -o IdentitiesOnly=yes ubuntu@57.131.162.204 true` ends with a refusal, and then delete `authorized_keys.bak` and the local key file (`~/.ssh/ref_clips_deploy*`).
If the key had an entry in `sudoers` or some other way of access, remove it too (`sudo grep -r claude /etc/sudoers /etc/sudoers.d`).

## Troubleshooting

- **No certificate / TLS error after the first start:** `docker logs edge-caddy`. The address must point to this server, and ports 80 and 443 must be reachable (ufw, the OVH firewall). On the shared `sslip.io` domain Let's Encrypt may return a rate limit — Caddy then tries another issuer automatically (ZeroSSL); if that fails too, use your own domain ("Own domain").
- **`deploy.sh`: „brak pliku .env”:** see "First deployment". **"permission denied" with docker:** add the user to the `docker` group or set up `sudo` without a password.
- **Large uploads break off:** Caddy has no time limit for the request body, and a tus chunk is 50 MB (the Caddy limit is 64 MB); check `docker compose logs app`, `docker logs edge-caddy` and the free disk space.
- **`deploy.sh` / the CI deploy stops with „stos edge nie jest zainstalowany” or „kontener edge-caddy nie działa”:** the edge proxy is missing or stopped; see "Installing the edge proxy". Nothing was changed.
- **A deploy fails with „walidacja lub przeładowanie edge nie powiodły się”:** the rendered `ref-clips.caddy` (or another site's file) is invalid; the previous file was restored. Run `/opt/edge/reload.sh` to see Caddy's message. A bad host in `.env` is reported earlier, by `deploy/render-site.sh`.
- **502 from the site after a deploy:** `app` is not on the `edge` network under the alias `ref-clips-app` (`docker inspect ref-clips-app-1 -f '{{json .NetworkSettings.Networks}}'`); `docker compose up -d` fixes it.
- **`deploy.sh` ends with code 3 („na serwerze coś trwa”):** this is a protective lock, nothing has changed. Wait, or use `--wait` or `--force` (see "Subsequent deployments"). If „konwersja nagrania #N — 0%” blocks for many hours and `docker compose ps` shows the worker as `unhealthy`: `docker compose restart worker` (the jobs return to the queue).
- **`/health` returns 503:** `curl -s .../health` shows which check fails. `worker: stale/missing` — `docker compose logs --tail 50 worker`, then `docker compose restart worker`; `disk: low` — `df -h /`, admin panel → „Retencja i dysk”.
- **The invitation has an `http://...` address:** there is no `REFCLIPS_PUBLIC_URL` in `.env`.
- **The login attempt limit blocks everyone at once:** `REFCLIPS_TRUST_PROXY=1` must be set, otherwise every user has the address of the proxy container.
