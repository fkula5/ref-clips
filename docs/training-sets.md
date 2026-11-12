# Training sets: user stories

Status: implemented on branch `feat/training-sets` (migration `mvp0009`, which only adds tables). Where the build differs from the stories below, the notes under „Implementation notes” apply.

## Purpose

A coach collects curated clips on one theme (e.g. „Akcja rzutowa (AOS)”, „Blok / szarża”) into a set, writes a training note for each clip and shows the set to referees. The referee watches the clips one by one without seeing who made the decision, so the discussion is about the play and not the person.

## Rules

- Every coach and every admin can edit every set. Referees only view.
- Every logged-in user sees every set. Sets never restrict access to matches or clips.
- Referee names are hidden in a set's views by default; a set setting switches them on.
- A set only collects clips. It never changes a clip: the clip's own description stays as it is, and the coach's note belongs to the set.

## User stories

Suggested UI labels are given in Polish, in quotes, e.g. „Zestawy” („Sets”).

### TS-01 Create and edit a set

As a coach or admin, I create a set with a name and a description, and I can edit them.

- The „Zestawy” page has a „Nowy zestaw” button for coaches and admins; referees do not see it.
- The name is required (up to 100 characters); the description is optional (up to 1000).
- Any coach or admin can edit or delete any set, not only the one who created it. Deleting a set removes the set, its order, notes and pins; clips are not touched.

### TS-02 Add a clip to a set

As a coach or admin, I add a clip to a set from the clip page, choosing an existing set or creating a new one.

- The „Dodaj do zestawu” card on the clip page offers the existing sets or a field for the name of a new one (not both at once).
- Only a clip that is already cut (status „wycięty” and the file exists) can be added.
- A clip is in a set at most once; sets that already hold the clip are marked and cannot be chosen again.
- The card lists the sets the clip is already in.

### TS-03 Training note per clip

As a coach or admin, I write my own note for each clip in a set.

- The note is edited under the clip in the set view (up to 5000 characters, like comments).
- The clip's original description is never changed.

### TS-04 Order and remove clips

As a coach or admin, I set the order of the clips with ▲ / ▼ buttons and remove a clip from the set.

- Removing a clip from a set does not delete the clip.

### TS-05 Pin a set to training groups

As a coach or admin, I pin a set to one or more training groups.

- A pinned set is highlighted on the group's page („Zestawy szkoleniowe tej grupy”, visible to the group's coaches and admins) and listed in the „Zestawy” column of the „Grupy” page, which a referee member sees too.
- Any group can be chosen, also one the coach does not lead (every group's name is already visible in the list filters).
- Unpinning is available on the set's page. Deleting a group removes its pins only.

### TS-06 List of sets

As any logged-in user, I open „Zestawy” and see all sets with their clip counts and pinned groups.

- The list is sorted by name and paginated with the same pager as the other lists (25 per page).

### TS-07 View a set clip by clip

As any logged-in user, I watch the clips of a set one after another.

- The set's page shows an overview list of its clips (match, crew function, category, note) and a button to start from the first clip.
- The clip view shows the video, category, the original description, the coach's note, the position („3 / 8”), „‹ poprzedni” / „następny ›” and a „przejdź do klipu” link to the full clip page.
- The match (date, level, teams) stays visible.

### TS-08 Hidden names

As a coach, I want referee names hidden by default, so that a set can be shown to the whole group.

- The set views show the crew function (CC, U1, U2) or „cały zespół” instead of the name.
- The set has a „Pokaż nazwiska sędziów” setting (default off) that coaches and admins switch on in the set's edit form; it applies to everybody who views the set.
- The set views show no ratings or comments of the clip, because they would reveal names.
- Downloading a clip from the set view with names hidden gives a file name with the function instead of the surname (`II-liga_CC_blok-szarza.mp4`); with names shown it is the usual `II-liga_Kowalski_blok-szarza.mp4`. Downloads outside the set views are unchanged.

### TS-09 Deleted clips

When a clip is deleted (also together with its match), it disappears from every set; the set itself remains.

## Out of scope / later

- „Test yourself” mode: watch, choose a decision, then reveal the verdict (see TODO).
- Sharing a set with a link without an account (see TODO).
- Drag and drop ordering, moving a clip to a position directly.
- Unique set names.

## Implementation notes

- Tables (migration `mvp0009`): `training_sets` (name, description, `show_names`, creator), `training_set_clips` (primary key `(set_id, clip_id)`, which is the „at most once” rule; `position` from 1; `note`) and `training_set_groups` (primary key `(set_id, group_id)`). The clip and the set rows cascade on delete, as does the group row; the creator is set to NULL when the account goes.
- Routes are under `/sets` (`app/routers/training_sets.py`), the clip page posts to `/clips/{id}/sets`. Reading needs only a login; every mutating route requires the coach or admin role (`permissions.can_edit_set`), so a referee gets 403. Forms carry the CSRF token like the rest of the app.
- A clip is addressed in a set by its clip id (`/sets/{set}/clips/{clip}`), so reordering never breaks a link. Positions are renumbered from 1 after every move or removal.
- The hidden-names rule is applied in the templates through one helper (`training_sets.official_text`) and in the download route (`services.clip_filename(..., function_only=True)`). It hides the crew names only: the clip's description and the coach's note are shown as written, and the „przejdź do klipu” link opens the ordinary clip page, which shows names, ratings and comments to every logged-in user as before.
- A clip that is being cut again after it was added stays in the set; its video is replaced by a notice until the new file is ready.
- Duplicate set names are allowed.
