"""Oceny szkoleniowców i komentarze (segment 6): każdy wiersz tabeli uprawnień przez API, walidacja,
upsert oceny, podsumowanie i filtr ocen w tabeli klipów, kaskady przy usuwaniu."""
import re

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app import feedback
from app.db import engine
from app.models import Clip, Comment, Match, Rating, User
from tests.conftest import login_client
from tests.helpers import make_match, make_ready_video, make_user

HTMX = {"HX-Request": "true"}


@pytest.fixture()
def world(db, make_client):
    """Dwa mecze z klipami; w obsadze meczu 1 jest `member`. Konta o różnych (łączonych) rolach."""
    people = {}
    for key, roles in dict(admin=("admin",), coach=("coach",), coach2=("coach",), referee=("referee",),
                           admin_coach=("admin", "coach"), referee_coach=("referee", "coach"),
                           norole=()).items():
        people[key] = make_client(*roles, name=f"Osoba {key}", email=f"{key}@example.com")
    member_client, member = make_client("referee", name="Sędzia z obsady")
    match = make_match(db, officials=(("CC", member), ("U1", "Wpisany Sędzia")), created_by=people["coach"][1])
    video = make_ready_video(db, match)
    other_match = make_match(db, officials=(("CC", "Ktoś Inny"), ("U1", "Ktoś Jeszcze")))
    other_video = make_ready_video(db, other_match)

    def clip(video_, time_sec):
        c = Clip(match_id=video_.match_id, video_id=video_.id, author_id=people["coach"][1].id, time_sec=time_sec)
        db.add(c)
        db.commit()
        return c

    return dict(people=people, member=(member_client, member), match=match, other_match=other_match,
                clip=clip(video, 100), clip2=clip(video, 200), other_clip=clip(other_video, 50),
                clients={k: v[0] for k, v in people.items()}, users={k: v[1] for k, v in people.items()})


def rate(client, clip, verdict="correct", comment="", **kw):
    return client.post(f"/clips/{clip.id}/rating", data={"verdict": verdict, "comment": comment},
                       follow_redirects=False, **kw)


def add_rating(db, clip, coach, verdict="correct", comment=""):
    rating = Rating(clip_id=clip.id, coach_id=coach.id, verdict=verdict, comment=comment)
    db.add(rating)
    db.commit()
    return rating


def add_comment(db, author, body="Komentarz", *, clip=None, match=None):
    comment = Comment(clip_id=clip.id if clip else None, match_id=match.id if match else None,
                      author_id=author.id, body=body)
    db.add(comment)
    db.commit()
    return comment


# === oceny: uprawnienia (tabela: „Ocena klipu”) =============================================
@pytest.mark.parametrize("who,allowed", [
    ("admin", False),            # sama rola administratora nie wystarcza
    ("coach", True),
    ("referee", False),
    ("admin_coach", True),       # role się sumują
    ("referee_coach", True),
    ("norole", False),
])
def test_rating_permission_per_role(world, db, who, allowed):
    r = rate(world["clients"][who], world["clip"], "incorrect", "Nie było kontaktu")
    assert r.status_code == (303 if allowed else 403), who
    rows = db.scalars(select(Rating)).all()
    if allowed:
        assert len(rows) == 1 and rows[0].coach_id == world["users"][who].id and rows[0].verdict == "incorrect"
    else:
        assert rows == []


def test_rating_requires_login_and_csrf(world, db, anon_client):
    assert anon_client.post(f"/clips/{world['clip'].id}/rating", data={"verdict": "correct"}).status_code == 401
    client = world["clients"]["coach"]
    client.headers.pop("X-CSRF-Token")
    assert client.post(f"/clips/{world['clip'].id}/rating", data={"verdict": "correct"}).status_code == 403
    client.headers["X-CSRF-Token"] = "zly-token"
    assert client.post(f"/clips/{world['clip'].id}/rating", data={"verdict": "correct"}).status_code == 403
    assert db.scalar(select(Rating)) is None


def test_rating_for_missing_clip_is_404(world):
    assert rate(world["clients"]["coach"], type("C", (), {"id": 99999})).status_code == 404


def test_rating_is_upsert_one_per_coach_and_clip(world, db):
    coach, clip = world["clients"]["coach"], world["clip"]
    assert rate(coach, clip, "correct", "Pierwsza").status_code == 303
    rating = db.scalar(select(Rating))
    assert rating.updated_at == rating.created_at and not feedback.is_edited(rating)
    assert rate(coach, clip, "debatable", "Po namyśle").status_code == 303
    db.expire_all()
    rows = db.scalars(select(Rating)).all()
    assert len(rows) == 1 and rows[0].verdict == "debatable" and rows[0].comment == "Po namyśle"
    assert feedback.is_edited(rows[0])
    # drugi szkoleniowiec i ten sam klip: osobna ocena; ten sam szkoleniowiec i inny klip: też
    assert rate(world["clients"]["coach2"], clip, "incorrect").status_code == 303
    assert rate(coach, world["clip2"], "correct").status_code == 303
    assert db.query(Rating).count() == 3


def test_resubmitting_the_same_rating_does_not_mark_it_changed(world, db):
    coach, clip = world["clients"]["coach"], world["clip"]
    rate(coach, clip, "correct", "Tak")
    before = db.scalar(select(Rating)).updated_at
    rate(coach, clip, "correct", "Tak")
    db.expire_all()
    assert db.scalar(select(Rating)).updated_at == before


def test_rating_race_on_unique_pair_updates_instead_of_failing(world, db, monkeypatch):
    """Dwa równoległe żądania: drugie nie widzi oceny pierwszego przy SELECT, ale unikalność go zatrzymuje."""
    clip, coach = world["clip"], world["users"]["coach"]
    add_rating(db, clip, coach, "correct", "Z pierwszego żądania")
    real = feedback._own_rating
    calls = []

    def stale(db_, clip_id, coach_id):
        calls.append(1)
        return None if len(calls) == 1 else real(db_, clip_id, coach_id)

    monkeypatch.setattr(feedback, "_own_rating", stale)
    r = rate(world["clients"]["coach"], clip, "incorrect", "Z drugiego żądania")
    assert r.status_code == 303 and len(calls) == 2
    db.expire_all()
    rows = db.scalars(select(Rating)).all()
    assert len(rows) == 1 and rows[0].verdict == "incorrect" and rows[0].comment == "Z drugiego żądania"


# === oceny: zmiana i usuwanie (autor albo administrator) ====================================
def test_rating_edit_and_delete_rules(world, db):
    clip, c = world["clip"], world["clients"]
    rating = add_rating(db, clip, world["users"]["coach"], "correct", "Moja")
    edit = f"/clips/{clip.id}/ratings/{rating.id}/edit"
    delete = f"/clips/{clip.id}/ratings/{rating.id}/delete"
    data = {"verdict": "incorrect", "comment": "Zmiana"}
    for who in ("coach2", "referee", "referee_coach", "norole"):   # cudza ocena: nie
        assert c[who].post(edit, data=data).status_code == 403, who
        assert c[who].post(delete).status_code == 403, who
    db.expire_all()
    assert db.get(Rating, rating.id).verdict == "correct"
    # autor zmienia
    assert c["coach"].post(edit, data=data, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(Rating, rating.id).verdict == "incorrect"
    # administrator (sama rola) zmienia cudzą ocenę, a autorem zostaje szkoleniowiec
    assert c["admin"].post(edit, data={"verdict": "debatable", "comment": "Admin"}, follow_redirects=False).status_code == 303
    db.expire_all()
    changed = db.get(Rating, rating.id)
    assert changed.verdict == "debatable" and changed.comment == "Admin"
    assert changed.coach_id == world["users"]["coach"].id and feedback.is_edited(changed)
    # admin+coach też zmienia cudzą (jako administrator)
    assert c["admin_coach"].post(edit, data=data, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(Rating, rating.id).coach_id == world["users"]["coach"].id
    # usunięcie: autor
    assert c["coach"].post(delete, follow_redirects=False).status_code == 303
    assert db.scalar(select(Rating)) is None


def test_admin_deletes_someone_elses_rating(world, db):
    rating = add_rating(db, world["clip"], world["users"]["coach"])
    r = world["clients"]["admin"].post(f"/clips/{world['clip'].id}/ratings/{rating.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and db.scalar(select(Rating)) is None


def test_rating_must_belong_to_clip_from_url(world, db):
    rating = add_rating(db, world["clip"], world["users"]["coach"])
    wrong = world["clip2"]
    for who in ("coach", "admin"):
        client = world["clients"][who]
        assert client.post(f"/clips/{wrong.id}/ratings/{rating.id}/edit",
                           data={"verdict": "incorrect"}).status_code == 404
        assert client.post(f"/clips/{wrong.id}/ratings/{rating.id}/delete").status_code == 404
    assert client.post(f"/clips/{world['clip'].id}/ratings/99999/delete").status_code == 404
    db.expire_all()
    assert db.get(Rating, rating.id).verdict == "correct"


def test_rating_write_routes_need_login_and_csrf(world, db, anon_client):
    rating = add_rating(db, world["clip"], world["users"]["coach"])
    base = f"/clips/{world['clip'].id}/ratings/{rating.id}"
    for suffix in ("/edit", "/delete"):
        assert anon_client.post(base + suffix, data={"verdict": "correct"}).status_code == 401
        client = world["clients"]["admin"]
        token = client.headers.pop("X-CSRF-Token")
        assert client.post(base + suffix, data={"verdict": "correct"}).status_code == 403
        client.headers["X-CSRF-Token"] = token
    assert db.get(Rating, rating.id) is not None


# === oceny: walidacja i widok ===============================================================
def test_rating_validation_errors_keep_the_typed_text(world, db):
    coach, clip = world["clients"]["coach"], world["clip"]
    r = rate(coach, clip, "swietna", "Mój komentarz")
    assert r.status_code == 422 and "Ocena: wybierz" in r.text and "Mój komentarz" in r.text
    r = rate(coach, clip, "")
    assert r.status_code == 422
    r = rate(coach, clip, "correct", "x" * 5001)
    assert r.status_code == 422 and "najwyżej 5000 znaków" in r.text
    assert db.scalar(select(Rating)) is None
    # HTMX dostaje samą kartę ocen z błędem
    r = rate(coach, clip, "swietna", "abc", headers=HTMX)
    assert r.status_code == 422 and 'id="oceny"' in r.text and "<html" not in r.text and "Ocena: wybierz" in r.text
    # dokładnie 5000 znaków przechodzi
    assert rate(coach, clip, "correct", "x" * 5000).status_code == 303


def test_rating_comment_is_optional_and_trimmed(world, db):
    rate(world["clients"]["coach"], world["clip"], "correct", "  \n ")
    assert db.scalar(select(Rating)).comment == ""


def test_clip_page_shows_all_ratings_with_author_and_change_info(world, db):
    clip = world["clip"]
    rate(world["clients"]["coach"], clip, "correct", "Zgadzam się <b>z</b> decyzją")
    rate(world["clients"]["coach2"], clip, "incorrect")
    rate(world["clients"]["coach"], clip, "debatable", "Jednak dyskusyjna")
    page = world["clients"]["referee"].get(f"/clips/{clip.id}").text
    card = page.split('id="oceny"')[1].split("</aside>")[0]
    assert "Osoba coach" in card and "Osoba coach2" in card
    assert "dyskusyjna" in card and "nieprawidłowa" in card and "zmieniona" in card
    assert "Zgadzam się" not in card and "Jednak dyskusyjna" in card
    # sędzia widzi oceny, ale bez formularza i bez przycisków zmiany
    assert 'id="rating-form"' not in card and "Zmień" not in card and "Usuń" not in card


def test_rating_form_only_for_coaches_and_prefilled(world, db):
    clip, c = world["clip"], world["clients"]
    for who in ("admin", "referee", "norole"):
        assert 'id="rating-form"' not in c[who].get(f"/clips/{clip.id}").text, who
    for who in ("coach", "admin_coach", "referee_coach"):
        assert 'id="rating-form"' in c[who].get(f"/clips/{clip.id}").text, who
    rate(c["coach"], clip, "debatable", "Wstępnie")
    form = c["coach"].get(f"/clips/{clip.id}").text.split('id="rating-form"')[1].split("</form>")[0]
    assert re.search(r'value="debatable"\s+checked', form) and "Wstępnie" in form and "Zmień swoją ocenę" in form


def test_admin_sees_change_and_delete_on_foreign_ratings(world, db):
    rating = add_rating(db, world["clip"], world["users"]["coach"], "correct", "Ocena trenera")
    admin_page = world["clients"]["admin"].get(f"/clips/{world['clip'].id}").text
    assert f"/ratings/{rating.id}/edit" in admin_page and f"/ratings/{rating.id}/delete" in admin_page
    other = world["clients"]["coach2"].get(f"/clips/{world['clip'].id}").text
    assert f"/ratings/{rating.id}/edit" not in other and f"/ratings/{rating.id}/delete" not in other
    own = world["clients"]["coach"].get(f"/clips/{world['clip'].id}").text
    assert f"/ratings/{rating.id}/edit" not in own      # własną zmienia się formularzem „Twoja ocena”
    assert f"/ratings/{rating.id}/delete" in own


def test_rating_htmx_returns_the_card_fragment(world, db):
    r = rate(world["clients"]["coach"], world["clip"], "correct", "Ok", headers=HTMX)
    assert r.status_code == 200 and r.text.lstrip().startswith("<") and 'id="oceny"' in r.text and "<html" not in r.text
    assert "prawidłowa" in r.text and "Osoba coach" in r.text


# === podsumowanie ocen i filtr w tabeli klipów =============================================
def test_table_shows_rating_summary_and_filters_by_rating(world, db):
    m, clip, clip2, clip3 = world["match"], world["clip"], world["clip2"], None
    v = clip.video
    clip3 = Clip(match_id=m.id, video_id=v.id, time_sec=300)
    db.add(clip3)
    db.commit()
    for who, verdict in (("coach", "correct"), ("coach2", "correct"), ("admin_coach", "debatable")):
        add_rating(db, clip, world["users"][who], verdict)
    add_rating(db, clip2, world["users"]["coach"], "incorrect")
    client = world["clients"]["referee"]

    page = client.get(f"/matches/{m.id}").text
    assert "2× prawidłowa" in page and "1× dyskusyjna" in page and "1× nieprawidłowa" in page

    def listed(**params):
        html = client.get("/clips", params={"match_id": m.id, **params}).text
        return [c.id for c in (clip, clip2, clip3) if f'href="/clips/{c.id}' in html]

    assert listed() == sorted([clip.id, clip2.id, clip3.id])
    assert listed(rating="correct") == [clip.id]
    assert listed(rating="debatable") == [clip.id]
    assert listed(rating="incorrect") == [clip2.id]
    assert listed(rating="any") == [clip.id, clip2.id]
    assert listed(rating="none") == [clip3.id]
    assert listed(rating="bzdura") == sorted([clip.id, clip2.id, clip3.id])    # nieznana wartość = bez filtra
    # filtr jest też w adresie nawigacji poprzedni/następny i w zakładce meczu
    tab = client.get(f"/matches/{m.id}", params={"rating": "none"}).text
    assert f'href="/clips/{clip3.id}?rating=none"' in tab and f'href="/clips/{clip.id}' not in tab
    assert '<option value="none" selected>' in tab


def test_clip_lists_do_not_run_per_clip_queries_for_ratings_and_comments(world, db):
    m, v = world["match"], world["clip"].video

    def populate(n):
        for i in range(n):
            c = Clip(match_id=m.id, video_id=v.id, time_sec=400 + i)
            db.add(c)
            db.commit()
            add_rating(db, c, world["users"]["coach"], "correct")
            add_comment(db, world["users"]["admin"], clip=c)

    def count_queries(url):
        statements = []
        listener = lambda conn, cur, stmt, *a: statements.append(stmt)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert world["clients"]["coach"].get(url).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    populate(2)
    small = {u: count_queries(u) for u in ("/clips", f"/matches/{m.id}")}
    populate(15)
    large = {u: count_queries(u) for u in ("/clips", f"/matches/{m.id}")}
    assert large == small


# === komentarze: uprawnienia ===============================================================
SCOPES = ("clip", "match")


def comment_url(world, scope, suffix=""):
    base = f"/clips/{world['clip'].id}" if scope == "clip" else f"/matches/{world['match'].id}"
    return f"{base}/comments{suffix}"


def comment_of(db, scope, world, author, body="Treść"):
    return add_comment(db, author, body, **({"clip": world["clip"]} if scope == "clip" else {"match": world["match"]}))


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("who", ["admin", "coach", "referee", "admin_coach", "referee_coach", "norole"])
def test_everyone_logged_in_comments(world, db, scope, who):
    r = world["clients"][who].post(comment_url(world, scope), data={"body": "Mój głos"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(comment_url(world, scope).split("/comments")[0] + "#comment-")
    comment = db.scalar(select(Comment))
    assert comment.author_id == world["users"][who].id and comment.body == "Mój głos"
    assert (comment.clip_id is not None) == (scope == "clip") and (comment.match_id is not None) == (scope == "match")


@pytest.mark.parametrize("scope", SCOPES)
def test_comment_routes_need_login_and_csrf(world, db, anon_client, scope):
    comment = comment_of(db, scope, world, world["users"]["coach"])
    for method, suffix, data in (("post", "", {"body": "x"}), ("post", f"/{comment.id}/edit", {"body": "x"}),
                                 ("post", f"/{comment.id}/delete", {}), ("get", f"/{comment.id}/edit", None)):
        kw = {"data": data} if data is not None else {}
        assert getattr(anon_client, method)(comment_url(world, scope, suffix), follow_redirects=False, **kw).status_code in (303, 401), suffix
    for suffix in ("", f"/{comment.id}/edit", f"/{comment.id}/delete"):
        client = world["clients"]["coach"]
        token = client.headers.pop("X-CSRF-Token")
        assert client.post(comment_url(world, scope, suffix), data={"body": "x"}).status_code == 403, suffix
        client.headers["X-CSRF-Token"] = token
    db.expire_all()
    assert db.query(Comment).count() == 1 and db.get(Comment, comment.id).body == "Treść"


@pytest.mark.parametrize("scope", SCOPES)
def test_anonymous_cannot_comment(world, db, anon_client, scope):
    r = anon_client.post(comment_url(world, scope), data={"body": "x"})
    assert r.status_code == 401 and db.scalar(select(Comment)) is None


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("who,allowed", [
    ("coach", True),                # autor
    ("admin", False),               # admin NIE edytuje cudzych
    ("admin_coach", False),
    ("coach2", False),
    ("referee", False),
    ("norole", False),
])
def test_only_the_author_edits_a_comment(world, db, scope, who, allowed):
    comment = comment_of(db, scope, world, world["users"]["coach"], "Pierwotny")
    client = world["clients"][who]
    r = client.post(comment_url(world, scope, f"/{comment.id}/edit"), data={"body": "Zmieniony"}, follow_redirects=False)
    assert r.status_code == (303 if allowed else 403), who
    assert client.get(comment_url(world, scope, f"/{comment.id}/edit")).status_code == (200 if allowed else 403)
    db.expire_all()
    stored = db.get(Comment, comment.id)
    assert (stored.body, stored.edited_at is not None) == (("Zmieniony", True) if allowed else ("Pierwotny", False))


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("who,allowed", [
    ("coach", True), ("admin", True), ("admin_coach", True),     # autor albo administrator
    ("coach2", False), ("referee", False), ("referee_coach", False), ("norole", False),
])
def test_author_or_admin_deletes_a_comment(world, db, scope, who, allowed):
    comment_id = comment_of(db, scope, world, world["users"]["coach"]).id
    r = world["clients"][who].post(comment_url(world, scope, f"/{comment_id}/delete"), follow_redirects=False)
    assert r.status_code == (303 if allowed else 403), who
    db.expire_all()
    assert (db.scalar(select(Comment).where(Comment.id == comment_id)) is None) == allowed


def test_comment_must_belong_to_the_clip_or_match_from_url(world, db):
    clip_comment = add_comment(db, world["users"]["coach"], "Pod klipem", clip=world["clip"])
    match_comment = add_comment(db, world["users"]["coach"], "Pod meczem", match=world["match"])
    other_clip_comment = add_comment(db, world["users"]["coach"], "Inny klip", clip=world["other_clip"])
    coach = world["clients"]["coach"]
    admin = world["clients"]["admin"]
    wrong = [  # (adres rodzica, komentarz) niezgodne
        (f"/clips/{world['clip2'].id}", clip_comment), (f"/clips/{world['clip'].id}", match_comment),
        (f"/matches/{world['match'].id}", clip_comment), (f"/matches/{world['other_match'].id}", match_comment),
        (f"/clips/{world['clip'].id}", other_clip_comment), (f"/clips/{world['clip'].id}", None),
    ]
    for base, comment in wrong:
        cid = comment.id if comment else 99999
        for client in (coach, admin):
            assert client.post(f"{base}/comments/{cid}/edit", data={"body": "Podmiana"}).status_code == 404, (base, cid)
            assert client.post(f"{base}/comments/{cid}/delete").status_code == 404, (base, cid)
        assert coach.get(f"{base}/comments/{cid}/edit").status_code == 404
        assert coach.get(f"{base}/comments/{cid}").status_code == 404
    db.expire_all()
    assert db.query(Comment).count() == 3
    assert {c.body for c in db.scalars(select(Comment))} == {"Pod klipem", "Pod meczem", "Inny klip"}
    # komentowanie nieistniejącego klipu/meczu
    assert coach.post("/clips/99999/comments", data={"body": "x"}).status_code == 404
    assert coach.post("/matches/99999/comments", data={"body": "x"}).status_code == 404


# === komentarze: walidacja, bezpieczeństwo, odpowiedzi HTMX =================================
@pytest.mark.parametrize("scope", SCOPES)
def test_comment_body_validation(world, db, scope):
    client = world["clients"]["coach"]
    for body in ("", "   ", "\n\t \r\n"):
        r = client.post(comment_url(world, scope), data={"body": body})
        assert r.status_code == 422 and "wpisz treść" in r.text, repr(body)
    r = client.post(comment_url(world, scope), data={"body": "z" * 5001})
    assert r.status_code == 422 and "najwyżej 5000 znaków" in r.text
    assert "z" * 5001 in r.text              # wpisana treść wraca do pola, nic nie ginie
    assert db.scalar(select(Comment)) is None
    assert client.post(comment_url(world, scope), data={"body": "z" * 5000}, follow_redirects=False).status_code == 303
    # limit liczony po normalizacji końców linii (przeglądarka wysyła \r\n)
    assert client.post(comment_url(world, scope), data={"body": "a\r\n" * 2499 + "b"}, follow_redirects=False).status_code == 303
    assert db.query(Comment).count() == 2


@pytest.mark.parametrize("scope", SCOPES)
def test_comment_edit_validation_keeps_comment_and_shows_error(world, db, scope):
    comment = comment_of(db, scope, world, world["users"]["coach"], "Pierwotny")
    client = world["clients"]["coach"]
    url = comment_url(world, scope, f"/{comment.id}/edit")
    r = client.post(url, data={"body": "  "})
    assert r.status_code == 422 and "wpisz treść" in r.text
    r = client.post(url, data={"body": "y" * 5001})
    assert r.status_code == 422 and "najwyżej 5000 znaków" in r.text
    r = client.post(url, data={"body": "y" * 5001}, headers=HTMX)
    assert r.status_code == 422 and "<html" not in r.text and "najwyżej 5000 znaków" in r.text
    db.expire_all()
    stored = db.get(Comment, comment.id)
    assert stored.body == "Pierwotny" and stored.edited_at is None


@pytest.mark.parametrize("scope", SCOPES)
def test_comment_is_trimmed_escaped_and_keeps_line_breaks(world, db, scope):
    client = world["clients"]["coach"]
    body = '  <script>alert(1)</script> & "cytat"\r\ndruga linia\n\n\ntrzecia  '
    client.post(comment_url(world, scope), data={"body": body})
    stored = db.scalar(select(Comment)).body
    assert stored == '<script>alert(1)</script> & "cytat"\ndruga linia\n\n\ntrzecia'
    page = client.get(comment_url(world, scope).split("/comments")[0]).text
    section = page.split('id="komentarze"')[1]
    assert "<script>alert(1)</script>" not in section
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &#34;cytat&#34;\ndruga linia\n\n\ntrzecia" in section
    assert "|safe" not in open("app/templates/_comment_item.html", encoding="utf-8").read()
    css = open("app/static/app.css", encoding="utf-8").read()
    assert re.search(r"\.comment \.body[^{]*\{[^}]*white-space: pre-wrap", css)


@pytest.mark.parametrize("scope", SCOPES)
def test_comment_edit_sets_edited_marker_only_on_real_change(world, db, scope):
    comment = comment_of(db, scope, world, world["users"]["coach"], "Pierwotny")
    client = world["clients"]["coach"]
    url = comment_url(world, scope, f"/{comment.id}/edit")
    client.post(url, data={"body": "Pierwotny  "})                       # bez zmiany treści
    db.expire_all()
    assert db.get(Comment, comment.id).edited_at is None
    client.post(url, data={"body": "Poprawiony"})
    db.expire_all()
    assert db.get(Comment, comment.id).edited_at is not None
    page = client.get(comment_url(world, scope).split("/comments")[0]).text
    assert "edytowano" in page and "Poprawiony" in page


@pytest.mark.parametrize("scope", SCOPES)
def test_comment_htmx_fragments(world, db, scope):
    client = world["clients"]["coach"]
    r = client.post(comment_url(world, scope), data={"body": "Nowy"}, headers=HTMX)
    assert r.status_code == 200 and "<html" not in r.text
    assert 'class="comment"' in r.text and "Nowy" in r.text
    assert 'id="no-comments"' in r.text and 'hx-swap-oob="true"' in r.text and 'id="comment-form"' in r.text
    comment = db.scalar(select(Comment))
    edit = client.get(comment_url(world, scope, f"/{comment.id}/edit"), headers=HTMX)
    assert edit.status_code == 200 and "<textarea" in edit.text and "Anuluj" in edit.text and "<html" not in edit.text
    cancel = client.get(comment_url(world, scope, f"/{comment.id}"), headers=HTMX)
    assert cancel.status_code == 200 and "Nowy" in cancel.text and "<textarea" not in cancel.text
    # bez HTMX: edycja to osobna strona, anulowanie wraca do rodzica
    page = client.get(comment_url(world, scope, f"/{comment.id}/edit"))
    assert page.status_code == 200 and "<html" in page.text and "Edycja komentarza" in page.text
    back = client.get(comment_url(world, scope, f"/{comment.id}"), follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"].endswith(f"#comment-{comment.id}")
    # błąd dodawania w HTMX: podmieniamy sam formularz
    bad = client.post(comment_url(world, scope), data={"body": " "}, headers=HTMX)
    assert bad.status_code == 422 and bad.headers["HX-Retarget"] == "#comment-form" and bad.headers["HX-Reswap"] == "outerHTML"
    # usunięcie: ostatni komentarz przywraca komunikat o braku komentarzy
    gone = client.post(comment_url(world, scope, f"/{comment.id}/delete"), headers=HTMX)
    assert gone.status_code == 200 and "Brak komentarzy." in gone.text and db.scalar(select(Comment)) is None
    db.expunge_all()
    comment = comment_of(db, scope, world, world["users"]["coach"])
    comment_of(db, scope, world, world["users"]["coach"], "Drugi")
    gone = client.post(comment_url(world, scope, f"/{comment.id}/delete"), headers=HTMX)
    assert "Brak komentarzy." not in gone.text


def test_pages_list_comments_with_authors_in_order(world, db):
    add_comment(db, world["users"]["coach"], "Pierwszy", match=world["match"])
    add_comment(db, world["users"]["admin"], "Drugi", match=world["match"])
    add_comment(db, world["users"]["coach"], "Do klipu", clip=world["clip"])
    match_page = world["clients"]["referee"].get(f"/matches/{world['match'].id}").text
    assert match_page.index("Pierwszy") < match_page.index("Drugi") and "Osoba coach" in match_page
    assert "Do klipu" not in match_page
    clip_page = world["clients"]["referee"].get(f"/clips/{world['clip'].id}").text
    assert "Do klipu" in clip_page and "Pierwszy" not in clip_page
    # sędzia widzi „Edytuj”/„Usuń” tylko przy swoich
    mine = add_comment(db, world["member"][1], "Mój", match=world["match"])
    page = world["member"][0].get(f"/matches/{world['match'].id}").text
    assert f"/comments/{mine.id}/edit" in page and f"/comments/{mine.id}/delete" in page
    foreign = [c.id for c in db.scalars(select(Comment)) if c.id != mine.id and c.match_id]
    assert foreign and all(f"/comments/{i}/edit" not in page and f"/comments/{i}/delete" not in page for i in foreign)


def test_htmx_refresh_of_match_page_does_not_render_comments(world, db):
    """Odświeżanie panelu nagrań/klipów (HTMX) nie obejmuje sekcji komentarzy ani jej nie wczytuje."""
    add_comment(db, world["users"]["coach"], "Widoczny tylko na pełnej stronie", match=world["match"])
    client = world["clients"]["coach"]
    full = client.get(f"/matches/{world['match'].id}").text
    partial = client.get(f"/matches/{world['match'].id}", headers=HTMX).text
    assert 'id="komentarze"' in full and 'id="komentarze"' not in partial
    # sekcja komentarzy jest poza elementami odświeżanymi: #videos-panel, #clips-head, #clips-list, #match-state
    refreshed = re.search(r'<div id="videos-panel".*?<h3>|<section id="clips-section">.*?</section>', full, re.S)
    assert refreshed and 'id="komentarze"' not in refreshed.group(0)
    clip_full = client.get(f"/clips/{world['clip'].id}").text
    clip_partial = client.get(f"/clips/{world['clip'].id}", headers=HTMX).text
    assert 'id="komentarze"' in clip_full and 'id="oceny"' in clip_full
    assert 'id="komentarze"' not in clip_partial and 'id="oceny"' not in clip_partial


def test_failed_comment_on_page_without_js_rerenders_page_with_draft(world, db):
    client = world["clients"]["coach"]
    r = client.post(f"/matches/{world['match'].id}/comments", data={"body": "q" * 5001})
    assert r.status_code == 422 and "<html" in r.text and "najwyżej 5000 znaków" in r.text and "Klipy (" in r.text
    r = client.post(f"/clips/{world['clip'].id}/comments", data={"body": " "})
    assert r.status_code == 422 and "<html" in r.text and "Opis klipu" in r.text


# === kaskady ===================================================================================
def test_deleting_a_clip_removes_its_comments_and_ratings(world, db):
    clip, other = world["clip"], world["clip2"]
    add_rating(db, clip, world["users"]["coach"])
    add_rating(db, other, world["users"]["coach"])
    add_comment(db, world["users"]["coach"], "Do skasowania", clip=clip)
    keep = add_comment(db, world["users"]["coach"], "Zostaje", clip=other)
    r = world["clients"]["admin"].post(f"/clips/{clip.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert [c.body for c in db.scalars(select(Comment))] == ["Zostaje"] and db.get(Comment, keep.id)
    assert [r_.clip_id for r_ in db.scalars(select(Rating))] == [other.id]


def test_deleting_a_match_removes_match_and_clip_comments_and_ratings(world, db):
    add_rating(db, world["clip"], world["users"]["coach"])
    add_rating(db, world["other_clip"], world["users"]["coach"])
    add_comment(db, world["users"]["coach"], "Mecz", match=world["match"])
    add_comment(db, world["users"]["coach"], "Klip", clip=world["clip"])
    keep = add_comment(db, world["users"]["coach"], "Inny mecz", match=world["other_match"])
    r = world["clients"]["admin"].post(f"/matches/{world['match'].id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert [c.id for c in db.scalars(select(Comment))] == [keep.id]
    assert [r_.clip_id for r_ in db.scalars(select(Rating))] == [world["other_clip"].id]


def test_database_level_cascades_work_with_foreign_keys_on(world, db):
    """Kaskada działa także na poziomie bazy (ON DELETE CASCADE, PRAGMA foreign_keys=ON), nie tylko w ORM."""
    from sqlalchemy import delete, text
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    add_rating(db, world["clip"], world["users"]["coach"])
    add_comment(db, world["users"]["coach"], "K", clip=world["clip"])
    add_comment(db, world["users"]["coach"], "M", match=world["match"])
    db.execute(delete(Match).where(Match.id == world["match"].id))
    db.commit()
    assert db.query(Comment).count() == 0 and db.query(Rating).count() == 0 and db.query(Clip).filter_by(match_id=world["match"].id).count() == 0


def test_accounts_with_ratings_or_comments_cannot_be_deleted(world, db):
    """Użytkowników się nie usuwa (panel admina tylko dezaktywuje); baza i tak chroni oceny i komentarze:
    ratings.coach_id i comments.author_id nie mają ON DELETE, więc usunięcie konta zostaje odrzucone."""
    coach = world["users"]["coach"]
    add_rating(db, world["clip"], coach)
    add_comment(db, coach, "Treść", match=world["match"])
    db.expunge_all()
    with pytest.raises(IntegrityError):
        db.delete(db.get(User, coach.id))
        db.flush()
    db.rollback()
    assert db.get(User, coach.id) is not None
