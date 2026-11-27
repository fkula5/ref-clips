"""A self-assessment the user may not see is answered with 404, never 403, so nobody learns that a colleague
started one (a crew member knows the match but must not learn that a draft exists). 403 only when the user may
see the sheet but not do what they asked (a coach editing a submitted sheet).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import flash, leagues, permissions, self_assessment_pdf, self_assessments, share
from app.auth import current_user, require
from app.db import get_db
from app.loaders import get_match
from app.models import Match, SelfAssessment, User
from app.pagination import parse_page
from app.self_assessments import SelfAssessmentError
from app.web import mark_seen, render

router = APIRouter()
log = logging.getLogger("self_assessments")

NOT_FOUND = "Nie ma takiej samooceny"


def sa_for(check: Callable[[User, SelfAssessment], bool]):
    def dependency(self_assessment_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> SelfAssessment:
        sa = db.get(SelfAssessment, self_assessment_id)
        if sa is None or not permissions.can_view_self_assessment(user, sa):
            raise HTTPException(404, NOT_FOUND)
        if not check(user, sa):
            raise HTTPException(403, "Brak uprawnień do tej operacji")
        return sa
    return Depends(dependency)


view_sa = sa_for(permissions.can_view_self_assessment)
edit_sa = sa_for(permissions.can_edit_self_assessment)
delete_sa = sa_for(permissions.can_delete_self_assessment)
reopen_sa = sa_for(permissions.can_reopen_self_assessment)


async def posted(request: Request) -> tuple[dict[str, str], list[int]]:
    """The text fields and the ids of the clip rows in the order the form showed them."""
    form = await request.form()
    fields = {k: v for k, v in form.items() if isinstance(v, str)}
    order = [int(v) for v in form.getlist("row") if isinstance(v, str) and v.isdigit()]
    return fields, order


def summary(sa: SelfAssessment) -> dict:
    return {"id": sa.id, "title": sa.title, "author": sa.author.name, "published": sa.is_submitted,
            "match_id": sa.match_id}


def _data(db: Session, sa: SelfAssessment, user: User) -> JSONResponse:
    editing = permissions.can_edit_self_assessment(user, sa)
    hints = self_assessments.clip_hint(sa) if editing else {}
    return JSONResponse({
        **summary(sa), "header": asdict(self_assessments.header(sa)),
        "can_edit": editing, "can_delete": permissions.can_delete_self_assessment(user, sa),
        "can_reopen": permissions.can_reopen_self_assessment(user, sa),
        "league_names": leagues.active_names(db) if editing and not sa.match_id else [],
        "questions": [{"key": key, "label": label} for key, label in self_assessments.QUESTIONS],
        "header_fields": [{"key": key, "label": label} for key, label, _ in self_assessments.HEADER_FIELDS],
        "min_clips": self_assessments.MIN_CLIPS,
        "values": self_assessments.form_values(sa),
        "rows": [{
            "id": row.id, "clip_id": row.clip_id, "manual": row.is_manual, "name": row.name_label,
            "time": row.time_label, "hint": hints.get(row.id), "name_key": self_assessments.name_key(row),
            "desc_key": self_assessments.desc_key(row),
        } for row in self_assessments.ordered(sa, None)],
        "available": [{"id": clip.id, "label": f"{name} · {time}"}
                      for clip, time, name in self_assessments.available_clips(db, sa)] if editing else [],
    }, headers={"Cache-Control": "no-store"})


def render_form(request: Request, db: Session, sa: SelfAssessment, *, values: dict[str, str] | None = None,
                order: list[int] | None = None, errors: list[str] | None = None, notice: str | None = None,
                status_code: int = 200):
    """After a failed save `values` is what the user typed; it is shown instead of the stored text."""
    return render(request, "self_assessment_form.html", status_code=status_code, sa=sa, match=sa.match,
                  h=self_assessments.header(sa), league_names=leagues.active_names(db), questions=self_assessments.QUESTIONS,
                  rows=self_assessments.ordered(sa, order), values={**self_assessments.form_values(sa), **(values or {})},
                  errors=errors or [], error_notice=notice, unsaved=bool(errors) and not notice,
                  hints=self_assessments.clip_hint(sa), available=self_assessments.available_clips(db, sa),
                  min_clips=self_assessments.MIN_CLIPS)


@router.get("/self-assessments")
def list_page(request: Request, db: Session = Depends(get_db),
              user: User = require(permissions.can_see_self_assessments)):
    submitted, pager, mine = self_assessments.listing(db, user, parse_page(request.query_params.get("page")))
    if request.headers.get("accept") == "application/json":
        return JSONResponse({
            "mine": [summary(sa) for sa in mine], "submitted": [summary(sa) for sa in submitted],
            "page": pager.page, "pages": pager.pages,
            "can_create": permissions.can_create_standalone_self_assessment(user),
        }, headers={"Cache-Control": "no-store"})
    return render(request, "self_assessments.html", submitted=submitted, pager=pager, mine=mine,
                  staff=permissions.can_view_submitted_self_assessments(user),
                  can_create_standalone=permissions.can_create_standalone_self_assessment(user))


@router.post("/self-assessments/new")
def open_standalone(request: Request, db: Session = Depends(get_db),
                    user: User = require(permissions.can_create_standalone_self_assessment)):
    sa = self_assessments.create_standalone(db, user)
    db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"id": sa.id, "editing": True})
    return flash.redirect_with_page_notice(f"/self-assessments/{sa.id}/edit", "Założono samoocenę jako szkic.")


@router.post("/matches/{match_id}/self-assessments")
def open_sa(request: Request, db: Session = Depends(get_db), match: Match = Depends(get_match),
            user: User = require(permissions.can_fill_self_assessment, get_match)):
    sa, created = self_assessments.get_or_create(db, match, user)
    db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"id": sa.id, "editing": not sa.is_submitted})
    if sa.is_submitted:
        return flash.redirect_with_page_notice(f"/self-assessments/{sa.id}", "Ta samoocena została już wysłana.")
    return flash.redirect_with_page_notice(
        f"/self-assessments/{sa.id}/edit", "Założono samoocenę jako szkic." if created else "Wracasz do swojego szkicu.")


@router.get("/self-assessments/{self_assessment_id}")
def show(request: Request, db: Session = Depends(get_db), sa: SelfAssessment = view_sa):
    mark_seen(request, db, self_assessment_id=sa.id)
    if request.headers.get("accept") == "application/json":
        return _data(db, sa, request.state.user)
    return render(request, "self_assessment.html", sa=sa, match=sa.match, h=self_assessments.header(sa),
                  questions=self_assessments.QUESTIONS)


def render_pdf_or_503(sa: SelfAssessment) -> bytes:
    try:
        return self_assessment_pdf.render_pdf(sa)
    except OSError:  # WeasyPrint's system libraries (pango) are missing
        log.error("PDF rendering failed", exc_info=True)
        raise HTTPException(503, "Eksport do PDF jest niedostępny na tym serwerze. Użyj „Drukuj”.") from None


@router.get("/self-assessments/{self_assessment_id}/pdf")
def pdf(sa: SelfAssessment = view_sa):
    content = render_pdf_or_503(sa)
    name = self_assessments.pdf_filename(sa)
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@router.get("/self-assessments/{self_assessment_id}/zip")
def zip_archive(sa: SelfAssessment = view_sa):
    if not sa.is_submitted:
        raise HTTPException(409, "ZIP z klipami jest dostępny dopiero po wysłaniu samooceny.")
    content = render_pdf_or_503(sa)
    try:
        path = self_assessments.build_zip(sa, content)
    except share.ZipBusy:
        raise HTTPException(503, "Serwer przygotowuje teraz inne paczki. Spróbuj ponownie za chwilę.",
                            headers={"Retry-After": "10"}) from None
    except share.ZipNoSpace:
        raise HTTPException(503, "Serwer nie ma teraz miejsca na przygotowanie paczki. Spróbuj później.",
                            headers={"Retry-After": "600"}) from None
    return FileResponse(path, media_type="application/zip", filename=self_assessments.zip_filename(sa),
                        headers={"Cache-Control": "private, no-store"},
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.get("/self-assessments/{self_assessment_id}/edit")
def edit_form(request: Request, db: Session = Depends(get_db), sa: SelfAssessment = edit_sa):
    if request.headers.get("accept") == "application/json":
        return _data(db, sa, request.state.user)
    return render_form(request, db, sa)


@router.post("/self-assessments/{self_assessment_id}/edit")
def save(request: Request, db: Session = Depends(get_db), sa: SelfAssessment = edit_sa,
         body: tuple[dict[str, str], list[int]] = Depends(posted)):
    """`action` is save, submit, or a row action: add:<clip id>, manual, remove:<row id>, up:<row id>, down:<row id>."""
    fields, order = body
    action = fields.get("action", "save")
    try:
        submitted = self_assessments.save(db, sa, fields, order, action)
    except SelfAssessmentError as exc:
        if exc.saved:
            db.commit()
        else:
            db.rollback()
        note = "Nie wysłano samooceny. Szkic został zapisany." if exc.saved else None
        if request.headers.get("accept") == "application/json":
            raise HTTPException(exc.status_code, " ".join([*([note] if note else []), *exc.errors])) from exc
        sa = db.get(SelfAssessment, sa.id)
        return render_form(request, db, sa, values=None if exc.saved else fields, order=None if exc.saved else order,
                           errors=exc.errors, notice=note, status_code=exc.status_code)
    db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"id": sa.id, "editing": not sa.is_submitted})
    if submitted:
        return flash.redirect_with_page_notice(f"/self-assessments/{sa.id}", "Wysłano samoocenę. Nie można jej już edytować.")
    if action != "save":
        return flash.redirect_with_page_notice(f"/self-assessments/{sa.id}/edit#klipy", "Zapisano szkic.")
    return flash.redirect_with_page_notice(f"/self-assessments/{sa.id}/edit", "Zapisano szkic.")


@router.post("/self-assessments/{self_assessment_id}/delete")
def delete(request: Request, db: Session = Depends(get_db), sa: SelfAssessment = delete_sa):
    back = f"/matches/{sa.match_id}#samoocena" if sa.match_id else "/self-assessments"
    db.delete(sa)
    db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"deleted": True})
    return flash.redirect_with_page_notice(back, "Usunięto szkic samooceny.")


@router.post("/self-assessments/{self_assessment_id}/reopen")
def reopen(request: Request, db: Session = Depends(get_db), sa: SelfAssessment = reopen_sa):
    self_assessments.reopen(sa)
    db.commit()
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"id": sa.id, "editing": False})
    return flash.redirect_with_page_notice(
        f"/self-assessments/{sa.id}", "Przywrócono samoocenę do edycji. Autor może ją znów poprawić i wysłać.")
