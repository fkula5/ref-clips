"""Funkcje ukryte w MVP (korekta granic klipu, eksport ZIP): kod jest utrzymywany, ale trasy
są dołączone tylko przy REFCLIPS_V2_FEATURES=1. Test montuje je w osobnej aplikacji."""
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.exceptions import HTTPException

from app import config
from app.auth import PROTECTED
from app.main import http_error
from app.models import Clip, Job, PeriodMark
from app.routers import clips_v2
from app.storage import storage
from tests.conftest import login_client
from tests.helpers import make_match, make_ready_video, make_user


@pytest.fixture()
def v2_client(db):
    app = FastAPI()
    app.include_router(clips_v2.router, dependencies=PROTECTED)
    app.add_exception_handler(HTTPException, http_error)
    base = login_client(db, make_user(db, ["admin"], email="v2@example.com"))
    client = TestClient(app)
    client.cookies.set(config.SESSION_COOKIE, base.cookies.get(config.SESSION_COOKIE))
    client.headers.update(base.headers)
    return client


def make_clip(db, video, time_sec=100):
    clip = Clip(match_id=video.match_id, video_id=video.id, time_sec=time_sec)
    db.add(clip)
    db.commit()
    return clip


def test_adjust_clip_requeues_cut(v2_client, db):
    clip = make_clip(db, make_ready_video(db, make_match(db)))
    r = v2_client.post(f"/clips/{clip.id}/adjust", data={"start": "1:30", "end": "1:50"}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(clip)
    assert (clip.margin_before, clip.margin_after) == (10, 10)
    v2_client.post(f"/clips/{clip.id}/adjust", data={"start": "85", "end": "2:00"})
    db.refresh(clip)
    assert (clip.margin_before, clip.margin_after) == (15, 20)
    assert len(db.scalars(select(Job).where(Job.type == "cut", Job.status == "pending")).all()) == 1
    assert v2_client.post(f"/clips/{clip.id}/adjust", data={"start": "2:00", "end": "2:10"}).status_code == 422


def test_zip_export(v2_client, db):
    video = make_ready_video(db, make_match(db))
    video.marks.append(PeriodMark(period="Q1", time_sec=0))
    db.commit()
    ids = []
    for t in (100, 100):  # dwie takie same nazwy -> unikalne w paczce
        clip = make_clip(db, video, t)
        clip.clip_path, clip.status = f"clips/{clip.id}_v1.mp4", "cut"
        clip.official_id = video.match.official("CC").id
        with storage.open_write(clip.clip_path) as fh:
            fh.write(b"clip%d" % clip.id)
        ids.append(clip.id)
    db.commit()
    z = v2_client.get("/clips/export.zip", params={"match_id": video.match_id})
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        assert sorted(zf.namelist()) == ["2026-10-28_Q1_01m40s_CC.mp4", "2026-10-28_Q1_01m40s_CC_2.mp4", "opisy.csv"]
        csv_text = zf.read("opisy.csv").decode("utf-8-sig")
        assert "Filip Kowalski" in csv_text and "Q1" in csv_text and csv_text.startswith("plik;")
    assert v2_client.get("/clips/export.zip", params={"ids": [9999]}).status_code == 404
