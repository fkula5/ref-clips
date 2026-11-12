"""Roles add up: one role granting the right is enough. Routes enforce these via `auth.require(...)`;
templates only hide unavailable buttons.
"""
from __future__ import annotations

from collections.abc import Iterable

ADMIN, COACH, REFEREE = "admin", "coach", "referee"


def _has(user, *roles: str) -> bool:
    return user is not None and bool(user.roles & set(roles))


def is_official(user, match) -> bool:
    """Only a slot linked to an account counts."""
    return user is not None and any(o.user_id == user.id for o in match.officials)


def _staff_or_official(user, match) -> bool:
    return _has(user, ADMIN, COACH) or (_has(user, REFEREE) and is_official(user, match))


def can_manage_users(user) -> bool:
    return _has(user, ADMIN)


def can_manage_categories(user) -> bool:
    return _has(user, ADMIN)


def can_manage_sheet_elements(user) -> bool:
    return _has(user, ADMIN)


def can_manage_retention(user) -> bool:
    return _has(user, ADMIN)


def can_view(user) -> bool:
    return user is not None and bool(user.is_active)


def can_comment(user) -> bool:
    return can_view(user)


def can_edit_comment(user, comment) -> bool:
    return can_view(user) and comment.author_id == user.id


def can_delete_comment(user, comment) -> bool:
    return can_view(user) and (_has(user, ADMIN) or comment.author_id == user.id)


def can_create_match(user) -> bool:
    return _has(user, ADMIN, COACH, REFEREE)


def can_save_match(user, official_user_ids: Iterable[int | None]) -> bool:
    if not can_create_match(user):
        return False
    if _has(user, ADMIN, COACH):
        return True
    return user.id in set(official_user_ids)


def can_upload_to_match(user, match) -> bool:
    return _staff_or_official(user, match)


def can_edit_match(user, match) -> bool:
    return _has(user, ADMIN) or (_has(user, COACH, REFEREE) and match.created_by == user.id)


def can_delete_match(user, match) -> bool:
    """A published sheet goes with the match, so only an admin may remove such a match; otherwise a
    referee who created it could erase the assessment of their own work.
    """
    if _has(user, ADMIN):
        return True
    return can_edit_match(user, match) and not any(sheet.is_published for sheet in match.sheets)


def can_delete_video(user, video) -> bool:
    if _has(user, ADMIN):
        return True
    return _has(user, COACH, REFEREE) and user.id in (video.created_by, video.match.created_by)


def can_manage_clips(user, match) -> bool:
    return _staff_or_official(user, match)


def can_describe_clip(user, clip) -> bool:
    return can_manage_clips(user, clip.match)


def can_delete_clip(user, clip) -> bool:
    return _has(user, ADMIN) or (_has(user, COACH, REFEREE) and clip.author_id == user.id)


def can_share_clip(user, clip) -> bool:
    return can_view(user) and (_has(user, ADMIN, COACH) or (_has(user, REFEREE) and clip.author_id == user.id))


def can_revoke_share(user, link) -> bool:
    return can_view(user) and (_has(user, ADMIN) or link.created_by == user.id)


def can_rate(user) -> bool:
    """Coach role only (the admin role alone is not enough)."""
    return _has(user, COACH)


def can_edit_rating(user, rating) -> bool:
    return _has(user, ADMIN) or (_has(user, COACH) and rating.coach_id == user.id)


def can_delete_rating(user, rating) -> bool:
    return can_edit_rating(user, rating)


def can_create_sheet(user) -> bool:
    """Coach role only (the admin role alone is not enough, as with ratings).
    One sheet per (match, coach) is enforced by the database; opening it again edits the existing
    one.
    """
    return _has(user, COACH)


def can_edit_sheet(user, sheet) -> bool:
    return can_view(user) and sheet.coach_id == user.id


def can_publish_sheet(user, sheet) -> bool:
    return can_edit_sheet(user, sheet)


def can_delete_sheet(user, sheet) -> bool:
    return can_view(user) and (_has(user, ADMIN) or (sheet.coach_id == user.id and sheet.status == "draft"))


def can_view_sheet(user, sheet) -> bool:
    """Everybody else (including a referee outside the crew) must not learn it exists."""
    if not can_view(user):
        return False
    if sheet.coach_id == user.id:
        return True
    return sheet.status == "published" and (_has(user, ADMIN, COACH) or is_official(user, sheet.match))


def can_view_notification(user, notification) -> bool:
    """Somebody else's notification is answered with 404, so its existence is not revealed."""
    return can_view(user) and notification.recipient_id == user.id


def is_group_coach(user, group) -> bool:
    return user is not None and any(m.user_id == user.id and m.role == "coach" for m in group.members)


def can_create_group(user) -> bool:
    return can_view(user) and _has(user, ADMIN, COACH)


def can_see_my_groups(user) -> bool:
    return can_view(user)


def can_view_group(user, group) -> bool:
    """Everybody else gets 404, so a group's referee list is not revealed to a coach who does not lead it."""
    return can_view(user) and (_has(user, ADMIN) or is_group_coach(user, group))


def can_manage_group(user, group) -> bool:
    return can_view_group(user, group)


def can_edit_set(user) -> bool:
    """Every coach and admin may edit every set, so the check does not look at the set."""
    return can_view(user) and _has(user, ADMIN, COACH)
