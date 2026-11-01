"""Funkcje odłożone do wersji 2: korekta granic klipu i eksport ZIP + CSV.

Kod jest utrzymywany i testowany, ale trasy nie są dołączone do aplikacji ani podlinkowane
w interfejsie MVP. Włącza je zmienna `REFCLIPS_V2_FEATURES=1` (patrz app/main.py).
"""
from __future__ import annotations

import csv
import io
import os
import tempfile
import zipfile

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import config, permissions, services
from app.auth import require, via_match
from app.db import get_db
from app.loaders import get_clip
from app.models import Clip, User
from app.notes_parser import parse_time
from app.routers.clips import query_clips
from app.storage import storage
from app.textutil import format_clock

router = APIRouter()


# --- eksport ZIP (przed trasami z {id}) -----------------------------------------
def _csv_text(clips: list[Clip], names: dict[int, str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["plik", "data_meczu", "mecz", "sedzia", "czas_w_nagraniu", "kwarta",
                     "kategoria", "opis", "komentarze"])
    for c in clips:
        writer.writerow([
            names[c.id], c.match.date.isoformat(), c.match.title, c.official_label,
            format_clock(c.time_sec), services.period_for(c.video.marks, c.time_sec) or "",
            c.category_label, c.description, " | ".join(cm.body for cm in c.comments),
        ])
    return out.getvalue()


@router.get("/clips/export.zip")
def export_zip(db: Session = Depends(get_db), user: User = require(permissions.can_view),
               match_id: int | None = None, video_id: int | None = None, person: str = "",
               category_id: int | None = None, period: str = "",
               ids: list[int] = Query(default=[])):
    clips = query_clips(db, match_id=match_id, video_id=video_id, person=person or None,
                        category_id=category_id, period=period or None, ids=ids or None)
    clips = [c for c in clips if c.clip_path and storage.exists(c.clip_path)]
    if not clips:
        raise HTTPException(404, "Brak wyciętych klipów do wyeksportowania")
    names: dict[int, str] = {}
    used: set[str] = set()
    for c in clips:
        name = services.clip_filename(c)
        n = 1
        while name in used:  # unikalne nazwy w paczce
            n += 1
            name = services.clip_filename(c)[:-4] + f"_{n}.mp4"
        used.add(name)
        names[c.id] = name
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=config.DATA_DIR / "tmp")
    with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as zf:
        for c in clips:
            zf.write(storage.local_path(c.clip_path), names[c.id])
        zf.writestr("opisy.csv", "﻿" + _csv_text(clips, names))
    return FileResponse(tmp_path, media_type="application/zip", filename="klipy.zip",
                        background=BackgroundTask(os.unlink, tmp_path))


# --- korekta granic klipu ---------------------------------------------------------
@router.post("/clips/{clip_id}/adjust")
def clip_adjust(db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(via_match(permissions.can_manage_clips), get_clip),
                start: str = Form(), end: str = Form()):
    """Korekta początku/końca klipu (m:ss lub liczba sekund) i ponowne wycięcie."""
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
    if start_s is None or end_s is None or start_s > clip.time_sec or end_s < clip.time_sec:
        raise HTTPException(422, "Początek musi być nie później, a koniec nie wcześniej niż moment znacznika")
    clip.margin_before = min(clip.time_sec - start_s, config.MAX_MARGIN)
    clip.margin_after = min(end_s - clip.time_sec, config.MAX_MARGIN)
    services.queue_cut(db, clip)
    db.commit()
    return RedirectResponse(f"/clips/{clip.id}", status_code=303)
