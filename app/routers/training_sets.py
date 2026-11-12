"""Every logged-in user views sets; every coach and admin edits every set (the check does not depend on the
set), so each mutating route is `require(permissions.can_edit_set)`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app import clip_list, flash, permissions, training_sets
from app.auth import require
from app.db import get_db
from app.loaders import get_clip, get_training_set
from app.models import Clip, TrainingSet, User
from app.pagination import parse_page
from app.routers.clips import render_clip
from app.storage import storage
from app.training_sets import SetError
from app.web import file_response, render

router = APIRouter()


def set_url(training_set: TrainingSet) -> str:
    return f"/sets/{training_set.id}"


def clip_in_set_url(training_set: TrainingSet, clip_id: int) -> str:
    return f"/sets/{training_set.id}/clips/{clip_id}"


@router.get("/sets")
def set_list(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    rows, pager = training_sets.list_sets(db, parse_page(request.query_params.get("page")))
    return render(request, "sets.html", rows=rows, pager=pager)


@router.get("/sets/new")
def new_set(request: Request, user: User = require(permissions.can_edit_set)):
    return render(request, "set_form.html", s=None, error=None,
                  values={"name": "", "description": "", "show_names": False})


@router.post("/sets")
def create_set(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_edit_set),
               name: str = Form(""), description: str = Form("")):
    try:
        training_set = training_sets.create_set(db, user, name, description)
    except SetError as exc:
        db.rollback()
        return render(request, "set_form.html", status_code=exc.status_code, s=None, error=str(exc),
                      values={"name": name, "description": description, "show_names": False})
    db.commit()
    return flash.redirect_with_page_notice(set_url(training_set), f"Utworzono zestaw „{training_set.name}”.")


@router.get("/sets/{set_id}")
def set_detail(request: Request, db: Session = Depends(get_db),
               training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_view)):
    editing = permissions.can_edit_set(user)
    return render(request, "set_detail.html", s=training_set, items=training_sets.items_of(db, training_set),
                  groups_to_pin=training_sets.unpinned_groups(db, training_set) if editing else [], error=None)


def render_set_clip(request: Request, db: Session, training_set: TrainingSet, clip_id: int, *,
                    status_code: int = 200, note_error: str | None = None, note_value: str | None = None):
    items = training_sets.items_of(db, training_set)
    index = training_sets.locate(items, clip_id)
    if index is None:
        raise HTTPException(404, "Tego klipu nie ma w zestawie")
    return render(request, "set_clip.html", status_code=status_code, s=training_set, items=items, index=index,
                  item=items[index], previous=items[index - 1] if index else None,
                  following=items[index + 1] if index + 1 < len(items) else None,
                  note_error=note_error, note_value=items[index].note if note_value is None else note_value)


@router.get("/sets/{set_id}/clips/{clip_id}")
def set_clip(request: Request, clip_id: int, db: Session = Depends(get_db),
             training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_view)):
    return render_set_clip(request, db, training_set, clip_id)


@router.get("/sets/{set_id}/clips/{clip_id}/download")
def set_clip_download(clip_id: int, db: Session = Depends(get_db),
                      training_set: TrainingSet = Depends(get_training_set),
                      user: User = require(permissions.can_view)):
    """The file name follows the set's name setting, so hidden names never reach a downloaded file."""
    item = db.get(training_sets.TrainingSetClip, (training_set.id, clip_id))
    if item is None:
        raise HTTPException(404, "Tego klipu nie ma w zestawie")
    clip = item.clip
    if not clip.clip_path or not storage.exists(clip.clip_path):
        raise HTTPException(404, "Klip nie jest jeszcze wycięty")
    return file_response(storage.local_path(clip.clip_path), download_name=training_sets.filename(clip, training_set))


@router.get("/sets/{set_id}/edit")
def edit_set(request: Request, training_set: TrainingSet = Depends(get_training_set),
             user: User = require(permissions.can_edit_set)):
    return render(request, "set_form.html", s=training_set, error=None,
                  values={"name": training_set.name, "description": training_set.description,
                          "show_names": training_set.show_names})


@router.post("/sets/{set_id}/edit")
def update_set(request: Request, db: Session = Depends(get_db),
               training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_edit_set),
               name: str = Form(""), description: str = Form(""), show_names: str = Form("")):
    try:
        training_sets.update_set(db, training_set, name, description, show_names == "1")
    except SetError as exc:
        db.rollback()
        return render(request, "set_form.html", status_code=exc.status_code, s=training_set, error=str(exc),
                      values={"name": name, "description": description, "show_names": show_names == "1"})
    return flash.redirect_with_page_notice(set_url(training_set), "Zapisano zestaw.")


@router.get("/sets/{set_id}/delete")
def confirm_delete(request: Request, db: Session = Depends(get_db),
                   training_set: TrainingSet = Depends(get_training_set),
                   user: User = require(permissions.can_edit_set)):
    return render(request, "set_delete.html", s=training_set, clip_count=len(training_set.items))


@router.post("/sets/{set_id}/delete")
def delete_set(db: Session = Depends(get_db), training_set: TrainingSet = Depends(get_training_set),
               user: User = require(permissions.can_edit_set)):
    name = training_set.name
    training_sets.delete_set(db, training_set)
    return flash.redirect_with_page_notice("/sets", f"Usunięto zestaw „{name}”.")


@router.post("/sets/{set_id}/clips/{clip_id}/note")
def save_note(request: Request, clip_id: int, db: Session = Depends(get_db),
              training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_edit_set),
              note: str = Form("")):
    try:
        training_sets.set_note(db, training_set, clip_id, note)
    except SetError as exc:
        db.rollback()
        if exc.status_code == 404:
            raise HTTPException(404, str(exc)) from None
        return render_set_clip(request, db, training_set, clip_id, status_code=exc.status_code,
                               note_error=str(exc), note_value=note)
    return flash.redirect_with_page_notice(clip_in_set_url(training_set, clip_id), "Zapisano notatkę.")


@router.post("/sets/{set_id}/clips/{clip_id}/move")
def move_clip(*, clip_id: int, db: Session = Depends(get_db),
              training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_edit_set),
              direction: str = Form("")):
    try:
        training_sets.move_clip(db, training_set, clip_id, direction)
    except SetError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    return flash.redirect_with_page_notice(set_url(training_set), "Zmieniono kolejność klipów.")


@router.post("/sets/{set_id}/clips/{clip_id}/remove")
def remove_clip(*, clip_id: int, db: Session = Depends(get_db),
                training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_edit_set)):
    try:
        training_sets.remove_clip(db, training_set, clip_id)
    except SetError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    return flash.redirect_with_page_notice(set_url(training_set), "Usunięto klip z zestawu.")


@router.post("/sets/{set_id}/groups")
def pin_to_group(request: Request, db: Session = Depends(get_db),
                 training_set: TrainingSet = Depends(get_training_set), user: User = require(permissions.can_edit_set),
                 group_id: str = Form("")):
    try:
        group = training_sets.pin(db, training_set, group_id)
    except SetError as exc:
        db.rollback()
        return render(request, "set_detail.html", status_code=exc.status_code, s=training_set,
                      items=training_sets.items_of(db, training_set),
                      groups_to_pin=training_sets.unpinned_groups(db, training_set), error=str(exc))
    return flash.redirect_with_page_notice(set_url(training_set), f"Przypięto zestaw do grupy „{group.name}”.")


@router.post("/sets/{set_id}/groups/{group_id}/unpin")
def unpin_from_group(*, group_id: int, db: Session = Depends(get_db),
                     training_set: TrainingSet = Depends(get_training_set),
                     user: User = require(permissions.can_edit_set)):
    try:
        group = training_sets.unpin(db, training_set, group_id)
    except SetError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    return flash.redirect_with_page_notice(set_url(training_set), f"Odpięto zestaw od grupy „{group.name}”.")


@router.post("/clips/{clip_id}/sets")
def add_clip_to_set(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                    user: User = require(permissions.can_edit_set),
                    set_id: str = Form(""), new_name: str = Form("")):
    try:
        training_set = training_sets.add_clip_to(db, user, clip, set_id, new_name)
    except SetError as exc:
        db.rollback()
        return render_clip(request, db, clip, clip_list.parse_filters(request.query_params),
                           status_code=exc.status_code, set_error=str(exc),
                           set_values={"set_id": set_id, "new_name": new_name})
    nav = clip_list.parse_filters(request.query_params).query(scope=False)
    return flash.redirect_with_page_notice(f"/clips/{clip.id}" + (f"?{nav}" if nav else ""),
                                           f"Dodano klip do zestawu „{training_set.name}”.")
