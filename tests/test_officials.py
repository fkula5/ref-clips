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
