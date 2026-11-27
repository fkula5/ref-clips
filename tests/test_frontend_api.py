from app.models import Clip, Comment, Rating
from app.services import clip_range
from app.storage import storage
from tests.helpers import PASSWORD, make_match, make_ready_video, make_user


BASE = "/api/frontend"


def test_anonymous_session_and_matches_require_login(anon_client):
    for path in ("/session", "/matches", "/matches/1", "/clips/1"):
        response = anon_client.get(BASE + path)
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")


def test_login_csrf_session_and_logout(anon_client, db):
    user = make_user(db)
    credentials = {"email": user.email, "password": PASSWORD}
    assert anon_client.post(BASE + "/login", data=credentials).status_code == 403
    bootstrap = anon_client.get(BASE + "/csrf")
    assert bootstrap.headers["Cache-Control"] == "no-store"
    headers = {"X-CSRF-Token": bootstrap.json()["csrf_token"]}
    invalid = anon_client.post(BASE + "/login", data={**credentials, "password": "wrong"}, headers=headers)
    assert invalid.status_code == 401
    response = anon_client.post(BASE + "/login", data=credentials, headers=headers)
    assert response.status_code == 200
    assert response.json()["user"]["id"] == user.id
    assert "password_hash" not in response.text
    session = anon_client.get(BASE + "/session")
    assert session.json()["csrf_token"] == response.json()["csrf_token"]
    assert session.headers["Cache-Control"] == "no-store"
    assert anon_client.post(BASE + "/logout").status_code == 403
    assert anon_client.post(BASE + "/logout", headers=headers).status_code == 403
    assert anon_client.post(BASE + "/logout", headers={"X-CSRF-Token": session.json()["csrf_token"]}).status_code == 204
    assert anon_client.get(BASE + "/session").status_code == 401


def test_matches_filters_and_pagination(make_client, db):
    client, user = make_client("referee")
    own = make_match(db, created_by=user)
    make_match(db)
    response = client.get(BASE + "/matches?mine=1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == own.id
    assert data["items"][0]["teams"] == "Legia – Wisła"
    assert data["items"][0]["officials"][0]["name"]
    assert data["items"][0]["state"]["label"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(BASE + "/matches?date_from=2027-01-01").json()["total"] == 0
    assert client.get(BASE + "/matches?level=Nieistniejąca").json()["total"] == 0
    assert client.get(BASE + "/matches?date_from=bad").json()["errors"]
    assert client.get(BASE + "/matches?page=999").json()["page"] == 1


def test_match_detail_scopes_clips_and_preserves_recording_permissions(db, make_client):
    client, _ = make_client("referee")
    match = make_match(db)
    other = make_match(db)
    video = make_ready_video(db, match)
    other_video = make_ready_video(db, other)
    clip = Clip(match_id=match.id, video_id=video.id, time_sec=74, description="Kontakt")
    db.add_all([clip, Clip(match_id=other.id, video_id=other_video.id, time_sec=80)])
    db.commit()

    response = client.get(f"{BASE}/matches/{match.id}?page=99")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == match.id
    assert data["videos"][0]["can_play"] is True
    assert data["can_edit"] is False
    assert data["can_upload"] is False
    assert data["clips"]["page"] == 1
    assert [item["id"] for item in data["clips"]["items"]] == [clip.id]
    assert "proxy_path" not in data["videos"][0]

    video.purged_at = match.created_at
    db.commit()
    assert client.get(f"{BASE}/matches/{match.id}").json()["videos"][0]["can_play"] is False
    assert client.get(f"{BASE}/matches/99999").status_code == 404


def test_clip_detail_exposes_feedback_and_only_available_media(db, make_client):
    client, user = make_client("coach")
    match = make_match(db)
    recording = make_ready_video(db, match)
    clip = Clip(match_id=match.id, video_id=recording.id, time_sec=74, status="queued")
    db.add(clip)
    db.flush()
    db.add_all([
        Rating(clip_id=clip.id, coach_id=user.id, verdict="correct", comment="Dobra decyzja."),
        Comment(clip_id=clip.id, author_id=user.id, body="Sprawdź ustawienie.\nDruga linia."),
    ])
    db.commit()
    url = f"{BASE}/clips/{clip.id}"
    response = client.get(url)
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["stream_url"] is None
    assert data["status_key"] == "queued"
    assert data["unavailable"] is False
    assert data["recording_url"] == f"/videos/{recording.id}?t=74.0"
    assert data["ratings"][0]["verdict"] == "prawidłowa"
    assert data["comments"][0]["text"] == "Sprawdź ustawienie.\nDruga linia."

    clip.status = "cut"
    clip.clip_path = f"clips/{clip.id}.mp4"
    clip.clip_version = 2
    db.commit()
    assert client.get(url).json()["unavailable"] is True
    with storage.open_write(clip.clip_path) as file:
        file.write(b"test clip")
    assert client.get(url).json()["stream_url"] == f"/clips/{clip.id}/file?v=2"
    assert client.get(f"{BASE}/clips/99999").status_code == 404


def test_cut_and_adjust_recording_range(db, make_client):
    owner, referee = make_client("referee")
    visitor, _ = make_client("referee")
    match = make_match(db, officials=(("CC", referee), ("U1", "Kasia Żółć")), created_by=referee)
    recording = make_ready_video(db, match)
    path = f"/api/videos/{recording.id}/clips"
    assert visitor.post(path, json={"start": 4.25, "end": 9.75}).status_code == 403
    assert owner.post(path, json={"start": 9, "end": 4}).status_code == 422

    response = owner.post(path, json={"start": 4.25, "end": 9.75})
    assert response.status_code == 201
    clip = db.get(Clip, response.json()["clip_id"])
    assert clip_range(clip) == (4.25, 9.75)
    assert clip.status == "queued"

    edit = f"/api/clips/{clip.id}/range"
    detail = f"{BASE}/clips/{clip.id}"
    assert visitor.get(detail).json()["adjust"] is None
    assert visitor.post(edit, json={"start": 3.5, "end": 10.25}).status_code == 403
    assert owner.post(edit, json={"start": 7.5, "end": 10.25}).status_code == 422
    assert owner.post(edit, json={"start": 3.5, "end": 10.25}).status_code == 204
    db.refresh(clip)
    assert clip_range(clip) == (3.5, 10.25)
    assert owner.get(detail).json()["adjust"]["start"] == 3.5


def test_vue_writes_use_existing_match_and_feedback_rules(db, make_client):
    coach, user = make_client("coach")
    referee, _ = make_client("referee")
    json = {"Accept": "application/json"}
    form = coach.get("/matches/new", headers=json).json()["values"]
    response = coach.post("/matches", data=form, headers=json)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    form.update(cc_name="Anna Nowak", u1_name="Ewa Nowak", team_a_name="Legia")
    response = coach.post("/matches", data=form, headers=json)
    assert response.status_code == 201
    match_id = response.json()["id"]
    assert coach.get(f"/matches/{match_id}/edit", headers=json).json()["values"]["team_a_name"] == "Legia"
    assert referee.get(f"/matches/{match_id}/edit", headers=json).status_code == 403
    match = make_match(db, created_by=user)
    video = make_ready_video(db, match)
    clip = Clip(match_id=match.id, video_id=video.id, time_sec=60)
    db.add(clip)
    db.commit()
    assert referee.post(f"/clips/{clip.id}/rating", data={"verdict": "correct"}, headers=json).status_code == 403
    assert coach.post(f"/clips/{clip.id}/rating", data={"verdict": "correct"}, headers=json).status_code == 204
    assert coach.post(f"/clips/{clip.id}/comments", data={"body": "Sprawdź decyzję."}, headers=json).status_code == 204
    library = coach.get(f"{BASE}/clips?match_id={match.id}&rating=correct").json()
    assert [item["id"] for item in library["items"]] == [clip.id]
    assert library["items"][0]["comments"] == 1


def test_vue_notes_preview_and_commit(db, make_client):
    coach, user = make_client("coach")
    match = make_match(db, created_by=user)
    video = make_ready_video(db, match)
    preview = coach.post(f"/api/videos/{video.id}/notes/preview", json={"text": "1:14 kontakt\n99:00 poza"})
    assert preview.status_code == 200
    assert [row["in_range"] for row in preview.json()["rows"]] == [True, False]
    saved = coach.post(
        f"/videos/{video.id}/notes/commit",
        data={"count": "2", "include_0": "1", "time_0": "1:14", "desc_0": "Kontakt"},
        headers={"Accept": "application/json"},
    )
    assert saved.json() == {"created": 1, "skipped": 0}
    assert coach.get(f"/api/videos/{video.id}/state").json()["clips"][0]["description"] == "Kontakt"


def test_vue_training_and_assessment_workflows_keep_access_controls(db, make_client):
    coach, user = make_client("coach")
    outsider, _ = make_client("referee")
    json_headers = {"Accept": "application/json"}
    group = coach.post("/groups", data={"name": "Sędziowie"}, headers=json_headers).json()["id"]
    assert outsider.get(f"/groups/{group}", headers=json_headers).status_code == 404
    assert coach.get(f"/groups/{group}/review", headers=json_headers).json()["items"] == []
    training_set = coach.post("/sets", data={"name": "Szkolenie"}, headers=json_headers).json()["id"]
    assert coach.post(f"/sets/{training_set}/groups", data={"group_id": str(group)}, headers=json_headers).is_success
    assert coach.get(f"/groups/{group}", headers=json_headers).json()["pinned"][0]["id"] == training_set
    assert outsider.get(f"/sets/{training_set}", headers=json_headers).json()["can_edit"] is False

    match = make_match(db, created_by=user)
    response = coach.post(f"/matches/{match.id}/sheets", headers=json_headers)
    assert response.is_success
    sheet_id = response.json()["id"]
    sheet = coach.get(f"/sheets/{sheet_id}/edit", headers=json_headers).json()
    assert sheet["columns"] and sheet["can_edit"]
    assert outsider.get(f"/sheets/{sheet_id}", headers=json_headers).status_code == 404
    own = outsider.post("/self-assessments/new", headers=json_headers).json()["id"]
    assessment = outsider.get(f"/self-assessments/{own}/edit", headers=json_headers).json()
    assert assessment["match_id"] is None and assessment["questions"]
    assert coach.get(f"/self-assessments/{own}", headers=json_headers).status_code == 404


def test_vue_admin_data_excludes_credentials_and_uses_role_gates(admin, make_client):
    administrator, _ = admin
    referee, _ = make_client("referee")
    headers = {"Accept": "application/json"}
    assert referee.get("/admin/users", headers=headers).status_code == 403
    response = administrator.get("/admin/users", headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert all("password_hash" not in row for row in response.json()["items"])
    assert administrator.get("/admin/categories", headers=headers).json()["items"]
    assert "usage" in administrator.get("/admin/retention", headers=headers).json()
