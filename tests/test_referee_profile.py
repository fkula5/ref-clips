import re
from datetime import date, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app import config, feedback, groups, referee_profile, share
from app.models import Clip, GroupMember, SelfAssessment, Sheet, TrainingSet
from app.storage import storage
from app.timeutil import utcnow
from tests.helpers import category_named, make_match, make_ready_video, make_user

TODAY = date.today()


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


@pytest.fixture()
def w(db, make_client):
    """`ref` is the profile's subject, in the group `g` led by `coach`; `coach2` leads nothing. Matches:
    m1 (10 days ago, CC ref), m2 (60 days ago, U1 ref), m3 (500 days ago, CC ref) and m4 (10 days ago, only
    `ref2`).
    """
    clients, users = {}, {}
    for name, role in {"coach": "coach", "coach2": "coach", "admin": "admin", "ref": "referee",
                       "ref2": "referee"}.items():
        clients[name], users[name] = make_client(role, name=f"Osoba {name}", email=f"{name}@sekret.example")
    group = groups.create_group(db, users["coach"], "Grupa Alfa", "")
    group.members.append(GroupMember(user_id=users["ref"].id, role="referee"))
    db.commit()
    matches = {}
    for key, day, crew in (("m1", 10, (("CC", users["ref"]), ("U1", "Kasia Żółć"))),
                           ("m2", 60, (("CC", users["ref2"]), ("U1", users["ref"]))),
                           ("m3", 500, (("CC", users["ref"]), ("U1", users["ref2"]))),
                           ("m4", 10, (("CC", users["ref2"]), ("U1", "Jan Obcy")))):
        match = make_match(db, officials=crew, created_by=users["coach"])
        match.date = ago(day)
        match.team_a_name = f"Dom {key}"
        matches[key] = (match, make_ready_video(db, match))
    db.commit()
    world = SimpleNamespace(c=clients, u=users, g=group, db=db, m={k: v[0] for k, v in matches.items()},
                            v={k: v[1] for k, v in matches.items()})

    def clip(match, function="CC", category="kroki", *, whole_team=False, description="Opis", at=None):
        row = Clip(match_id=world.m[match].id, video_id=world.v[match].id, author_id=users["coach"].id,
                   time_sec=10.0, official_id=world.m[match].official(function).id if function else None,
                   whole_team=whole_team, category_id=category_named(db, category) if category else None,
                   description=description, status="cut", described_at=utcnow(), created_at=at or utcnow())
        db.add(row)
        db.commit()
        row.clip_path, row.clip_version = f"clips/{row.id}_v1.mp4", 1
        with storage.open_write(row.clip_path) as fh:
            fh.write(b"x" * 64)
        db.commit()
        return row

    def rate(clip_row, who, verdict, comment=""):
        rating = feedback.save_own_rating(db, clip_row, users[who].id, verdict, comment)
        db.commit()
        return rating

    def comment(clip_row, who, body):
        row = feedback.create_comment(db, users[who].id, body, clip_id=clip_row.id)
        db.commit()
        return row

    world.clip, world.rate, world.comment = clip, rate, comment
    return world


def profile(w, viewer="coach", who="ref", **params):
    return w.c[viewer].get(f"/referees/{w.u[who].id}", params=params)


def main(html: str) -> str:
    """The page without the top bar (its account menu links to the viewer's own profile)."""
    return html.split("<main>", 1)[1]


def clip_ids(html: str) -> set[int]:
    return {int(i) for i in re.findall(r'href="/clips/(\d+)[?"#]', html)}


def section(html: str, marker: str) -> str:
    """The part of the page from the heading with id `marker` to the next heading."""
    start = html.index(f'id="{marker}"')
    end = html.find("<h2", start)
    return html[start:end if end != -1 else None]


# --- access -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("viewer", ["ref", "ref2", "coach", "coach2", "admin"])
def test_every_logged_in_user_opens_any_referee_profile(w, viewer):
    r = profile(w, viewer)
    assert r.status_code == 200
    assert "Osoba ref" in r.text


def test_anonymous_user_is_sent_to_login(w, anon_client):
    r = anon_client.get(f"/referees/{w.u['ref'].id}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")


def test_only_referee_accounts_have_a_profile(w, db, make_client):
    assert profile(w, who="coach").status_code == 404
    assert profile(w, who="admin").status_code == 404
    assert w.c["coach"].get("/referees/99999").status_code == 404
    both_client, both = make_client("coach", "referee", name="Trener i sędzia")
    assert w.c["coach"].get(f"/referees/{both.id}").status_code == 200


def test_inactive_referee_still_has_a_marked_profile(w, db):
    old = make_user(db, ("referee",), email="old@example.com", name="Były Sędzia", active=False)
    match = make_match(db, officials=(("CC", old), ("U1", "Ktoś")))
    r = w.c["coach"].get(f"/referees/{old.id}")
    assert r.status_code == 200 and "konto nieaktywne" in r.text and "Były Sędzia" in r.text
    assert "konto nieaktywne" not in profile(w).text
    assert str(match.id) in r.text


# --- counts and links --------------------------------------------------------------------------------

def test_category_table_counts_clips_by_verdict_and_links_to_the_clip_list(w):
    a = w.clip("m1", category="kroki")
    b = w.clip("m1", category="kroki")
    c = w.clip("m2", "U1", category="kroki")
    d = w.clip("m1", category="osobisty")
    other = w.clip("m4", category="kroki")  # another referee's clip
    team = w.clip("m1", None, category="kroki", whole_team=True)
    w.rate(a, "coach", "correct")
    w.rate(a, "coach2", "incorrect")  # two verdicts on one clip: it counts under both
    w.rate(c, "coach", "incorrect")
    w.rate(d, "coach", "correct")
    w.rate(other, "coach", "debatable")
    w.rate(team, "coach", "debatable")

    page = profile(w, range="all").text
    table = section(page, "kategorie")
    row = re.search(r"<tr>\s*<td data-label=\"Kategoria\"[^>]*>kroki</td>(.*?)</tr>", table, re.S).group(1)
    cells = dict(re.findall(r'data-label="([^"]+)">(.*?)</td>', row, re.S))
    text = {k: re.sub(r"<[^>]+>", "", v).strip() for k, v in cells.items()}
    assert text == {"Klipy": "3", "prawidłowa": "1", "nieprawidłowa": "2", "dyskusyjna": "0", "Bez ocen": "1"}

    key = f"u{w.u['ref'].id}"
    kroki = category_named(w.db, "kroki")
    expected = {  # link -> clips the list must show for it
        f"/clips?person={key}&category_id={kroki}": {a.id, b.id, c.id},
        f"/clips?person={key}&category_id={kroki}&rating=correct": {a.id},
        f"/clips?person={key}&category_id={kroki}&rating=incorrect": {a.id, c.id},
        f"/clips?person={key}&category_id={kroki}&rating=none": {b.id},
    }
    for link, ids in expected.items():
        assert f'href="{link.replace("&", "&amp;")}"' in table, link
        assert clip_ids(w.c["coach"].get(link).text) == ids
    assert "/clips?person=" + key + f"&amp;category_id={kroki}&amp;rating=debatable" not in table  # zero: no link


def test_every_number_in_the_tables_matches_the_list_it_links_to(w):
    clips = [w.clip("m1"), w.clip("m1", category="osobisty"), w.clip("m2", "U1", category="3 s"), w.clip("m3")]
    for i, row in enumerate(clips):
        w.rate(row, "coach", ("correct", "incorrect", "debatable", "correct")[i])
    page = profile(w, range="all").text
    links = re.findall(r'<a href="(/clips\?[^"]+)">(\d+)</a>', section(page, "mecze") + section(page, "kategorie"))
    assert len(links) > 10
    for href, number in links:
        href = href.replace("&amp;", "&")
        assert len(clip_ids(w.c["coach"].get(href).text)) == int(number), href
        assert parse_qs(urlsplit(href).query)["person"] == [f"u{w.u['ref'].id}"]


def test_note_says_the_numbers_are_not_an_efficiency_score_and_links_ignore_the_period(w):
    w.clip("m1")
    page = profile(w, range="30").text
    assert "nie są miarą skuteczności" in page and "nie ma filtra dat" in page
    assert "nie ma filtra dat" not in profile(w, range="all").text
    assert "date" not in " ".join(re.findall(r'href="(/clips\?[^"]+)"', page))


def test_match_table_has_one_row_per_match_newest_first_with_crew_function(w):
    a, b = w.clip("m1"), w.clip("m1")
    w.clip("m2", "U1")
    w.rate(a, "coach", "correct")
    w.rate(b, "coach", "incorrect")
    w.rate(b, "coach2", "debatable")
    w.clip("m4")
    table = section(profile(w, range="all").text, "mecze")
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]
    assert [int(re.search(r'href="/matches/(\d+)"', r).group(1)) for r in rows] == [
        w.m["m1"].id, w.m["m2"].id, w.m["m3"].id]
    cells = [{k: re.sub(r"<[^>]+>", "", v).strip() for k, v in re.findall(r'data-label="([^"]+)"[^>]*>(.*?)</td>', r, re.S)}
             for r in rows]
    assert [c["Funkcja"] for c in cells] == ["CC", "U1", "CC"]
    assert [c["Klipy"] for c in cells] == ["2", "1", "0"]
    assert [c["Ocenione"] for c in cells] == ["2", "0", "0"]
    assert [(c["prawidłowa"], c["nieprawidłowa"], c["dyskusyjna"]) for c in cells][0] == ("1", "1", "1")
    assert "Dom m4" not in table and "II liga" in table


def test_a_typed_name_equal_to_the_account_name_counts_for_the_account(w, db):
    match = make_match(db, officials=(("CC", "osoba REF"), ("U1", "Ktoś")))  # same normalised name as "Osoba ref"
    match.date = ago(5)
    video = make_ready_video(db, match)
    db.add(Clip(match_id=match.id, video_id=video.id, author_id=w.u["coach"].id, time_sec=3.0,
                official_id=match.official("CC").id, category_id=category_named(db, "kroki"), status="cut"))
    db.commit()
    page = profile(w).text
    assert f'href="/matches/{match.id}"' in page and "Klipy: <strong>1</strong>" in page


def test_matches_are_paginated(w, monkeypatch):
    monkeypatch.setattr(config, "MATCH_PAGE_SIZE", 2)
    first = profile(w, range="all").text
    assert f'href="/matches/{w.m["m1"].id}"' in first and f'href="/matches/{w.m["m3"].id}"' not in first
    assert "strona 1 z 2" in first and f"/referees/{w.u['ref'].id}?range=all&amp;page=2#mecze" in first
    second = profile(w, range="all", page="2").text
    assert f'href="/matches/{w.m["m3"].id}"' in second and "strona 2 z 2" in second


# --- period ------------------------------------------------------------------------------------------

def test_period_filter_limits_matches_counts_clips_ratings_and_comments(w):
    recent, middle, old = w.clip("m1"), w.clip("m2", "U1"), w.clip("m3")
    for clip, text in ((recent, "nowy"), (middle, "średni"), (old, "stary")):
        w.rate(clip, "coach", "correct", f"ocena-{text}")
        w.comment(clip, "coach2", f"komentarz-{text}")

    def shown(period):
        page = profile(w, range=period).text
        return ({m for m in "m1 m2 m3".split() if f'href="/matches/{w.m[m].id}"' in section(page, "mecze")},
                {t for t in ("nowy", "średni", "stary") if f"ocena-{t}" in page},
                {t for t in ("nowy", "średni", "stary") if f"komentarz-{t}" in page},
                re.search(r"Klipy: <strong>(\d+)", page).group(1))

    assert shown("30") == ({"m1"}, {"nowy"}, {"nowy"}, "1")
    assert shown("90") == ({"m1", "m2"}, {"nowy", "średni"}, {"nowy", "średni"}, "2")
    assert shown("all") == ({"m1", "m2", "m3"}, {"nowy", "średni", "stary"}, {"nowy", "średni", "stary"}, "3")
    assert shown("garbage") == shown(referee_profile.DEFAULT_PERIOD)


def test_season_starts_in_august():
    assert referee_profile.period_start("season", date(2026, 11, 22)) == date(2026, 8, 1)
    assert referee_profile.period_start("season", date(2027, 3, 1)) == date(2026, 8, 1)
    assert referee_profile.period_start("season", date(2027, 8, 1)) == date(2027, 8, 1)
    assert referee_profile.period_start("30", date(2026, 11, 22)) == date(2026, 10, 23)
    assert referee_profile.period_start("all", date(2026, 11, 22)) is None


# --- recent clips, ratings and comments ----------------------------------------------------------------

def test_recent_lists_show_latest_first_with_snippets_and_links(w, monkeypatch):
    monkeypatch.setattr(referee_profile, "RECENT_LIMIT", 2)
    clips = [w.clip("m1", at=utcnow() - timedelta(minutes=10 - i)) for i in range(3)]
    long_text = "x" * 400
    for i, clip in enumerate(clips):
        w.rate(clip, "coach", "incorrect", f"uwaga {i} " + long_text)
        w.comment(clip, "coach2", f"pytanie {i} " + long_text)
    page = profile(w).text
    assert clip_ids(section(page, "klipy")) == {clips[2].id, clips[1].id}
    ratings, comments = section(page, "oceny"), section(page, "komentarze")
    assert "uwaga 2" in ratings and "uwaga 1" in ratings and "uwaga 0" not in ratings
    assert ratings.index("uwaga 2") < ratings.index("uwaga 1")
    assert "pytanie 2" in comments and "pytanie 0" not in comments
    assert long_text not in ratings and long_text not in comments and "…" in ratings
    assert "Osoba coach" in ratings and "Osoba coach2" in comments
    assert f'href="/clips/{clips[2].id}#rating-' in ratings and f'href="/clips/{clips[2].id}#comment-' in comments
    assert f'href="/clips?person=u{w.u["ref"].id}"' in section(page, "klipy")  # "Wszystkie klipy sędziego"
    assert "Wszystkie klipy sędziego" in page


def test_ratings_and_comments_of_other_referees_clips_are_not_listed(w):
    mine, other = w.clip("m1"), w.clip("m4")
    w.rate(mine, "coach", "correct", "dla-mnie")
    w.rate(other, "coach", "correct", "dla-innego")
    w.comment(other, "coach2", "komentarz-innego")
    page = profile(w).text
    assert "dla-mnie" in page and "dla-innego" not in page and "komentarz-innego" not in page


# --- visibility --------------------------------------------------------------------------------------

@pytest.mark.parametrize("viewer", ["ref", "ref2", "coach", "coach2", "admin"])
def test_profile_only_shows_what_the_clip_list_and_clip_pages_show_to_that_viewer(w, viewer):
    clips = [w.clip("m1"), w.clip("m2", "U1", category="3 s")]
    for i, clip in enumerate(clips):
        w.rate(clip, "coach", "debatable", f"widoczna-ocena-{i}")
        w.comment(clip, "ref2", f"widoczny-komentarz-{i}")
    client = w.c[viewer]
    page = profile(w, viewer, range="all").text
    listed = clip_ids(client.get(f"/clips?person=u{w.u['ref'].id}").text)
    assert clip_ids(section(page, "klipy")) <= listed == {c.id for c in clips}
    for i, clip in enumerate(clips):
        detail = client.get(f"/clips/{clip.id}").text
        assert f"widoczna-ocena-{i}" in detail and f"widoczny-komentarz-{i}" in detail
        assert f"widoczna-ocena-{i}" in page and f"widoczny-komentarz-{i}" in page


def test_sheets_and_self_assessments_never_appear_on_the_profile(w, db):
    match = w.m["m1"]
    db.add(Sheet(match_id=match.id, coach_id=w.u["coach"].id, status="published", difficulty="normalny",
                 published_at=utcnow(), crew_note="SEKRET-ARKUSZ"))
    db.add(SelfAssessment(match_id=match.id, user_id=w.u["ref"].id, status="submitted", submitted_at=utcnow(),
                          good="SEKRET-SAMOOCENA", bad="SEKRET-SAMOOCENA", opinion="SEKRET-SAMOOCENA"))
    db.commit()
    w.clip("m1")
    for viewer in w.c:
        page = main(profile(w, viewer, range="all").text)
        assert "SEKRET" not in page and "/sheets/" not in page and "/self-assessments" not in page
        assert "arkusz" not in page.lower() and "samoocen" not in page.lower()


def test_email_addresses_and_other_accounts_details_are_not_shown(w):
    for viewer in ("ref2", "coach", "admin"):
        assert "sekret.example" not in profile(w, viewer).text


def test_groups_are_listed_only_to_those_who_may_open_them(w):
    link = f'href="/groups/{w.g.id}"'
    for viewer in ("coach", "admin"):
        page = profile(w, viewer).text
        assert link in page and "Grupa Alfa" in page
    for viewer in ("coach2", "ref", "ref2"):
        page = profile(w, viewer).text
        assert "Grupa Alfa" not in page and 'id="profile-groups"' not in page
    assert w.c["coach2"].get(f"/groups/{w.g.id}").status_code == 404  # the rule being reused


def test_a_coach_of_the_group_but_not_a_member_referee_sees_nothing_about_other_groups(w, db):
    other = groups.create_group(db, w.u["coach2"], "Grupa Beta", "")
    other.members.append(GroupMember(user_id=w.u["ref2"].id, role="referee"))
    db.commit()
    assert "Grupa Beta" not in profile(w, "coach").text
    assert "Grupa Beta" in profile(w, "coach2", who="ref2").text


# --- name links --------------------------------------------------------------------------------------

def profile_link(w, who="ref"):
    return f'href="/referees/{w.u[who].id}"'


def test_names_link_to_the_profile_in_the_group_activity_table(w):
    page = w.c["coach"].get(f"/groups/{w.g.id}").text
    assert re.search(rf'<a {profile_link(w)}>Osoba ref</a>', section_after(page, "activity"))


def section_after(html: str, marker: str) -> str:
    return html[html.index(f'id="{marker}"'):]


def test_crew_names_on_the_match_page_link_only_for_referee_accounts(w, db):
    page = w.c["coach"].get(f"/matches/{w.m['m1'].id}").text
    head = page[:page.index('id="match-state"')]  # the crew sits before the state line
    assert re.search(rf'<strong>CC</strong> <a {profile_link(w)}>Osoba ref</a>', head)
    assert "Kasia Żółć" in head and "/referees/" + "Kasia" not in head
    assert main(head).count("/referees/") == 1
    # an account that lost the referee role has no profile, so its name stays plain text
    w.u["ref2"].set_roles(["coach"])
    db.commit()
    again = w.c["coach"].get(f"/matches/{w.m['m4'].id}").text
    assert "Osoba ref2" in again and "/referees/" not in main(again[:again.index('id="match-state"')])


def test_clip_page_and_match_list_link_the_referee(w):
    clip = w.clip("m1")
    detail = w.c["coach"].get(f"/clips/{clip.id}").text
    assert re.search(rf'<dt>Sędzia</dt><dd>CC · <a {profile_link(w)}>Osoba ref</a></dd>', detail)
    team = w.clip("m1", None, whole_team=True)
    assert "cały zespół" in w.c["coach"].get(f"/clips/{team.id}").text
    listing = w.c["coach"].get("/").text
    assert f'<span class="chip">CC <a {profile_link(w)}>Osoba ref</a></span>' in listing
    assert "Kasia Żółć</span>" in listing  # typed name: plain text


def test_names_are_not_linked_where_they_are_hidden_on_purpose(w, db, anon_client):
    clip = w.clip("m1")
    w.rate(clip, "coach", "correct")
    training_set = TrainingSet(name="Zestaw", description="", created_by=w.u["coach"].id)
    db.add(training_set)
    db.commit()
    w.c["coach"].post(f"/clips/{clip.id}/sets", data={"set_id": str(training_set.id)}, follow_redirects=False)
    for show_names in (False, True):
        training_set.show_names = show_names
        db.commit()
        for viewer in ("coach", "ref"):
            for url in (f"/sets/{training_set.id}", f"/sets/{training_set.id}/clips/{clip.id}"):
                r = w.c[viewer].get(url)
                assert r.status_code == 200, url
                assert "/referees/" not in main(r.text), (url, show_names)
        assert ("Osoba ref" in w.c["coach"].get(f"/sets/{training_set.id}").text) is show_names
    _, code = share.create_link(db, w.u["coach"], [str(clip.id)], "7")
    public = anon_client.get(f"/s/{code}")
    assert public.status_code == 200 and "/referees/" not in public.text and "Osoba ref" not in public.text


def test_clip_list_rows_do_not_get_profile_links(w):
    w.clip("m1")
    assert "/referees/" not in main(w.c["coach"].get("/clips").text)


# --- navigation ------------------------------------------------------------------------------------------

def test_referees_get_a_link_to_their_own_profile_in_the_account_menu(w, make_client):
    assert f'<a href="/referees/{w.u["ref"].id}">Mój profil</a>' in w.c["ref"].get("/").text
    assert "Mój profil" not in w.c["coach"].get("/").text
    assert "Mój profil" not in w.c["admin"].get("/").text
    both_client, both = make_client("coach", "referee", name="Podwójna rola")
    assert f'href="/referees/{both.id}">Mój profil' in both_client.get("/").text
