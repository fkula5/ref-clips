"""A group's page is answered with 404 to anyone who may not see it, so its referee list is not revealed
to coaches who do not lead it. Members who are not coaches only get the list of their own groups.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app import flash, groups, permissions, training_sets
from app.auth import current_user, require
from app.db import get_db
from app.groups import GroupError
from app.models import TrainingGroup, User
from app.pagination import parse_page
from app.web import mark_seen, render

router = APIRouter(prefix="/groups")

NOT_FOUND = "Nie ma takiej grupy"


def group_for(check: Callable[[User, TrainingGroup], bool]):
    """404 when the user may not view the group or it does not exist; 403 only when `check` is stricter
    than viewing.
    """
    def dependency(group_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> TrainingGroup:
        group = db.get(TrainingGroup, group_id)
        if group is None or not permissions.can_view_group(user, group):
            raise HTTPException(404, NOT_FOUND)
        if not check(user, group):
            raise HTTPException(403, "Brak uprawnień do tej operacji")
        return group
    return Depends(dependency)


def group_url(group: TrainingGroup, days: int = groups.DEFAULT_DAYS) -> str:
    return f"/groups/{group.id}" + (f"?days={days}" if days != groups.DEFAULT_DAYS else "")


def render_group(request: Request, db: Session, group: TrainingGroup, days: int, *, status_code: int = 200,
                 error: str | None = None, add_values: dict | None = None):
    return render(
        request, "group_detail.html", status_code=status_code, g=group, days=days, periods=groups.PERIOD_CHOICES,
        rows=groups.activity(db, group, days), review_count=groups.review_count(db, group, request.state.user.id),
        error=error, add_values=add_values or {},
        pinned=training_sets.pinned_sets(db, [group.id]).get(group.id, []),
        referee_options=groups.candidates(db, group, "referee"), coach_options=groups.candidates(db, group, "coach"))


@router.get("")
def group_list(request: Request, db: Session = Depends(get_db),
               user: User = require(permissions.can_see_my_groups)):
    items = groups.groups_of(db, user)
    mark_seen(request, db, group_ids=[g.id for g in items])
    return render(request, "groups.html", items=items,
                  pinned=training_sets.pinned_sets(db, [g.id for g in items]),
                  viewable={g.id for g in items if permissions.can_view_group(user, g)})


@router.get("/new")
def new_group(request: Request, user: User = require(permissions.can_create_group)):
    return render(request, "group_form.html", g=None, values={"name": "", "description": ""}, error=None)


@router.post("")
def create_group(request: Request, db: Session = Depends(get_db),
                 user: User = require(permissions.can_create_group),
                 name: str = Form(""), description: str = Form("")):
    try:
        group = groups.create_group(db, user, name, description)
    except GroupError as exc:
        db.rollback()
        return render(request, "group_form.html", status_code=exc.status_code, g=None, error=str(exc),
                      values={"name": name, "description": description})
    return flash.redirect_with_page_notice(group_url(group), f"Utworzono grupę „{group.name}”.")


@router.get("/{group_id}")
def group_detail(request: Request, db: Session = Depends(get_db),
                 group: TrainingGroup = group_for(permissions.can_view_group), days: str = ""):
    return render_group(request, db, group, groups.parse_days(days))


@router.get("/{group_id}/review")
def group_review(request: Request, db: Session = Depends(get_db),
                 group: TrainingGroup = group_for(permissions.can_view_group)):
    coach_id = request.state.user.id
    clips, pager = groups.review_queue(db, group, coach_id, parse_page(request.query_params.get("page")))
    return render(request, "group_review.html", g=group, clips=clips, pager=pager)


@router.get("/{group_id}/edit")
def edit_group(request: Request, group: TrainingGroup = group_for(permissions.can_manage_group)):
    return render(request, "group_form.html", g=group, error=None,
                  values={"name": group.name, "description": group.description})


@router.post("/{group_id}/edit")
def update_group(request: Request, db: Session = Depends(get_db),
                 group: TrainingGroup = group_for(permissions.can_manage_group),
                 name: str = Form(""), description: str = Form("")):
    try:
        groups.update_group(db, group, name, description)
    except GroupError as exc:
        db.rollback()
        return render(request, "group_form.html", status_code=exc.status_code, g=group, error=str(exc),
                      values={"name": name, "description": description})
    return flash.redirect_with_page_notice(group_url(group), "Zapisano grupę.")


def _add(request: Request, db: Session, group: TrainingGroup, role: str, user_id: str):
    actor = request.state.user
    try:
        added = groups.add_member(db, group, user_id, role, actor)
    except GroupError as exc:
        db.rollback()
        return render_group(request, db, group, groups.DEFAULT_DAYS, status_code=exc.status_code,
                            error=str(exc), add_values={role: user_id})
    noun = "sędziego" if role == "referee" else "szkoleniowca"
    return flash.redirect_with_page_notice(group_url(group), f"Dodano {noun}: {added.name}.")


@router.post("/{group_id}/referees")
def add_referee(request: Request, db: Session = Depends(get_db),
                group: TrainingGroup = group_for(permissions.can_manage_group),
                user_id: str = Form("")):
    return _add(request, db, group, "referee", user_id)


@router.post("/{group_id}/coaches")
def add_coach(request: Request, db: Session = Depends(get_db),
              group: TrainingGroup = group_for(permissions.can_manage_group),
              user_id: str = Form("")):
    return _add(request, db, group, "coach", user_id)


@router.post("/{group_id}/referees/{user_id}/remove")
def remove_referee(request: Request, user_id: int, db: Session = Depends(get_db),
                   group: TrainingGroup = group_for(permissions.can_manage_group), days: str = Form("")):
    try:
        removed = groups.remove_referee(db, group, user_id)
    except GroupError as exc:
        db.rollback()
        return render_group(request, db, group, groups.parse_days(days), status_code=exc.status_code,
                            error=str(exc))
    return flash.redirect_with_page_notice(group_url(group, groups.parse_days(days)),
                                           f"Usunięto z grupy: {removed.name}.")


@router.get("/{group_id}/delete")
def confirm_delete(request: Request, group: TrainingGroup = group_for(permissions.can_manage_group)):
    return render(request, "group_delete.html", g=group)


@router.post("/{group_id}/delete")
def delete_group(db: Session = Depends(get_db), group: TrainingGroup = group_for(permissions.can_manage_group)):
    name = group.name
    groups.delete_group(db, group)
    return flash.redirect_with_page_notice("/groups", f"Usunięto grupę „{name}”.")
