# Releases and automatic deployment (GitHub Actions)

> Status: the configuration is ready, but **the first real release has not yet taken place** — the workflow can be fully
> verified only on GitHub. Before anything works, do the [one-time steps](#one-time-steps-after-the-merge-manual)
> (the order matters). Manual deployment from a computer (`deploy/deploy.sh`) still works as an emergency exit.

## How it works

1. **Work in PRs.** Changes reach `main` only through a pull request. On every PR `ci.yml` starts with two jobs:
   `unit` (`pytest -q`) and `e2e` (Playwright + Chromium, `scripts/e2e.sh`). Both names are required in the `main`
   protection. If `e2e` fails, screenshots and logs are in the run artifacts (`e2e-artefakty`, 7 days).
2. **PR title = history entry.** When merging with squash, the PR title becomes the commit on `main`, and from the commits
   [release-please](https://github.com/googleapis/release-please-action) calculates the version number and the list of changes
   (Conventional Commits): `fix:` raises the last digit, `feat:` the middle one, `feat!:` or `BREAKING CHANGE:` the first;
   `docs:`, `ci:`, `chore:`, `test:` alone do not create a release.
3. **Release PR.** After every merge into `main` the workflow `release.yml` runs release-please. It opens (or updates)
   the PR "chore: release vX.Y.Z" with a change to `version.txt`, `.release-please-manifest.json` and `CHANGELOG.md`.
   Nothing is deployed until you merge it.
4. **Merging the release PR** creates the tag `vX.Y.Z` and a GitHub Release, and in the same run the following jobs:
   - `build` — builds the image on GitHub and publishes it to GHCR: `ghcr.io/fkula5/ref-clips:vX.Y.Z` and `:sha-xxxxxxx`
     (the version number in the image: `--build-arg REFCLIPS_VERSION`, visible in the footer when logged in; an existing
     tag's image is not overwritten),
   - `deploy` (environment `production`) — a single command `ssh server deploy vX.Y.Z`. The server builds nothing,
     it only pulls the ready image.
5. **On the server** the command goes to the forced script `deploy/ci-entry.sh` (installed as
   `/usr/local/bin/ref-clips-ci-entry`): it fetches the version's files from the public repository, **waits up to 2 hours
   until nothing is running** (upload, conversion — the same check `app/busy.py` as in `deploy.sh`), pulls the image,
   replaces the files and `REFCLIPS_IMAGE` in `.env`, restarts the stack and checks `/health`. If the new version does not
   start, it **rolls back to the previous one by itself**. After 2 hours of waiting it ends with a clear error (code 3),
   and the deployment is retried with one button (see "Retrying a deployment and rolling back to an older version").

```
PR ──► ci.yml: unit + e2e ──(zielone)──► merge do main ──► release.yml: release-please
                                                           └► PR „wydanie vX.Y.Z” ──► ci.yml (dispatch) ──► merge
merge PR-a wydania ──► tag + Release ──► build (GHCR) ──► deploy: ssh … deploy vX.Y.Z ──► ci-entry.sh na serwerze
```

Why build and deployment are jobs of `release.yml` and not separate "on tag" workflows: a tag created by `GITHUB_TOKEN`
does not start any other workflow (events from `GITHUB_TOKEN` do not create runs — the exception is
`workflow_dispatch` and `repository_dispatch`; release-please's documentation describes the same).

### Tests on the release PR (the `GITHUB_TOKEN` trap)

A PR opened by `GITHUB_TOKEN` (that is, by release-please without a personal token) **does not trigger a
`pull_request` event**, so the required checks on it would not run. The solution without a PAT, applied in `release.yml`:
after creating or updating the release PR the workflow calls `ci.yml` via `workflow_dispatch` on its branch
(`release-please--branches--main`, permission `actions: write`; `workflow_dispatch` is an exception and creates a run
also for `GITHUB_TOKEN`). The run concerns exactly the commit that is the end of the PR.

**Caveat (checked in the documentation, not live):** GitHub's documentation
([Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks))
states explicitly that checks from workflow jobs run by `workflow_dispatch` on a PR branch **do not appear in the PR's
checks section and do not satisfy a required check in the rules (ruleset)**, even when they pass; the limitation applies
only to checks from workflow jobs, not to *commit statuses*. Therefore the last step of each of the `unit` and `e2e` jobs
(only with `workflow_dispatch` on a `release-please--*` branch) **additionally writes a commit status with the same name**
(`unit`, `e2e`; `POST /repos/…/statuses/{sha}`, permission `statuses: write`). The status goes to the same commit and
satisfies the required check of that name, as long as the rule does not force the source "GitHub Actions" (leave
**Any source**, step 6). If the merge of the first release PR is still blocked ("Waiting for status to be reported"),
there are two options: an administrator merges the release PR bypassing the rule (once), or we switch to a GitHub App
token / PAT for release-please (then the PR triggers the normal `pull_request`; secret `RELEASE_PLEASE_TOKEN` + `token:`
in the release-please step, everything else unchanged).

## What the CI key may do

The private key is in the secret `DEPLOY_SSH_KEY` of the `production` environment. On the server its entry in
`authorized_keys` has a **forced command and `restrict`** (no terminal, port forwarding, agent), so regardless of what
the client sends, only `ref-clips-ci-entry` runs. The script (owned by root, outside the application directory, so the CI
key cannot change it) accepts exactly two commands, with strict regular expressions, without `eval` and without passing
arguments on:

| Command | Action |
|---|---|
| `deploy vX.Y.Z` | deploys a version (described below) |
| `status` | prints the deployed version (`.deploy-commit`) and the state of the services |

Everything else ends with code 2. The CI key has no write channel to the server: the server fetches the version files
itself over HTTPS from the public repository (`codeload.github.com/fkula5/ref-clips`), and the image from GHCR. The script
replaces only `compose.yaml`, `compose.prod.yaml` and `deploy/` in `/opt/ref-clips` and one line `REFCLIPS_IMAGE` in `.env`
(`.env` is not printed, the data is in volumes). A side effect of the trust model: whoever can merge code into `main`
controls what is deployed to the server — that is why the `main` protection and the `production` environment matter.

The server's host key is pinned in the repository (`deploy/known_hosts`, a public value), and `ssh` runs with
`StrictHostKeyChecking=yes`. After reinstalling the server or changing the host key, update this file (`ssh-keygen -F
57.131.162.204`, only the `ssh-ed25519` line, **in unhashed form** with the host name; check the fingerprint on the
server: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).

### Steps of `deploy` on the server

1. an `flock` lock (`/opt/ref-clips/.deploy.lock`, the same as in `deploy.sh`) for the whole duration;
2. fetching the version's files into a temporary directory (a wrong tag ends immediately, not after 2 hours of waiting);
3. waiting until nothing is running: `app/busy.py` sent to the input of `python -` of the running `app` container; a stopped
   stack does not block, **a failed check blocks** (code 1); checking every 60 s, up to 120 min in total, then code 3 and
   a message saying what is running;
4. `docker pull` of the version's image (before any change) and **a re-check of busyness right before the restart**;
5. a copy of the previous files to `.rollback/`, replacing the files, `REFCLIPS_IMAGE=ghcr.io/fkula5/ref-clips:vX.Y.Z` in `.env`
   (a new file next to it + `mv`, one line; the same image is used by `deploy/backup.sh`);
6. `docker compose up -d --no-build --remove-orphans --wait --wait-timeout 300`; Caddy restarts only after a change to
   `Caddyfile`;
7. a check of `GET /health` through Caddy (up to 150 s). When `up` or `/health` fails: **return to the previous files and the
   previous `REFCLIPS_IMAGE`**, code 4 (the rollback succeeded) or 5 (it did not succeed — you need to log in to the server).
   Exception: if `/health` returns an error only because of the disk (database and worker `ok`), it is not the version's
   fault — the new version stays, with a warning;
8. writing `vX.Y.Z` to `.deploy-commit` (instead of the hash) and removing old images `ghcr.io/fkula5/ref-clips` — the 3 newest
   are kept, plus the current and the previous one (the local image `ref-clips:local` and other images are untouched; no `prune`).

Exit codes (visible in the run summary): 0 ok · 1 error before changes (no image, failed check…) · 2 disallowed command ·
3 something was running for 2 hours · 4 the new version did not start, previous one restored · 5 did not start and the
rollback failed · 255 ssh connection error.

**Database migrations and rollback.** Migrations (`init` on start) run when the new version starts and **are not reversed**
when rolling back to an older image. An older image therefore must run on a newer schema, so migrations must be
*additive* (new tables and columns that allow `NULL` or have a default value; deleting and renaming columns only in a later
release, after no working version uses them). A destructive migration or one that changes the meaning of data requires a
backup (`sudo /opt/ref-clips/deploy/backup.sh`) before merging the release PR, and a deliberate rollback with restoring the
database (`deploy/restore.md`).

## One-time steps after the merge (manual)

Order: do steps 1–6 **before** merging this branch, and step 7 **after** it (a workflow run manually must first reach
`main`). If `release.yml` ran before steps 3–4, its run will end with an error — it is enough to run it again afterwards.
The first PR (the one with the pipeline) is also the first test of `ci.yml`; the names `unit` and `e2e` will appear in the
list of required checks only after the first run.
Below, `fkula5/ref-clips` is the repository, and `57.131.162.204` / `ubuntu` are the server and the user from `docs/wdrozenie.md`.

### 1. A separate CI key (not `ref_clips_deploy`)

On your own computer (without a passphrase on the key — CI has no way to enter it):

```bash
ssh-keygen -t ed25519 -N '' -C ref-clips-ci -f ~/.ssh/ref_clips_ci
cat ~/.ssh/ref_clips_ci.pub        # jedna linia „ssh-ed25519 AAAA… ref-clips-ci” — przyda się w kroku 2
```

### 2. Server: the input script and the forced command

The script `deploy/ci-entry.sh` is installed as a root file **outside** `/opt/ref-clips`. From the computer, from the
repository (after reviewing the script), with your existing key:

```bash
scp -i ~/.ssh/ref_clips_deploy deploy/ci-entry.sh ubuntu@57.131.162.204:/tmp/ref-clips-ci-entry.sh
ssh -i ~/.ssh/ref_clips_deploy ubuntu@57.131.162.204 \
  'sudo install -o root -g root -m 755 /tmp/ref-clips-ci-entry.sh /usr/local/bin/ref-clips-ci-entry && rm /tmp/ref-clips-ci-entry.sh && ls -l /usr/local/bin/ref-clips-ci-entry'
```

On the server (logged in as usual) append the public key to `~ubuntu/.ssh/authorized_keys` **with the forced command**
(paste your line from step 1 after `restrict `):

```bash
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
echo 'command="/usr/local/bin/ref-clips-ci-entry",restrict ssh-ed25519 AAAA…TWÓJ_KLUCZ… ref-clips-ci' >> ~/.ssh/authorized_keys
```

The server needs `curl`, `tar` and `flock` (they are present on Ubuntu 24.04). A check **from the computer** (the CI key
should give only `status`):

```bash
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204 status     # wersja i stan usług
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204 'id'       # ma być: Niedozwolone polecenie…
ssh -i ~/.ssh/ref_clips_ci -o IdentitiesOnly=yes ubuntu@57.131.162.204            # bez polecenia też odmowa (kod 2), bez powłoki
```

After changes to `deploy/ci-entry.sh` in the repository, install it again with the same `install` command (after reviewing
the changes) — the deployment does not do this by itself, and in case of a difference it prints a reminder. To revoke
access: remove the `ref-clips-ci` line from `authorized_keys`.

### 3. GitHub: the `production` environment, secret and variables

The environment must exist before you set its secrets:

```bash
gh api --method PUT repos/fkula5/ref-clips/environments/production
gh secret set DEPLOY_SSH_KEY --env production --repo fkula5/ref-clips < ~/.ssh/ref_clips_ci
gh variable set DEPLOY_HOST --env production --repo fkula5/ref-clips --body 57.131.162.204
gh variable set DEPLOY_USER --env production --repo fkula5/ref-clips --body ubuntu
```

`DEPLOY_HOST` must be exactly the address that is in `deploy/known_hosts` (here: the IP). The key goes from the file to
standard input, nothing is displayed. After uploading you may delete the local private key file (`shred -u ~/.ssh/ref_clips_ci`;
if needed, generate a new one and replace the entry on the server).
In the interface (Settings → Environments → production) also set **Deployment branches and tags → Selected branches → `main`**;
optionally **Required reviewers** (then each deployment needs approval with a button — it increases safety, but removes
the automation).

### 4. Allowing Actions to create PRs

Without this, release-please will not open a release PR. Settings → Actions → General → Workflow permissions →
tick **Allow GitHub Actions to create and approve pull requests** (the default permissions may stay "Read", the jobs
declare their own). The same with a command:

```bash
gh api --method PUT repos/fkula5/ref-clips/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
```

### 5. First PR and CI test

Open a PR from `ci/release-pipeline` to `main` and check that `unit` and `e2e` run and pass. Only then are the names
available to choose in the `main` protection.

### 6. Protection of `main`

Settings → Rules → Rulesets → New branch ruleset (or the classic branch protection), target: `main`:

- **Require a pull request before merging** (0 approvals — you are the only author; you merge the release PR yourself);
- **Require status checks to pass**: add exactly `unit` and `e2e`, source **Any source** (do not pin it to "GitHub Actions" —
  the status of the release PR comes from outside the workflow checks, see above);
- **Block force pushes** and **Restrict deletions**; do not add bypass exceptions unless necessary.

### 7. After the merge: a trial on `v1.1.0`, GHCR package visibility, the first release

Packages created by the workflow inherit the repository's permissions, but **not its visibility** — a new package is private,
and the server (without logging in to GHCR) will not pull the image. After this branch is merged, release-please will open
a PR "chore: release v1.2.0" (since `v1.1.0` there is a `feat(app)`) — **do not merge it yet**. First a "dress rehearsal"
on a version that already runs: Actions → **Release** → Run workflow → tag `v1.1.0` (the same: `gh workflow run release.yml -f tag=v1.1.0`).
The `build` job will build that version's image and create the package, and `deploy` will end with the error
„nie udało się pobrać obrazu” ("could not pull the image") (code 1, nothing on the server changed). Then:

1. GitHub → profile `fkula5` → Packages → `ref-clips` → Package settings → Danger Zone → **Change visibility → Public**
   (this cannot be done through the workflow);
2. check that the image pulls anonymously (e.g. on the server: `docker logout ghcr.io; docker pull ghcr.io/fkula5/ref-clips:v1.1.0`);
3. run the same workflow again (`v1.1.0`) — the deployment switches the server from the local image to the GHCR image
   (a short break for the restart, but only when nothing is running); check it in the step log, with `status` and `/health`;
4. only now merge the PR "chore: release v1.2.0" (after green tests; check that its commit has the `unit` and `e2e` statuses) —
   the workflow will build the image itself and deploy `v1.2.0`.

If you prefer to keep the package private: on the server run `docker login ghcr.io` with a classic token with the
`read:packages` permission (this is an extra secret on the server, so we recommend a public package — the image contains
no secrets).

## Retrying a deployment and rolling back to an older version

Actions → **Release** → **Run workflow** (branch `main`) → the field `tag`, e.g. `v1.1.0`; from the command line:

```bash
gh workflow run release.yml -f tag=v1.1.0
gh run watch                       # podgląd
```

The workflow checks the tag format (`^v\d+\.\d+\.\d+$`) and whether it exists, builds the image only if it is not yet in GHCR,
and then deploys it the same way as a fresh release (waiting up to 2 h for a free server). This is how you retry a deployment
after an error (e.g. code 3 after two hours) and how you roll back to an older version — remembering the note about
migrations above. Old images stay on the server only for the 3 latest versions; the server will pull the rest from GHCR
(images in GHCR are not deleted).

As an emergency, when GitHub is unavailable, on the server (the image must still be local; check with
`docker image ls ghcr.io/fkula5/ref-clips`):

```bash
cd /opt/ref-clips
nano .env                          # zmień jedną linię REFCLIPS_IMAGE=ghcr.io/fkula5/ref-clips:vX.Y.Z
COMPOSE_FILE=compose.yaml:compose.prod.yaml docker compose up -d --no-build --wait
```

or build the current code on the server from the computer: `deploy/deploy.sh` (see below).

## Emergency exit: `deploy/deploy.sh`

The script still sends the commit from the computer and builds the image on the server. Since `.env` may have
`REFCLIPS_IMAGE` from GHCR, during the deployment the script **forces `REFCLIPS_IMAGE=ref-clips:local`** (an image built
on the server does not pose as a GHCR tag), and just before the restart writes this value to `.env`, so that
`deploy/backup.sh` uses the same image as the running stack. The next deployment from GitHub will replace this line with the
GHCR tag. The "something is running" lock (`--wait`, `--force`) works as before; both paths use the same `.deploy.lock`
lock, so they will not overlap.
Note: `deploy.sh` writes the commit hash to `.deploy-commit`, deployments from GitHub write the version number.

## Files

| File | Role |
|---|---|
| `.github/workflows/ci.yml` | tests `unit` and `e2e` on PRs to `main`, and manually |
| `.github/workflows/release.yml` | release-please, image build, deployment; manual retry/rollback (`tag`) |
| `release-please-config.json`, `.release-please-manifest.json`, `version.txt`, `CHANGELOG.md` | configuration and version state (start: 1.1.0, tag without a component: `v1.2.3`) |
| `deploy/ci-entry.sh` | forced command of the CI key on the server (`deploy vX.Y.Z`, `status`) |
| `deploy/known_hosts` | pinned host key of the server for `ssh` from Actions |
| `deploy/deploy.sh` | emergency deployment (build on the server) |
| `tests/test_ci_entry.py` | test of `ci-entry.sh` with stubbed `docker` and `curl` |

Actions from other authors are pinned to full SHAs (a comment next to each gives the version); update them consciously.
Images in GHCR and releases on GitHub have no automatic cleanup.
