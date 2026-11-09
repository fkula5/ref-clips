"""Ekran opisywania znaczników: kolejka, propozycje z notatek, walidacja, kwarta nieustalona,
pomiń/usuń, edycja opisanego klipu i uprawnienia."""
import re
from datetime import datetime

import pytest
from sqlalchemy import select

from app import services
from app.models import Clip, Video
from app.storage import storage
from tests.helpers import category_named, make_match, make_ready_video, make_user, mark_periods


@pytest.fixture()
def setup(db, make_client):
    """Mecz CC=konto sędziego (`member`), U1=wpisany; dwa nagrania z kwartami; klipy w wielu nagraniach."""
    member_client, member = make_client("referee", name="Rafał Sędzia")
    coach_client, coach = make_client("coach", name="Trener")
    outsider_client, _ = make_client("referee", name="Sędzia Obcy")
    match = make_match(db, officials=(("CC", member), ("U1", "Ewa Druga"), ("U2", "Ula Trzecia")), created_by=coach)
    v1 = mark_periods(db, make_ready_video(db, match, duration=700))
    v2 = mark_periods(db, make_ready_video(db, match, duration=700))

    def clip(video, t, **kw):
        c = Clip(match_id=match.id, video_id=video.id, author_id=coach.id, time_sec=t, **kw)
        db.add(c)
        db.commit()
        return c

    clips = dict(a=clip(v1, 100), b=clip(v1, 40), c=clip(v2, 10), d=clip(v1, 200, described_at=datetime(2026, 10, 29)))
    return dict(match=match, v1=v1, v2=v2, clips=clips, member=member_client, member_user=member,
                coach=coach_client, coach_user=coach, outsider=outsider_client)


def screen(client, match, **params):
    return client.get(f"/matches/{match.id}/describe", params=params)


def ids_in_list(html):
    """Kolejność klipów na liście z boku ekranu."""
    return [int(i) for i in re.findall(r'href="/matches/\d+/describe\?clip=(\d+)', html.split('id="describe-list"')[1])]


def test_queue_is_ordered_by_recording_then_time_and_skips_described(setup):
    s, c = setup, setup["clips"]
    page = screen(s["coach"], s["match"]).text
    assert ids_in_list(page) == [c["b"].id, c["a"].id, c["c"].id]       # nagranie 1 (40 s, 100 s), nagranie 2 (10 s)
    assert c["d"].id not in ids_in_list(page)
    assert "Znacznik 1 z 3" in page and 'data-clip="%d"' % c["b"].id in page
    assert "Nieopisane znaczniki (3)" in page


def test_clip_param_selects_current_and_video_scope_limits_queue(setup):
    s, c = setup, setup["clips"]
    page = screen(s["coach"], s["match"], clip=c["a"].id).text
    assert "Znacznik 2 z 3" in page and 'data-clip="%d"' % c["a"].id in page
    scoped = screen(s["coach"], s["match"], video_id=s["v2"].id).text
    assert ids_in_list(scoped) == [c["c"].id] and "Znacznik 1 z 1" in scoped
    assert f"video_id={s['v2'].id}" in scoped
    foreign = screen(s["coach"], s["match"], video_id=99999).text      # obce nagranie: cały mecz
    assert len(ids_in_list(foreign)) == 3


def test_empty_queue_shows_everything_described(setup, db):
    s = setup
    for clip in s["clips"].values():
        clip.described_at = datetime(2026, 10, 29)
    db.commit()
    page = screen(s["coach"], s["match"]).text
    assert 'id="all-described"' in page and "Wszystkie znaczniki są opisane" in page


def test_proposal_from_notes_is_prefilled_and_marked(setup, db):
    s = setup
    clip = s["clips"]["a"]
    clip.official_id, clip.category_id = s["match"].official("U1").id, category_named(db, "kroki")
    clip.description = "1:40 Ewa kroki"
    db.commit()
    page = screen(s["coach"], s["match"], clip=clip.id).text
    assert 'id="proposal-note"' in page and "pochodzą z notatek" in page
    assert re.search(rf'value="{s["match"].official("U1").id}"[^>]*checked', page)       # radio U1 zaznaczone
    assert re.search(rf'<option value="{category_named(db, "kroki")}"[^>]*selected', page)
    assert "1:40 Ewa kroki" in page
    assert page.count('class="chip" title="Sędzia lub kategoria z notatek"') == 1       # tylko ten klip jest propozycją
    clean = screen(s["coach"], s["match"], clip=s["clips"]["b"].id).text
    assert 'id="proposal-note"' not in clean


def test_form_lists_crew_team_and_grouped_categories(setup, db):
    s = setup
    page = screen(s["coach"], s["match"]).text
    for label in ("CC · Rafał Sędzia", "U1 · Ewa Druga", "U2 · Ula Trzecia", "cały zespół"):
        assert label in page
    for group in ("Faule", "Naruszenia", "Bez gwizdka", "Mechanika", "Inne"):
        assert f'<optgroup label="{group}">' in page
    assert 'data-key="1"' in page and 'data-key="0"' in page


def approve(client, clip, db, official, category="kroki", *, scope=None, **extra):
    data = {"official": str(official), "category_id": str(category_named(db, category)) if category else "",
            "description": "", **extra}
    url = f"/clips/{clip.id}/update?context=describe" + (f"&video_id={scope}" if scope else "")
    return client.post(url, data=data, follow_redirects=False)


def test_approving_sets_described_at_and_goes_to_next_undescribed(setup, db):
    s, c = setup, setup["clips"]
    cc = s["match"].official("CC")
    r = approve(s["coach"], c["b"], db, cc.id, description=" Spóźniony gwizdek ")
    assert r.status_code == 303
    assert r.headers["location"] == f"/matches/{s['match'].id}/describe?clip={c['a'].id}"
    db.refresh(c["b"])
    assert c["b"].described_at is not None and c["b"].official_id == cc.id and c["b"].description == "Spóźniony gwizdek"
    assert c["b"].category.name == "kroki" and not c["b"].whole_team
    # ostatni w kolejce wraca do pierwszego z pozostałych (pominiętego), a po opisaniu wszystkich: ekran „wszystko opisane”
    assert approve(s["coach"], c["c"], db, "team").headers["location"].endswith(f"describe?clip={c['a'].id}")
    r = approve(s["coach"], c["a"], db, "team")
    assert r.headers["location"] == f"/matches/{s['match'].id}/describe"
    db.refresh(c["c"])
    assert c["c"].whole_team and c["c"].official_id is None


def test_next_after_approving_keeps_video_scope(setup, db):
    s, c = setup, setup["clips"]
    r = approve(s["coach"], c["b"], db, "team", scope=s["v1"].id)
    assert r.headers["location"] == f"/matches/{s['match'].id}/describe?clip={c['a'].id}&video_id={s['v1'].id}"
    r = approve(s["coach"], c["a"], db, "team", scope=s["v1"].id)
    assert r.headers["location"] == f"/matches/{s['match'].id}/describe?video_id={s['v1'].id}"   # nagranie 2 poza zakresem


def test_next_goes_forward_in_order_before_wrapping(setup, db):
    s, c = setup, setup["clips"]
    r = approve(s["coach"], c["a"], db, "team")                  # 100 s -> następny w kolejności to nagranie 2
    assert r.headers["location"].endswith(f"clip={c['c'].id}")
    r = approve(s["coach"], c["c"], db, "team")                  # ostatni: wraca do 40 s
    assert r.headers["location"].endswith(f"clip={c['b'].id}")


@pytest.mark.parametrize("data, message", [
    ({"official": "", "category": "kroki"}, "Wybierz sędziego"),
    ({"official": "99999", "category": "kroki"}, "Wybierz sędziego"),
    ({"official": "team", "category": None}, "Wybierz kategorię."),
    ({"official": "team", "category": "własna"}, "wpisz jej nazwę"),
    ({"official": "team", "category": "własna", "custom_category": "   "}, "wpisz jej nazwę"),
    ({"official": "team", "category": "własna", "custom_category": "x" * 101}, "najwyżej 100 znaków"),
    ({"official": "team", "category": "kroki", "description": "x" * 2001}, "Opis: najwyżej 2000"),
])
def test_validation_errors_keep_values_and_change_nothing(setup, db, data, message):
    s, clip = setup, setup["clips"]["a"]
    data = dict(data)
    r = approve(s["coach"], clip, db, data.pop("official"), data.pop("category"), **data)
    assert r.status_code == 422 and message in r.text
    assert 'id="form-error"' in r.text and 'id="clip-form"' in r.text         # ekran z komunikatem w formularzu
    db.refresh(clip)
    assert clip.described_at is None and clip.category_id is None and not clip.whole_team


def test_custom_category_requires_name_and_stores_it(setup, db):
    s, clip = setup, setup["clips"]["a"]
    r = approve(s["coach"], clip, db, "team", "własna", custom_category="  kontakt   z trenerem ")
    assert r.status_code == 303
    db.refresh(clip)
    assert clip.category_label == "kontakt z trenerem" and clip.custom_category == "kontakt z trenerem"
    # nazwa z innej kategorii nie zostaje
    approve(s["coach"], clip, db, "team", "kroki", custom_category="stara")
    db.refresh(clip)
    assert clip.custom_category is None and clip.category_label == "kroki"


def test_error_screen_preserves_chosen_values(setup, db):
    s, clip = setup, setup["clips"]["a"]
    cc = s["match"].official("CC")
    r = approve(s["coach"], clip, db, cc.id, "własna", description="Mój opis")
    assert r.status_code == 422
    assert re.search(rf'value="{cc.id}"[^>]*checked', r.text) and "Mój opis" in r.text
    assert re.search(rf'<option value="{category_named(db, "własna")}"[^>]*selected', r.text)


def test_inactive_category_cannot_be_chosen_but_existing_one_stays(setup, db):
    from app.models import Category
    s, clip = setup, setup["clips"]["a"]
    cat = db.get(Category, category_named(db, "aut"))
    cat.is_active = False
    db.commit()
    assert approve(s["coach"], clip, db, "team", "aut").status_code == 422
    clip.category_id = cat.id
    db.commit()
    assert approve(s["coach"], clip, db, "team", "aut").status_code == 303        # bez zmiany kategorii
    assert '<option value="%d"' % cat.id in s["coach"].get(f"/clips/{clip.id}").text   # i widać ją w formularzu edycji


# --- kwarta nieustalona ----------------------------------------------------------
def test_clip_from_video_without_period_marks_cannot_be_described(setup, db):
    s = setup
    bare = make_ready_video(db, s["match"], duration=700)                    # cały mecz bez znaczników kwart
    clip = Clip(match_id=s["match"].id, video_id=bare.id, time_sec=50)
    db.add(clip)
    db.commit()
    r = approve(s["coach"], clip, db, "team")
    assert r.status_code == 422
    assert "Kwarta tego klipu jest nieustalona" in r.text and "brakuje: Q1, Q2, Q3, Q4" in r.text
    assert f'href="/videos/{bare.id}#poczatki-kwart"' in r.text
    db.refresh(clip)
    assert clip.described_at is None
    page = screen(s["coach"], s["match"], clip=clip.id).text
    assert 'id="describe-block"' in page and 'id="clip-form"' not in page            # formularza nie ma
    assert f'id="set-periods-link" href="/videos/{bare.id}#poczatki-kwart"' in page
    assert "kwarta nieustalona" in page
    assert 'id="describe-block"' in s["coach"].get(f"/clips/{clip.id}").text         # i na stronie klipu


def test_incomplete_marks_block_even_when_clip_has_a_quarter(setup, db):
    s = setup
    partial = mark_periods(db, make_ready_video(db, s["match"], duration=700), times=(0.0, 300.0), periods=("Q1", "Q2"))
    clip = Clip(match_id=s["match"].id, video_id=partial.id, time_sec=50)       # w Q1, ale brakuje Q3 i Q4
    db.add(clip)
    db.commit()
    assert approve(s["coach"], clip, db, "team").status_code == 422
    # jedna kwarta nie wymaga znaczników, ale moment przed jej początkiem jest nieustalony
    single = make_ready_video(db, s["match"], duration=700)
    single.content = "Q2"
    db.commit()
    mark_periods(db, single, times=(100.0,), periods=("Q2",))
    before = Clip(match_id=s["match"].id, video_id=single.id, time_sec=50)
    inside = Clip(match_id=s["match"].id, video_id=single.id, time_sec=150)
    db.add_all([before, inside])
    db.commit()
    r = approve(s["coach"], before, db, "team")
    assert r.status_code == 422 and "wypada przed początkiem pierwszej kwarty" in r.text
    assert approve(s["coach"], inside, db, "team").status_code == 303


def test_clip_with_unset_quarter_can_be_described_after_purge(setup, db):
    """Po usunięciu pełnego nagrania kwart nie da się ustawić, więc blokada opisu znika: klip
    można opisać, a jego kwarta zostaje „nieustalona” (liczona z period_marks)."""
    s = setup
    bare = make_ready_video(db, s["match"], duration=700)
    bare.purged_at = datetime(2026, 11, 1)
    clip = Clip(match_id=s["match"].id, video_id=bare.id, time_sec=50)
    db.add(clip)
    db.commit()
    assert services.describe_block(clip) is None
    page = screen(s["coach"], s["match"], clip=clip.id).text
    assert "klipu nie można opisać" not in page and "kwarta nieustalona" in page
    assert approve(s["coach"], clip, db, "team").status_code == 303
    db.refresh(clip)
    assert clip.described_at is not None and services.period_short(bare.marks, clip.time_sec) == "nieustalona"


def test_editing_a_described_clip_whose_quarters_vanished_is_blocked(setup, db):
    s, d = setup, setup["clips"]["d"]
    db.delete(s["v1"].marks[0])
    db.commit()
    assert approve(s["coach"], d, db, "team").status_code == 422


# --- pomiń, usuń ------------------------------------------------------------------
def test_skip_changes_nothing_and_points_at_the_next_clip(setup, db):
    s, c = setup, setup["clips"]
    page = screen(s["coach"], s["match"], clip=c["b"].id).text
    assert f'id="btn-skip" href="/matches/{s["match"].id}/describe?clip={c["a"].id}"' in page
    last = screen(s["coach"], s["match"], clip=c["c"].id).text
    assert f'id="btn-skip" href="/matches/{s["match"].id}/describe?clip={c["b"].id}"' in last     # po ostatnim wraca
    db.refresh(c["b"])
    assert c["b"].described_at is None
    only = setup
    for key in ("a", "c"):
        only["clips"][key].described_at = datetime(2026, 10, 29)
    db.commit()
    assert 'id="btn-skip"' not in screen(s["coach"], s["match"]).text         # jeden nieopisany: nie ma dokąd


def test_delete_marker_removes_file_and_goes_to_next(setup, db):
    s, c = setup, setup["clips"]
    c["b"].clip_path, c["b"].status = "clips/b.mp4", "cut"
    with storage.open_write("clips/b.mp4") as fh:
        fh.write(b"x")
    db.commit()
    page = screen(s["coach"], s["match"], clip=c["b"].id).text
    assert f'action="/clips/{c["b"].id}/delete?context=describe"' in page and "confirm(" in page
    ids = {k: v.id for k, v in c.items()}
    r = s["coach"].post(f"/clips/{ids['b']}/delete?context=describe", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/matches/{s['match'].id}/describe?clip={ids['a']}"
    db.expire_all()
    assert db.get(Clip, ids["b"]) is None and not storage.exists("clips/b.mp4")
    r = s["coach"].post(f"/clips/{ids['a']}/delete?context=describe&video_id={s['v1'].id}", follow_redirects=False)
    assert r.headers["location"] == f"/matches/{s['match'].id}/describe?video_id={s['v1'].id}"
    # poza ekranem opisywania: wracamy do zakładki klipów meczu
    r = s["coach"].post(f"/clips/{ids['c']}/delete", follow_redirects=False)
    assert r.headers["location"] == f"/matches/{s['match'].id}#klipy"


# --- edycja opisanego klipu ---------------------------------------------------------
def test_edit_keeps_first_described_at_and_changes_download_name(setup, db):
    s, d = setup, setup["clips"]["d"]
    cc = s["match"].official("CC")
    d.clip_path, d.status = "clips/d.mp4", "cut"
    with storage.open_write(d.clip_path) as fh:
        fh.write(b"x")
    db.commit()
    first = d.described_at
    r = s["coach"].post(f"/clips/{d.id}/update", data={"official": str(cc.id), "category_id": str(category_named(db, "blok / szarża"))},
                        follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/clips/{d.id}"
    db.refresh(d)
    assert d.described_at == first
    cd = s["coach"].get(f"/clips/{d.id}/download").headers["content-disposition"]
    assert 'filename="II-liga_Sedzia_blok-szarza.mp4"' in cd
    s["coach"].post(f"/clips/{d.id}/update", data={"official": "team", "category_id": str(category_named(db, "własna")),
                                                   "custom_category": "Zażalenie / trener!"})
    cd = s["coach"].get(f"/clips/{d.id}/download").headers["content-disposition"]
    assert 'filename="II-liga_zespol_Zazalenie-trener.mp4"' in cd


def test_edit_from_clip_page_shows_error_in_place(setup, db):
    s, d = setup, setup["clips"]["d"]
    r = s["coach"].post(f"/clips/{d.id}/update", data={"official": "", "category_id": ""})
    assert r.status_code == 422 and "Wybierz sędziego" in r.text and "Edytuj opis" in r.text


def test_filter_query_survives_edit_redirect(setup, db):
    s, d = setup, setup["clips"]["d"]
    r = s["coach"].post(f"/clips/{d.id}/update?period=Q2&described=1&junk=1",
                        data={"official": "team", "category_id": str(category_named(db, "aut"))}, follow_redirects=False)
    assert r.headers["location"] == f"/clips/{d.id}?period=Q2&described=1"


# --- podgląd i błędy cięcia ----------------------------------------------------------
def test_preview_is_the_clip_file_when_cut_and_a_draft_while_queued(setup, db):
    s, c = setup, setup["clips"]
    draft = screen(s["coach"], s["match"], clip=c["b"].id).text                 # znacznik w 40 s, nowy
    assert f'src="/videos/{s["v1"].id}/stream"' in draft and 'data-start="25.0"' in draft and 'data-end="55.0"' in draft
    assert "Klip czeka na wycięcie" in draft
    c["b"].clip_path, c["b"].status, c["b"].clip_version = "clips/b.mp4", "cut", 2
    with storage.open_write("clips/b.mp4") as fh:
        fh.write(b"x")
    db.commit()
    cut = screen(s["coach"], s["match"], clip=c["b"].id).text
    assert f'src="/clips/{c["b"].id}/file?v=2"' in cut and "data-end" not in cut


def test_draft_is_clamped_at_the_start_of_the_recording(setup):
    s = setup
    page = screen(s["coach"], s["match"], clip=s["clips"]["c"].id).text          # 10 s: początek obcięty do 0
    assert 'data-start="0.0"' in page and 'data-end="25.0"' in page


def test_cut_error_screen_offers_recut_or_just_delete(setup, db):
    s, c = setup, setup["clips"]
    c["b"].status, c["b"].error = "error", "ffmpeg: coś poszło nie tak"
    c["a"].status, c["a"].error = "error", "Moment poza nagraniem: 99:00 (nagranie trwa 10:00)"
    db.commit()
    page = screen(s["coach"], s["match"], clip=c["b"].id).text
    assert "Nie udało się wyciąć klipu: ffmpeg: coś poszło nie tak" in page and "Wytnij ponownie" in page
    outside = screen(s["coach"], s["match"], clip=c["a"].id).text
    assert "Moment poza nagraniem" in outside and "Wytnij ponownie" not in outside and "Usuń znacznik" in outside


# --- uprawnienia ---------------------------------------------------------------------
def test_describe_screen_needs_permission_to_manage_clips(setup, make_client):
    s = setup
    assert screen(s["member"], s["match"]).status_code == 200                      # sędzia z obsady
    assert screen(s["coach"], s["match"]).status_code == 200
    assert screen(s["outsider"], s["match"]).status_code == 403                    # sędzia spoza obsady
    plain, _ = make_client()
    assert screen(plain, s["match"]).status_code == 403
    assert s["coach"].get("/matches/9999/describe").status_code == 404


def test_outsider_gets_403_on_every_describe_write_route(setup, db):
    s, c = setup, setup["clips"]["a"]
    out = s["outsider"]
    data = {"official": "team", "category_id": str(category_named(db, "aut"))}
    assert out.post(f"/clips/{c.id}/update?context=describe", data=data).status_code == 403
    assert out.post(f"/clips/{c.id}/update", data=data).status_code == 403
    assert out.post(f"/clips/{c.id}/delete?context=describe").status_code == 403
    assert out.post(f"/clips/{c.id}/recut").status_code == 403
    db.refresh(c)
    assert c.described_at is None and db.get(Clip, c.id) is not None


def test_crew_referee_describes_but_deletes_only_own_markers(setup, db):
    s, c = setup, setup["clips"]
    assert approve(s["member"], c["a"], db, "team").status_code == 303
    assert s["member"].post(f"/clips/{c['b'].id}/delete?context=describe").status_code == 403    # znacznik trenera
    assert 'btn-delete' not in screen(s["member"], s["match"], clip=c["b"].id).text


def test_writes_require_csrf_and_login(setup, anon_client, db):
    c = setup["clips"]["a"]
    assert anon_client.post(f"/clips/{c.id}/update?context=describe", data={"official": "team"}).status_code == 401
    no_csrf = setup["coach"]
    del no_csrf.headers["X-CSRF-Token"]
    assert no_csrf.post(f"/clips/{c.id}/update?context=describe", data={"official": "team"}).status_code == 403


# --- czyste funkcje kolejki ------------------------------------------------------------
class Fake:
    def __init__(self, id, video_id, time_sec):
        self.id, self.video_id, self.time_sec = id, video_id, time_sec


def test_next_in_queue_and_neighbours():
    a, b, c, d = Fake(1, 1, 10), Fake(2, 1, 50), Fake(3, 2, 5), Fake(4, 2, 80)
    assert services.next_in_queue([d, a, c, b], a).id == 2
    assert services.next_in_queue([d, a, c, b], b).id == 3
    assert services.next_in_queue([d, a, c, b], d).id == 1                     # po ostatnim: pierwszy z pozostałych
    assert services.next_in_queue([a], a) is None and services.next_in_queue([], None) is None
    assert services.next_in_queue([c, d], b).id == 3                           # bieżący spoza kolejki (np. już opisany)
    assert [x.id if x else None for x in services.neighbours([a, b, c, d], b)] == [1, 3]
    assert [x.id if x else None for x in services.neighbours([a, b, c, d], a)] == [None, 2]
    assert [x.id if x else None for x in services.neighbours([a, c], b)] == [1, 3]       # bieżący poza listą
    assert [x.id if x else None for x in services.neighbours([], b)] == [None, None]
