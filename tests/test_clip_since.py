import re
from datetime import date

import pytest

from app import clip_list, config
from app.models import Clip
from tests.helpers import make_match, make_ready_video


@pytest.fixture()
def clips(db):
    """One clip in a match on each of three dates; returns {date: clip id}."""
    found = {}
    for day in (date(2026, 8, 1), date(2026, 9, 15), date(2026, 10, 30)):
        match = make_match(db)
        match.date = day
        db.commit()
        clip = Clip(match_id=match.id, video_id=make_ready_video(db, match).id, time_sec=5.0, status="cut")
        db.add(clip)
        db.commit()
        found[day] = clip.id
    return found


def listed(client, **params) -> set[int]:
    r = client.get("/clips", params=params)
    assert r.status_code == 200
    return {int(i) for i in re.findall(r'href="/clips/(\d+)[?"]', r.text)}


def test_since_keeps_clips_from_matches_on_or_after_the_date(client, clips):
    assert listed(client) == set(clips.values())
    assert listed(client, since="2026-09-15") == {clips[date(2026, 9, 15)], clips[date(2026, 10, 30)]}
    assert listed(client, since="2026-09-16") == {clips[date(2026, 10, 30)]}
    assert listed(client, since="2026-11-01") == set()


def test_an_invalid_since_is_ignored(client, clips):
    for bad in ("", "wczoraj", "2026-13-40", "15.09.2026"):
        assert listed(client, since=bad) == set(clips.values())
    assert clip_list.parse_filters({"since": "nonsense"}).since is None
    assert not clip_list.parse_filters({"since": "nonsense"}).active


def test_since_combines_with_other_filters_and_shows_as_a_chip_and_a_field(client, clips):
    page = client.get("/clips", params={"since": "2026-09-15"}).text
    assert "Mecze od 15.09.2026" in page and 'name="since" value="2026-09-15"' in page
    assert 'href="/clips"' in page  # the chip's remove link
    assert 'id="since-chip"' not in client.get("/clips").text


def test_since_survives_pagination_and_the_clip_page_navigation(client, clips, monkeypatch):
    monkeypatch.setattr(config, "CLIP_PAGE_SIZE", 1)
    first = client.get("/clips", params={"since": "2026-09-15"}).text
    assert "strona 1 z 2" in first and "page=2" in first
    assert re.search(r'href="/clips\?[^"]*since=2026-09-15[^"]*page=2"', first)
    second = client.get("/clips", params={"since": "2026-09-15", "page": "2"}).text
    assert "strona 2 z 2" in second
    assert listed(client, since="2026-09-15", page="1") | listed(client, since="2026-09-15", page="2") == {
        clips[date(2026, 9, 15)], clips[date(2026, 10, 30)]}
    assert 'href="/clips/%d?since=2026-09-15"' % clips[date(2026, 10, 30)] in first + second
    assert "since=2026-09-15" in clip_list.parse_filters({"since": "2026-09-15", "page": "2"}).page_query(3)
