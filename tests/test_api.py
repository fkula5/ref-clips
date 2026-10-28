import io
import zipfile

from sqlalchemy import select

from app.models import Decision, Job, Match, Video
from app.storage import storage
from tests.helpers import make_match, make_ready_video

MATCH_FORM = {
    "date": "2026-10-28", "level": "II liga", "team_a_name": "Legia", "team_a_color": "białe",
    "team_b_name": "Wisła", "team_b_color": "ciemne",
    "ref_name": ["Filip Kowalski", "Kasia", ""], "ref_role": ["crew_chief", "umpire", "umpire"],
}


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Mecze" in r.text


def test_create_match(client, db):
    r = client.post("/matches", data=MATCH_FORM, follow_redirects=False)
    assert r.status_code == 303
    match = db.scalar(select(Match))
    assert match.date.isoformat() == "2026-10-28"
    assert [(mr.referee.name, mr.role) for mr in match.referees] == [
        ("Filip Kowalski", "crew_chief"), ("Kasia", "umpire")]
    page = client.get(r.headers["location"])
    assert page.status_code == 200 and "Filip Kowalski" in page.text
    # edycja obsady
    form = {**MATCH_FORM, "ref_name": ["Kasia"], "ref_role": ["crew_chief"]}
    assert client.post(f"/matches/{match.id}", data=form, follow_redirects=False).status_code == 303
    db.refresh(match)
    assert [mr.referee.name for mr in match.referees] == ["Kasia"]
    assert match.referees[0].role == "crew_chief"


def test_upload_streams_to_disk_and_queues_transcode(client, db):
    match = make_match(db)
    payload = b"x" * (5 * 1024 * 1024)
    r = client.post(f"/matches/{match.id}/upload", params={"filename": "mecz ąę.mp4", "label": "Całość"},
                    content=payload)
    assert r.status_code == 200 and r.json()["size"] == len(payload)
    video = db.scalar(select(Video))
    assert video.status == "queued" and video.size_bytes == len(payload)
    assert storage.size(video.original_path) == len(payload)
    assert video.original_path.startswith("uploads/") and " " not in video.original_path
    job = db.scalar(select(Job))
    assert job.type == "transcode" and job.status == "pending" and job.video_id == video.id


def test_upload_empty_rejected(client, db):
    match = make_match(db)
    r = client.post(f"/matches/{match.id}/upload", params={"filename": "a.mp4"}, content=b"")
    assert r.status_code == 400
    assert db.scalar(select(Video)) is None


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
    text = "2:54 Filip PTS\n3:17 Kasia Dlaczego nie blok?\n4:00 Zenek kroki białe"
    rows = client.post(f"/api/videos/{video.id}/notes/parse", json={"text": text}).json()
    assert [r["time_sec"] for r in rows] == [174, 197, 240]
    assert rows[0]["referee"] == "Filip" and rows[0]["tags"] == ["PTS"]
    assert rows[1]["tags"] == ["blok"]
    assert rows[2]["referee"] is None and rows[2]["team"] == "a"
    assert any("Nieznany sędzia" in w for w in rows[2]["warnings"])


def test_notes_preview_and_commit_creates_decisions(client, db):
    video = make_ready_video(db, make_match(db))
    ref_id = video.match.referees[0].referee_id
    text = "2:54 Filip PTS\n99:00 Filip poza nagraniem"
    preview = client.post(f"/videos/{video.id}/notes/preview", data={"text": text})
    assert preview.status_code == 200 and "Czas poza nagraniem" in preview.text
    form = {"count": "2", "include_0": "1", "time_0": "2:54", "referee_0": str(ref_id), "team_0": "a",
            "tags_0": "PTS, blok", "desc_0": "2:54 Filip PTS",
            "include_1": "1", "time_1": "99:00", "referee_1": "", "tags_1": "", "desc_1": "x"}
    r = client.post(f"/videos/{video.id}/notes/commit", data=form, follow_redirects=False)
    assert r.status_code == 303 and "created=1" in r.headers["location"] and "skipped=1" in r.headers["location"]
    d = db.scalar(select(Decision))
    assert d.time_sec == 174 and d.referee_id == ref_id and d.team == "a"
    assert {t.name for t in d.tags} == {"PTS", "blok"}
    assert (d.margin_before, d.margin_after) == (10, 10) and d.status == "queued"
    job = db.scalar(select(Job).where(Job.type == "cut"))
    assert job.decision_id == d.id


def test_quarter_from_period_marks(client, db):
    video = make_ready_video(db, make_match(db), duration=4000)
    url = f"/api/videos/{video.id}"
    # bez znaczników kwarta jest nieznana
    d0 = client.post(f"{url}/quick-decision", json={"time_sec": 50, "text": "Filip PTS"}).json()
    assert d0["decision"]["period"] is None
    # Q key: kolejne znaczniki dostają kolejne kwarty
    assert client.post(f"{url}/marks", json={"time_sec": 30}).json()["period"] == "Q1"
    assert client.post(f"{url}/marks", json={"time_sec": 1000}).json()["period"] == "Q2"
    state = client.post(f"{url}/marks", json={"time_sec": 2000}).json()
    assert state["next_period"] == "Q4"

    def period_at(t):
        return client.post(f"{url}/quick-decision", json={"time_sec": t, "text": "Filip PTS"}).json()["decision"]["period"]

    assert period_at(10) is None
    assert period_at(30) == "Q1"
    assert period_at(999) == "Q1"
    assert period_at(1000) == "Q2"
    assert period_at(2500) == "Q3"
    # istniejąca kwarta jest przesuwana, a okres starych decyzji liczy się na nowo
    client.post(f"{url}/marks", json={"time_sec": 40, "period": "Q1"})
    decisions = client.get(f"{url}/state").json()["decisions"]
    assert next(d for d in decisions if d["time_sec"] == 50)["period"] == "Q1"
    # usunięcie znacznika Q3 -> decyzja z 2500 wraca do Q2
    q3 = next(m for m in state["marks"] if m["period"] == "Q3")
    after = client.delete(f"/api/marks/{q3['id']}").json()
    assert next(d for d in after["decisions"] if d["time_sec"] == 2500)["period"] == "Q2"


def test_quick_decision_parses_line_and_clamps(client, db):
    video = make_ready_video(db, make_match(db), duration=100)
    res = client.post(f"/api/videos/{video.id}/quick-decision",
                      json={"time_sec": 500, "text": "kasia kroki ciemne"}).json()
    d = res["decision"]
    assert d["time_sec"] == 100 and d["referee"] == "Kasia" and d["tags"] == ["kroki"]
    assert d["team"] == "Wisła" and d["status"] == "queued"
    assert (d["clip_start"], d["clip_end"]) == (90, 100)  # obcięte do końca nagrania
    res = client.post(f"/api/videos/{video.id}/quick-decision", json={"time_sec": 5, "text": "Ktoś PTS"}).json()
    assert res["decision"]["referee"] is None and res["warnings"]


def test_adjust_clip_requeues_cut(client, db):
    video = make_ready_video(db, make_match(db))
    d = client.post(f"/api/videos/{video.id}/quick-decision", json={"time_sec": 100, "text": "Filip PTS"}).json()["decision"]
    r = client.post(f"/clips/{d['id']}/adjust", data={"start": "1:30", "end": "1:50"}, follow_redirects=False)
    assert r.status_code == 303
    dec = db.get(Decision, d["id"])
    db.refresh(dec)
    assert (dec.margin_before, dec.margin_after) == (10, 10)
    client.post(f"/clips/{d['id']}/adjust", data={"start": "85", "end": "2:00"})
    db.refresh(dec)
    assert (dec.margin_before, dec.margin_after) == (15, 20)
    assert db.scalars(select(Job).where(Job.type == "cut", Job.status == "pending")).all().__len__() == 1
    bad = client.post(f"/clips/{d['id']}/adjust", data={"start": "2:00", "end": "2:10"})
    assert bad.status_code == 422


def test_clips_filters(client, db):
    video = make_ready_video(db, make_match(db))
    url = f"/api/videos/{video.id}"
    client.post(f"{url}/marks", json={"time_sec": 0})
    client.post(f"{url}/marks", json={"time_sec": 300})
    ids = {}
    for t, text in ((100, "Filip PTS"), (400, "Kasia kroki")):
        ids[t] = client.post(f"{url}/quick-decision", json={"time_sec": t, "text": text}).json()["decision"]["id"]
    d = db.get(Decision, ids[400])
    d.rating = "incorrect"
    db.commit()

    def listed(**params):
        html = client.get("/clips", params=params).text
        return [i for i in ids.values() if f'href="/clips/{i}"' in html]

    assert len(listed()) == 2
    assert listed(period="Q2") == [ids[400]]
    assert listed(period="Q1") == [ids[100]]
    assert listed(tag="PTS") == [ids[100]]
    assert listed(rating="incorrect") == [ids[400]]
    ref = video.match.referees[1].referee_id
    assert listed(referee_id=ref) == [ids[400]]
    assert len(listed(match_id=video.match_id)) == 2


def test_comments_and_clip_page(client, db):
    video = make_ready_video(db, make_match(db))
    d = client.post(f"/api/videos/{video.id}/quick-decision", json={"time_sec": 100, "text": "Filip PTS"}).json()["decision"]
    page = client.get(f"/clips/{d['id']}")
    assert page.status_code == 200
    r = client.post(f"/clips/{d['id']}/comments", data={"body": "Za późno gwizdek", "at_sec": "9.5"})
    assert "Za późno gwizdek" in r.text and "9.5 s" in r.text
    dec = db.get(Decision, d["id"])
    cid = dec.comments[0].id
    client.post(f"/clips/{d['id']}/comments", data={"body": "Zgoda", "parent_id": str(cid)})
    db.refresh(dec)
    assert len(dec.comments) == 2 and dec.comments[1].parent_id == cid
    r = client.post(f"/comments/{cid}/delete")
    assert "Za późno gwizdek" not in r.text


def test_download_and_zip_export(client, db):
    video = make_ready_video(db, make_match(db))
    client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 0})
    ids = []
    for t in (100, 100):  # dwie takie same nazwy -> unikalne w paczce
        ids.append(client.post(f"/api/videos/{video.id}/quick-decision",
                               json={"time_sec": t, "text": "Filip PTS"}).json()["decision"]["id"])
    for i in ids:
        d = db.get(Decision, i)
        d.clip_path, d.status = f"clips/{i}_v1.mp4", "cut"
        with storage.open_write(d.clip_path) as fh:
            fh.write(b"clip%d" % i)
    db.commit()
    dl = client.get(f"/clips/{ids[0]}/download")
    assert dl.status_code == 200
    assert 'filename="2026-10-28_Q1_01m40s_Filip_PTS.mp4"' in dl.headers["content-disposition"]
    z = client.get("/clips/export.zip", params={"match_id": video.match_id})
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = sorted(zf.namelist())
        assert names == ["2026-10-28_Q1_01m40s_Filip_PTS.mp4", "2026-10-28_Q1_01m40s_Filip_PTS_2.mp4", "opisy.csv"]
        csv_text = zf.read("opisy.csv").decode("utf-8-sig")
        assert "Filip" in csv_text and "Q1" in csv_text and csv_text.startswith("plik;")
    assert client.get("/clips/export.zip", params={"ids": [9999]}).status_code == 404


def test_tags_page_crud(client, db):
    assert "kroki" in client.get("/tags").text
    client.post("/tags", data={"name": "faul w ataku", "aliases": "faul atak"})
    r = client.post("/tags", data={"name": "FAUL W ATAKU"})
    assert r.status_code == 422
    assert "faul w ataku" in client.get("/tags").text


def test_delete_match_cleans_files(client, db):
    match = make_match(db)
    video = make_ready_video(db, match)
    key = video.proxy_path
    client.post(f"/matches/{match.id}/delete")
    assert not storage.exists(key)
    assert db.scalar(select(Match)) is None


def test_status_endpoint(client):
    assert "ffmpeg" in client.get("/api/status").json()
