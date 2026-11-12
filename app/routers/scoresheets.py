"""Scoresheet files of a match. Everybody logged in views them; uploading and deleting needs
`permissions.can_manage_scoresheet` (checked per match, server-side). Files are never reachable by a path
or from the public share links.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import flash, permissions, scoresheets
from app.auth import require
from app.db import get_db
from app.loaders import get_match, get_scoresheet
from app.models import Match, MatchScoresheet, User
from app.routers.matches import render_match
from app.scoresheets import Incoming, ScoresheetError
from app.storage import storage

router = APIRouter()

SECTION = "#protokol"
# `no-cache`, not `no-store`: the ETag keeps repeated page views cheap, but a changed permission or a
# deleted file is noticed on the next request.
FILE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"}
manager = require(permissions.can_manage_scoresheet, get_match)


async def posted_files(request: Request) -> list[Incoming]:
    """An empty file input still sends one part, which arrives as a plain string."""
    form = await request.form()
    return [Incoming(f.filename, f.file) for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]


@router.post("/matches/{match_id}/scoresheets")
def upload_scoresheets(request: Request, db: Session = Depends(get_db), match: Match = Depends(get_match),
                       user: User = manager, incoming: list[Incoming] = Depends(posted_files)):
    try:
        added = scoresheets.add_files(db, user, match, incoming)
    except ScoresheetError as exc:
        return render_match(request, db, match, status_code=exc.status_code, scoresheet_error=str(exc))
    return flash.redirect_with_page_notice(
        f"/matches/{match.id}{SECTION}", f"Dodano do protokołu: {scoresheets.plural_files(len(added))}.")


def _serve(scoresheet: MatchScoresheet, disposition: str):
    if not storage.exists(scoresheet.path):
        raise HTTPException(404, "Plik protokołu nie jest już dostępny")
    return FileResponse(storage.local_path(scoresheet.path), media_type=scoresheet.content_type,
                        filename=scoresheet.original_filename, content_disposition_type=disposition,
                        headers=FILE_HEADERS)


@router.get("/matches/{match_id}/scoresheets/{scoresheet_id}/file")
def scoresheet_file(scoresheet: MatchScoresheet = Depends(get_scoresheet),
                    user: User = require(permissions.can_view)):
    return _serve(scoresheet, "inline")


@router.get("/matches/{match_id}/scoresheets/{scoresheet_id}/download")
def scoresheet_download(scoresheet: MatchScoresheet = Depends(get_scoresheet),
                        user: User = require(permissions.can_view)):
    return _serve(scoresheet, "attachment")


@router.post("/matches/{match_id}/scoresheets/{scoresheet_id}/delete")
def delete_scoresheet(db: Session = Depends(get_db), match: Match = Depends(get_match),
                      scoresheet: MatchScoresheet = Depends(get_scoresheet), user: User = manager):
    scoresheets.remove(db, scoresheet)
    return flash.redirect_with_page_notice(f"/matches/{match.id}{SECTION}", "Usunięto plik protokołu.")
