import re
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import config, groups, services, training_sets
from app.models import (Clip, Comment, GroupMember, Match, Rating, TrainingGroup, TrainingSet, TrainingSetClip,
                        TrainingSetGroup)
from app.storage import storage
from tests.helpers import category_named, make_match, make_ready_video, mark_periods

SECRETS = ["Kowalski", "Filip", "Żółć", "Kasia", "SEKRET-OCENA", "SEKRET-KOMENTARZ"]


@pytest.fixture()
def w(db, make_client):
    """`coach` and `other` are coaches, `ref` a referee; the match crew is CC Filip Kowalski, U1 Kasia Żółć."""
    clients, users = {}, {}
    for name, role in {"coach": "coach", "other": "coach", "admin": "admin", "ref": "referee"}.items():
        clients[name], users[name] = make_client(role, name=f"Osoba {name}")
    match = make_match(db, created_by=users["coach"])
    video = mark_periods(db, make_ready_video(db, match))
    world = SimpleNamespace(c=clients, u=users, db=db, match=match, video=video)

    def clip(*, official="CC", category="kroki", status="cut", file=True, whole_team=False, description="Opis klipu", t=100.0):
        row = Clip(match_id=match.id, video_id=video.id, author_id=users["coach"].id, time_sec=t,
                   official_id=match.official(official).id if official else None, whole_team=whole_team,
                   category_id=category_named(db, category), description=description, status=status)
        db.add(row)
        db.commit()
        if file:
            row.clip_path, row.clip_version = f"clips/{row.id}_v1.mp4", 1
            with storage.open_write(row.clip_path) as fh:
                fh.write(b"x" * 64)
            db.commit()
        return row

    world.clip = clip
    return world


def post(w, who, url, status=303, **data):
    r = w.c[who].post(url, data=data, follow_redirects=False)
    assert r.status_code == status, r.text[:300]
    w.db.expire_all()
    return r


def make_set(w, who="coach", name="Akcja rzutowa", description="", **clips):
    r = post(w, who, "/sets", name=name, description=description)
    return w.db.get(TrainingSet, int(r.headers["location"].rsplit("/", 1)[-1]))


def fill(w, training_set, *clips):
    for clip in clips:
        post(w, "coach", f"/clips/{clip.id}/sets", set_id=str(training_set.id))
    w.db.expire_all()


def order(w, training_set):
    w.db.expire_all()
    return [i.clip_id for i in training_sets.items_of(w.db, training_set)]


def test_everyone_views_but_only_coaches_and_admins_mutate(w):
    training_set = make_set(w)
    clip = w.clip()
    fill(w, training_set, clip)
    group = groups.create_group(w.db, w.u["coach"], "Grupa A", "")
    mutations = [
        ("get", "/sets/new", {}), ("post", "/sets", {"name": "x"}), ("get", "/sets/{s}/edit", {}),
        ("post", "/sets/{s}/edit", {"name": "x"}), ("get", "/sets/{s}/delete", {}), ("post", "/sets/{s}/delete", {}),
        ("post", "/sets/{s}/clips/{c}/note", {"note": "x"}), ("post", "/sets/{s}/clips/{c}/move", {"direction": "down"}),
        ("post", "/sets/{s}/clips/{c}/remove", {}), ("post", "/sets/{s}/groups", {"group_id": str(group.id)}),
        ("post", "/sets/{s}/groups/{g}/unpin", {}), ("post", "/clips/{c}/sets", {"set_id": "{s}"}),
    ]
    for method, url, data in mutations:
        url = url.format(s=training_set.id, c=clip.id, g=group.id)
        data = {k: v.format(s=training_set.id) for k, v in data.items()}
        r = getattr(w.c["ref"], method)(url, **({"data": data} if method == "post" else {}))
        assert r.status_code == 403, (method, url)
    w.db.expire_all()
    assert (training_set.name, len(training_set.items), len(training_set.pins)) == ("Akcja rzutowa", 1, 0)
    for url in ("/sets", f"/sets/{training_set.id}", f"/sets/{training_set.id}/clips/{clip.id}"):
        assert w.c["ref"].get(url).status_code == 200, url
    page = w.c["ref"].get(f"/sets/{training_set.id}").text
    assert "Edytuj" not in page and "Usuń zestaw" not in page and "/move" not in page and "Przypnij" not in page
    assert "Nowy zestaw" not in w.c["ref"].get("/sets").text and "Nowy zestaw" in w.c["coach"].get("/sets").text
    assert 'id="clip-sets"' not in w.c["ref"].get(f"/clips/{clip.id}").text
    assert 'id="clip-sets"' in w.c["other"].get(f"/clips/{clip.id}").text
    make_set(w, "admin", name="Od admina")
    make_set(w, "other", name="Od innego")


def test_any_coach_edits_any_set_and_csrf_is_required(w):
    training_set = make_set(w, "coach")
    post(w, "other", f"/sets/{training_set.id}/edit", name="Zmieniony", description="Nowy opis", show_names="1")
    assert (training_set.name, training_set.description, training_set.show_names) == ("Zmieniony", "Nowy opis", True)
    post(w, "admin", f"/sets/{training_set.id}/delete")
    assert w.db.scalar(select(func.count()).select_from(TrainingSet)) == 0
    r = w.c["coach"].post("/sets", data={"name": "Bez tokenu"}, headers={"X-CSRF-Token": "zly"})
    assert r.status_code == 403 and w.db.scalar(select(func.count()).select_from(TrainingSet)) == 0


def test_form_errors_keep_the_typed_values(w):
    r = w.c["coach"].post("/sets", data={"name": "  ", "description": "wpisany opis"})
    assert r.status_code == 422 and "Podaj nazwę zestawu" in r.text and "wpisany opis" in r.text
    r = w.c["coach"].post("/sets", data={"name": "n" * 101})
    assert r.status_code == 422 and "najwyżej 100 znaków" in r.text
    r = w.c["coach"].post("/sets", data={"name": "ok", "description": "d" * 1001})
    assert r.status_code == 422 and "najwyżej 1000 znaków" in r.text
    training_set = make_set(w)
    r = w.c["coach"].post(f"/sets/{training_set.id}/edit", data={"name": "", "description": "inny opis"})
    assert r.status_code == 422 and "inny opis" in r.text
    assert w.db.scalar(select(func.count()).select_from(TrainingSet)) == 1


def test_user_text_is_escaped(w):
    training_set = make_set(w, name="<b>Zestaw</b>", description="<script>alert(1)</script>")
    clip = w.clip(description="<i>opis</i>")
    fill(w, training_set, clip)
    post(w, "coach", f"/sets/{training_set.id}/clips/{clip.id}/note", note="<img src=x onerror=alert(2)>")
    for url in ("/sets", f"/sets/{training_set.id}", f"/sets/{training_set.id}/clips/{clip.id}"):
        page = w.c["ref"].get(url).text
        assert "<b>Zestaw" not in page and "<script>alert" not in page and "<img src=x" not in page and "<i>opis" not in page
    assert "&lt;img src=x" in w.c["ref"].get(f"/sets/{training_set.id}/clips/{clip.id}").text


def test_only_cut_clips_with_a_file_are_added_and_only_once(w):
    training_set = make_set(w)
    ready = w.clip()
    for bad in (w.clip(status="new", file=False), w.clip(status="queued", file=False), w.clip(status="error", file=False),
                w.clip(status="cut", file=False)):
        r = w.c["coach"].post(f"/clips/{bad.id}/sets", data={"set_id": str(training_set.id)})
        assert r.status_code == 409 and "tylko wycięty klip" in r.text
        r = w.c["coach"].post(f"/clips/{bad.id}/sets", data={"new_name": "Nowy"})
        assert r.status_code == 409
    assert w.db.scalar(select(func.count()).select_from(TrainingSet)) == 1  # the "new set" was not created either
    assert w.db.scalar(select(func.count()).select_from(TrainingSetClip)) == 0
    r = post(w, "coach", f"/clips/{ready.id}/sets", set_id=str(training_set.id))
    assert r.headers["location"] == f"/clips/{ready.id}"
    assert "Dodano klip do zestawu" in w.c["coach"].get(f"/clips/{ready.id}").text
    r = w.c["other"].post(f"/clips/{ready.id}/sets", data={"set_id": str(training_set.id)})
    assert r.status_code == 409 and "już jest w zestawie" in r.text
    assert w.db.scalar(select(func.count()).select_from(TrainingSetClip)) == 1
    assert "(klip już jest w zestawie)" in w.c["coach"].get(f"/clips/{ready.id}").text


def test_add_to_a_new_or_existing_set_from_the_clip_page(w):
    clip = w.clip()
    post(w, "coach", f"/clips/{clip.id}/sets", new_name="  Blok / szarża ")
    created = w.db.scalar(select(TrainingSet).where(TrainingSet.name == "Blok / szarża"))
    assert created.created_by == w.u["coach"].id and [i.clip_id for i in created.items] == [clip.id]
    for data, message in [({}, "Wybierz zestaw z listy"), ({"set_id": "999"}, "Wybierz zestaw z listy"),
                          ({"set_id": "abc"}, "Wybierz zestaw z listy"),
                          ({"set_id": str(created.id), "new_name": "Drugi"}, "nie oba naraz"),
                          ({"new_name": "n" * 101}, "najwyżej 100 znaków")]:
        r = w.c["coach"].post(f"/clips/{w.clip().id}/sets?described=1", data=data)
        assert r.status_code == 422 and message in r.text, data
    assert w.db.scalar(select(func.count()).select_from(TrainingSet)) == 1
    other_clip = w.clip(t=200)
    r = w.c["coach"].post(f"/clips/{other_clip.id}/sets", data={"set_id": "", "new_name": "n" * 101})
    assert "Nazwa zestawu" in r.text and 'value="' + "n" * 101 in r.text  # typed value stays in the form


def test_order_can_be_changed_and_clips_removed(w):
    training_set = make_set(w)
    a, b, c = w.clip(t=10), w.clip(t=20), w.clip(t=30)
    fill(w, training_set, a, b, c)
    assert order(w, training_set) == [a.id, b.id, c.id]
    move = lambda who, clip, direction: post(w, who, f"/sets/{training_set.id}/clips/{clip.id}/move", direction=direction)  # noqa: E731
    move("coach", c, "up")
    assert order(w, training_set) == [a.id, c.id, b.id]
    move("other", a, "down")
    assert order(w, training_set) == [c.id, a.id, b.id]
    move("admin", c, "up")  # already first
    move("admin", b, "down")  # already last
    assert order(w, training_set) == [c.id, a.id, b.id]
    assert [i.position for i in training_sets.items_of(w.db, training_set)] == [1, 2, 3]
    assert w.c["coach"].post(f"/sets/{training_set.id}/clips/{a.id}/move", data={"direction": "sideways"}).status_code == 422
    post(w, "coach", f"/sets/{training_set.id}/clips/{a.id}/remove")
    assert order(w, training_set) == [c.id, b.id]
    assert [i.position for i in training_sets.items_of(w.db, training_set)] == [1, 2]
    assert w.db.get(Clip, a.id) is not None  # only the membership goes
    assert w.c["coach"].post(f"/sets/{training_set.id}/clips/{a.id}/remove").status_code == 404
    assert w.c["coach"].post(f"/sets/{training_set.id}/clips/{a.id}/move", data={"direction": "up"}).status_code == 404
    page = w.c["coach"].get(f"/sets/{training_set.id}").text
    assert page.index(f'id="clip-{c.id}"') < page.index(f'id="clip-{b.id}"')
    new = w.clip(t=40)
    fill(w, training_set, new)
    assert order(w, training_set) == [c.id, b.id, new.id]


def test_viewer_shows_position_and_neighbours(w):
    training_set = make_set(w)
    a, b, c = w.clip(t=10), w.clip(t=20), w.clip(t=30)
    fill(w, training_set, a, b, c)
    base = f"/sets/{training_set.id}/clips/"
    first, middle, last = (w.c["ref"].get(base + str(x.id)).text for x in (a, b, c))
    assert ">1 / 3<" in first and ">2 / 3<" in middle and ">3 / 3<" in last
    assert 'id="prev-clip"' not in first and f'href="{base}{b.id}"' in first
    assert f'id="prev-clip" rel="prev" href="{base}{a.id}"' in middle and f'id="next-clip" rel="next" href="{base}{c.id}"' in middle
    assert 'id="next-clip"' not in last
    assert f'<video id="clip-video" src="/clips/{b.id}/file?v=1"' in middle and f'href="/clips/{b.id}"' in middle
    assert w.c["ref"].get(f"/sets/{training_set.id}/clips/{w.clip().id}").status_code == 404  # not in this set
    assert w.c["ref"].get(f"/sets/999/clips/{a.id}").status_code == 404
    assert f'href="{base}{a.id}"' in w.c["ref"].get(f"/sets/{training_set.id}").text  # the overview


def test_notes_are_the_coachs_own_and_never_change_the_description(w):
    training_set = make_set(w)
    clip = w.clip(description="Oryginalny opis")
    fill(w, training_set, clip)
    url = f"/sets/{training_set.id}/clips/{clip.id}"
    r = post(w, "other", url + "/note", note="  Patrz na pozycję CC.\r\nDruga linia  ")
    assert r.headers["location"] == url
    w.db.expire_all()
    assert w.db.get(TrainingSetClip, (training_set.id, clip.id)).note == "Patrz na pozycję CC.\nDruga linia"
    assert w.db.get(Clip, clip.id).description == "Oryginalny opis"
    page = w.c["ref"].get(url).text
    assert "Patrz na pozycję CC." in page and "Oryginalny opis" in page and "<textarea" not in page
    assert "Patrz na pozycję CC." in w.c["coach"].get(url).text
    post(w, "coach", url + "/note", note="")
    assert "Brak notatki." in w.c["ref"].get(url).text
    r = w.c["coach"].post(url + "/note", data={"note": "z" * (config.TEXT_MAX_CHARS + 1)})
    assert r.status_code == 422 and "najwyżej" in r.text and "z" * 50 in r.text
    assert w.db.get(TrainingSetClip, (training_set.id, clip.id)).note == ""
    other_clip = w.clip()
    assert w.c["coach"].post(f"/sets/{training_set.id}/clips/{other_clip.id}/note", data={"note": "x"}).status_code == 404
    assert w.db.get(Clip, clip.id).description == "Oryginalny opis"


def test_names_are_hidden_until_the_set_shows_them(w):
    training_set = make_set(w)
    cc, u1, team, nobody = w.clip(official="CC"), w.clip(official="U1"), w.clip(whole_team=True, official=None), w.clip(official=None)
    fill(w, training_set, cc, u1, team, nobody)
    w.db.add(Rating(clip_id=cc.id, coach_id=w.u["coach"].id, verdict="correct", comment="SEKRET-OCENA"))
    w.db.add(Comment(clip_id=cc.id, author_id=w.u["coach"].id, body="SEKRET-KOMENTARZ"))
    w.db.commit()
    urls = [f"/sets/{training_set.id}"] + [f"/sets/{training_set.id}/clips/{c.id}" for c in (cc, u1, team, nobody)]
    for who in ("ref", "coach", "admin"):
        for url in urls:
            page = w.c[who].get(url).text
            assert not any(secret in page for secret in SECRETS), (who, url)
            assert "28.10.2026" in page and "Legia – Wisła" in page and "II liga" in page
        viewer = w.c[who].get(urls[1]).text
        assert re.search(r"<dt>Funkcja</dt><dd>CC</dd>", viewer)
        assert "<dd>U1</dd>" in w.c[who].get(urls[2]).text and "<dd>cały zespół</dd>" in w.c[who].get(urls[3]).text
    assert "Nazwiska sędziów: ukryte" in w.c["ref"].get(urls[0]).text
    assert "Pokaż nazwiska sędziów" in w.c["coach"].get(f"/sets/{training_set.id}/edit").text
    post(w, "other", f"/sets/{training_set.id}/edit", name="Akcja rzutowa", description="", show_names="1")
    for who in ("ref", "coach"):
        overview = w.c[who].get(urls[0]).text
        assert "CC · Filip Kowalski" in overview and "U1 · Kasia Żółć" in overview and "cały zespół" in overview
        assert "Nazwiska sędziów: widoczne" in overview
        assert re.search(r"<dt>Sędzia</dt><dd>CC · Filip Kowalski</dd>", w.c[who].get(urls[1]).text)
    assert "SEKRET" not in w.c["ref"].get(urls[1]).text  # ratings and comments stay on the clip page
    assert "SEKRET-OCENA" in w.c["ref"].get(f"/clips/{cc.id}").text
    post(w, "coach", f"/sets/{training_set.id}/edit", name="Akcja rzutowa", description="")  # unchecked = hidden again
    assert "Kowalski" not in w.c["ref"].get(urls[1]).text


def test_download_filename_follows_the_names_setting(w):
    training_set = make_set(w)
    cc, team = w.clip(official="CC"), w.clip(whole_team=True, official=None, category="aut")
    fill(w, training_set, cc, team)
    base = f"/sets/{training_set.id}/clips/"

    def name(who, clip):
        r = w.c[who].get(f"{base}{clip.id}/download")
        assert r.status_code == 200 and r.content == b"x" * 64
        return re.search(r'filename="([^"]+)"', r.headers["content-disposition"])[1]

    for who in ("ref", "coach"):
        assert name(who, cc) == "II-liga_CC_kroki.mp4" and name(who, team) == "II-liga_zespol_aut.mp4"
    assert "II-liga_CC_kroki.mp4" in w.c["ref"].get(base + str(cc.id)).text
    post(w, "coach", f"/sets/{training_set.id}/edit", name="Akcja rzutowa", description="", show_names="1")
    assert name("ref", cc) == "II-liga_Kowalski_kroki.mp4" and name("ref", team) == "II-liga_zespol_aut.mp4"
    assert w.c["ref"].get(f"/clips/{cc.id}/download").headers["content-disposition"].endswith('II-liga_Kowalski_kroki.mp4"')
    assert w.c["ref"].get(f"{base}{w.clip().id}/download").status_code == 404
    post(w, "coach", f"/sets/{training_set.id}/edit", name="Akcja rzutowa", description="")
    assert w.c["ref"].get(f"/clips/{cc.id}/download").headers["content-disposition"].endswith('II-liga_Kowalski_kroki.mp4"')  # unchanged elsewhere


def test_clip_filename_variants(w):
    clip = w.clip(official="U1")
    assert services.clip_filename(clip) == "II-liga_Zolc_kroki.mp4"
    assert services.clip_filename(clip, function_only=True) == "II-liga_U1_kroki.mp4"
    assert services.clip_filename(clip, with_referee=False, function_only=True) == "II-liga_kroki.mp4"


def test_deleted_clips_and_matches_leave_the_set_but_the_set_stays(w):
    training_set = make_set(w)
    kept = w.clip(t=10)
    doomed = w.clip(t=20)
    other = make_match(w.db)
    video = make_ready_video(w.db, other)
    other_match_clip = Clip(match_id=other.id, video_id=video.id, time_sec=5, status="cut", clip_path="clips/om.mp4")
    w.db.add(other_match_clip)
    w.db.commit()
    with storage.open_write(other_match_clip.clip_path) as fh:
        fh.write(b"x")
    fill(w, training_set, kept, doomed, other_match_clip)
    assert order(w, training_set) == [kept.id, doomed.id, other_match_clip.id]
    post(w, "admin", f"/clips/{doomed.id}/delete")
    assert order(w, training_set) == [kept.id, other_match_clip.id]
    w.db.delete(w.db.get(Match, other.id))
    w.db.commit()
    assert order(w, training_set) == [kept.id]
    page = w.c["ref"].get(f"/sets/{training_set.id}").text
    assert w.c["ref"].get(f"/sets/{training_set.id}/clips/{kept.id}").status_code == 200 and "Klipy (1)" in page
    w.db.delete(w.db.get(Match, w.match.id))
    w.db.commit()
    assert order(w, training_set) == [] and w.db.get(TrainingSet, training_set.id) is not None
    assert "W zestawie nie ma jeszcze klipów" in w.c["coach"].get(f"/sets/{training_set.id}").text


def test_deleting_a_set_keeps_clips_and_groups(w):
    training_set = make_set(w)
    clip = w.clip()
    fill(w, training_set, clip)
    group = groups.create_group(w.db, w.u["coach"], "Grupa A", "")
    post(w, "coach", f"/sets/{training_set.id}/groups", group_id=str(group.id))
    page = w.c["coach"].get(f"/sets/{training_set.id}/delete").text
    assert "Akcja rzutowa" in page and "Klipy, mecze i oceny zostają bez zmian" in page
    r = post(w, "coach", f"/sets/{training_set.id}/delete")
    assert r.headers["location"] == "/sets"
    w.db.expire_all()
    assert w.db.get(Clip, clip.id) and w.db.get(TrainingGroup, group.id)
    assert w.db.scalar(select(func.count()).select_from(TrainingSetClip)) == 0
    assert w.db.scalar(select(func.count()).select_from(TrainingSetGroup)) == 0


def test_pinning_a_set_highlights_it_in_the_group_view(w):
    training_set = make_set(w)
    plain = make_set(w, name="Bez grupy")
    fill(w, training_set, w.clip(), w.clip(t=2))
    group = groups.create_group(w.db, w.u["coach"], "Grupa A", "")
    empty = groups.create_group(w.db, w.u["coach"], "Pusta", "")
    group.members.append(GroupMember(user_id=w.u["ref"].id, role="referee"))
    w.db.commit()
    assert 'id="pinned-sets"' not in w.c["coach"].get(f"/groups/{group.id}").text
    r = post(w, "other", f"/sets/{training_set.id}/groups", group_id=str(group.id))
    assert r.headers["location"] == f"/sets/{training_set.id}"
    page = w.c["coach"].get(f"/groups/{group.id}").text
    assert 'id="pinned-sets"' in page and 'href="/sets/%d"' % training_set.id in page and "klipów: 2" in page
    assert "Bez grupy" not in page and 'id="pinned-sets"' not in w.c["admin"].get(f"/groups/{empty.id}").text
    assert 'id="pinned-sets"' in w.c["admin"].get(f"/groups/{group.id}").text
    for who in ("ref", "coach"):  # the referee only sees the list of their groups
        assert 'class="chip pinned" href="/sets/%d"' % training_set.id in w.c[who].get("/groups").text
    assert "Grupa A" in w.c["ref"].get(f"/sets/{training_set.id}").text
    r = w.c["coach"].post(f"/sets/{training_set.id}/groups", data={"group_id": str(group.id)})
    assert r.status_code == 409 and "już przypięty" in r.text
    post(w, "coach", f"/sets/{plain.id}/groups", group_id=str(group.id))
    post(w, "coach", f"/sets/{plain.id}/groups", group_id=str(empty.id))
    assert {p.group_id for p in plain.pins} == {group.id, empty.id}
    for bad in ("", "999", "x"):
        assert w.c["coach"].post(f"/sets/{plain.id}/groups", data={"group_id": bad}).status_code == 422
    post(w, "admin", f"/sets/{training_set.id}/groups/{group.id}/unpin")
    assert 'href="/sets/%d"' % training_set.id not in w.c["coach"].get(f"/groups/{group.id}").text
    assert w.c["coach"].post(f"/sets/{training_set.id}/groups/{group.id}/unpin").status_code == 404
    w.db.delete(w.db.get(TrainingGroup, group.id))
    w.db.commit()
    w.db.expire_all()
    assert w.db.get(TrainingSet, plain.id) and [p.group_id for p in w.db.get(TrainingSet, plain.id).pins] == [empty.id]


def test_set_list_is_paginated_with_clip_counts(w, monkeypatch):
    monkeypatch.setattr(config, "SET_PAGE_SIZE", 2)
    sets = [make_set(w, name=f"Zestaw {n}") for n in range(1, 6)]
    fill(w, sets[0], w.clip(), w.clip(t=2), w.clip(t=3))

    def listed(**params):
        page = w.c["ref"].get("/sets", params=params).text
        rows = re.findall(r'<td data-label="Zestaw" class="main-cell"><a href="/sets/\d+">([^<]+)</a></td>'
                          r'.*?<td data-label="Klipy">(\d+)</td>', page, re.S)
        return rows, page

    rows, page = listed()
    assert rows == [("Zestaw 1", "3"), ("Zestaw 2", "0")] and "Zestawy: 5 · strona 1 z 3" in page
    assert "page=2" in page and "page=0" not in page
    assert listed(page=2)[0] == [("Zestaw 3", "0"), ("Zestaw 4", "0")]
    rows, page = listed(page=3)
    assert rows == [("Zestaw 5", "0")] and "strona 3 z 3" in page and "Starsze" not in page
    assert listed(page=99)[0] == rows and listed(page="abc")[0][0][0] == "Zestaw 1"


def test_empty_list_and_unknown_set(w):
    assert "Nie ma jeszcze żadnego zestawu" in w.c["ref"].get("/sets").text
    assert "Utwórz zestaw" in w.c["coach"].get("/sets").text
    for who in ("ref", "coach"):
        assert w.c[who].get("/sets/999").status_code == 404
