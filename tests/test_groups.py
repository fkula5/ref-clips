import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app import groups, match_list, notify
from app.db import engine
from app.models import Clip, GroupMember, Match, Notification, Rating, TrainingGroup, User, Video
from tests.helpers import make_match, make_ready_video, make_user

NOW = datetime(2026, 11, 11, 12, 0)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


@pytest.fixture()
def w(db, make_client):
    """`coach` leads the group `g` with the referees `r1` and `r2`; `r3` is a free referee account, `lead2`
    another coach and `other` a coach who does not lead `g`.
    """
    clients, users = {}, {}
    for name, role in {"coach": "coach", "lead2": "coach", "other": "coach", "admin": "admin",
                       "r1": "referee", "r2": "referee", "r3": "referee"}.items():
        clients[name], users[name] = make_client(role, name=f"Osoba {name}")
    group = groups.create_group(db, users["coach"], "Grupa A", "Opis A")
    for name in ("r1", "r2"):
        group.members.append(GroupMember(user_id=users[name].id, role="referee"))
    db.commit()
    return SimpleNamespace(c=clients, u=users, g=group, db=db)


def post(w, who, url, status=303, **data):
    r = w.c[who].post(url, data=data, follow_redirects=False)
    assert r.status_code == status, r.text[:300]
    return r


def names(w, role=None):
    w.db.expire_all()
    return {m.user.name.split()[-1] for m in w.db.get(TrainingGroup, w.g.id).members if role in (None, m.role)}


def add_clip(w, match, video, author="r1", *, described=True, at=None, by=None, **fields):
    at = at or ago(1)
    clip = Clip(match_id=match.id, video_id=video.id, author_id=w.u[author].id, time_sec=10, created_at=at,
                described_at=at if described else None,
                described_by_id=w.u[by or author].id if described else None, **fields)
    w.db.add(clip)
    w.db.commit()
    return clip


def crew_match(w, *crew):
    match = make_match(w.db, officials=tuple(zip(("CC", "U1", "U2"), [w.u[c] if c in w.u else c for c in crew])))
    return match, make_ready_video(w.db, match)


@contextmanager
def count_statements():
    seen = []
    listener = lambda conn, cursor, statement, *rest: seen.append(statement)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", listener)


def test_create_makes_the_creator_a_coach_and_errors_keep_typed_values(w):
    r = post(w, "other", "/groups", name=" Nowa ", description="")
    created = w.db.scalar(select(TrainingGroup).where(TrainingGroup.name == "Nowa"))
    assert r.headers["location"] == f"/groups/{created.id}"
    assert [(m.user_id, m.role) for m in created.members] == [(w.u["other"].id, "coach")]
    for url in ("/groups", f"/groups/{w.g.id}/edit"):
        r = w.c["coach"].post(url, data={"name": "  ", "description": "wpisany opis"})
        assert r.status_code == 422 and "Podaj nazwę grupy" in r.text and "wpisany opis" in r.text
    post(w, "admin", f"/groups/{w.g.id}/edit", name="Zmieniona", description="")
    w.db.refresh(w.g)
    assert (w.g.name, w.g.description) == ("Zmieniona", "")


@pytest.mark.parametrize("who,method,url,status", [
    ("r1", "get", "/groups/new", 403), ("r1", "post", "/groups", 403),
    ("r1", "get", "/groups/{g}", 404), ("r1", "get", "/groups/{g}/review", 404),
    ("r1", "get", "/groups/{g}/edit", 404), ("r1", "post", "/groups/{g}/edit", 404),
    ("r1", "post", "/groups/{g}/referees", 404), ("r1", "post", "/groups/{g}/referees/{r2}/remove", 404),
    ("r1", "post", "/groups/{g}/delete", 404),
    ("other", "get", "/groups/{g}", 404), ("other", "post", "/groups/{g}/referees", 404),
    ("other", "post", "/groups/{g}/coaches", 404), ("other", "post", "/groups/{g}/delete", 404),
])
def test_only_group_coaches_and_admins_reach_a_group(w, who, method, url, status):
    url = url.format(g=w.g.id, r2=w.u["r2"].id)
    form = {"data": {"name": "x", "user_id": str(w.u["r3"].id)}} if method == "post" else {}
    r = getattr(w.c[who], method)(url, **form)
    assert r.status_code == status
    assert names(w, "referee") == {"r1", "r2"} and w.g.name == "Grupa A" and w.db.get(TrainingGroup, w.g.id)


def test_group_lists_per_role(w, db):
    groups.create_group(db, w.u["other"], "Grupa B", "")
    seen = {who: set(re.findall(r"Grupa [AB]", w.c[who].get("/groups").text)) for who in ("coach", "admin", "r1", "r3")}
    assert seen == {"coach": {"Grupa A"}, "admin": {"Grupa A", "Grupa B"}, "r1": {"Grupa A"}, "r3": set()}
    page = w.c["r1"].get("/groups").text
    assert "Osoba coach" in page and "Osoba r2" not in page  # the leaders, not the other referees
    assert 'href="/groups/' not in page and "Nowa grupa" not in page
    assert "Nowa grupa" in w.c["coach"].get("/groups").text
    assert "Nie należysz jeszcze do żadnej grupy" in w.c["r3"].get("/groups").text


@pytest.mark.parametrize("kind,target", [
    ("referees", "r1"),  # already a member
    ("coaches", "coach"),  # already a coach
    ("coaches", "r1"),  # in the group as a referee: one row per account
    ("referees", "lead2"),  # a coach account is not a referee account
    ("coaches", "r3"),  # and the other way round
    ("referees", "inactive"),
    ("referees", "missing"),
])
def test_add_member_rejections_change_nothing(w, db, kind, target):
    inactive = make_user(db, ("referee",), email="off@example.com", name="Osoba off", active=False)
    user_id = {"inactive": inactive.id, "missing": 9999}.get(target) or w.u[target].id
    r = w.c["coach"].post(f"/groups/{w.g.id}/{kind}", data={"user_id": str(user_id)})
    assert r.status_code == 422 and 'id="group-error"' in r.text
    assert names(w) == {"coach", "r1", "r2"} and db.scalar(select(Notification)) is None


def test_pickers_list_only_active_accounts_with_the_role_who_are_not_members(w, db):
    make_user(db, ("referee",), email="off@example.com", name="Osoba off", active=False)
    page = w.c["coach"].get(f"/groups/{w.g.id}").text
    referee_picker, coach_picker = re.findall(r'<select name="user_id" required>(.*?)</select>', page, re.S)
    assert re.findall(r">(Osoba \w+)<", referee_picker) == ["Osoba r3"]
    assert re.findall(r">(Osoba \w+)<", coach_picker) == ["Osoba lead2", "Osoba other"]


def test_adding_and_removing_members(w):
    post(w, "coach", f"/groups/{w.g.id}/referees", user_id=str(w.u["r3"].id))
    post(w, "admin", f"/groups/{w.g.id}/coaches", user_id=str(w.u["lead2"].id))
    assert names(w, "referee") == {"r1", "r2", "r3"} and names(w, "coach") == {"coach", "lead2"}
    assert w.c["lead2"].get(f"/groups/{w.g.id}").status_code == 200  # a new coach has the same rights
    post(w, "lead2", f"/groups/{w.g.id}/referees/{w.u['r3'].id}/remove")
    assert names(w, "referee") == {"r1", "r2"}
    for who in ("r3", "coach"):  # not a member any more / a coach is not removed as a referee
        assert w.c["coach"].post(f"/groups/{w.g.id}/referees/{w.u[who].id}/remove").status_code == 404


def test_removing_a_referee_leaves_their_matches_and_clips(w, db):
    match, video = crew_match(w, "r1", "Ktoś")
    clip = add_clip(w, match, video)
    post(w, "coach", f"/groups/{w.g.id}/referees/{w.u['r1'].id}/remove")
    assert db.get(Clip, clip.id).author_id == w.u["r1"].id and match.officials[0].user_id == w.u["r1"].id


def test_deleting_a_group_removes_memberships_and_notifications_but_not_accounts(w, db):
    post(w, "coach", f"/groups/{w.g.id}/referees", user_id=str(w.u["r3"].id))
    assert w.c["coach"].get(f"/groups/{w.g.id}/delete").status_code == 200 and db.scalar(select(TrainingGroup))
    post(w, "coach", f"/groups/{w.g.id}/delete")
    assert db.scalar(select(TrainingGroup)) is None and db.scalar(select(GroupMember)) is None
    assert db.scalar(select(Notification)) is None and db.get(User, w.u["r1"].id) is not None


@pytest.mark.parametrize("days,expected", [
    (7, [(1, 1, 1), (0, 0, 0)]), (14, [(1, 2, 1), (0, 0, 0)]), (30, [(2, 3, 2), (0, 1, 1)]),
])
def test_activity_counts_only_the_period_but_last_activity_ignores_it(w, db, days, expected):
    match, video = crew_match(w, "r1", "Ktoś")
    db.add_all([Video(match_id=match.id, created_by=w.u["r1"].id, created_at=ago(d)) for d in (3, 20)]
               + [Video(match_id=match.id, created_by=w.u["r2"].id, created_at=ago(60))])
    add_clip(w, match, video, "r1", at=ago(1))
    add_clip(w, match, video, "r1", at=ago(10), described=False)
    add_clip(w, match, video, "r1", at=ago(20))
    add_clip(w, match, video, "r2", at=ago(25))
    rows = {r.user.name: r for r in groups.activity(db, w.g, days, now=NOW)}
    assert [(r.recordings, r.markers, r.described) for r in (rows["Osoba r1"], rows["Osoba r2"])] == expected
    assert (rows["Osoba r1"].last, rows["Osoba r2"].last) == (ago(1), ago(25))


def test_described_clips_are_credited_to_the_describer_not_the_author(w, db):
    match, video = crew_match(w, "r1", "Ktoś")
    add_clip(w, match, video, "r1", by="r2", at=ago(1))
    add_clip(w, match, video, "r1", by="coach", at=ago(2))
    add_clip(w, match, video, "r1", at=ago(3)).described_by_id = None
    db.commit()
    rows = {r.user.name: r for r in groups.activity(db, w.g, 14, now=NOW)}
    assert (rows["Osoba r1"].markers, rows["Osoba r1"].described) == (3, 0)
    assert (rows["Osoba r2"].markers, rows["Osoba r2"].described, rows["Osoba r2"].last) == (0, 1, ago(1))


def test_page_highlights_referees_without_activity_in_the_chosen_period(w, db, monkeypatch):
    monkeypatch.setattr(groups, "utcnow", lambda: NOW)
    match, video = crew_match(w, "r1", "Ktoś")
    add_clip(w, match, video, "r2", at=ago(30))

    def flagged(days):
        page = w.c["coach"].get(f"/groups/{w.g.id}?days={days}").text
        return re.findall(r'(Osoba r\d)\s*<span class="chip warn">brak aktywności', page)

    assert flagged(14) == ["Osoba r1", "Osoba r2"] and flagged(90) == ["Osoba r1"]
    assert flagged("bogus") == flagged(14) and "ostatnie 14 dni" in w.c["coach"].get(f"/groups/{w.g.id}?days=5").text
    assert "<option value=\"90\" selected>" in w.c["coach"].get(f"/groups/{w.g.id}?days=90").text


def test_group_pages_do_not_query_per_referee_or_per_clip(w, db):
    match, video = crew_match(w, "r1", "Ktoś")

    def statements(url):
        with count_statements() as seen:
            assert w.c["coach"].get(url).status_code == 200
        return len(seen)

    add_clip(w, match, video, "r1")
    page, review = statements(f"/groups/{w.g.id}"), statements(f"/groups/{w.g.id}/review")
    for i in range(5):
        referee = make_user(db, ("referee",), email=f"x{i}@example.com", name=f"Dodatkowy {i}")
        w.g.members.append(GroupMember(user_id=referee.id, role="referee"))
        db.commit()
        db.add(Video(match_id=match.id, created_by=referee.id))
        w.u[f"x{i}"] = referee
        add_clip(w, match, video, f"x{i}")
    assert (statements(f"/groups/{w.g.id}"), statements(f"/groups/{w.g.id}/review")) == (page, review)


def test_review_queue_lists_described_unrated_clips_of_the_groups_matches_newest_first(w, db):
    in_group, video = crew_match(w, "r1", "Ktoś")
    elsewhere, other_video = crew_match(w, "r3", "Ktoś")
    old = add_clip(w, in_group, video, "r2", at=ago(5), description="stary")
    new = add_clip(w, in_group, video, "r1", at=ago(1), description="nowy")
    rated_by_me = add_clip(w, in_group, video, "r1", at=ago(2))
    rated_by_other = add_clip(w, in_group, video, "r1", at=ago(3))
    add_clip(w, in_group, video, "r1", described=False)
    add_clip(w, elsewhere, other_video, "r3")
    db.add_all([Rating(clip_id=rated_by_me.id, coach_id=w.u["coach"].id, verdict="correct"),
                Rating(clip_id=rated_by_other.id, coach_id=w.u["lead2"].id, verdict="correct")])
    db.commit()
    queue = lambda who: [c.id for c in groups.review_queue(db, w.g, w.u[who].id)]  # noqa: E731
    assert queue("coach") == [new.id, rated_by_other.id, old.id]
    assert queue("lead2") == [new.id, rated_by_me.id, old.id]
    assert groups.review_count(db, w.g, w.u["coach"].id) == 3
    page = w.c["coach"].get(f"/groups/{w.g.id}/review").text
    assert page.count('class="btn small"') == 3
    assert f"/groups/{w.g.id}/review" in w.c["coach"].get(f"/groups/{w.g.id}").text
    w.c["coach"].post(f"/clips/{new.id}/rating", data={"verdict": "incorrect", "comment": ""})
    assert queue("coach") == [rated_by_other.id, old.id]


def test_group_filter_combines_with_other_filters_and_pagination_on_matches(w, db):
    member_match, _ = crew_match(w, "r1", "Ktoś")
    member_match.level = "I liga"
    second, _ = crew_match(w, "Ktoś", "r2")
    second.date = member_match.date - timedelta(days=1)
    outsider, _ = crew_match(w, "r3", "Ktoś")
    db.commit()

    def listed(**params):
        return [int(i) for i in re.findall(r'<td data-label="Mecz"[^>]*><a href="/matches/(\d+)"',
                                           w.c["r3"].get("/", params=params).text)]

    assert listed(group=w.g.id) == [member_match.id, second.id]  # open to every logged-in user
    assert listed(group=w.g.id, level="I liga") == [member_match.id]
    assert listed(group=w.g.id, person=f"u{w.u['r2'].id}") == [second.id]
    assert listed(group=9999) == []
    assert set(listed(group="abc")) == {member_match.id, second.id, outsider.id}  # not a number: ignored


def test_group_filter_works_with_match_pagination(w, db):
    for _ in range(3):
        crew_match(w, "r1", "Ktoś")
    crew_match(w, "r3", "Ktoś")
    filters = match_list.parse_filters({"group": str(w.g.id), "page": "2"})
    page = match_list.list_matches(db, filters, w.u["r1"].id, page_size=2)
    assert (page.total, len(page.rows), page.page) == (3, 1, 2)
    assert f"group={w.g.id}" in filters.query(1) and "page=2" in filters.query(2)


def test_group_filter_on_clips_combines_with_the_described_filter(w, db):
    member_match, video = crew_match(w, "r1", "Ktoś")
    elsewhere, other_video = crew_match(w, "r3", "Ktoś")
    described = add_clip(w, member_match, video)
    undescribed = add_clip(w, member_match, video, described=False)
    add_clip(w, elsewhere, other_video)

    def listed(**params):
        return {int(i) for i in re.findall(r'href="/clips/(\d+)', w.c["r3"].get("/clips", params=params).text)}

    assert listed(group=w.g.id) == {described.id, undescribed.id}
    assert listed(group=w.g.id, described="1") == {described.id}
    assert re.search(rf"/clips/\d+\?group={w.g.id}", w.c["r3"].get("/clips", params={"group": w.g.id}).text)


def test_adding_notifies_once_removing_does_not_and_rejections_do_not(w, db):
    for kind, who, target in (("referees", "coach", "r3"), ("coaches", "admin", "lead2")):
        post(w, who, f"/groups/{w.g.id}/{kind}", user_id=str(w.u[target].id))
    w.c["coach"].post(f"/groups/{w.g.id}/referees", data={"user_id": str(w.u["r3"].id)})  # duplicate
    post(w, "coach", f"/groups/{w.g.id}/referees/{w.u['r3'].id}/remove")
    rows = db.scalars(select(Notification).order_by(Notification.id)).all()
    assert [(n.recipient_id, n.kind, n.actor_id, n.group_id, n.match_id) for n in rows] == [
        (w.u["r3"].id, "group_added", w.u["coach"].id, w.g.id, None),
        (w.u["lead2"].id, "group_added", w.u["admin"].id, w.g.id, None)]
    page = w.c["r3"].get("/notifications").text
    assert "Osoba coach" in page and "dodano Cię do grupy „Grupa A”" in page
    assert w.c["r3"].post(f"/notifications/{rows[0].id}/open", follow_redirects=False).headers["location"] == "/groups"
    assert (notify.unread_count(db, w.u["r3"].id), notify.unread_count(db, w.u["lead2"].id)) == (0, 1)
