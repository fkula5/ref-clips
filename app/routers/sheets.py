"""A sheet the user may not see is answered with 404, never 403, so its existence is not revealed (a
referee outside the crew knows the match but must not learn that a sheet exists).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import flash, permissions, sheets
from app.auth import current_user, require
from app.db import get_db
from app.loaders import get_match
from app.models import Match, Sheet, User
from app.sheets import SheetError
from app.web import render

router = APIRouter()

NOT_FOUND = "Nie ma takiego arkusza"


def sheet_for(check: Callable[[User, Sheet], bool], *, gate: Callable[[User, Sheet], bool] = permissions.can_view_sheet):
    """404 when the user fails `gate` or the sheet does not exist, so both look the same; 403 only when
    `check` fails for someone who passed the gate.
    """
    def dependency(sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Sheet:
        sheet = db.get(Sheet, sheet_id)
        if sheet is None or not gate(user, sheet):
            raise HTTPException(404, NOT_FOUND)
        if not check(user, sheet):
            raise HTTPException(403, "Brak uprawnień do tej operacji")
        return sheet
    return Depends(dependency)


def can_see_or_delete(user: User, sheet: Sheet) -> bool:
    return permissions.can_view_sheet(user, sheet) or permissions.can_delete_sheet(user, sheet)


view_sheet = sheet_for(permissions.can_view_sheet)
edit_sheet = sheet_for(permissions.can_edit_sheet)
delete_sheet_dep = sheet_for(permissions.can_delete_sheet, gate=can_see_or_delete)


async def posted_values(request: Request) -> dict[str, str]:
    return {k: v for k, v in (await request.form()).items() if isinstance(v, str)}


def render_form(request: Request, db: Session, sheet: Sheet, *, values: dict[str, str] | None = None,
                errors: list[str] | None = None, status_code: int = 200):
    """After a failed save `values` is what the user typed; it is shown instead of the stored text."""
    shown = {**sheets.form_values(sheet), **(values or {})}
    return render(request, "sheet_form.html", status_code=status_code, sheet=sheet, match=sheet.match,
                  grid=sheets.grid(sheet), values=shown, errors=errors or [], unsaved=bool(errors),
                  changes=[] if sheet.is_published else sheets.crew_changes(sheet))


@router.post("/matches/{match_id}/sheets")
def open_sheet(db: Session = Depends(get_db), match: Match = Depends(get_match),
               user: User = require(permissions.can_create_sheet)):
    try:
        sheet, created = sheets.create(db, match, user)
    except SheetError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    db.commit()
    return flash.redirect_with_page_notice(
        f"/sheets/{sheet.id}/edit", "Założono arkusz jako szkic." if created else "Wracasz do swojego arkusza.")


@router.get("/sheets/{sheet_id}")
def show_sheet(request: Request, sheet: Sheet = view_sheet, user: User = Depends(current_user)):
    return render(request, "sheet.html", sheet=sheet, match=sheet.match, grid=sheets.grid(sheet))


@router.get("/sheets/{sheet_id}/edit")
def edit_form(request: Request, db: Session = Depends(get_db), sheet: Sheet = edit_sheet):
    return render_form(request, db, sheet)


@router.post("/sheets/{sheet_id}/edit")
def save_sheet(request: Request, db: Session = Depends(get_db), sheet: Sheet = edit_sheet,
               user: User = Depends(current_user), posted: dict[str, str] = Depends(posted_values)):
    """`action` is save, publish, or refresh (crew of a draft)."""
    action = posted.get("action", "save")
    if action == "refresh" and sheet.is_published:
        action = "save"  # the crew of a published sheet is frozen
    if action == "publish" and not permissions.can_publish_sheet(user, sheet):
        raise HTTPException(403, "Brak uprawnień do tej operacji")
    try:
        published = sheets.save(db, sheet, posted, publish=action == "publish")
        notes = sheets.refresh_crew(db, sheet) if action == "refresh" else []
    except SheetError as exc:
        db.rollback()
        return render_form(request, db, sheet, values=posted, errors=exc.errors, status_code=exc.status_code)
    db.commit()
    if published:
        empty, total = sheets.empty_count(sheet)
        return flash.redirect_with_page_notice(
            f"/sheets/{sheet.id}", "Opublikowano arkusz." + (f" Puste pola: {empty} z {total}." if empty else ""))
    if action == "refresh":
        return flash.redirect_with_page_notice(f"/sheets/{sheet.id}/edit", " ".join(["Odświeżono obsadę arkusza.", *notes]))
    if sheet.is_published:
        return flash.redirect_with_page_notice(f"/sheets/{sheet.id}", "Zapisano zmiany w arkuszu.")
    return flash.redirect_with_page_notice(f"/sheets/{sheet.id}/edit", "Zapisano szkic.")


@router.get("/sheets/{sheet_id}/delete")
def confirm_delete(request: Request, sheet: Sheet = delete_sheet_dep):
    empty, total = sheets.empty_count(sheet)
    return render(request, "sheet_delete.html", sheet=sheet, match=sheet.match, filled=total - empty)


@router.post("/sheets/{sheet_id}/delete")
def delete_sheet(db: Session = Depends(get_db), sheet: Sheet = delete_sheet_dep):
    match_id = sheet.match_id
    db.delete(sheet)
    db.commit()
    return flash.redirect_with_page_notice(f"/matches/{match_id}#arkusz", "Usunięto arkusz.")
