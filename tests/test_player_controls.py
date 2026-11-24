"""Every page with a video loads Video.js and the shared player script (player_controls.js) and marks its <video>."""
import re
from datetime import datetime

import pytest

from app import share, training_sets
from app.models import Clip
from app.storage import storage
from app.web import asset
from tests.helpers import category_named, make_match, make_ready_video, mark_periods

MARKER = "data-controls-strip"
SCRIPT = f'<script src="{asset("player_controls.js")}"></script>'
VENDOR = "/static/vendor/videojs-8.24.1/"


@pytest.fixture()
def world(db, make_client):
    coach_client, coach = make_client("coach", name="Trener")
    match = make_match(db, created_by=coach)
    video = mark_periods(db, make_ready_video(db, match))
    video.fps = 30.0
    db.commit()

    def clip(*, described=True, status="cut"):
        row = Clip(match_id=match.id, video_id=video.id, author_id=coach.id, time_sec=100.0,
                   official_id=match.official("CC").id, category_id=category_named(db, "kroki"),
                   description="Opis", status=status, described_at=datetime(2026, 10, 29) if described else None)
        db.add(row)
        db.commit()
        if status == "cut":
            row.clip_path, row.clip_version = f"clips/{row.id}_v1.mp4", 1
            with storage.open_write(row.clip_path) as fh:
                fh.write(b"x" * 64)
            db.commit()
        return row

    return {"client": coach_client, "user": coach, "match": match, "video": video, "clip": clip, "db": db}


def video_tags(html):
    return re.findall(r"<video\b[^>]*>", html)


def test_match_player_has_a_clickable_fullscreen_and_no_keyboard_only_markup(world):
    page = world["client"].get(f"/videos/{world['video'].id}").text
    assert page.index(VENDOR + "video.min.js") < page.index("/static/player_controls.js") < page.index("/static/player.js")
    assert VENDOR + "video-js.min.css" in page and VENDOR + "pl.js" in page
    # the control bar is built by Video.js; the old template-only controls and the native full screen block are gone
    assert 'id="btn-fs"' not in page and "fs-only" not in page and 'id="speed"' not in page
    assert "nofullscreen" not in page and "playsinline" in video_tags(page)[0]
    for text in ('id="btn-z"', 'id="btn-undo"', 'id="video-wrap"', 'id="timeline"'):
        assert text in page


def test_clip_page_video_gets_the_strip_with_the_recording_fps(world):
    clip = world["clip"]()
    page = world["client"].get(f"/clips/{clip.id}").text
    [tag] = video_tags(page)
    assert MARKER in tag and 'data-fps="30.0"' in tag and "playsinline" in tag
    assert SCRIPT in page


def test_clip_page_without_a_cut_file_loads_no_video(world):
    clip = world["clip"](status="new")
    page = world["client"].get(f"/clips/{clip.id}").text
    assert video_tags(page) == []


def test_describe_screen_preview_gets_the_strip(world):
    clip = world["clip"](described=False)
    page = world["client"].get(f"/matches/{world['match'].id}/describe?clip={clip.id}").text
    [tag] = video_tags(page)
    assert MARKER in tag and 'data-fps="30.0"' in tag
    assert page.index("/static/player_controls.js") < page.index("/static/describe.js")


def test_draft_preview_keeps_its_range_attributes(world):
    clip = world["clip"](described=False, status="new")
    page = world["client"].get(f"/matches/{world['match'].id}/describe?clip={clip.id}").text
    [tag] = video_tags(page)
    assert MARKER in tag and "data-start=" in tag and "data-end=" in tag


def test_training_set_clip_view_gets_the_strip(world):
    clip = world["clip"]()
    training_set = training_sets.create_set(world["db"], world["user"], "Zestaw")
    training_sets.add_clip(world["db"], training_set, clip)
    world["db"].commit()
    page = world["client"].get(f"/sets/{training_set.id}/clips/{clip.id}").text
    [tag] = video_tags(page)
    assert MARKER in tag and 'data-fps="30.0"' in tag
    assert SCRIPT in page


def test_public_share_page_gets_the_strip_without_new_data(world, client):
    first, second = world["clip"](), world["clip"]()
    _, code = share.create_link(world["db"], world["user"], [str(first.id), str(second.id)], "7")
    page = client.get(f"/s/{code}").text
    tags = video_tags(page)
    assert len(tags) == 2 and all(MARKER in t and 'data-fps="30.0"' in t and "playsinline" in t for t in tags)
    assert SCRIPT in page
    for secret in ("Trener", "Legia", "Wisła", "Kowalski"):
        assert secret not in page


def test_video_js_is_vendored_and_only_pages_with_a_player_load_it(world, client):
    from pathlib import Path
    folder = Path(__file__).resolve().parents[1] / "app" / "static" / "vendor" / "videojs-8.24.1"
    assert sorted(p.name for p in folder.iterdir()) == ["LICENSE", "pl.js", "video-js.min.css", "video.min.js"]
    assert "Video.js 8.24.1" in (folder / "video.min.js").read_text()[:400]
    assert client.get(VENDOR + "video.min.js").status_code == 200
    for path in ("/", "/clips", "/matches"):
        page = world["client"].get(path).text
        assert "videojs" not in page and "player_controls" not in page
    page = world["client"].get(f"/videos/{world['video'].id}").text
    assert page.count(VENDOR + "video.min.js") == 1
    assert "cdn" not in page
