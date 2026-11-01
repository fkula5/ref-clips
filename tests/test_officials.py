"""Edycja obsady: klipy zostają przy tej samej OSOBIE, nie przy pozycji."""
from sqlalchemy import select

from app.models import Clip, MatchOfficial
from tests.helpers import make_match, make_ready_video, make_user

BASE = {"date": "2026-10-28", "level": "II liga", "team_a_name": "Legia", "team_b_name": "Wisła"}


def clip_for(db, video, official):
    clip = Clip(match_id=video.match_id, video_id=video.id, time_sec=10, official_id=official.id)
    db.add(clip)
    db.commit()
    return clip.id


def edit(client, db, match, **crew):
    r = client.post(f"/matches/{match.id}", data={**BASE, **crew}, follow_redirects=False)
    assert r.status_code == 303, r.text
    db.expire_all()


def who(db, clip_id):
    """(funkcja, osoba) przypisana do klipu albo None."""
    clip = db.get(Clip, clip_id)
    return (clip.official.function, clip.official.display_name) if clip.official else None


def test_swapping_two_accounts_keeps_clips_with_the_same_people(client, db):
    a = make_user(db, ["referee"], email="a@example.com", name="Adam Sędzia")
    b = make_user(db, ["referee"], email="b@example.com", name="Beata Sędzia")
    match = make_match(db, officials=(("CC", a), ("U1", b), ("U2", "Cezary Trzeci")))
    video = make_ready_video(db, match)
    ca, cb, cc = (clip_for(db, video, match.official(f)) for f in ("CC", "U1", "U2"))
    edit(client, db, match, cc_user=str(b.id), u1_user=str(a.id), u2_name="Cezary Trzeci")
    assert who(db, ca) == ("U1", "Adam Sędzia")
    assert who(db, cb) == ("CC", "Beata Sędzia")
    assert who(db, cc) == ("U2", "Cezary Trzeci")
    assert {o.function: o.user_id for o in db.get(type(match), match.id).officials if o.user_id} == {
        "CC": b.id, "U1": a.id}


def test_three_way_rotation_with_all_positions_taken(client, db):
    match = make_match(db, officials=(("CC", "Jan Pierwszy"), ("U1", "Ewa Druga"), ("U2", "Kuba Trzeci")))
    video = make_ready_video(db, match)
    clips = {n: clip_for(db, video, match.official(f)) for n, f in
             (("Jan Pierwszy", "CC"), ("Ewa Druga", "U1"), ("Kuba Trzeci", "U2"))}
    edit(client, db, match, cc_name="Kuba Trzeci", u1_name="Jan Pierwszy", u2_name="Ewa Druga")
    assert who(db, clips["Jan Pierwszy"]) == ("U1", "Jan Pierwszy")
    assert who(db, clips["Ewa Druga"]) == ("U2", "Ewa Druga")
    assert who(db, clips["Kuba Trzeci"]) == ("CC", "Kuba Trzeci")


def test_replacing_a_person_unassigns_their_clips(client, db):
    a = make_user(db, ["referee"], email="a@example.com", name="Adam Sędzia")
    k = make_user(db, ["referee"], email="k@example.com", name="Kasia Sędzia")
    match = make_match(db, officials=(("CC", a), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    c_adam = clip_for(db, video, match.official("CC"))
    c_ewa = clip_for(db, video, match.official("U1"))
    edit(client, db, match, cc_user=str(k.id), u1_name="Ewa Druga")  # na CC zamiast Adama jest Kasia
    assert who(db, c_adam) is None                      # nie przechodzi na Kasię
    assert who(db, c_ewa) == ("U1", "Ewa Druga")
    assert db.get(Clip, c_adam) is not None             # sam klip zostaje


def test_typed_names_are_matched_ignoring_case_spacing_and_diacritics(client, db):
    match = make_match(db, officials=(("CC", "Łukasz Żółć"), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    c_lukasz = clip_for(db, video, match.official("CC"))
    edit(client, db, match, cc_name="Ewa  Druga", u1_name="lukasz zolc")  # zamiana i inna pisownia
    assert who(db, c_lukasz) == ("U1", "lukasz zolc")


def test_replacing_typed_name_unassigns_clips_and_new_person_gets_new_slot(client, db):
    match = make_match(db, officials=(("CC", "Filip Kowalski"), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    c_filip = clip_for(db, video, match.official("CC"))
    edit(client, db, match, cc_name="Kasia Nowak", u1_name="Ewa Druga")
    assert who(db, c_filip) is None
    names = {o.function: o.display_name for o in db.scalars(select(MatchOfficial))}
    assert names == {"CC": "Kasia Nowak", "U1": "Ewa Druga"}


def test_removing_u2_unassigns_only_their_clips(client, db):
    match = make_match(db, officials=(("CC", "Jan Pierwszy"), ("U1", "Ewa Druga"), ("U2", "Kuba Trzeci")))
    video = make_ready_video(db, match)
    c_jan = clip_for(db, video, match.official("CC"))
    c_kuba = clip_for(db, video, match.official("U2"))
    edit(client, db, match, cc_name="Jan Pierwszy", u1_name="Ewa Druga")
    assert who(db, c_jan) == ("CC", "Jan Pierwszy") and who(db, c_kuba) is None


# --- duplikaty w formularzu ---------------------------------------------------------------
def post_new(client, **crew):
    return client.post("/matches", data={**BASE, **crew}, follow_redirects=False)


def test_form_rejects_same_typed_name_on_two_positions(client, db):
    from app.models import Match
    r = post_new(client, cc_name="Łukasz  Żółć", u1_name="lukasz zolc")  # inna pisownia, ta sama osoba
    assert r.status_code == 422
    assert "ta sama osoba" in r.text and "CC i U1" in r.text
    assert 'value="Łukasz  Żółć"' in r.text and 'value="lukasz zolc"' in r.text   # wpisane wartości zostają w formularzu
    assert db.query(Match).count() == 0


def test_form_rejects_typed_duplicate_on_u2(client, db):
    r = post_new(client, cc_name="Jan Pierwszy", u1_name="Ewa Druga", u2_name="EWA DRUGA")
    assert r.status_code == 422 and "U1 i U2" in r.text


def test_form_rejects_same_account_twice(client, db):
    a = make_user(db, ["referee"], email="a@example.com", name="Adam Sędzia")
    r = post_new(client, cc_user=str(a.id), u1_user=str(a.id))
    assert r.status_code == 422 and "To samo konto" in r.text


def test_form_rejects_account_and_typed_name_of_same_person(client, db):
    a = make_user(db, ["referee"], email="a@example.com", name="Adam Sędzia")
    for crew in (dict(cc_user=str(a.id), u1_name="adam  sedzia"),    # konto, potem nazwisko
                 dict(cc_name="Adam Sędzia", u1_user=str(a.id))):    # nazwisko, potem konto
        r = post_new(client, **crew)
        assert r.status_code == 422 and "ta sama osoba" in r.text, crew
    assert f'<option value="{a.id}" selected>' in r.text   # wybór konta zachowany


def test_form_allows_typed_name_equal_to_ambiguous_accounts(client, db):
    """Dwa konta o tym samym imieniu i nazwisku: wpisane nazwisko nie jest żadnym z nich."""
    a = make_user(db, ["referee"], email="a@example.com", name="Jan Dubel")
    make_user(db, ["referee"], email="b@example.com", name="Jan Dubel")
    r = post_new(client, cc_user=str(a.id), u1_name="Jan Dubel")
    assert r.status_code == 303


def test_edit_form_rejects_duplicate_and_keeps_old_crew(client, db):
    match = make_match(db, officials=(("CC", "Jan Pierwszy"), ("U1", "Ewa Druga")))
    r = client.post(f"/matches/{match.id}", data={**BASE, "cc_name": "Ewa Druga", "u1_name": "ewa druga"})
    assert r.status_code == 422 and "ta sama osoba" in r.text
    db.expire_all()
    assert {o.function: o.name for o in db.get(type(match), match.id).officials} == {
        "CC": "Jan Pierwszy", "U1": "Ewa Druga"}


# --- ta sama osoba: wpisane nazwisko i konto -------------------------------------------------
def test_typed_name_replaced_by_the_persons_account_keeps_clips(client, db):
    kasia = make_user(db, ["referee"], email="k@example.com", name="Kasia Żółć")
    match = make_match(db, officials=(("CC", "Filip Kowalski"), ("U1", "kasia zolc")))
    video = make_ready_video(db, match)
    c_kasia = clip_for(db, video, match.official("U1"))
    c_filip = clip_for(db, video, match.official("CC"))
    old_id = match.official("U1").id
    edit(client, db, match, cc_name="Filip Kowalski", u1_user=str(kasia.id))
    after = db.get(type(match), match.id).official("U1")
    assert after.user_id == kasia.id and after.name is None and after.id == old_id  # ta sama pozycja
    assert who(db, c_kasia) == ("U1", "Kasia Żółć")
    assert who(db, c_filip) == ("CC", "Filip Kowalski")


def test_typed_name_replaced_by_account_on_another_position_keeps_clips(client, db):
    kasia = make_user(db, ["referee"], email="k@example.com", name="Kasia Żółć")
    match = make_match(db, officials=(("CC", "Filip Kowalski"), ("U1", "Kasia Żółć")))
    video = make_ready_video(db, match)
    c_kasia = clip_for(db, video, match.official("U1"))
    edit(client, db, match, cc_user=str(kasia.id), u1_name="Filip Kowalski")  # zamiana funkcji + konto
    assert who(db, c_kasia) == ("CC", "Kasia Żółć")
    assert db.get(type(match), match.id).official("CC").user_id == kasia.id


def test_account_replaced_by_typed_name_of_same_person_keeps_clips(client, db):
    """W drugą stronę: konto zamienione na wpisane nazwisko tej samej osoby."""
    kasia = make_user(db, ["referee"], email="k@example.com", name="Kasia Żółć")
    match = make_match(db, officials=(("CC", kasia), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    c_kasia = clip_for(db, video, match.official("CC"))
    edit(client, db, match, cc_name="kasia zolc", u1_name="Ewa Druga")
    assert who(db, c_kasia) == ("CC", "kasia zolc")
    assert db.get(type(match), match.id).official("CC").user_id is None


def test_ambiguous_account_name_is_not_merged_with_typed_name(client, db):
    """Dwa konta o tym samym imieniu i nazwisku: wpisane nazwisko to inna osoba niż konto."""
    first = make_user(db, ["referee"], email="a@example.com", name="Jan Dubel")
    make_user(db, ["referee"], email="b@example.com", name="Jan Dubel")
    match = make_match(db, officials=(("CC", "Jan Dubel"), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    c_jan = clip_for(db, video, match.official("CC"))
    edit(client, db, match, cc_user=str(first.id), u1_name="Ewa Druga")
    assert who(db, c_jan) is None                          # nie łączymy: klip traci przypisanie
    assert db.get(type(match), match.id).official("CC").user_id == first.id


def test_inactive_namesake_account_also_blocks_merging(client, db):
    kasia = make_user(db, ["referee"], email="k@example.com", name="Kasia Żółć")
    make_user(db, ["referee"], email="k2@example.com", name="Kasia Zolc", active=False)
    match = make_match(db, officials=(("CC", "Kasia Żółć"), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    clip = clip_for(db, video, match.official("CC"))
    edit(client, db, match, cc_user=str(kasia.id), u1_name="Ewa Druga")
    assert who(db, clip) is None


def test_identity_helpers():
    from app import services
    accounts = {"kasia zolc": 7}
    assert services.identity(None, "KASIA  Żółć", accounts) == ("u", 7)
    assert services.identity(7, None, accounts) == ("u", 7)
    assert services.identity(None, "Ewa Druga", accounts) == ("n", "ewa druga")
    assert services.person_key(None, "Kasia Zolc", accounts) == "u7"
