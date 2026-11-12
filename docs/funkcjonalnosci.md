# ref-clips: feature catalogue (MVP)

> Draft version 0.1, 2026-10-29. This document is used to design the MVP from scratch: each feature can be kept, changed or dropped.
> The **Status** column describes what already works in the current prototype (stage 1). It does not decide what goes into the MVP.

## 1. Product purpose

A tool for basketball referees and coaches for **analysing referee decisions in match recordings**:
- quick marking of situations in the recording (with and without a whistle),
- automatic cutting of clips around those situations,
- description, rating and discussion of a clip,
- eventually a shared library of training clips for the referee group.

**What the product does not do:** it does not judge decisions by itself. Automation may at most *suggest* moments (e.g. a whistle); a human always rates the decision.

## 2. Users and roles

| Role | Who it is | What it does |
|---|---|---|
| **Referee** | member of a training group | uploads matches, marks and describes their own situations, responds to comments, browses the library |
| **Coach** | observer / instructor | points out situations to describe, rates, comments, publishes clips to the library |
| **Admin** | group leader | manages accounts, dictionaries (tags, league levels), settings |

Referee functions in a match crew: **CC** (first referee), **U1** (second), **U2** (optional third).

## 3. Glossary

- **Match:** date, teams (name + kit colour), league level, crew (CC/U1/U2).
- **Recording:** a video file assigned to a match. A match may have several recordings, e.g. separate quarters or different cameras.
- **Proxy:** a copy of the recording converted to a format that is convenient in the browser (H.264/AAC MP4, max 720p, a keyframe every 1 s). The original stays unchanged.
- **Period marker:** the moment in the recording where Q1–Q4 or overtime starts. The quarter of each decision is calculated from these markers, without reading the clock from the image.
- **Decision (clip):** a situation at a specific moment of the recording. It has a referee, tags, a description, a rating and a clip file (default ±10 s).
- **Note:** a line of text in the format `time referee description`, e.g. `2:54 Filip PTS`, from which a decision is created.
- **Tag:** a category of situation (PTS, block/charge, travel, out of bounds, no whistle…) with aliases in the dictionary.
- **Rating:** correct / incorrect / doubtful / to be discussed.

## 4. Features

Status legend: ✅ is in the prototype · 🔧 is there, but needs changes · ⬜ missing.
Priority: **M** = must be in the MVP · **S** = worth having · **P** = later (outside the MVP). The priority column is filled in together.

### 4.1 Matches

| ID | Feature | Status | Priority |
|---|---|---|---|
| M-01 | Creating a match: date, level, teams (name + colour) | ✅ | |
| M-02 | Crew of the match with functions CC / U1 / U2, default assignment by order | 🔧 currently „R” and „U” | |
| M-03 | Editing and deleting a match (with its recordings and clips) | ✅ | |
| M-04 | Match list on the home page | ✅ | |
| M-05 | Dictionary of referees (people repeatedly chosen for crews) | ✅ (created automatically) | |
| M-06 | Dictionary of league levels (a list instead of free text) | ⬜ | |
| M-07 | Match scoresheet („Protokół”): on the match page, up to 10 files per match (PDF, JPEG, PNG, WebP, HEIC/HEIF; 20 MB each; type checked by the file's magic bytes). Uploaded from a phone too (camera or photos); the crew's referees, coaches and admins upload and delete (with confirmation), every logged-in user views and downloads. Images show as thumbnails, PDF opens in a new tab, HEIC is a download tile. The match list marks matches that have one; deleting the match deletes the files. Not in public share links or training sets. Details: `docs/match-scoresheet.md` | ✅ | |

### 4.2 Recordings

| ID | Feature | Status | Priority |
|---|---|---|---|
| N-01 | Uploading a file (also 2–6 GB) with a progress bar, streaming save | ✅ (not tested on large files) | |
| N-02 | Several recordings in one match, with a label (e.g. „Q1–Q2”) and a source (Veo / phone / YouTube / file) | ✅ | |
| N-03 | Automatic conversion to a proxy in the background, with status and progress | ✅ | |
| N-04 | Retrying the conversion after an error | ✅ | |
| N-05 | Choice of proxy quality (720p / 1080p) or cutting clips from the original | ⬜ | |
| N-06 | Downloading a recording from a YouTube link | ⬜ | |
| N-07 | Synchronising several recordings of the same match (e.g. a Veo camera + a phone) | ⬜ | |

### 4.3 Player

| ID | Feature | Status | Priority |
|---|---|---|---|
| O-01 | Playback with seeking (HTTP Range) | ✅ | |
| O-02 | Shortcuts: space, ←/→ ±1 s, Shift ±5 s, `,`/`.` frame by frame | ✅ (not checked in the browser) | |
| O-03 | Speed 0.25×–2× | ✅ | |
| O-04 | `M` adds a decision at the current moment (quick text entry) | ✅ | |
| O-05 | `Q` adds a marker for the next quarter, with the option to edit and delete | ✅ | |
| O-06 | Timeline with markers for quarters and decisions (clicking moves to the moment) | ⬜ | |
| O-07 | Zoom into part of the picture, e.g. for a distant shot from Veo | ⬜ | |
| O-08 | „Oglądaj razem”: a room for one recording with a link for logged-in users and a list of those present (WebSocket, state in memory; a room closes 10 minutes after the last person leaves, a restart drops all rooms) | ✅ | |
| O-09 | The room creator leads (play/pause, seeking, speed, frame steps); the others follow (drift above 0.5 s is corrected, heartbeat every 2 s). The leader can hand control to a participant; a leader who drops keeps the lead for 10 s, then it passes to the longest-present participant | ✅ | |
| O-10 | A follower cannot drive playback (controls and keys disabled, volume stays local) but may „Odłącz” (watch alone) and „Dołącz z powrotem” | ✅ | |
| O-11 | `Z` (and other marker changes) by any participant appear for everyone at once; the marker is created by the normal marker endpoint with that participant as its author | ✅ | |
| O-12 | Safety: session cookie and `Origin` checked at the handshake, random room ids kept out of logs, limits on message size and rate, rooms (30), rooms per user (3) and participants (10); voice happens outside the app | ✅ (not tried over a real network or in Safari) | |

### 4.4 Notes and creating decisions

| ID | Feature | Status | Priority |
|---|---|---|---|
| D-01 | Pasting a block of notes, where one line is one decision | ✅ | |
| D-02 | Time in the formats `m:ss`, `h:mm:ss`, also `2.54` / `2,54` | ✅ | |
| D-03 | Recognising a referee from the crew (regardless of letter case and Polish diacritics) | ✅ | |
| D-04 | Recognising a referee by function (`CC`, `U1`, `U2`) and by diminutives / nicknames | ⬜ | |
| D-05 | Recognising tags and the team from the text | ✅ | |
| D-06 | Preview table with the option to correct before saving, and warnings | ✅ | |
| D-07 | „Cut all”: mass cutting of clips ±10 s | ✅ | |
| D-08 | Default clip margins set per user or per tag | ⬜ | |

### 4.5 Clips

| ID | Feature | Status | Priority |
|---|---|---|---|
| K-01 | Clip list with filters: match, referee, tag, rating, quarter | ✅ | |
| K-02 | Clip page: playback, editing of the description, tags, rating | ✅ | |
| K-03 | Correction of the clip start and end with automatic re-cutting | ✅ | |
| K-04 | Downloading the clip as MP4 with a readable name (`kategoria-rozgrywek_nazwisko_decyzja.mp4`) | ✅ | |
| K-05 | ZIP export: selected clips + `opisy.csv` | ✅ | |
| K-06 | Deleting a clip | ✅ | |
| K-07 | Playlist: a set of clips to discuss (order, title) | ⬜ | |
| K-08 | Link to one or several clips for people **without an account** (`/s/<kod>`): viewing and downloading (MP4 or one ZIP), validity 1/7/30 days, revoking, list of links and visit count at the clip | ✅ | |

**K-08, details.** Created by: the administrator, the coach and the marker's author (`Clip.author_id`); selection in the clip list
(`/clips`, the match tab) or a button on the clip page. If the selection contains a clip that is not allowed or not cut, the whole
form returns an error and nothing is created. A link holds at most 30 clips. Revoked by the link's creator or the administrator.
The full address is visible **once**, right after creation (afterwards only a hash of the code is in the database). The public page
shows only the video, the league and the decision category — without surnames, teams, date, descriptions, ratings, comments and
app navigation; the file name is `liga_decyzja.mp4` (e.g. `III-liga_blok-szarza.mp4`), and in the ZIP repeats get `_2`, `_3`.
Logged-in users still download clips with the referee's surname. The recipient of a link may pass it on, and revoking does not
undo files that were already downloaded. Note: text typed manually as the „własna” (custom) category and the match's „liga” (league)
field are public.

### 4.6 Comments and rating

| ID | Feature | Status | Priority |
|---|---|---|---|
| C-01 | Clip comments with replies (threads) | ✅ | |
| C-02 | A comment pinned to a second of the clip (clicking moves to the moment) | ✅ | |
| C-03 | Drawing on a still frame (arrows, lines, positions) attached to a comment | ⬜ | |
| C-04 | A coach's rating separate from the referee's self-assessment | ⬜ | |
| C-05 | A reference to the FIBA rule / interpretation for a clip | ⬜ | |
| C-06 | Qualifier assessment sheet: a descriptive assessment of the match crew (a comment on each item for each referee, overall assessment and recommendation, a note about the pair), draft and publication, printing to PDF; items editable in the admin panel. Details: `docs/arkusz-kwalifikatora.md` | ✅ | |

### 4.7 Dictionaries and settings

| ID | Feature | Status | Priority |
|---|---|---|---|
| S-01 | Tag dictionary with aliases, editable | ✅ | |
| S-02 | Meaning of abbreviations in the dictionary (e.g. what exactly „PTS” means) | ⬜ | |

### 4.8 Group work (stage 2)

| ID | Feature | Status | Priority |
|---|---|---|---|
| G-01 | Accounts, login, invitations from the admin | ⬜ (data model ready) | |
| G-02 | Roles referee / coach / admin and permissions | ⬜ | |
| G-03 | Clip visibility: private / group / library | ⬜ (the field exists in the database) | |
| G-04 | Tasks from the coach („describe the situation at 3:17”) and the referee's task list | ⬜ | |
| G-05 | In-app notifications (bell with the unread count, list at `/notifications`): new or changed rating and new comment on a clip, new comment on a match, first publication of an assessment sheet; to the crew, the clip author or match creator and earlier commenters, never to the actor; read ones vanish after 30 days, unread after 90; no e-mail, no tasks yet | ✅ | |
| G-06 | Training library: search by tags, model rating, option to hide surnames | ⬜ | |
| G-07 | Training groups (`/groups`): a coach or admin creates a group (name, description) and adds existing referee accounts and other coaches; the group page shows each referee's activity for 7/14/30/90 days (recordings, markers, described clips, last activity; no activity is flagged in text), the „Do oceny” queue (described clips from the group's matches not yet rated by me) and removal of referees; „Grupa” filter on the match and clip lists; a referee sees only their groups and coaches; adding a person sends a notification. Groups never restrict access. Details: `docs/training-groups.md` | ✅ | |
| G-08 | Training sets (`/sets`): a coach or admin creates a set (name, description), adds cut clips from the clip page („Dodaj do zestawu”, a clip at most once), writes their own note for each clip, orders them with ▲/▼, removes them and pins the set to training groups (highlighted on the group page and in the group list); any coach or admin edits any set, referees and everybody else only view it clip by clip (video, category, description, note, position, „przejdź do klipu”). Referee names are hidden by default (function CC/U1/U2 instead, also in the download file name) unless the set's „Pokaż nazwiska sędziów” is on; no ratings or comments in the set views. Deleting a clip removes it from sets. Details: `docs/training-sets.md` | ✅ | |

### 4.9 Deployment and automation (stage 3)

| ID | Feature | Status | Priority |
|---|---|---|---|
| W-01 | Hosting on a server (Docker, Postgres, S3 file storage) | ⬜ | |
| W-02 | A JSON API next to the pages, for a future frontend or mobile app | ⬜ | |
| W-03 | Whistle suggestions from audio (markers on the timeline) | ⬜ | |
| W-04 | Reading the match clock from the image (OCR) when it is visible | ⬜ | |

## 5. Non-functional requirements

- **Polish-language interface**, readable also for non-technical people.
- **Browsers:** Chrome and Edge on Windows. Ultimately also a phone for viewing and commenting.
- **Video sources:** Veo, phone (including HEVC/.mov from an iPhone), YouTube.
- **Scale (estimate):** ~25 recorded matches per referee per season, 2–6 GB per match.
- **Data:** recordings may show players, including minors. Access to them must be limited to the group (important in stages 2/3, GDPR).

## 6. Architectural decisions (for now)

- The Python backend (FastAPI, SQLAlchemy, ffmpeg) stays permanently.
- Frontend: templates + HTMX. The most interactive elements (timeline, drawing) may be built as separate components (e.g. Svelte/React). A full SPA only when a mobile app is needed.
- At stage 2 we add a JSON API (W-02).

## 7. Open questions for the MVP

1. **Scope of the MVP:** is the MVP a version for one person (stage 1), or should it already include group work (G-01…G-04)?
2. **Who uploads recordings:** each referee themselves, or e.g. only the coach or admin?
3. **„PTS” and other abbreviations:** what is the list of abbreviations used in your group? (for the dictionary S-01/S-02)
4. **Rating:** are four states (correct / incorrect / doubtful / to be discussed) enough? Is a scale, an error category (e.g. position, interpretation, mechanics) or a split into self-assessment and coach assessment (C-04) needed?
5. **Image quality:** is 720p enough for assessment, or is 1080p or cutting from the original needed (N-05)?
6. **Clip margins:** does ±10 s always fit, or does e.g. a foul in a shooting action need more "before"?
7. **Phone:** does the MVP need comfortable viewing and commenting of clips on a phone?
