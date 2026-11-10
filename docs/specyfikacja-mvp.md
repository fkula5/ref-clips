# Tool for cutting match clips for basketball referees

> Specification for Claude Code. **We build only the MVP** (section 1). The other sections describe the target vision — treat them as context, not as scope of work.
> Version 0.3, 2026-11-01. Takes into account the decisions from the specification review.

## 0. Context

A web application in which basketball referees and coaches upload match recordings and mark moments for analysis (decisions, situations without a whistle, referees' movement), and the tool automatically cuts clips from them for analysis, commenting and rating.

**Problem:** after a match someone reviews 1.5–2 h of recording, writes down the times on paper and cuts out fragments by hand in a general video editor. This takes hours, and the clips end up in folders without descriptions.

**Assumptions:**
- For our own use, for referees of one district (dozens of users, not thousands)
- Free — no payments and no subscriptions
- Online only — no offline mode
- Interface in Polish
- Recordings come from any source (a referee's phone, a Veo camera, etc.) — always as a file uploaded to the system (MP4, MOV); files may be large (several GB)
- A prototype `ref-clips` exists (FastAPI + SQLite + ffmpeg, without login): conversion of recordings, quarter markers, notes parser, clip cutting, video streaming. The technical plan is to justify whether we develop it further or replace it.

## 1. MVP – scope to build

### Happy path

1. The user logs in to the platform.
2. Uploads a match, enters the referee crew (CC, U1, optionally U2) and optionally pastes notes with the moments to cut.
3. If the file contains more than one quarter, sets the quarter-start markers.
4. Watches the match and marks subsequent moments (without interrupting the viewing). Describes them later, in one place.
5. From each marker a clip of 30 s is created: 15 s before and 15 s after.
6. The clips of the match appear under the recording or in a separate tab. Each has a description: referee, category, quarter and time since the start of the quarter.
7. After opening a clip one sees its description, comments and coaches' ratings.

### Roles and permissions

A user may have **several roles at once** (e.g. administrator + coach). Permissions add up.

| Permission | Administrator | Coach | Referee |
| --- | --- | --- | --- |
| Managing accounts and assigning roles | Yes | No | No |
| Managing the category dictionary | Yes | No | No |
| Viewing all matches and clips | Yes | Yes | Yes |
| Uploading matches and entering the crew | Yes | Yes | Yes, only matches in which they were in the crew |
| Creating and describing clips | Yes, every match | Yes, every match | Only matches in which they were in the crew |
| Rating a clip | No (unless they also have the coach role) | Yes, each their own | No |
| Commenting on matches and clips | Yes | Yes | Yes |
| Editing and deleting | Everything | Own matches, clips, ratings, comments | Own matches, clips, comments |

**Visibility in the MVP:** every logged-in user sees all matches and clips. Visibility restrictions ("scopes") are outside the MVP.

### Referee crew

- Functions: **CC** (first referee), **U1** (second), **U2** (third, optional).
- Each crew position is filled by **choosing a user** from a list or by **typing a first and last name** (a referee without an account). The "was in the crew" permission works only for positions linked to an account.
- The referee who uploads a match must be in its crew. The form inserts them automatically into the first free position, and they may change the function.

### Uploading a match

- A match is uploaded as a whole (one file) or split into quarters (separate files).
- When uploading, the user states what the file contains: the whole match, one quarter (which one) or several quarters (which ones).
- Match data: date, league, teams (name + kit colour), referee crew.
- **Notes on upload (optional):** a text field, one line is one moment, e.g. `2:54 Filip PTS`, `3:17 U1 dlaczego nie blok?`.
  - The time means the **recording time** in the format `m:ss` / `h:mm:ss`; `2.54` and `2,54` are allowed.
  - The referee is recognised by first name, last name or function (CC/U1/U2), regardless of letter case and Polish diacritics.
  - The category is recognised from the dictionary and its aliases. The rest of the line goes into the description.
  - Before saving, the user sees a preview table with warnings and can correct it.
  - Markers are created from the notes, and clips from them once the recording is ready.
- **Quarter markers:** if the file contains more than one quarter, after uploading the user sets the start of each quarter. Until then, the clips from this file have the "nieustalona" („undetermined”) quarter and cannot be described. Cutting may already start.
  - A file with one quarter: the start marker is optional, default 0:00. It can be moved, e.g. when there is a warm-up at the beginning of the recording.

### Player and markers

- A video player with seeking, slow motion (0.25×–2×), frame-by-frame stepping and keyboard shortcuts.
- The „Zaznacz” ("Mark") button / key adds a marker at the current recording time **without stopping playback**.
- Markers are visible in a list next to the player (time, quarter). Clicking moves to the moment, and a marker can be deleted.
- Describing happens **after watching**: a list of undescribed markers, with a clip preview and the description fields beside each.

### Clips

- From each marker a clip of 30 s is created: 15 s before and 15 s after (trimmed to the recording boundaries).
- Clip description:
  - **referee** from the crew of the match the situation concerns (a choice of CC/U1/U2) or "whole team" („cały zespół”),
  - **category** from the dictionary (list below) or "custom" („własna”) with a short name typed in by hand,
  - **quarter and time since the start of the quarter in the recording**, calculated automatically from the quarter markers. The interface labels it directly, e.g. „Q2 · 4:12 od początku kwarty (czas nagrania)” ("Q2 · 4:12 since the start of the quarter (recording time)"). **This is not the match clock.**
  - an optional text description.
- Starting dictionary of categories (editable by the administrator, with aliases for recognition in notes):
  - **Fouls:** personal, in a shooting action, block / charge, unsportsmanlike, technical, disqualifying.
  - **Violations:** travelling, double dribble, 3 s, 5 s, 8 s, 24 s, out of bounds, goaltending / interference.
  - **No whistle:** no whistle (there should have been one), whistle not needed.
  - **Mechanics:** position / movement, rotation, teamwork, signalling.
  - **Other:** other, custom.
- Clip list of the match under the recording or in a separate tab, with filters by referee, category and quarter.
- Clip view: player, description, coaches' ratings, user comments.

### Coach rating

- Each coach may give **their own** rating of a clip: correct / incorrect / debatable, plus a comment.
- The rating may be changed or deleted by its author or the administrator. The clip shows all ratings with their authors.

### Comments

- Every logged-in user may comment on a match and on every clip.
- The author may edit and delete their own comment. The administrator may delete any comment.

### Data retention

- The original file is deleted after a successful conversion to a proxy. Only the proxy stays.
- The proxy of a full match is deleted after **N days** from the upload. N is set by the administrator, default 30. Clips stay permanently.
- Before deletion the match is marked in the interface ("full recording available for X more days"). After deletion no new markers can be added.
- The administrator sees disk usage and can delete a full recording earlier, manually.

## 2. Non-functional requirements

- A desktop browser. Viewing clips and commenting comfortable also on a phone.
- Smooth seeking through recordings of up to 2 h. Uploading large files robust against interruption (resume from where it stopped).
- GDPR: the recordings contain the image of players, including minors. Access only for logged-in users; data stored in the EU.
- Login with an account; roles and permissions checked on the server side.
- Accounts are created by the administrator (no public registration).
- **Starting infrastructure:** a VPS with 2 vCPU, 4 GB RAM, 40 GB disk, in the EU. The solution must fit on it, including the conversion queue (one job at a time) and retention. It must also be possible later to move the files to object storage (S3) without a rebuild.

## 3. Outside the MVP scope (vision for later)

- **Version 2:**
  - manual correction of clip boundaries, drawing on a still frame,
  - a clip library with search (category, referee, league, rating, date), training sets,
  - several camera angles of the same match,
  - sharing by link with a validity date, exporting clips,
  - visibility scopes for roles and matches.
- **Version 3:** referee statistics, PDF reports, a mobile app, integration with the match crew system.

## 4. To be decided in the technical plan

Propose and justify before writing code:
- Technology stack (frontend, backend, database), taking the `ref-clips` prototype into account
- Storage of video files with a 40 GB disk and the retention from section 1; upload robust against interruption
- Cutting clips: when full recordings are deleted, the clips must exist as separate files. Justify the cutting method and its quality.
- Login and account management (accounts created by the administrator)
- Deployment on the given VPS: database backups, HTTPS, updates

## 5. MVP acceptance criteria

- A 4 GB file uploads to the end despite a connection drop halfway through.
- After uploading a file with two quarters and setting the markers, every clip has a correct quarter and time since the start of the quarter.
- Notes pasted during the upload create clips at the given moments, and unrecognised lines are shown with a warning.
- A clip is 30 s long (shorter only at the recording boundary) and plays in Chrome on a computer and in Safari/Chrome on a phone.
- A referee outside the crew cannot create clips from a match. The server rejects such a request, also one sent bypassing the interface.
- After the retention period the full recording disappears from disk, and its clips still play.
