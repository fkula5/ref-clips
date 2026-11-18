import io
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app import digest, notify, self_assessments
from app.models import (Clip, EmailPreference, GroupMember, Notification, SelfAssessment, SelfAssessmentClip,
                        TrainingGroup)
from app.timeutil import utcnow
from tests.helpers import category_named, make_match, make_ready_video, make_user, mark_periods

ANSWERS = {"opinion": "Dobrze, ale za późno reagowałem.", "good": "Komunikacja z U1.", "bad": "Pozycja w kontrataku."}


@pytest.fixture()
def w(db, make_client):
    """`ref` (CC) and `ref2` (U1) are the crew; `coach` leads the group `ref` belongs to; `coach2` leads
    another group; `outsider` is a referee outside the crew. The match has four clips, three of them
    described.
    """
    clients, users = {}, {}
    for name, roles in (("ref", ("referee",)), ("ref2", ("referee",)), ("outsider", ("referee",)),
                        ("coach", ("coach",)), ("coach2", ("coach",)), ("admin", ("admin",))):
        clients[name], users[name] = make_client(*roles, name=f"Osoba {name}")
    group_a, group_b = TrainingGroup(name="Grupa A"), TrainingGroup(name="Grupa B")
    group_a.members += [GroupMember(user_id=users["coach"].id, role="coach"),
                        GroupMember(user_id=users["ref"].id, role="referee")]
    group_b.members += [GroupMember(user_id=users["coach2"].id, role="coach")]
    db.add_all([group_a, group_b])
    match = make_match(db, officials=(("CC", users["ref"]), ("U1", users["ref2"]), ("U2", "Wpisany Sędzia")))
    video = mark_periods(db, make_ready_video(db, match))
    clips = []
    for i, (category, text) in enumerate((("kroki", "Kroki po zbiórce"), ("osobisty", "Kontakt przy koszu"),
                                          ("blok / szarża", "Szarża w obronie"), (None, ""))):
        clip = Clip(match_id=match.id, video_id=video.id, author_id=users["ref"].id, time_sec=20 + 40 * i,
                    category_id=category_named(db, category) if category else None, description=text,
                    described_at=utcnow() if text else None)
        db.add(clip)
        clips.append(clip)
    other = make_match(db, officials=(("CC", users["ref"]), ("U1", "Ktoś")))
    foreign = Clip(match_id=other.id, video_id=make_ready_video(db, other).id, time_sec=5, description="Obcy")
    db.add(foreign)
    db.commit()
    return SimpleNamespace(c=clients, u=users, match=match, clips=clips, foreign=foreign, other=other, db=db)


def post(w, who, url, expect=(200, 303), **data):
    r = w.c[who].post(url, data=data, follow_redirects=False)
    assert r.status_code in expect, (r.status_code, r.text[:500])
    return r


def open_sheet(w, who="ref", match=None):
    r = post(w, who, f"/matches/{(match or w.match).id}/self-assessments")
    return int(re.search(r"/self-assessments/(\d+)", r.headers["location"]).group(1))


def sheet(w, sa_id) -> SelfAssessment:
    w.db.expire_all()
    return w.db.get(SelfAssessment, sa_id)


def edit(w, who, sa_id, action="save", expect=(200, 303), **fields):
    """Posts the form the way the page does: the row ids in order and the stored text of each field unless
    overridden.
    """
    sa = sheet(w, sa_id)
    data = {**self_assessments.form_values(sa), **fields, "action": action, "row": [r.id for r in sa.rows]}
    r = w.c[who].post(f"/self-assessments/{sa_id}/edit", data=data, follow_redirects=False)
    assert r.status_code in expect, (r.status_code, r.text[:800])
    return r


def add_clips(w, sa_id, clips=None, describe=True):
    for clip in clips or w.clips[:3]:
        edit(w, "ref", sa_id, f"add:{clip.id}")
    if describe:
        sa = sheet(w, sa_id)
        edit(w, "ref", sa_id, **{f"desc_{row.id}": f"Opis {row.id}" for row in sa.rows})


def complete(w, sa_id):
    add_clips(w, sa_id)
    edit(w, "ref", sa_id, **ANSWERS)


def submit(w, sa_id, who="ref", expect=(303,)):
    return edit(w, who, sa_id, "submit", expect=expect)


# ---------- access ----------

def test_a_crew_referee_opens_one_draft_and_gets_the_same_one_again(w):
    first = open_sheet(w)
    assert open_sheet(w) == first
    assert w.db.query(SelfAssessment).count() == 1
    sa = sheet(w, first)
    assert (sa.user_id, sa.status, sa.submitted_at) == (w.u["ref"].id, "draft", None)
    assert w.c["ref"].get(f"/self-assessments/{first}/edit").status_code == 200


def test_two_crew_members_each_get_their_own_sheet(w):
    assert open_sheet(w, "ref") != open_sheet(w, "ref2")


@pytest.mark.parametrize("who", ["outsider", "coach", "admin"])
def test_only_a_crew_referee_may_start_one(w, who):
    post(w, who, f"/matches/{w.match.id}/self-assessments", expect=(403,))
    assert w.db.query(SelfAssessment).count() == 0


def test_a_draft_is_visible_only_to_its_author(w):
    sa_id = open_sheet(w)
    for who in ("ref2", "outsider", "coach", "coach2", "admin"):
        for url in (f"/self-assessments/{sa_id}", f"/self-assessments/{sa_id}/edit", f"/self-assessments/{sa_id}/pdf"):
            assert w.c[who].get(url).status_code == 404, (who, url)
    for url in (f"/self-assessments/{sa_id}", f"/self-assessments/{sa_id}/edit", f"/self-assessments/{sa_id}/pdf"):
        assert w.c["ref"].get(url).status_code == 200


def test_a_submitted_sheet_is_visible_to_coaches_and_admins_but_not_to_other_referees(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    for who in ("ref", "coach", "coach2", "admin"):
        assert w.c[who].get(f"/self-assessments/{sa_id}").status_code == 200, who
        assert w.c[who].get(f"/self-assessments/{sa_id}/pdf").status_code == 200, who
    for who in ("ref2", "outsider"):
        assert w.c[who].get(f"/self-assessments/{sa_id}").status_code == 404, who
        assert w.c[who].get(f"/self-assessments/{sa_id}/pdf").status_code == 404, who


def test_nobody_but_the_author_edits_and_a_coach_who_may_see_it_gets_403(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    edit(w, "ref2", sa_id, expect=(404,))
    submit(w, sa_id)
    assert edit(w, "coach", sa_id, expect=(403,)).status_code == 403
    assert w.c["coach"].get(f"/self-assessments/{sa_id}/edit").status_code == 403


def test_the_match_card_shows_each_role_only_what_it_may_see(w):
    mine, theirs = open_sheet(w, "ref"), open_sheet(w, "ref2")
    page = w.c["ref"].get(f"/matches/{w.match.id}").text
    assert f'data-self-assessment="{mine}"' in page and f'data-self-assessment="{theirs}"' not in page
    assert "Kontynuuj szkic" in page and 'id="sa-open"' not in page  # the author already has a draft
    assert 'id="sa-card"' not in w.c["outsider"].get(f"/matches/{w.match.id}").text
    coach_page = w.c["coach"].get(f"/matches/{w.match.id}").text
    assert "Nikt jeszcze nie wysłał" in coach_page and 'data-self-assessment=' not in coach_page
    complete(w, mine)
    submit(w, mine)
    coach_page = w.c["coach"].get(f"/matches/{w.match.id}").text
    assert f'data-self-assessment="{mine}"' in coach_page and f'data-self-assessment="{theirs}"' not in coach_page
    assert "Zobacz wysłaną" in w.c["ref"].get(f"/matches/{w.match.id}").text


def test_a_referee_with_no_sheet_is_offered_to_start_one_on_the_match_page(w):
    assert 'id="sa-open"' in w.c["ref"].get(f"/matches/{w.match.id}").text
    assert 'id="sa-card"' not in w.c["outsider"].get(f"/matches/{w.match.id}").text


def test_the_list_page_shows_coaches_submitted_sheets_and_referees_their_own(w):
    done, draft = open_sheet(w, "ref"), open_sheet(w, "ref2")
    complete(w, done)
    submit(w, done)
    coach_page = w.c["coach"].get("/self-assessments").text
    assert f'data-self-assessment="{done}"' in coach_page and f'data-self-assessment="{draft}"' not in coach_page
    ref2_page = w.c["ref2"].get("/self-assessments").text
    assert f'data-self-assessment="{draft}"' in ref2_page and f'data-self-assessment="{done}"' not in ref2_page
    assert "Moje samooceny" in w.c["ref2"].get("/").text and "Samooceny" in w.c["coach"].get("/").text
    assert w.c["outsider"].get("/self-assessments").status_code == 200


# ---------- clips ----------

def test_a_clip_is_added_with_time_and_name_filled_in_from_it(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[1].id}")
    row = sheet(w, sa_id).rows[0]
    assert (row.clip_id, row.position) == (w.clips[1].id, 0)
    assert row.name_label == "osobisty"
    assert row.time_label == "Całość, 1:00 (Q1 · 1:00)"
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    assert f'href="/clips/{w.clips[1].id}"' in page


def test_a_clip_without_a_category_is_named_bez_kategorii(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[3].id}")
    assert sheet(w, sa_id).rows[0].name_label == "bez kategorii"


def test_the_picker_offers_the_match_clips_with_a_preview_link_and_not_those_already_added(w):
    sa_id = open_sheet(w)
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    for clip in w.clips:
        assert f'value="add:{clip.id}"' in page and f'href="/clips/{clip.id}" target="_blank"' in page
    assert f'value="add:{w.foreign.id}"' not in page
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    assert f'value="add:{w.clips[0].id}"' not in w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text


def test_the_same_clip_cannot_be_added_twice(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    r = edit(w, "ref", sa_id, f"add:{w.clips[0].id}", expect=(422,))
    assert "Ten klip jest już w samoocenie." in r.text
    assert len(sheet(w, sa_id).rows) == 1


def test_a_clip_of_another_match_is_rejected(w):
    sa_id = open_sheet(w)
    r = edit(w, "ref", sa_id, f"add:{w.foreign.id}", expect=(422,))
    assert "Tego klipu nie ma w tym meczu." in r.text
    assert edit(w, "ref", sa_id, "add:99999", expect=(422,)).status_code == 422
    assert edit(w, "ref", sa_id, "add:abc", expect=(422,)).status_code == 422
    assert sheet(w, sa_id).rows == []


def test_rows_are_reordered_and_removed_and_positions_stay_consecutive(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id)
    rows = sheet(w, sa_id).rows
    ids = [r.clip_id for r in rows]
    edit(w, "ref", sa_id, f"down:{rows[0].id}")
    assert [r.clip_id for r in sheet(w, sa_id).rows] == [ids[1], ids[0], ids[2]]
    edit(w, "ref", sa_id, f"up:{rows[2].id}")
    assert [r.clip_id for r in sheet(w, sa_id).rows] == [ids[1], ids[2], ids[0]]
    edit(w, "ref", sa_id, f"up:{sheet(w, sa_id).rows[0].id}")  # the first cannot go higher
    edit(w, "ref", sa_id, f"remove:{rows[2].id}")
    sa = sheet(w, sa_id)
    assert [(r.clip_id, r.position) for r in sa.rows] == [(ids[1], 0), (ids[0], 1)]
    assert w.db.query(SelfAssessmentClip).count() == 2


def test_the_order_the_form_shows_is_stored_on_save(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id)
    sa = sheet(w, sa_id)
    reverse = [r.id for r in reversed(sa.rows)]
    w.c["ref"].post(f"/self-assessments/{sa_id}/edit", data={"action": "save", "row": reverse})
    assert [r.id for r in sheet(w, sa_id).rows] == reverse


def test_typed_text_survives_a_row_action(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    row = sheet(w, sa_id).rows[0]
    edit(w, "ref", sa_id, f"add:{w.clips[1].id}", **{f"desc_{row.id}": "Moja wersja"}, opinion="Wstępnie")
    sa = sheet(w, sa_id)
    assert sa.rows[0].description == "Moja wersja" and sa.opinion == "Wstępnie"


# ---------- descriptions ----------

def test_adding_a_clip_prefills_the_row_with_the_clips_description(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    assert sheet(w, sa_id).rows[0].description == "Kroki po zbiórce"
    assert "Kroki po zbiórce" in w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text


def test_editing_the_row_leaves_the_clips_own_description_alone(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    row = sheet(w, sa_id).rows[0]
    edit(w, "ref", sa_id, **{f"desc_{row.id}": "Zupełnie inny opis"})
    assert sheet(w, sa_id).rows[0].description == "Zupełnie inny opis"
    w.db.expire_all()
    assert w.db.get(Clip, w.clips[0].id).description == "Kroki po zbiórce"


def test_a_clip_without_a_description_gives_an_empty_field(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[3].id}")
    assert sheet(w, sa_id).rows[0].description == ""
    assert not w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text.count("Wstaw opis z klipu")


def test_a_later_change_of_the_clip_description_does_not_overwrite_the_row(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    w.clips[0].description = "Zmieniony w systemie"
    w.db.commit()
    edit(w, "ref", sa_id)
    sa = sheet(w, sa_id)
    assert sa.rows[0].description == "Kroki po zbiórce"
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    assert 'class="btn small sa-insert"' in page and 'data-text="Zmieniony w systemie"' in page


# ---------- validation and submit ----------

def errors_of(r):
    return re.findall(r"<li>([^<]+)</li>", r.text.split('id="sa-errors"')[1].split("</div>")[0])


def test_submitting_needs_three_clips(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id, w.clips[:2])
    edit(w, "ref", sa_id, **ANSWERS)
    r = submit(w, sa_id, expect=(422,))
    assert errors_of(r) == ["Dodaj co najmniej 3 klipy — teraz jest ich 2."]
    assert sheet(w, sa_id).status == "draft"


def test_an_empty_description_blocks_submitting_and_names_the_clip(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id, w.clips[1:4], describe=False)
    rows = sheet(w, sa_id).rows
    edit(w, "ref", sa_id, **{f"desc_{rows[0].id}": "Jest", f"desc_{rows[1].id}": "Jest"}, **ANSWERS)
    r = submit(w, sa_id, expect=(422,))
    assert errors_of(r) == ["Klip 3 (bez kategorii): wpisz opis."]


def test_an_empty_answer_blocks_submitting(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id)
    edit(w, "ref", sa_id, opinion="Tak", good="  ")
    r = submit(w, sa_id, expect=(422,))
    assert errors_of(r) == ["Pytanie 2: wpisz odpowiedź.", "Pytanie 3: wpisz odpowiedź."]


def test_a_failed_submit_keeps_what_was_typed_as_a_draft(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id, w.clips[:1])
    r = edit(w, "ref", sa_id, "submit", expect=(422,), opinion="Zostaje")
    assert "Szkic został zapisany" in r.text and "Zostaje" in r.text
    assert sheet(w, sa_id).opinion == "Zostaje"


def test_a_draft_may_be_incomplete(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, good="Tylko to")
    sa = sheet(w, sa_id)
    assert (sa.good, sa.opinion, sa.status) == ("Tylko to", "", "draft")


def test_too_long_text_is_refused_and_the_typed_text_stays_in_the_form(w):
    sa_id = open_sheet(w)
    r = edit(w, "ref", sa_id, expect=(422,), opinion="x" * 5001)
    assert errors_of(r) == ["Pytanie 1: najwyżej 5000 znaków (jest 5001)."]
    assert sheet(w, sa_id).opinion == ""


def test_submitting_locks_the_sheet_for_the_author(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    r = submit(w, sa_id)
    assert r.headers["location"] == f"/self-assessments/{sa_id}"
    sa = sheet(w, sa_id)
    assert sa.status == "submitted" and sa.submitted_at is not None
    edit(w, "ref", sa_id, expect=(403,), opinion="Za późno")
    edit(w, "ref", sa_id, "submit", expect=(403,))
    edit(w, "ref", sa_id, f"add:{w.clips[3].id}", expect=(403,))
    post(w, "ref", f"/self-assessments/{sa_id}/delete", expect=(403,))
    assert w.c["ref"].get(f"/self-assessments/{sa_id}/edit").status_code == 403
    assert sheet(w, sa_id).opinion == ANSWERS["opinion"]
    assert post(w, "ref", f"/matches/{w.match.id}/self-assessments").headers["location"] == f"/self-assessments/{sa_id}"


def test_only_an_admin_reopens_a_submitted_sheet_and_submitted_at_is_kept(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    post(w, "ref", f"/self-assessments/{sa_id}/reopen", expect=(404, 403))
    submit(w, sa_id)
    first_sent = sheet(w, sa_id).submitted_at
    for who in ("ref", "coach"):
        post(w, who, f"/self-assessments/{sa_id}/reopen", expect=(403,))
    for who in ("ref2", "outsider"):
        post(w, who, f"/self-assessments/{sa_id}/reopen", expect=(404,))
    assert 'id="sa-reopen"' in w.c["admin"].get(f"/self-assessments/{sa_id}").text
    assert 'id="sa-reopen"' not in w.c["coach"].get(f"/self-assessments/{sa_id}").text
    post(w, "admin", f"/self-assessments/{sa_id}/reopen")
    sa = sheet(w, sa_id)
    assert (sa.status, sa.submitted_at) == ("draft", first_sent)
    edit(w, "ref", sa_id, opinion="Poprawiona")
    assert w.c["coach"].get(f"/self-assessments/{sa_id}").status_code == 404  # a draft again
    submit(w, sa_id)
    sa = sheet(w, sa_id)
    assert sa.status == "submitted" and sa.opinion == "Poprawiona" and sa.submitted_at >= first_sent


def test_an_admin_cannot_reopen_a_draft(w):
    sa_id = open_sheet(w)
    post(w, "admin", f"/self-assessments/{sa_id}/reopen", expect=(404,))


def test_the_author_deletes_their_draft_and_nobody_else_can(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id)
    for who in ("ref2", "coach", "admin"):
        post(w, who, f"/self-assessments/{sa_id}/delete", expect=(404,))
    r = post(w, "ref", f"/self-assessments/{sa_id}/delete")
    assert r.headers["location"] == f"/matches/{w.match.id}#samoocena"
    assert w.db.query(SelfAssessment).count() == 0 and w.db.query(SelfAssessmentClip).count() == 0
    assert w.db.query(Clip).count() == 5  # the clips themselves are untouched


# ---------- the snapshot ----------

def test_the_snapshot_keeps_a_submitted_sheet_readable_after_a_clip_is_deleted(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    before = [(r.time_label, r.name_label, r.description) for r in sheet(w, sa_id).rows]
    w.db.delete(w.db.get(Clip, w.clips[0].id))
    w.db.commit()
    rows = sheet(w, sa_id).rows
    assert len(rows) == 3 and rows[0].clip_id is None
    assert [(r.time_label, r.name_label, r.description) for r in rows] == before
    page = w.c["coach"].get(f"/self-assessments/{sa_id}")
    assert page.status_code == 200 and before[0][0] in page.text and before[0][2] in page.text


def test_a_draft_row_of_a_deleted_clip_is_marked_and_still_counts(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    w.db.delete(w.db.get(Clip, w.clips[0].id))
    w.db.commit()
    assert "klip został usunięty" in w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    submit(w, sa_id)
    assert sheet(w, sa_id).status == "submitted"


def test_a_draft_follows_a_change_of_the_clips_category_but_a_submitted_sheet_does_not(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    w.clips[0].category_id = category_named(w.db, "osobisty")
    w.db.commit()
    edit(w, "ref", sa_id)
    first = sheet(w, sa_id).rows[0].name_label
    assert first == w.clips[0].category_label
    submit(w, sa_id)
    w.clips[0].category_id = category_named(w.db, "kroki")
    w.db.commit()
    assert sheet(w, sa_id).rows[0].name_label == first


def test_deleting_the_match_removes_its_self_assessments(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    post(w, "admin", f"/matches/{w.match.id}/delete")
    assert w.db.query(SelfAssessment).count() == 0 and w.db.query(SelfAssessmentClip).count() == 0


def test_a_match_with_a_submitted_self_assessment_can_only_be_deleted_by_an_admin(w):
    w.match.created_by = w.u["ref"].id
    w.db.commit()
    other_draft, mine = open_sheet(w, "ref2"), open_sheet(w, "ref")
    complete(w, mine)
    assert w.c["ref"].get(f"/matches/{w.match.id}/delete").status_code == 200  # only drafts: the creator may
    submit(w, mine)
    assert w.c["ref"].get(f"/matches/{w.match.id}/delete").status_code == 403
    assert "samooceny sędziów: <strong>2</strong>" in w.c["admin"].get(f"/matches/{w.match.id}/delete").text
    assert other_draft


# ---------- the report ----------

def test_the_report_has_the_header_the_clip_blocks_and_the_excel_questions(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    page = w.c["coach"].get(f"/self-assessments/{sa_id}").text
    assert "ARKUSZ SAMOOCENY RC 2026/27" in page
    for text in ("Liga:", "II liga", "Data meczu:", "28.10.2026", "Gospodarze:", "Legia", "Goście:", "Wisła",
                 "Sędzia główny:", "Osoba ref", "Sędzia pomocniczy:", "Osoba ref2, Wpisany Sędzia",
                 "Czas z nagrania", "Nazwa klipu", "Opis"):
        assert text in page, text
    assert page.count('class="sa-block"') == 6
    assert "Co uważam o swoim sędziowaniu? (ogólne opinię o swoim sędziowaniu)" in page
    assert "Co było dobre w tym meczu i co chciałbym zachować na kolejne mecze?" in page
    assert "Co było złe w tym meczu i co chciałbym zmienić w kolejnych meczach?" in page
    assert ANSWERS["bad"] in page and 'id="sa-draft-mark"' not in page


def test_more_than_three_clips_make_more_blocks(w):
    sa_id = open_sheet(w)
    add_clips(w, sa_id, w.clips)
    edit(w, "ref", sa_id, **ANSWERS, **{f"desc_{r.id}": "x" for r in sheet(w, sa_id).rows})
    submit(w, sa_id)
    assert w.c["coach"].get(f"/self-assessments/{sa_id}").text.count('id="sa-clip-') == 4


def test_the_author_previews_a_draft_with_the_draft_marker(w):
    sa_id = open_sheet(w)
    page = w.c["ref"].get(f"/self-assessments/{sa_id}").text
    assert 'id="sa-draft-mark"' in page and "SZKIC" in page and "Pobierz PDF" in page
    assert f'href="/self-assessments/{sa_id}/edit"' in page


def test_the_report_escapes_what_the_author_wrote(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, opinion="<script>alert(1)</script>")
    page = w.c["ref"].get(f"/self-assessments/{sa_id}").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page


# ---------- the PDF ----------

def pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def test_the_pdf_is_a_real_pdf_with_polish_text_and_a_sanitised_file_name(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    edit(w, "ref", sa_id, good="Zażółć gęślą jaźń")
    submit(w, sa_id)
    r = w.c["coach"].get(f"/self-assessments/{sa_id}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert r.headers["content-disposition"] == 'attachment; filename="samoocena_2026-10-28_Legia-Wisla_CC.pdf"'
    text = pdf_text(r.content)
    for expected in ("ARKUSZ SAMOOCENY RC 2026/27", "Sędzia główny", "Goście", "Zażółć gęślą jaźń",
                     "ogólne opinię", "Całość, 0:20 (Q1 · 0:20)", "kroki", "Czas z nagrania"):
        assert expected in text, expected
    assert "SZKIC" not in text


def test_a_draft_pdf_carries_the_draft_marker(w):
    sa_id = open_sheet(w)
    r = w.c["ref"].get(f"/self-assessments/{sa_id}/pdf")
    assert r.content.startswith(b"%PDF") and "SZKIC" in pdf_text(r.content)


def test_a_long_report_does_not_split_a_clip_block_across_pages(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    sa = sheet(w, sa_id)
    edit(w, "ref", sa_id, **{f"desc_{r.id}": f"Długi opis klipu {i} " * 60 for i, r in enumerate(sa.rows)},
         opinion="Bardzo długa odpowiedź. " * 150)
    r = w.c["ref"].get(f"/self-assessments/{sa_id}/pdf")
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) >= 2
    for i in range(3):
        marker = f"Długi opis klipu {i}"
        assert sum(marker in p.extract_text() for p in pages) == 1


# ---------- notifications and digest ----------

def notes(w, kind="self_assessment"):
    w.db.expire_all()
    return list(w.db.scalars(select(Notification).where(Notification.kind == kind).order_by(Notification.id)))


def test_a_submitted_sheet_notifies_the_coaches_of_the_authors_groups_only(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    assert notes(w) == []  # a draft tells nobody
    submit(w, sa_id)
    [note] = notes(w)
    assert (note.recipient_id, note.actor_id, note.match_id, note.self_assessment_id) == (
        w.u["coach"].id, w.u["ref"].id, w.match.id, sa_id)
    assert notify.target_url(note) == f"/self-assessments/{sa_id}"
    bell = w.c["coach"].get("/notifications").text
    assert "wysłana samoocena" in bell and "Osoba ref" in bell
    assert notes(w) and "Powiadomienia: 1" in w.c["coach"].get("/notifications/bell").text


def test_opening_the_sheet_marks_its_notification_read(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    assert notify.unread_count(w.db, w.u["coach"].id) == 1
    w.c["coach"].get(f"/self-assessments/{sa_id}")
    assert notify.unread_count(w.db, w.u["coach"].id) == 0


def test_the_bell_link_leads_to_the_sheet(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    [note] = notes(w)
    r = post(w, "coach", f"/notifications/{note.id}/open")
    assert r.headers["location"] == f"/self-assessments/{sa_id}"


def test_a_deactivated_group_coach_is_not_notified(w):
    w.u["coach"].is_active = False
    w.db.commit()
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    assert notes(w) == []


def test_an_author_without_a_group_notifies_nobody_but_coaches_still_see_the_sheet(w):
    sa_id = open_sheet(w, "ref2")
    add_clips_as(w, "ref2", sa_id)
    edit(w, "ref2", sa_id, **ANSWERS)
    submit(w, sa_id, "ref2")
    assert notes(w) == []
    assert w.c["coach2"].get(f"/self-assessments/{sa_id}").status_code == 200


def add_clips_as(w, who, sa_id):
    for clip in w.clips[:3]:
        edit(w, who, sa_id, f"add:{clip.id}")
    sa = sheet(w, sa_id)
    edit(w, who, sa_id, **{f"desc_{row.id}": "Opis" for row in sa.rows})


def test_a_reopened_and_resubmitted_sheet_notifies_again(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    post(w, "admin", f"/self-assessments/{sa_id}/reopen")
    submit(w, sa_id)
    assert len(notes(w)) == 2


def test_deleting_the_match_removes_the_notification(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    post(w, "admin", f"/matches/{w.match.id}/delete")
    assert notes(w) == []


NOW = utcnow().replace(microsecond=0)


def digest_text(w, user):
    from app import mail
    sender = mail.MemorySender()
    mail.OUTBOX.clear()
    w.db.execute(Notification.__table__.update().values(created_at=NOW))
    w.db.commit()
    digest.run_due(w.db, now=NOW.replace(hour=12) if NOW.hour < 12 else NOW, sender=sender,
                   base="https://klipy.example.pl")
    found = [m for m in mail.OUTBOX if m["To"].addresses[0].addr_spec == user.email]
    return found[0].get_body(("plain",)).get_content() if found else None


def test_the_digest_lists_the_submitted_sheet_for_a_group_coach_by_default(w, mailbox):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    text = digest_text(w, w.u["coach"])
    assert "Wysłano samoocenę sędziego: Osoba ref" in text
    assert f"https://klipy.example.pl/self-assessments/{sa_id}" in text


def test_the_digest_item_follows_the_switch(w, mailbox):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    w.db.add(EmailPreference(user_id=w.u["coach"].id, digest_enabled=True, self_assessment_submitted=False))
    w.db.commit()
    assert digest_text(w, w.u["coach"]) is None or "samoocenę" not in digest_text(w, w.u["coach"])


def test_the_switch_defaults_to_coaches_and_is_hidden_from_referees(w):
    assert "self_assessment_submitted" in digest.default_for({"coach"})
    assert "self_assessment_submitted" not in digest.default_for({"referee"})
    assert "self_assessment_submitted" not in digest.default_for({"admin"})
    assert "self_assessment_submitted" in digest.configurable_events(w.u["coach"])
    assert "self_assessment_submitted" in digest.configurable_events(w.u["admin"])
    assert "self_assessment_submitted" not in digest.configurable_events(w.u["ref"])


def test_the_settings_page_shows_and_saves_the_switch(w):
    page = w.c["coach"].get("/settings/notifications").text
    assert 'name="self_assessment_submitted" value="1" checked' in page
    assert "Wysłane samooceny sędziów z moich grup" in page
    w.c["coach"].post("/settings/notifications", data={"digest_enabled": "1"})
    w.db.expire_all()
    assert w.db.get(EmailPreference, w.u["coach"].id).self_assessment_submitted is False
    w.c["coach"].post("/settings/notifications", data={"digest_enabled": "1", "self_assessment_submitted": "1"})
    w.db.expire_all()
    assert w.db.get(EmailPreference, w.u["coach"].id).self_assessment_submitted is True
    assert "self_assessment_submitted" not in w.c["ref"].get("/settings/notifications").text


@pytest.mark.skipif(not shutil.which("fc-list") or "Carlito" not in subprocess.run(
    ["fc-list"], capture_output=True, text=True).stdout, reason="the layout is calibrated for Carlito (Calibri metrics)")
def test_a_three_clip_sheet_fits_on_one_a4_page_like_the_excel_original(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    reader = PdfReader(io.BytesIO(w.c["coach"].get(f"/self-assessments/{sa_id}/pdf").content))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (595, 842)
