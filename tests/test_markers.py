"""Znaczniki „Zaznacz” (klawisz Z), lista znaczników, cofanie, usuwanie, ochrona przed
podwójnym kliknięciem, uprawnienia i nagranie z usuniętą pełną wersją."""
import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import config
from app.models import Clip, Job
from app.storage import storage
from app.timeutil import utcnow
from tests.helpers import make_match, make_ready_video, make_user


@pytest.fixture()
def no_debounce(monkeypatch):
    """Testy, które dodają kilka znaczników pod rząd, nie podlegają ochronie przed podwójnym kliknięciem."""
    monkeypatch.setattr(config, "MARKER_DEBOUNCE_SECONDS", 0.0)


def fresh(db, clip_id):
    db.expire_all()
    return db.get(Clip, clip_id)


def mark(client, video_id, t):
    return client.post(f"/api/videos/{video_id}/markers", json={"time_sec": t})


def init_state(html):
    raw = re.search(r'<script type="application/json" id="init-state">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw.replace("\\u0026", "&").replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0027", "'"))


# --- tworzenie ---------------------------------------------------------------------------
def test_marker_creates_undescribed_clip_and_queues_cut(client, db):
    video = make_ready_video(db, make_match(db), duration=600)
    r = mark(client, video.id, 125.4)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    m = body["marker"]
    assert m["time_sec"] == 125.4 and m["described"] is False and m["status"] == "queued"
    assert (m["clip_start"], m["clip_end"]) == pytest.approx((110.4, 140.4))
    clip = fresh(db, m["id"])
    assert (clip.margin_before, clip.margin_after) == (15, 15)
    assert clip.described_at is None and clip.author_id is not None
    job = db.scalar(select(Job).where(Job.type == "cut"))
    assert job.clip_id == clip.id and job.status == "pending"
    # stan odtwarzacza zawiera nowy znacznik i oznaczenie „mój”
    assert [(c["id"], c["mine"], c["can_delete"]) for c in body["clips"]] == [(clip.id, True, True)]


def test_marker_time_is_clamped_to_the_recording(client, db):
    video = make_ready_video(db, make_match(db), duration=100)
    assert mark(client, video.id, 500).json()["marker"]["time_sec"] == 100
    assert mark(client, video.id, -5).json()["created"] is False  # < 1 s po poprzednim


def test_marker_shows_period_and_time_since_period_start(client, db, no_debounce):
    video = make_ready_video(db, make_match(db), duration=4000)
    client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 1000})
    m = mark(client, video.id, 1252).json()["marker"]
    assert (m["period"], m["period_clock"]) == ("Q1", "4:12")
    m = mark(client, video.id, 500).json()["marker"]
    assert m["period"] is None and m["period_clock"] is None  # kwarta nieustalona


# --- podwójne kliknięcie ---------------------------------------------------------------
def test_second_marker_within_a_second_is_ignored(client, db):
    video = make_ready_video(db, make_match(db), duration=600)
    first = mark(client, video.id, 100).json()
    second = mark(client, video.id, 100.4).json()
    assert first["created"] is True and second["created"] is False
    assert second["marker"]["id"] == first["marker"]["id"]
    assert len(db.scalars(select(Clip)).all()) == 1
    assert len(db.scalars(select(Job).where(Job.type == "cut")).all()) == 1
    # po sekundzie kolejny znacznik jest przyjmowany
    clip = fresh(db, first["marker"]["id"])
    clip.created_at = utcnow() - timedelta(seconds=1.5)
    db.commit()
    assert mark(client, video.id, 130).json()["created"] is True
    assert len(db.scalars(select(Clip)).all()) == 2


def test_debounce_is_per_author_and_per_video(make_client, db):
    match = make_match(db)
    one, other = make_ready_video(db, match), make_ready_video(db, match)
    alice, _ = make_client("coach")
    bob, _ = make_client("coach")
    assert mark(alice, one.id, 10).json()["created"] is True
    assert mark(bob, one.id, 10).json()["created"] is True       # inny autor
    assert mark(alice, other.id, 10).json()["created"] is True   # inne nagranie
    assert mark(alice, one.id, 11).json()["created"] is False


# --- uprawnienia -----------------------------------------------------------------------------
def test_marker_permissions(make_client, db):
    crew_client, crew = make_client("referee")
    match = make_match(db, officials=(("CC", crew), ("U1", "Kasia Żółć")))
    video = make_ready_video(db, match)
    outsider, _ = make_client("referee")
    assert mark(outsider, video.id, 5).status_code == 403
    assert outsider.post(f"/api/videos/{video.id}/markers/undo").status_code == 403
    assert db.scalar(select(Clip)) is None
    for roles in (("coach",), ("admin",), ("coach", "referee")):
        who, _ = make_client(*roles)
        assert mark(who, video.id, 5).status_code == 200, roles
    assert mark(crew_client, video.id, 5).status_code == 200      # sędzia z obsady
    nobody, _ = make_client()                                     # konto bez ról
    assert mark(nobody, video.id, 5).status_code == 403


def test_button_hidden_for_users_without_permission(make_client, db):
    crew_client, crew = make_client("referee")
    video = make_ready_video(db, make_match(db, officials=(("CC", crew), ("U1", "Kasia Żółć"))))
    outsider, _ = make_client("referee")
    assert 'id="btn-z"' in crew_client.get(f"/videos/{video.id}").text
    page = outsider.get(f"/videos/{video.id}").text      # może oglądać, nie zaznacza
    assert 'id="btn-z"' not in page and 'id="btn-undo"' not in page and "window.CAN_CLIP = false" in page
    assert 'id="btn-q"' not in page and "window.CAN_MARK = false" in page


def test_referee_removed_from_crew_loses_access(make_client, db):
    ref_client, ref = make_client("referee")
    match = make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć")))
    video = make_ready_video(db, match)
    assert mark(ref_client, video.id, 5).status_code == 200
    match.officials = [o for o in match.officials if o.user_id != ref.id]
    db.commit()
    assert mark(ref_client, video.id, 50).status_code == 403


# --- usuwanie i cofanie ---------------------------------------------------------------------
def with_file(db, clip_id):
    clip = fresh(db, clip_id)
    clip.clip_path, clip.status = f"clips/{clip_id}_v1.mp4", "cut"
    with storage.open_write(clip.clip_path) as fh:
        fh.write(b"clip")
    db.commit()
    return clip.clip_path


def test_delete_marker_removes_clip_file(client, db):
    video = make_ready_video(db, make_match(db))
    clip_id = mark(client, video.id, 100).json()["marker"]["id"]
    key = with_file(db, clip_id)
    assert storage.exists(key)
    r = client.delete(f"/api/clips/{clip_id}")
    assert r.status_code == 200 and r.json()["clips"] == []
    assert fresh(db, clip_id) is None and not storage.exists(key)
    assert db.scalar(select(Job).where(Job.clip_id == clip_id)) is None


def test_deleting_a_described_marker_needs_confirmation(client, db):
    video = make_ready_video(db, make_match(db))
    clip_id = mark(client, video.id, 100).json()["marker"]["id"]
    clip = fresh(db, clip_id)
    clip.described_at = utcnow()
    db.commit()
    key = with_file(db, clip_id)
    r = client.delete(f"/api/clips/{clip_id}")
    assert r.status_code == 409 and "opisany" in r.json()["detail"]
    assert fresh(db, clip_id) is not None and storage.exists(key)
    assert client.delete(f"/api/clips/{clip_id}", params={"confirm": "true"}).status_code == 200
    assert fresh(db, clip_id) is None and not storage.exists(key)


def test_delete_marker_permissions(make_client, db, client):
    owner, _ = make_client("coach")
    other, _ = make_client("coach")
    video = make_ready_video(db, make_match(db))
    clip_id = mark(owner, video.id, 100).json()["marker"]["id"]
    state = other.get(f"/api/videos/{video.id}/state").json()
    assert state["clips"][0]["mine"] is False and state["clips"][0]["can_delete"] is False
    assert other.delete(f"/api/clips/{clip_id}").status_code == 403    # cudzy znacznik
    assert client.delete(f"/api/clips/{clip_id}").status_code == 200    # administrator może wszystko


def test_undo_removes_only_own_latest_undescribed_marker(make_client, db, no_debounce):
    me, _ = make_client("coach")
    other, _ = make_client("coach")
    video = make_ready_video(db, make_match(db))
    a = mark(me, video.id, 10).json()["marker"]["id"]
    b = mark(me, video.id, 20).json()["marker"]["id"]
    theirs = mark(other, video.id, 30).json()["marker"]["id"]
    described = fresh(db, b)
    described.described_at = utcnow()
    db.commit()
    key = with_file(db, a)
    # najnowszy własny nieopisany to a (b jest opisany, theirs jest cudzy)
    r = me.post(f"/api/videos/{video.id}/markers/undo")
    assert r.status_code == 200 and r.json()["removed"] == a and r.json()["time_sec"] == 10
    assert fresh(db, a) is None and not storage.exists(key)
    assert fresh(db, b) is not None and fresh(db, theirs) is not None
    r = me.post(f"/api/videos/{video.id}/markers/undo")                 # nic więcej do cofnięcia
    assert r.status_code == 404
    assert fresh(db, b) is not None and fresh(db, theirs) is not None


# --- nagranie bez pełnej wersji ----------------------------------------------------------------
def purge(db, video):
    storage.delete(video.proxy_path)
    video.proxy_path, video.purged_at = None, utcnow()
    db.commit()


def test_purged_video_has_no_player_and_no_markers(client, db):
    video = make_ready_video(db, make_match(db))
    clip_id = mark(client, video.id, 100).json()["marker"]["id"]
    purge(db, video)
    page = client.get(f"/videos/{video.id}")
    assert page.status_code == 200
    assert "Pełne nagranie zostało usunięte" in page.text and "<video" not in page.text
    assert 'id="purged-banner"' in page.text and "player.js" not in page.text
    assert mark(client, video.id, 5).status_code == 409
    assert client.post(f"/api/videos/{video.id}/markers/undo").status_code == 409
    assert client.post(f"/api/videos/{video.id}/quick-clip", json={"time_sec": 5, "text": "x"}).status_code == 409
    assert client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 5}).status_code == 409
    assert client.get(f"/videos/{video.id}/notes").status_code == 409
    assert client.get(f"/videos/{video.id}/stream").status_code == 409
    assert fresh(db, clip_id) is not None   # klipy zostają
    assert "Odtwarzacz" not in client.get(f"/matches/{video.match_id}").text.split("Klipy (")[0]


def test_marker_on_video_that_is_not_ready_is_refused(client, db):
    video = make_ready_video(db, make_match(db))
    video.status = "processing"
    db.commit()
    assert mark(client, video.id, 5).status_code == 409
    assert "Wersja robocza nie jest jeszcze gotowa" in client.get(f"/videos/{video.id}").text


# --- strona odtwarzacza ------------------------------------------------------------------------
def test_player_page_state_and_shortcuts_help(client, db):
    video = make_ready_video(db, make_match(db))
    page = client.get(f"/videos/{video.id}").text
    for text in ('id="btn-z"', "Zaznacz (Z)", 'id="help"', "Początki kwart", 'id="marks-banner"',
                 'controlsList="nofullscreen"', "Cofnij (Backspace)"):
        assert text in page, text
    state = init_state(page)
    assert state["missing_periods"] == ["Q1", "Q2", "Q3", "Q4"] and state["next_period"] == "Q1"
    assert [p["period"] for p in state["periods"]] == ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"]
    assert [p["required"] for p in state["periods"]] == [True] * 4 + [False] * 3


def test_client_debounce_matches_server_window():
    """Okno ochrony przed podwójnym Z jest w dwóch miejscach (serwer: config, klient: player.js) —
    muszą się zgadzać, bo testy interfejsu czekają na koniec obu."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "player.js").read_text(encoding="utf-8")
    ms = int(re.search(r"const DEBOUNCE_MS = (\d+);", js).group(1))
    assert ms == config.MARKER_DEBOUNCE_SECONDS * 1000
