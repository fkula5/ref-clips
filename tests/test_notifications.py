import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import config, notify, worker
from app.models import Clip, Comment, Notification, Rating, Sheet
from app.timeutil import utcnow
from tests.helpers import make_match, make_ready_video, make_user, mark_periods

NAMES = ("coach", "coach2", "crew", "author", "commenter", "outsider", "admin")


@pytest.fixture()
def w(db, make_client):
    """Crew: `crew` (CC) and `crew_off` (U1, deactivated). `author` made the clip, `commenter` only commented;
    `crew` and `author` also commented, so they are in the set twice.
    """
    clients, users = {}, {}
    for name in NAMES:
        clients[name], users[name] = make_client(*{"coach": ("coach",), "coach2": ("coach",), "admin": ("admin",)}
                                                 .get(name, ("referee",)), name=f"Osoba {name}")
    users["crew_off"] = make_user(db, ("referee",), email="off@example.com", name="Osoba crew_off", active=False)
    match = make_match(db, officials=(("CC", users["crew"]), ("U1", users["crew_off"]), ("U2", "Wpisany Sędzia")),
                       created_by=users["coach"])
    video = mark_periods(db, make_ready_video(db, match))
    clip = Clip(match_id=match.id, video_id=video.id, author_id=users["author"].id, time_sec=170)
    db.add(clip)
    db.commit()
    for name in ("commenter", "crew", "author", "crew_off"):
        db.add(Comment(clip_id=clip.id, author_id=users[name].id, body="Wcześniej"))
    for name in ("commenter", "coach"):
        db.add(Comment(match_id=match.id, author_id=users[name].id, body="Wcześniej o meczu"))
    db.commit()
    return SimpleNamespace(c=clients, u=users, match=match, clip=clip, db=db)


def post(w, who, url, **data):
    r = w.c[who].post(url, data=data, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    return r


def rate(w, who, verdict, comment=""):
    return post(w, who, f"/clips/{w.clip.id}/rating", verdict=verdict, comment=comment)


def prior_rating(w, verdict="correct"):
    rating = Rating(clip_id=w.clip.id, coach_id=w.u["coach"].id, verdict=verdict, comment="")
    w.db.add(rating)
    w.db.commit()
    return rating


def comment_on(w, who, scope):
    base = f"/clips/{w.clip.id}" if scope == "clip" else f"/matches/{w.match.id}"
    return post(w, who, f"{base}/comments", body="Nowy komentarz")


def publish_sheet(w, **extra):
    r = post(w, "coach", f"/matches/{w.match.id}/sheets")
    sheet_id = int(re.search(r"/sheets/(\d+)/edit", r.headers["location"])[1])
    post(w, "coach", f"/sheets/{sheet_id}/edit", action="save", result="70:60")
    post(w, "coach", f"/sheets/{sheet_id}/edit", action="publish", difficulty="normalny", **extra)
    return sheet_id


def republish_sheet(w):
    sheet_id = publish_sheet(w)
    w.db.query(Notification).delete()
    w.db.commit()
    post(w, "coach", f"/sheets/{sheet_id}/edit", action="publish", difficulty="normalny", result="80:50")
    post(w, "coach", f"/sheets/{sheet_id}/edit", action="save", difficulty="trudny")


def change_verdict(w):
    prior_rating(w)
    rate(w, "coach", "incorrect")


def admin_changes_rating(w):
    rating = prior_rating(w)
    post(w, "admin", f"/clips/{w.clip.id}/ratings/{rating.id}/edit", verdict="debatable")


def reword_rating(w):
    prior_rating(w)
    rate(w, "coach", "correct", "Inny komentarz")


def delete_rating(w):
    rating = prior_rating(w)
    post(w, "coach", f"/clips/{w.clip.id}/ratings/{rating.id}/delete")


def edit_and_delete_comments(w):
    mine, other = (w.db.scalar(select(Comment).where(Comment.clip_id == w.clip.id, Comment.author_id == w.u[n].id))
                   for n in ("commenter", "author"))
    post(w, "commenter", f"/clips/{w.clip.id}/comments/{mine.id}/edit", body="Poprawiony")
    post(w, "admin", f"/clips/{w.clip.id}/comments/{other.id}/delete")


# name: (action, who gets exactly one notification, kind)
SCENARIOS = {
    "new rating": (lambda w: rate(w, "coach", "incorrect"), {"crew", "author", "commenter"}, "rating"),
    "verdict changed": (change_verdict, {"crew", "author", "commenter"}, "rating_changed"),
    "verdict changed by an admin": (admin_changes_rating, {"crew", "author", "commenter"}, "rating_changed"),
    "same verdict, new comment": (reword_rating, set(), None),
    "rating deleted": (delete_rating, set(), None),
    "clip comment": (lambda w: comment_on(w, "coach2", "clip"), {"crew", "author", "commenter"}, "clip_comment"),
    "clip comment by its author": (lambda w: comment_on(w, "author", "clip"), {"crew", "commenter"}, "clip_comment"),
    "comments edited and deleted": (edit_and_delete_comments, set(), None),
    "match comment": (lambda w: comment_on(w, "coach2", "match"), {"crew", "coach", "commenter"}, "match_comment"),
    "match comment by its creator": (lambda w: comment_on(w, "coach", "match"), {"crew", "commenter"}, "match_comment"),
    "match comment by the crew": (lambda w: comment_on(w, "crew", "match"), {"coach", "commenter"}, "match_comment"),
    "sheet published": (publish_sheet, {"crew"}, "sheet_published"),
    "sheet published again or corrected": (republish_sheet, set(), None),
}


@pytest.mark.parametrize("action,expected,kind", SCENARIOS.values(), ids=SCENARIOS)
def test_recipients_of_each_event(w, action, expected, kind):
    action(w)
    rows = w.db.scalars(select(Notification).order_by(Notification.id)).all()
    wanted = sorted(w.u[name].id for name in expected)
    assert sorted(n.recipient_id for n in rows) == wanted  # one each: no actor, inactive, outsider or duplicate
    assert {n.kind for n in rows} <= {kind}
    assert all(n.actor_id is not None and n.read_at is None for n in rows)


def test_rating_notification_carries_the_verdict_and_the_clip(w):
    rate(w, "coach", "incorrect")
    n = w.db.scalar(select(Notification))
    assert (n.verdict, n.clip_id, n.match_id, n.actor_id) == ("incorrect", w.clip.id, w.match.id, w.u["coach"].id)


@pytest.fixture()
def feed(w):
    """Notifications of `crew`, oldest first, for the list and the write routes."""
    now = utcnow()
    sheet = Sheet(match_id=w.match.id, coach_id=w.u["coach"].id, status="published", difficulty="normalny",
                  published_at=now)
    w.db.add(sheet)
    w.db.commit()
    rows = [
        Notification(recipient_id=w.u["crew"].id, kind="rating", actor_id=w.u["coach"].id, match_id=w.match.id,
                     clip_id=w.clip.id, verdict="incorrect", created_at=now - timedelta(hours=3)),
        Notification(recipient_id=w.u["crew"].id, kind="match_comment", actor_id=w.u["coach2"].id,
                     match_id=w.match.id, created_at=now - timedelta(hours=2), read_at=now),
        Notification(recipient_id=w.u["crew"].id, kind="sheet_published", actor_id=w.u["coach"].id,
                     match_id=w.match.id, sheet_id=sheet.id, created_at=now - timedelta(hours=1)),
    ]
    w.db.add_all(rows)
    w.db.commit()
    return rows


def unread(w, who="crew"):
    return notify.unread_count(w.db, w.u[who].id)


def list_items(page):
    items = re.findall(r'<li class="notif( unread)?">(.*?)</li>', page, re.S)
    return [(bool(flag), " ".join(re.sub(r"<[^>]+>", " ", body).split())) for flag, body in items]


def test_list_is_newest_first_and_marks_unread_ones(w, feed):
    w.db.add(Notification(recipient_id=w.u["author"].id, kind="clip_comment", match_id=w.match.id, clip_id=w.clip.id))
    w.db.commit()
    page = w.c["crew"].get("/notifications").text
    (sheet_unread, sheet), (comment_unread, comment), (rating_unread, rating) = list_items(page)
    assert sheet_unread and sheet.startswith("Osoba coach : opublikowany arkusz oceny w meczu Legia – Wisła")
    assert not comment_unread and "Osoba coach2 : komentarz do meczu Legia – Wisła" in comment
    assert rating_unread and "Osoba coach : nowa ocena klipu Q2 · 0:20 w meczu Legia – Wisła : nieprawidłowa" in rating
    assert unread(w) == 2 and "Oznacz wszystkie jako przeczytane" in page


def test_list_empty_state_and_cap(w, feed, monkeypatch):
    assert "Brak powiadomień" in w.c["outsider"].get("/notifications").text
    monkeypatch.setattr(config, "NOTIFICATION_LIST_LIMIT", 2)
    page = w.c["crew"].get("/notifications").text
    assert page.count('<li class="notif') == 2 and "Pokazano 2 najnowszych" in page


@pytest.mark.parametrize("count,label", [
    (0, "Powiadomienia"), (1, "Powiadomienia: 1 nowe"), (3, "Powiadomienia: 3 nowe"),
    (5, "Powiadomienia: 5 nowych"), (12, "Powiadomienia: 12 nowych"), (22, "Powiadomienia: 22 nowe"),
])
def test_bell_label_uses_polish_plural(count, label):
    assert notify.bell_label(count) == label


def test_bell_fragment_and_page_show_unread_count(w, feed):
    fragment = w.c["crew"].get("/notifications/bell", headers={"HX-Request": "true"})
    assert 'aria-label="Powiadomienia: 2 nowe"' in fragment.text and 'class="bell-count"' in fragment.text
    assert "<html" not in fragment.text and fragment.headers["cache-control"] == "no-store"
    assert 'aria-label="Powiadomienia: 2 nowe"' in w.c["crew"].get("/").text
    quiet = w.c["outsider"].get("/notifications/bell").text
    assert 'aria-label="Powiadomienia"' in quiet and "bell-count" not in quiet
    post(w, "crew", "/notifications/read-all")
    assert 'aria-label="Powiadomienia"' in w.c["crew"].get("/notifications/bell").text


def test_opening_marks_read_and_goes_to_the_target(w, feed):
    rating, _, sheet = feed
    assert w.c["crew"].get(f"/notifications/{rating.id}/open").status_code == 405  # GET changes nothing
    assert unread(w) == 2
    r = post(w, "crew", f"/notifications/{rating.id}/open")
    assert (r.status_code, r.headers["location"]) == (303, f"/clips/{w.clip.id}#oceny")
    assert unread(w) == 1
    r = post(w, "crew", f"/notifications/{sheet.id}/open")
    assert r.headers["location"] == f"/sheets/{sheet.sheet_id}" and unread(w) == 0
    assert w.c["crew"].get(r.headers["location"]).status_code == 200


@pytest.mark.parametrize("kind,target", [
    ("rating_changed", "/clips/{clip}#oceny"), ("clip_comment", "/clips/{clip}#komentarze"),
    ("match_comment", "/matches/{match}#komentarze"),
])
def test_target_anchor_per_kind(w, kind, target):
    n = Notification(recipient_id=w.u["crew"].id, kind=kind, match_id=w.match.id, clip_id=w.clip.id)
    assert notify.target_url(n) == target.format(clip=w.clip.id, match=w.match.id)


def test_mark_read_and_mark_all_touch_only_own_notifications(w, feed):
    w.db.add(Notification(recipient_id=w.u["author"].id, kind="clip_comment", match_id=w.match.id, clip_id=w.clip.id))
    w.db.commit()
    assert post(w, "crew", f"/notifications/{feed[0].id}/read").headers["location"] == "/notifications"
    assert unread(w) == 1
    post(w, "crew", "/notifications/read-all")
    assert (unread(w), unread(w, "author")) == (0, 1)


@pytest.mark.parametrize("action", ["open", "read"])
def test_someone_elses_or_missing_notification_is_404(w, feed, action):
    for who, notification_id in (("outsider", feed[0].id), ("admin", feed[0].id), ("crew", 99999)):
        assert w.c[who].post(f"/notifications/{notification_id}/{action}").status_code == 404
    assert unread(w) == 2


def test_writes_need_login_and_csrf(w, feed, anon_client):
    urls = [f"/notifications/{feed[0].id}/open", f"/notifications/{feed[0].id}/read", "/notifications/read-all"]
    client = w.c["crew"]
    for url in urls:
        assert anon_client.post(url).status_code == 401
        client.headers["X-CSRF-Token"] = "zly-token"
        assert client.post(url).status_code == 403
    assert unread(w) == 2


@pytest.mark.parametrize("deleted,left", [
    ("clip", {"match_comment", "sheet_published"}), ("sheet", {"rating", "match_comment"}), ("match", set()),
])
def test_deleting_the_target_deletes_its_notifications(w, feed, deleted, left):
    w.db.delete({"clip": w.clip, "sheet": w.db.get(Sheet, feed[2].sheet_id), "match": w.match}[deleted])
    w.db.commit()
    assert {n.kind for n in w.db.scalars(select(Notification))} == left


def test_deleting_a_comment_keeps_its_notification(w):
    comment_on(w, "coach2", "clip")
    comment = w.db.scalar(select(Comment).where(Comment.author_id == w.u["coach2"].id))
    post(w, "admin", f"/clips/{w.clip.id}/comments/{comment.id}/delete")
    assert w.db.scalar(select(Notification).where(Notification.kind == "clip_comment")) is not None


def test_maintenance_prunes_read_after_30_days_and_unread_after_90(w):
    now = utcnow()
    for age, is_read in [(31, True), (29, True), (31, False), (91, False), (89, False)]:
        w.db.add(Notification(recipient_id=w.u["crew"].id, kind="match_comment", match_id=w.match.id,
                              created_at=now - timedelta(days=age), read_at=now if is_read else None))
    w.db.commit()
    worker.run_maintenance()
    w.db.expire_all()
    kept = sorted((n.read_at is not None, (now - n.created_at).days) for n in w.db.scalars(select(Notification)))
    assert kept == [(False, 31), (False, 89), (True, 29)]


def test_inactive_user_is_not_a_recipient_even_when_directly_addressed(w):
    notify._deliver(w.db, [w.u["crew_off"].id, w.u["crew"].id], actor_id=w.u["coach"].id, kind="match_comment",
                    match=w.match)
    assert [n.recipient_id for n in w.db.scalars(select(Notification))] == [w.u["crew"].id]
