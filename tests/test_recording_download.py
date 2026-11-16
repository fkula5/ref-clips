from types import SimpleNamespace

import pytest

from app import services
from app.storage import storage
from tests.helpers import make_match, make_ready_video

CONTENT = b"fakevideo-bytes"


@pytest.fixture()
def world(db, make_client):
    crew_client, crew = make_client("referee", name="Sędzia Z Obsady")
    out_client, _ = make_client("referee", name="Sędzia Spoza Obsady")
    coach_client, coach = make_client("coach", name="Trener Jan")
    admin_client, _ = make_client("admin", name="Szef")
    plain_client, _ = make_client()
    match = make_match(db, officials=(("CC", crew), ("U1", "Kasia Żółć")), created_by=coach)
    video = make_ready_video(db, match, content=CONTENT)
    video.proxy_bytes = len(CONTENT)
    db.commit()
    return SimpleNamespace(db=db, match=match, video=video, crew=crew_client, outsider=out_client,
                           coach=coach_client, admin=admin_client, plain=plain_client)


def url(world):
    return f"/videos/{world.video.id}/download"


@pytest.mark.parametrize("who,status", [("crew", 200), ("coach", 200), ("admin", 200),
                                        ("outsider", 403), ("plain", 403)])
def test_who_may_download(world, who, status):
    r = getattr(world, who).get(url(world))
    assert r.status_code == status
    assert (r.content == CONTENT) is (status == 200)


def test_anonymous_is_refused(world, anon_client):
    r = anon_client.get(url(world), follow_redirects=False)
    assert r.status_code in (303, 401) and not r.content.startswith(CONTENT)


def test_unknown_video_is_404(world):
    assert world.coach.get("/videos/99999/download").status_code == 404


def test_purged_recording_is_409(world):
    world.video.purged_at = world.video.created_at
    world.db.commit()
    r = world.coach.get(url(world))
    assert r.status_code == 409 and "usunięte" in r.text


def test_recording_that_is_not_ready_is_409(world):
    world.video.status = "processing"
    world.db.commit()
    assert world.coach.get(url(world)).status_code == 409


def test_missing_file_is_409(world):
    storage.delete(world.video.proxy_path)
    assert world.coach.get(url(world)).status_code == 409


def test_download_is_an_attachment_named_from_match_data(world):
    r = world.crew.get(url(world))
    assert r.headers["content-disposition"] == 'attachment; filename="2026-10-28_Legia-Wisla_Calosc.mp4"'
    assert r.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize("label,content,team_a,team_b,expected", [
    ("", "full", "Legia", "Wisła", "2026-10-28_Legia-Wisla_caly-mecz.mp4"),
    ("", "Q1,Q2", "Legia", "Wisła", "2026-10-28_Legia-Wisla_kwarty-Q1-Q2.mp4"),
    ("", "Q3", "", "", "2026-10-28_kwarta-Q3.mp4"),
    ("Kamera / boczna", "full", "Śląsk Wrocław", "", "2026-10-28_Slask-Wroclaw_Kamera-boczna.mp4"),
    ("../../etc\\passwd\n", "full", "A\"B", "C;D", "2026-10-28_A-B-C-D_etc-passwd.mp4"),
])
def test_filename_is_ascii_and_safe(world, label, content, team_a, team_b, expected):
    world.video.label, world.video.content = label, content
    world.match.team_a_name, world.match.team_b_name = team_a, team_b
    world.db.commit()
    assert services.recording_filename(world.video) == expected


def test_filename_has_no_referee_names_and_keeps_long_parts_short(world):
    world.match.team_a_name = "Bardzo Długa Nazwa Drużyny Koszykarskiej Z Miasta Wojewódzkiego"
    world.db.commit()
    name = services.recording_filename(world.video)
    assert "Kowalski" not in name and "Obsady" not in name and "Kasia" not in name
    assert len(name) < 100 and name.isascii()


def panel(client, world):
    r = client.get(f"/matches/{world.match.id}/videos-panel")
    assert r.status_code == 200
    return r.text


def test_link_is_shown_only_to_those_who_may_download(world):
    link = f'href="/videos/{world.video.id}/download"'
    for who in ("crew", "coach", "admin"):
        text = panel(getattr(world, who), world)
        assert link in text and " download>" in text
        assert "Pobierz nagranie" in text and "720p" in text and "15 B" in text
    for who in ("outsider", "plain"):
        text = panel(getattr(world, who), world)
        assert link not in text and "Pobierz nagranie" not in text and "720p" not in text


def test_link_is_also_on_the_match_page(world):
    assert f'href="/videos/{world.video.id}/download"' in world.crew.get(f"/matches/{world.match.id}").text
    assert f'href="/videos/{world.video.id}/download"' not in world.outsider.get(f"/matches/{world.match.id}").text


def test_no_link_while_the_recording_is_not_downloadable(world):
    link = f'href="/videos/{world.video.id}/download"'
    world.video.status = "processing"
    world.db.commit()
    assert link not in panel(world.coach, world)
    world.video.status = "ready"
    world.video.purged_at = world.video.created_at
    world.db.commit()
    assert link not in panel(world.coach, world)


def test_size_is_left_out_when_unknown(world):
    world.video.proxy_bytes = None
    world.db.commit()
    text = panel(world.coach, world)
    assert "Pobierz nagranie</a>" in text
