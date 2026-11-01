from sqlalchemy import select

from app.models import Category, Clip, Comment, Job, Match, Video
from app.storage import storage
from tests.helpers import make_match, make_ready_video, make_user, tus_create, tus_upload

MATCH_FORM = {
    "date": "2026-10-28", "level": "II liga", "team_a_name": "Legia", "team_a_color": "białe",
    "team_b_name": "Wisła", "team_b_color": "ciemne",
    "cc_name": "Filip Kowalski", "u1_name": "Kasia Żółć",
}


def category_id(db, name):
    return db.scalar(select(Category.id).where(Category.name == name))


def quick(client, video_id, time_sec, text=""):
    return client.post(f"/api/videos/{video_id}/quick-clip", json={"time_sec": time_sec, "text": text})


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Mecze" in r.text and "Admin Testowy" in r.text


def test_create_and_edit_match_with_officials(client, db):
    ref = make_user(db, ["referee"], email="r@example.com", name="Robert Sędzia")
    form = {**MATCH_FORM, "cc_user": str(ref.id), "cc_name": "ignorowane", "u2_name": "Zenon Trzeci"}
    r = client.post("/matches", data=form, follow_redirects=False)
    assert r.status_code == 303
    match = db.scalar(select(Match))
    assert match.date.isoformat() == "2026-10-28" and match.created_by is not None
    got = {o.function: (o.user_id, o.name, o.display_name) for o in match.officials}
    assert got == {"CC": (ref.id, None, "Robert Sędzia"), "U1": (None, "Kasia Żółć", "Kasia Żółć"),
                   "U2": (None, "Zenon Trzeci", "Zenon Trzeci")}
    page = client.get(r.headers["location"])
    assert page.status_code == 200 and "Robert Sędzia" in page.text and "Zenon Trzeci" in page.text
    # edycja: usunięcie U2, zmiana CC na wpisane nazwisko
    form = {**MATCH_FORM, "cc_name": "Ktoś Inny"}
    assert client.post(f"/matches/{match.id}", data=form, follow_redirects=False).status_code == 303
    db.refresh(match)
    assert {o.function: o.display_name for o in match.officials} == {"CC": "Ktoś Inny", "U1": "Kasia Żółć"}


def test_match_form_validation(client, db):
    r = client.post("/matches", data={**MATCH_FORM, "u1_name": ""})
    assert r.status_code == 422 and "U1" in r.text
    r = client.post("/matches", data={**MATCH_FORM, "cc_user": "999"})
    assert r.status_code == 422
    coach = make_user(db, ["coach"], email="c@example.com")  # nie jest sędzią -> nie do obsady
    r = client.post("/matches", data={**MATCH_FORM, "cc_user": str(coach.id)})
    assert r.status_code == 422
    ref = make_user(db, ["referee"], email="r@example.com")
    r = client.post("/matches", data={**MATCH_FORM, "cc_user": str(ref.id), "u1_user": str(ref.id)})
    assert r.status_code == 422
    r = client.post("/matches", data={**MATCH_FORM, "date": "nie-data"})
    assert r.status_code == 422
    assert db.scalar(select(Match)) is None


def test_new_match_form_prefills_referee(make_client, db):
    ref_client, ref = make_client("referee", name="Rafał Sędzia")
    page = ref_client.get("/matches/new").text
    assert f'<option value="{ref.id}" selected>' in page
    admin_client, _ = make_client("admin")
    assert "selected>Rafał" not in admin_client.get("/matches/new").text


def test_upload_streams_to_disk_and_queues_transcode(client, db):
    match = make_match(db)
    payload = b"x" * (5 * 1024 * 1024)
    tus_upload(client, match.id, payload, filename="mecz ąę.mp4", chunk=2 * 1024 * 1024, label="Całość")
    video = db.scalar(select(Video))
    assert video.status == "queued" and video.size_bytes == len(payload) and video.label == "Całość"
    assert video.created_by is not None and video.expires_at is not None  # retencja 30 dni
    assert storage.size(video.original_path) == len(payload)
    assert video.original_path.startswith("uploads/") and " " not in video.original_path
    job = db.scalar(select(Job))
    assert job.type == "transcode" and job.status == "pending" and job.video_id == video.id


def test_upload_empty_rejected(client, db):
    match = make_match(db)
    assert tus_create(client, match.id, 0).status_code == 400
    assert db.scalar(select(Video)) is None


def test_old_raw_upload_route_is_gone(client, db):
    match = make_match(db)
    r = client.post(f"/matches/{match.id}/upload", params={"filename": "a.mp4"}, content=b"x")
    assert r.status_code in (404, 405)


def test_stream_supports_range(client, db):
    video = make_ready_video(db, make_match(db), content=bytes(range(256)) * 4)
    full = client.get(f"/videos/{video.id}/stream")
    assert full.status_code == 200 and len(full.content) == 1024
    assert full.headers["accept-ranges"] == "bytes"
    part = client.get(f"/videos/{video.id}/stream", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.headers["content-range"] == "bytes 100-199/1024"
    assert part.content == full.content[100:200]
    tail = client.get(f"/videos/{video.id}/stream", headers={"Range": "bytes=1000-"})
    assert tail.status_code == 206 and len(tail.content) == 24


def test_stream_not_ready(client, db):
    match = make_match(db)
    video = Video(match_id=match.id, status="queued")
    db.add(video)
    db.commit()
    assert client.get(f"/videos/{video.id}/stream").status_code == 409


def test_notes_parse_api(client, db):
    video = make_ready_video(db, make_match(db))
    text = "2:54 Filip kroki\n3:17 U1 Dlaczego nie blok?\n4:00 Zenek aut"
    rows = client.post(f"/api/videos/{video.id}/notes/parse", json={"text": text}).json()
    assert [r["time_sec"] for r in rows] == [174, 197, 240]
    assert rows[0]["official"] == "Filip Kowalski" and rows[0]["category"] == "kroki"
    assert rows[1]["official"] == "Kasia Żółć" and rows[1]["category"] == "blok / szarża"
    assert rows[2]["official"] is None and rows[2]["category"] == "aut"
    assert any("Nieznany sędzia" in w for w in rows[2]["warnings"])


def test_notes_preview_and_commit_creates_clips(client, db):
    video = make_ready_video(db, make_match(db))
    cc = video.match.official("CC")
    text = "2:54 CC kroki\n99:00 Filip poza nagraniem"
    preview = client.post(f"/videos/{video.id}/notes/preview", data={"text": text})
    assert preview.status_code == 200 and "Czas poza nagraniem" in preview.text
    assert "Naruszenia: kroki" in preview.text
    form = {"count": "2", "include_0": "1", "time_0": "2:54", "referee_0": str(cc.id),
            "category_0": str(category_id(db, "kroki")), "desc_0": "2:54 CC kroki",
            "include_1": "1", "time_1": "99:00", "referee_1": "", "category_1": "", "desc_1": "x"}
    r = client.post(f"/videos/{video.id}/notes/commit", data=form, follow_redirects=False)
    assert r.status_code == 303 and "created=1" in r.headers["location"] and "skipped=1" in r.headers["location"]
    c = db.scalar(select(Clip))
    assert c.time_sec == 174 and c.official_id == cc.id and c.category.name == "kroki"
    assert (c.margin_before, c.margin_after) == (15, 15) and c.status == "queued"
    assert c.described_at is None and c.author_id is not None
    job = db.scalar(select(Job).where(Job.type == "cut"))
    assert job.clip_id == c.id


def test_quarter_from_period_marks(client, db):
    video = make_ready_video(db, make_match(db), duration=4000)
    url = f"/api/videos/{video.id}"
    # bez znaczników kwarta jest nieznana
    assert quick(client, video.id, 50, "Filip kroki").json()["clip"]["period"] is None
    # kolejne znaczniki dostają kolejne kwarty
    assert client.post(f"{url}/marks", json={"time_sec": 30}).json()["period"] == "Q1"
    assert client.post(f"{url}/marks", json={"time_sec": 1000}).json()["period"] == "Q2"
    state = client.post(f"{url}/marks", json={"time_sec": 2000}).json()
    assert state["next_period"] == "Q4"

    def period_at(t):
        return quick(client, video.id, t, "Filip kroki").json()["clip"]["period"]

    assert period_at(10) is None
    assert period_at(30) == "Q1"
    assert period_at(999) == "Q1"
    assert period_at(1000) == "Q2"
    assert period_at(2500) == "Q3"
    # istniejąca kwarta jest przesuwana, a okres starych klipów liczy się na nowo
    client.post(f"{url}/marks", json={"time_sec": 40, "period": "Q1"})
    clips = client.get(f"{url}/state").json()["clips"]
    assert next(c for c in clips if c["time_sec"] == 50)["period"] == "Q1"
    # usunięcie znacznika Q3 -> klip z 2500 wraca do Q2
    q3 = next(m for m in state["marks"] if m["period"] == "Q3")
    after = client.delete(f"/api/marks/{q3['id']}").json()
    assert next(c for c in after["clips"] if c["time_sec"] == 2500)["period"] == "Q2"


def test_period_label_shows_time_since_period_start(client, db):
    video = make_ready_video(db, make_match(db), duration=4000)
    client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 1000})
    clip_id = quick(client, video.id, 1252, "Filip kroki").json()["clip"]["id"]
    assert "Q1 · 4:12 od początku kwarty (czas nagrania)" in client.get(f"/clips/{clip_id}").text


def test_quick_clip_parses_line_and_clamps(client, db):
    video = make_ready_video(db, make_match(db), duration=100)
    res = quick(client, video.id, 500, "kasia kroki").json()
    c = res["clip"]
    assert c["time_sec"] == 100 and c["official"] == "U1 · Kasia Żółć" and c["category"] == "kroki"
    assert c["status"] == "queued" and c["described"] is False
    assert (c["clip_start"], c["clip_end"]) == (85, 100)  # 15 s przed, obcięte do końca nagrania
    res = quick(client, video.id, 5, "Ktoś kroki").json()
    assert res["clip"]["official"] is None and res["warnings"]


def test_describe_clip(client, db):
    video = make_ready_video(db, make_match(db))
    clip_id = quick(client, video.id, 100, "").json()["clip"]["id"]
    clip = db.get(Clip, clip_id)
    cc = video.match.official("CC")
    r = client.post(f"/clips/{clip_id}/update", follow_redirects=False, data={
        "official": str(cc.id), "category_id": str(category_id(db, "kroki")),
        "description": " Za późno "})
    assert r.status_code == 303
    db.refresh(clip)
    assert clip.official_id == cc.id and clip.category.name == "kroki" and clip.description == "Za późno"
    assert clip.is_described and not clip.whole_team
    # cały zespół + kategoria „własna” wymaga nazwy
    own = str(category_id(db, "własna"))
    assert client.post(f"/clips/{clip_id}/update", data={"official": "team", "category_id": own}).status_code == 422
    client.post(f"/clips/{clip_id}/update", data={"official": "team", "category_id": own,
                                                  "custom_category": "kontakt z trenerem"})
    db.refresh(clip)
    assert clip.whole_team and clip.official_id is None
    assert clip.category_label == "kontakt z trenerem"
    page = client.get(f"/clips/{clip_id}").text
    assert "cały zespół" in page and "Mechanika" in page  # grupy kategorii w formularzu


def test_clips_filters(client, db):
    video = make_ready_video(db, make_match(db))
    url = f"/api/videos/{video.id}"
    client.post(f"{url}/marks", json={"time_sec": 0})
    client.post(f"{url}/marks", json={"time_sec": 300})
    ids = {}
    for t, text in ((100, "Filip kroki"), (400, "Kasia aut")):
        ids[t] = quick(client, video.id, t, text).json()["clip"]["id"]

    def listed(**params):
        html = client.get("/clips", params=params).text
        return [i for i in ids.values() if f'href="/clips/{i}"' in html]

    assert len(listed()) == 2
    assert listed(period="Q2") == [ids[400]]
    assert listed(period="Q1") == [ids[100]]
    assert listed(category_id=category_id(db, "kroki")) == [ids[100]]
    assert listed(person="nkasia zolc") == [ids[400]]
    assert len(listed(match_id=video.match_id)) == 2
    assert listed(match_id=video.match_id + 1) == []


def test_comments_and_clip_page(client, db, admin):
    video = make_ready_video(db, make_match(db))
    clip_id = quick(client, video.id, 100, "Filip kroki").json()["clip"]["id"]
    assert client.get(f"/clips/{clip_id}").status_code == 200
    r = client.post(f"/clips/{clip_id}/comments", data={"body": "Za późno gwizdek"})
    assert r.status_code == 200 and "Za późno gwizdek" in r.text and "Admin Testowy" in r.text
    comment = db.scalar(select(Comment))
    assert comment.clip_id == clip_id and comment.match_id is None and comment.author_id == admin[1].id
    r = client.post(f"/comments/{comment.id}/delete")
    assert "Za późno gwizdek" not in r.text and db.scalar(select(Comment)) is None


def test_download(client, db):
    video = make_ready_video(db, make_match(db))
    client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 0})
    clip_id = quick(client, video.id, 100, "CC kroki").json()["clip"]["id"]
    assert client.get(f"/clips/{clip_id}/download").status_code == 404  # jeszcze niewycięty
    clip = db.get(Clip, clip_id)
    clip.clip_path, clip.status = f"clips/{clip_id}_v1.mp4", "cut"
    with storage.open_write(clip.clip_path) as fh:
        fh.write(b"clip")
    db.commit()
    dl = client.get(f"/clips/{clip_id}/download")
    assert dl.status_code == 200
    assert 'filename="2026-10-28_Q1_01m40s_CC_kroki.mp4"' in dl.headers["content-disposition"]
    assert client.get(f"/clips/{clip_id}/file").content == b"clip"


def test_delete_match_cleans_files(client, db):
    match = make_match(db)
    video = make_ready_video(db, match)
    key = video.proxy_path
    client.post(f"/matches/{match.id}/delete")
    assert not storage.exists(key)
    assert db.scalar(select(Match)) is None


def test_delete_clip(client, db):
    video = make_ready_video(db, make_match(db))
    clip_id = quick(client, video.id, 100, "Filip kroki").json()["clip"]["id"]
    r = client.post(f"/clips/{clip_id}/delete", follow_redirects=False)
    assert r.status_code == 303 and db.get(Clip, clip_id) is None


def test_status_endpoint(client):
    assert "ffmpeg" in client.get("/api/status").json()


def test_v2_features_are_not_routed():
    """Korekta granic klipu i eksport ZIP są ukryte w MVP (REFCLIPS_V2_FEATURES=0)."""
    from app.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/clips/export.zip" not in paths and "/clips/{clip_id}/adjust" not in paths
    assert "/tags" not in paths
