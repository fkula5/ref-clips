# Training groups: user stories

Status: implemented in the next release (branch `feat/training-groups`, migration `mvp0008`). Where the build differs from the stories below, the notes under „Implementation notes” apply.

## Purpose

A coach works with a specific set of referees and needs one place to see them, their activity and their clips. A training group gathers those referees under a coach, so the coach can see their activity over a chosen period, find clips that are waiting for a rating, and filter the match and clip lists by group. Referees see which groups they belong to and who leads them.

## Rules

- Members are accounts only. No names are typed in from a match crew. Referees join as members; coaches join as the group's coaches.
- A group is managed by its coaches and by admins.
- Groups only organise views. They do not restrict access: every logged-in user still sees all matches and clips.
- The activity period defaults to the last 14 days and can be changed on the group page.
- Activity means: an uploaded recording, added markers, described clips.

## User stories

Suggested UI labels are given in Polish, in quotes, e.g. „Grupy” („Groups”).

### TG-01 Create and edit a group

As a coach or admin, I create a group with a name and description, and I can edit them.

- The „Grupy” page has a „Nowa grupa” button for coaches and admins; referees do not see it.
- The name is required; the description is optional.
- The user who creates the group becomes its coach.
- The group's coaches and admins can change the name and description; a referee who is only a member cannot.

### TG-02 Add and remove referees

As a coach of the group, I add referees to the group and remove them.

- The coach picks referees from a list of existing referee accounts; a name cannot be typed in.
- A referee already in the group cannot be added twice.
- Removing a referee takes them out of the group only; their matches and clips are not changed.

### TG-03 Add another coach

As a coach of the group, I add another coach to the group.

- The coach picks from existing accounts with the coach role; the new person joins as a coach, not as a member.
- The added coach has the same rights to manage the group as the coach who added them.
- An account that is already a coach of the group cannot be added again.
- Any manager of the group (its coaches and admins) can remove a coach with „Usuń z grupy”, after a confirmation. A group must keep at least one coach: removing the last one is refused with a message, admins included. A coach who removes themself loses access and lands on „Grupy”.
- When no account is left to add, the page shows a hint instead of the picker; admins get a link to the user administration, where the role is granted.

### TG-04 See the referees in my groups

As a coach, I see which referees are in my groups.

- The „Grupy” page lists the groups I coach.
- Opening a group shows its full list of referees and its coaches.
- A coach does not see the referee list of a group they do not coach.

### TG-05 Admin sees and edits all groups

As an admin, I see all groups and can edit any of them.

- The admin's „Grupy” page lists every group, including groups where the admin is not a coach.
- The admin can change the name, description, referees and coaches of any group.
- The admin's changes are visible to the group's coaches in the same way as changes made by a coach.

### TG-06 See referee activity in a group

As a coach, I see the activity of each referee in my group over the chosen period (matches, new clips, undescribed markers, last activity), and referees with no activity in the period are highlighted.

- The group page shows one row per referee with: matches with an uploaded recording, new clips, undescribed markers, and the date of the last activity.
- The period defaults to the last 14 days; the coach can change it on the group page and the table updates to match.
- A referee with no activity in the period is highlighted and labelled as such in text (e.g. „brak aktywności”), not only by colour.
- A referee's activity counts only inside the chosen period, except „last activity”, which is the most recent activity of any date.

### TG-07 See described clips not yet rated by me

As a coach, I see the clips of my group's referees that are described but not yet rated by me.

- The list contains clips whose author is a referee in one of my groups, that have a description, and that I have not rated.
- When I rate a clip, it leaves my list; a rating by another coach does not remove it.
- The list is reachable from the group page (suggested label: „Do oceny”).

### TG-08 Filter matches and clips by group

As a coach, I can filter the match list and the clip list by group, together with the existing filters.

- The match list and the clip list each get a „Grupa” filter next to the existing filters.
- A clip is in the group when its referee is a member; a match is in the group when one of its crew members is a member.
- The group filter combines with the existing filters (all conditions must match) and works with the existing pagination and sorting.
- The filter is available to every logged-in user, because groups do not restrict access.

### TG-09 See my groups and their leaders

As a referee, I see which groups I belong to and who leads them.

- The „Grupy” page lists every group the referee is a member of.
- Each group shows the names of its coaches.
- A referee who is in no group sees an empty-state message instead of an empty table.

### TG-10 Get notified when added to a group

As a referee, I get an in-app notification when I am added to a group.

- When a coach adds me to a group, a notification appears in the app's existing notifications.
- The notification names the group and who added me.
- The notification is created once for each addition, and it is marked as read in the same way as other notifications.

## Out of scope / later

- Archiving a group after a season.
- A per-referee summary (most frequent categories, distribution of ratings).
- Referees leaving a group by themselves (only coaches remove members).
- A referee profile page (see TODO).

## Implementation notes

- A match belongs to a group when any account in its crew is a referee member of the group (typed names in the crew do not count). Clips follow their match; this rule is used by the „Grupa” filters (TG-08) and by „Do oceny” (TG-07), which therefore lists described clips from those matches, not only clips written by a member.
- Only the group's coaches and admins open a group's page, activity table and „Do oceny”; everybody else gets 404. Referees see TG-09 only (`/groups`).
- Activity (TG-06) counts recordings uploaded, recordings are credited to the uploader, markers to the clip's author and described clips to the person who first described them (`Clip.described_by_id`, set together with `described_at`; later edits keep it). Clips described before this was recorded have no describer and are not counted for anyone. The table is computed with three grouped queries. The period is 7, 14, 30 or 90 days (`?days=`, default 14).
- Adding a referee or a coach sends a „group_added” notification to the added person; removing sends nothing. Deleting a group keeps the accounts and removes its notifications.
- An account is in a group once, as a coach or as a referee.
