"""Klipy (decyzje): lista z filtrami, szczegóły, korekta, komentarze, pobieranie, eksport ZIP."""
from __future__ import annotations

import csv
import io
import os
import tempfile
import zipfile

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask

from app import config, services
from app.db import get_db
from app.models import (RATINGS, VISIBILITIES, Comment, Decision, Match, Referee, Tag,
                        decision_tags)
from app.notes_parser import parse_time
from app.storage import storage
from app.textutil import format_clock
from app.web import file_response, render

router = APIRouter()


def _get_decision(db: Session, decision_id: int) -> Decision:
    d = db.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "Nie ma takiego klipu")
    return d


def _query_decisions(db: Session, *, match_id=None, video_id=None, referee_id=None, tag=None,
                     rating=None, period=None, ids=None) -> list[Decision]:
    stmt = select(Decision).options(
        selectinload(Decision.tags), selectinload(Decision.comments),
    ).order_by(Decision.match_id.desc(), Decision.video_id, Decision.time_sec)
    if match_id:
        stmt = stmt.where(Decision.match_id == match_id)
    if video_id:
        stmt = stmt.where(Decision.video_id == video_id)
    if referee_id:
        stmt = stmt.where(Decision.referee_id == referee_id)
    if rating:
        stmt = stmt.where(Decision.rating == rating)
    if tag:
        stmt = stmt.where(Decision.id.in_(
            select(decision_tags.c.decision_id).join(Tag, Tag.id == decision_tags.c.tag_id)
            .where(Tag.name == tag)))
    if ids:
        stmt = stmt.where(Decision.id.in_(ids))
    decisions = list(db.scalars(stmt))
    if period:  # kwarta jest wyliczana ze znaczników, więc filtrujemy w Pythonie
        decisions = [d for d in decisions
                     if (services.period_for(d.video.marks, d.time_sec) or "") == period]
    return decisions


# --- lista ----------------------------------------------------------------------
@router.get("/clips")
def clips_list(request: Request, db: Session = Depends(get_db), match_id: int | None = None,
               video_id: int | None = None, referee_id: int | None = None, tag: str = "",
               rating: str = "", period: str = "", created: int | None = None, skipped: int = 0):
    decisions = _query_decisions(db, match_id=match_id, video_id=video_id, referee_id=referee_id,
                                 tag=tag or None, rating=rating or None, period=period or None)
    pending = any(d.status in ("new", "queued") for d in decisions)
    return render(
        request, "clips.html", decisions=decisions, pending=pending, created=created,
        skipped=skipped,
        matches=db.scalars(select(Match).order_by(Match.date.desc())).all(),
        referees=db.scalars(select(Referee).order_by(Referee.name)).all(),
        tags=db.scalars(select(Tag).order_by(Tag.sort, Tag.name)).all(),
        f={"match_id": match_id, "video_id": video_id, "referee_id": referee_id, "tag": tag,
           "rating": rating, "period": period},
        query=str(request.url.query),
    )


# --- eksport ZIP (przed trasami z {id}) -----------------------------------------
def _csv_text(decisions: list[Decision], names: dict[int, str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["plik", "data_meczu", "mecz", "sedzia", "czas_w_nagraniu", "kwarta", "tagi",
                     "ocena", "opis", "komentarze"])
    for d in decisions:
        writer.writerow([
            names[d.id], d.match.date.isoformat(), d.match.title,
            d.referee.name if d.referee else "", format_clock(d.time_sec),
            services.period_for(d.video.marks, d.time_sec) or "", ", ".join(t.name for t in d.tags),
            RATINGS.get(d.rating or "", ""), d.description,
            " | ".join((f"[{format_clock(c.at_sec)}] " if c.at_sec is not None else "") + c.body
                       for c in d.comments),
        ])
    return out.getvalue()


@router.get("/clips/export.zip")
def export_zip(db: Session = Depends(get_db), match_id: int | None = None,
               video_id: int | None = None, referee_id: int | None = None, tag: str = "",
               rating: str = "", period: str = "", ids: list[int] = Query(default=[])):
    decisions = _query_decisions(db, match_id=match_id, video_id=video_id, referee_id=referee_id,
                                 tag=tag or None, rating=rating or None, period=period or None,
                                 ids=ids or None)
    decisions = [d for d in decisions if d.clip_path and storage.exists(d.clip_path)]
    if not decisions:
        raise HTTPException(404, "Brak wyciętych klipów do wyeksportowania")
    names: dict[int, str] = {}
    used: set[str] = set()
    for d in decisions:
        name = services.clip_filename(d)
        n = 1
        while name in used:  # unikalne nazwy w paczce
            n += 1
            name = services.clip_filename(d)[:-4] + f"_{n}.mp4"
        used.add(name)
        names[d.id] = name
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=config.DATA_DIR / "tmp")
    with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as zf:
        for d in decisions:
            zf.write(storage.local_path(d.clip_path), names[d.id])
        zf.writestr("opisy.csv", "﻿" + _csv_text(decisions, names))
    return FileResponse(tmp_path, media_type="application/zip", filename="klipy.zip",
                        background=BackgroundTask(os.unlink, tmp_path))


# --- szczegóły ------------------------------------------------------------------
@router.get("/clips/{decision_id}")
def clip_detail(request: Request, decision_id: int, db: Session = Depends(get_db)):
    d = _get_decision(db, decision_id)
    return render(
        request, "clip_detail.html", d=d,
        referees=[mr.referee for mr in d.match.referees],
        filename=services.clip_filename(d),
        tags_text=", ".join(t.name for t in d.tags),
        all_tags=db.scalars(select(Tag).order_by(Tag.sort, Tag.name)).all(),
        busy=d.status in ("new", "queued"),
    )


@router.post("/clips/{decision_id}/update")
def clip_update(decision_id: int, db: Session = Depends(get_db), referee_id: str = Form(""),
                team: str = Form(""), tags: str = Form(""), rating: str = Form(""),
                visibility: str = Form("private"), description: str = Form("")):
    d = _get_decision(db, decision_id)
    valid = {mr.referee_id for mr in d.match.referees}
    d.referee_id = int(referee_id) if referee_id.isdigit() and int(referee_id) in valid else None
    d.team = team if team in ("a", "b") else None
    d.rating = rating if rating in RATINGS else None
    d.visibility = visibility if visibility in VISIBILITIES else "private"
    d.description = description.strip()
    d.tags = services.resolve_tags(db, tags.split(","))
    db.commit()
    return RedirectResponse(f"/clips/{d.id}", status_code=303)


@router.post("/clips/{decision_id}/adjust")
def clip_adjust(decision_id: int, db: Session = Depends(get_db), start: str = Form(),
                end: str = Form()):
    """Korekta początku/końca klipu (m:ss lub liczba sekund) i ponowne wycięcie."""
    d = _get_decision(db, decision_id)

    def to_seconds(text: str) -> float | None:
        text = text.strip().replace(",", ".")
        parsed = parse_time(text)
        if parsed is not None:
            return parsed
        try:
            return float(text)
        except ValueError:
            return None

    start_s, end_s = to_seconds(start), to_seconds(end)
    if start_s is None or end_s is None or start_s > d.time_sec or end_s < d.time_sec:
        raise HTTPException(422, "Początek musi być nie później, a koniec nie wcześniej niż moment decyzji")
    d.margin_before = min(d.time_sec - start_s, config.MAX_MARGIN)
    d.margin_after = min(end_s - d.time_sec, config.MAX_MARGIN)
    services.queue_cut(db, d)
    db.commit()
    return RedirectResponse(f"/clips/{d.id}", status_code=303)


@router.post("/clips/{decision_id}/recut")
def clip_recut(decision_id: int, db: Session = Depends(get_db)):
    d = _get_decision(db, decision_id)
    services.queue_cut(db, d)
    db.commit()
    return RedirectResponse(f"/clips/{d.id}", status_code=303)


@router.post("/clips/{decision_id}/delete")
def clip_delete(decision_id: int, db: Session = Depends(get_db)):
    d = _get_decision(db, decision_id)
    match_id = d.match_id
    services.remove_decision_files(d)
    db.delete(d)
    db.commit()
    return RedirectResponse(f"/clips?match_id={match_id}", status_code=303)


def _clip_file(db: Session, request: Request, decision_id: int, download: bool):
    d = _get_decision(db, decision_id)
    if not d.clip_path or not storage.exists(d.clip_path):
        raise HTTPException(404, "Klip nie jest jeszcze wycięty")
    return file_response(storage.local_path(d.clip_path),
                         download_name=services.clip_filename(d) if download else None)


@router.get("/clips/{decision_id}/file")
def clip_file(request: Request, decision_id: int, db: Session = Depends(get_db)):
    return _clip_file(db, request, decision_id, download=False)


@router.get("/clips/{decision_id}/download")
def clip_download(request: Request, decision_id: int, db: Session = Depends(get_db)):
    return _clip_file(db, request, decision_id, download=True)


# --- komentarze -----------------------------------------------------------------
@router.post("/clips/{decision_id}/comments")
def add_comment(request: Request, decision_id: int, db: Session = Depends(get_db),
                body: str = Form(), at_sec: str = Form(""), parent_id: str = Form("")):
    d = _get_decision(db, decision_id)
    if body.strip():
        try:
            at = float(at_sec) if at_sec.strip() else None
        except ValueError:
            at = None
        parent = int(parent_id) if parent_id.isdigit() else None
        if parent and not any(c.id == parent for c in d.comments):
            parent = None
        db.add(Comment(decision_id=d.id, author_id=services.default_user(db).id,
                       body=body.strip(), at_sec=at, parent_id=parent))
        db.commit()
        db.refresh(d)
    return render(request, "_comments.html", d=d)


@router.post("/comments/{comment_id}/delete")
def delete_comment(request: Request, comment_id: int, db: Session = Depends(get_db)):
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(404)
    d = comment.decision
    db.delete(comment)
    db.commit()
    db.refresh(d)
    return render(request, "_comments.html", d=d)
