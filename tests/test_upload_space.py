import pytest

from app import config, uploads
from app.storage import storage
from app.web import gb_label
from tests.helpers import make_match, tus_create, tus_patch


@pytest.fixture()
def space(monkeypatch):
    monkeypatch.setattr(config, "DRAFT_RESERVE_BYTES", 1000)
    monkeypatch.setattr(config, "DISK_SAFETY_BYTES", 500)
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 8000)

    def set_free(value):
        monkeypatch.setattr(storage, "free_bytes", lambda: value)
    return set_free


@pytest.mark.parametrize("value,label", [
    (6 * config.GB, "6 GB"), (int(8.47 * config.GB), "8,4 GB"), (int(0.99 * config.GB), "0,9 GB"), (0, "0 GB")])
def test_gb_label_is_polish_and_rounds_down(value, label):
    assert gb_label(value) == label


def test_acceptable_size_matches_what_check_space_lets_through(client, db, space):
    match = make_match(db)
    space(5000)
    assert uploads.acceptable_bytes(db) == 5000 - 1000 - 500
    assert tus_create(client, match.id, 3501).status_code == 507
    assert tus_create(client, match.id, 3500).status_code == 201


def test_own_unfinished_upload_does_not_shrink_the_room_for_the_same_file(make_client, db, space):
    a, user = make_client("admin")
    other, _ = make_client("coach")
    match = make_match(db)
    space(10_000)
    url = tus_create(a, match.id, 4000).headers["Location"]
    tus_patch(a, url, 0, b"x" * 1000)
    space(9000)  # the written kilobyte is on the disk now
    assert uploads.acceptable_bytes(db, user) == 10_000 - 1000 - 500  # restarting frees its file and reservation
    assert uploads.acceptable_bytes(db) == 9000 - (5000 - 1000) - 1000 - 500
    assert other.get("/api/upload-space").json()["acceptable_bytes"] == 3500


def test_space_endpoint_reports_limit_room_and_the_active_upload(client, db, space):
    match = make_match(db)
    space(100_000)
    body = client.get("/api/upload-space").json()
    assert body == {"max_bytes": 8000, "acceptable_bytes": 8000, "acceptable_label": gb_label(8000),
                    "note": "", "active": None}
    tus_create(client, match.id, 4000, filename="mecz.mov")
    assert client.get("/api/upload-space").json()["active"] == {"filename": "mecz.mov", "size": 4000}


def test_space_endpoint_needs_upload_rights(make_client):
    guest, _ = make_client("referee")
    viewer, _ = make_client()
    assert guest.get("/api/upload-space").status_code == 200
    assert viewer.get("/api/upload-space").status_code == 403


def test_form_shows_the_limit_and_warns_only_when_space_is_short(client, db, monkeypatch):
    match = make_match(db)
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 6 * config.GB)
    monkeypatch.setattr(config, "DRAFT_RESERVE_BYTES", 0)
    monkeypatch.setattr(config, "DISK_SAFETY_BYTES", 0)
    monkeypatch.setattr(storage, "free_bytes", lambda: 100 * config.GB)
    page = client.get(f"/matches/{match.id}").text
    assert "maks. 6 GB każdy" in page and 'id="upload-space" class="warn-text" aria-live="polite" hidden' in page
    monkeypatch.setattr(storage, "free_bytes", lambda: int(4.25 * config.GB))
    assert "Na serwerze zmieści się teraz plik do 4,2 GB." in client.get(f"/matches/{match.id}").text
    monkeypatch.setattr(storage, "free_bytes", lambda: config.GB // 2)
    assert "brakuje teraz miejsca" in client.get(f"/matches/{match.id}").text
