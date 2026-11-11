import re
from datetime import datetime, timedelta

import pytest

from app import config
from app.models import Clip
from app.pagination import paginate, parse_page
from app.storage import storage
from tests.helpers import make_match, make_ready_video, mark_periods
from tests.test_retention import ready

DONE = datetime(2026, 10, 29, 12, 0)


@pytest.mark.parametrize("total,requested,size,expected", [
    (0, 1, 25, (1, 1)),    # empty list: one empty page, not zero pages
    (25, 1, 25, (1, 1)),   # exact multiple does not add a page
    (26, 1, 25, (1, 2)),
    (50, 2, 25, (2, 2)),
    (50, 3, 25, (2, 2)),   # past the end: the last page
    (50, 999, 25, (2, 2)),
])
def test_page_is_clamped_to_the_existing_range(total, requested, size, expected):
    page = paginate(total, requested, size)
    assert (page.page, page.pages) == expected and page.offset == (expected[0] - 1) * size


@pytest.mark.parametrize("raw,expected", [("2", 2), ("0", 1), ("-4", 1), ("abc", 1), ("", 1), (None, 1), ("1e3", 1)])
def test_invalid_page_numbers_mean_the_first_page(raw, expected):
    assert parse_page(raw) == expected


@pytest.fixture()
def world(db, client, monkeypatch):
    """Five clips: three in an older match, two in a newer one, 2 per page."""
    monkeypatch.setattr(config, "CLIP_PAGE_SIZE", 2)
    old, new = make_match(db), make_match(db)
    clips = {}
    for match, name, times in ((old, "old", (10, 400, 410)), (new, "new", (20, 30))):
        video = mark_periods(db, make_ready_video(db, match), times=(0.0, 300.0, 600.0, 900.0))
        for i, t in enumerate(times, start=1):
            clips[f"{name}{i}"] = Clip(match_id=match.id, video_id=video.id, time_sec=t, status="cut",
                                       clip_path=f"clips/{name}{i}.mp4", described_at=DONE if i != 2 else None)
    db.add_all(clips.values())
    db.commit()
    for clip in clips.values():
        with storage.open_write(clip.clip_path) as fh:
            fh.write(b"x" * 100)
    return clips, old, new


def listed(client, url="/clips", **params):
    page = client.get(url, params=params).text
    return [int(i) for i in re.findall(r'<td data-label="Sędzia" class="main-cell"><a href="/clips/(\d+)', page)], page


@pytest.mark.parametrize("params,pages", [
    ({}, [["new1", "new2"], ["old1", "old2"], ["old3"]]),
    ({"described": "1"}, [["new1", "old1"], ["old3"]]),
    ({"described": "0"}, [["new2", "old2"]]),  # exactly one full page: no second, empty one
    ({"period": "Q1"}, [["new1", "new2"], ["old1"]]),  # derived from the quarter markers
    ({"period": "Q2"}, [["old2", "old3"]]),
])
def test_clip_list_pages_keep_every_filter(client, world, params, pages):
    clips, *_ = world
    for number, names in enumerate(pages, start=1):
        ids, page = listed(client, **params, page=number)
        assert ids == [clips[n].id for n in names]
        assert f"strona {number} z {len(pages)}" in page
    if len(pages) > 1:
        link = re.search(r'href="(/clips\?[^"]*page=2)"', listed(client, **params)[1]).group(1)
        assert all(f"{k}={v}" in link for k, v in params.items())
    assert listed(client, **params, page=len(pages) + 1)[0] == [clips[n].id for n in pages[-1]]


@pytest.mark.parametrize("page,expected", [("99", ["old3"]), ("0", ["new1", "new2"]), ("-1", ["new1", "new2"]),
                                           ("x", ["new1", "new2"])])
def test_clip_list_page_out_of_range_or_invalid(client, world, page, expected):
    ids, _ = listed(client, page=page)
    assert ids == [world[0][n].id for n in expected]


def test_empty_clip_list_has_no_pager(client, db):
    _, page = listed(client, page=3)
    assert "Brak klipów" in page and "strona" not in page


def test_clip_page_neighbours_cross_the_list_page_boundary(client, world):
    clips, *_ = world

    def neighbours(clip, **params):
        page = client.get(f"/clips/{clip.id}", params=params).text
        return [re.search(rf'id="{side}-clip"[^>]*href="([^"]*)"', page) and
                re.search(rf'id="{side}-clip"[^>]*href="([^"]*)"', page).group(1) for side in ("prev", "next")]

    # old2 ends page 2 of the list and old3 is alone on page 3, yet they are neighbours
    assert neighbours(clips["old2"]) == [f"/clips/{clips['old1'].id}", f"/clips/{clips['old3'].id}"]
    assert neighbours(clips["old3"], described="1", page=3)[0] == f"/clips/{clips['old1'].id}?described=1"


def test_sharing_selection_works_on_the_second_page(client, world):
    clips, *_ = world
    _, page2 = listed(client, page=2)
    assert f'class="share-check" name="clip_ids" value="{clips["old1"].id}"' in page2
    assert "share-bar hidden" not in page2 and 'form="share-form"' in page2
    ids = [clips["new1"].id, clips["old3"].id]  # one clip from the first page, one from the last
    r = client.post("/share-links", data={"clip_ids": ids, "days": "7"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/share-links/created"


def test_match_clip_tab_is_paginated_and_polls_its_own_page(client, db, world, monkeypatch):
    clips, old, _ = world
    page = client.get(f"/matches/{old.id}", params={"described": "1"}).text
    assert "Klipy: 2 · strona 1 z 1" in page and "Klipy (3, nieopisane: 1)" in page
    second = client.get(f"/matches/{old.id}", params={"page": 2}).text
    assert "strona 2 z 2" in second and f'href="/clips/{clips["old3"].id}"' in second
    assert f'hx-get="/matches/{old.id}?page=2" hx-target="#clips-list"' in client.get(f"/matches/{old.id}").text
    clips["old3"].status = "queued"
    db.commit()
    monkeypatch.setattr(config, "CLIP_PAGE_SIZE", 1)
    polling = client.get(f"/matches/{old.id}", params={"page": 2, "described": "1"}).text
    assert re.search(rf'<div id="clips-list" hx-get="/matches/{old.id}\?described=1&amp;page=2" hx-trigger="every 3s"',
                     polling)


def test_retention_video_list_pages_by_deadline(client, db, monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PAGE_SIZE", 2)
    soon, later, none = ready(db, expires_in_days=2), ready(db, expires_in_days=9), ready(db)
    none.expires_at = None
    db.commit()

    def shown(**params):
        page = client.get("/admin/retention", params=params).text
        return [int(i) for i in re.findall(r'<tr data-video="(\d+)"', page)], page

    assert shown()[0] == [soon.id, later.id] and "Nagrania (3)" in shown()[1]
    ids, page = shown(page=2)
    assert ids == [none.id] and "strona 2 z 2" in page and 'href="/admin/retention">‹ Poprzednie' in page
    assert shown(page=50)[0] == [none.id]
