"""Public pages: no login, session or CSRF (read-only). Routes do not use `current_user`, `render()` or
base.html: no session cookie is read or set, and no user data is shown even if the browser is logged
in. URLs carry the stable position of the clip in the link, never the clip id or file path. Privacy
headers come from `app.privacy`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import share
from app.db import get_db
from app.storage import storage
from app.web import templates

router = APIRouter()

NO_STORE = {"Cache-Control": "no-store"}
VIDEO_HEADERS = {"Cache-Control": "private, no-store"}  # Range (206) works; the browser does not keep the file


def message_page(request: Request, status_code: int, heading: str, message: str, headers: dict | None = None):
    return templates.TemplateResponse(request, "share_message.html", {"heading": heading, "message": message},
                                      status_code=status_code, headers=headers)


def gone_response(request: Request):
    """One response for a missing, expired, revoked or empty link (and any bad URL under `/s/`), so the
    cases cannot be told apart.
    """
    return message_page(request, 404, "Link jest nieaktywny",
                        "Ten link nie istnieje, wygasł albo został unieważniony. Poproś osobę, która go "
                        "przesłała, o nowy.")


@router.api_route("/s/{code}", methods=["GET", "HEAD"])
def share_page(request: Request, code: str, db: Session = Depends(get_db)):
    view = share.open_link(db, code)
    if view is None:
        return gone_response(request)
    if request.method == "GET":  # only page visits count; files, Range, HEAD and ZIP do not
        share.count_view(db, view.link.id)
    return templates.TemplateResponse(request, "share.html", {"code": code, "view": view}, headers=NO_STORE)


@router.api_route("/s/{code}/clips/{position}/file", methods=["GET", "HEAD"])
def share_file(request: Request, code: str, position: str, db: Session = Depends(get_db)):
    view = share.open_link(db, code)
    entry = view.clip_at(position) if view else None
    if entry is None:
        return gone_response(request)
    return FileResponse(storage.local_path(entry.clip.clip_path), media_type="video/mp4", headers=VIDEO_HEADERS)


@router.get("/s/{code}/clips/{position}/download")
def share_download(request: Request, code: str, position: str, db: Session = Depends(get_db)):
    view = share.open_link(db, code)
    entry = view.clip_at(position) if view and view.single else None
    if entry is None:
        return gone_response(request)
    return FileResponse(storage.local_path(entry.clip.clip_path), media_type="video/mp4", filename=entry.filename,
                        content_disposition_type="attachment", headers=NO_STORE)


@router.get("/s/{code}/zip")
def share_zip(request: Request, code: str, db: Session = Depends(get_db)):
    view = share.open_link(db, code)
    if view is None or view.single:
        return gone_response(request)
    try:
        path = share.build_zip(view.clips)
    except share.ZipBusy:
        return message_page(request, 503, "Paczka jest przygotowywana",
                            "Serwer przygotowuje teraz inne paczki. Spróbuj ponownie za chwilę albo obejrzyj "
                            "klipy na stronie.", {**NO_STORE, "Retry-After": "10"})
    except share.ZipNoSpace:
        return message_page(request, 503, "Brak miejsca na paczkę",
                            "Serwer nie ma teraz miejsca na przygotowanie paczki. Spróbuj później albo obejrzyj "
                            "klipy na stronie.", {**NO_STORE, "Retry-After": "600"})
    return FileResponse(path, media_type="application/zip", filename="klipy.zip", headers=NO_STORE,
                        background=BackgroundTask(path.unlink, missing_ok=True))
