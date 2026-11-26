import io
import re
import shutil
import subprocess
import zipfile
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import config, digest, notify, self_assessments, share
from app.models import (Clip, EmailPreference, GroupMember, Notification, SelfAssessment, SelfAssessmentClip,
                        TrainingGroup)
from app.storage import storage
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
    before = [(r.name_label, r.description) for r in sheet(w, sa_id).rows]
    w.db.delete(w.db.get(Clip, w.clips[0].id))
    w.db.commit()
    rows = sheet(w, sa_id).rows
    assert len(rows) == 3 and rows[0].clip_id is None
    assert [(r.name_label, r.description) for r in rows] == before
    page = w.c["coach"].get(f"/self-assessments/{sa_id}")
    assert page.status_code == 200 and before[0][0] in page.text and before[0][1] in page.text


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
                     "ogólne opinię", "kroki", "Czas z nagrania"):
        assert expected in text, expected
    assert "SZKIC" not in text and "0:20" not in text  # the recording time column is left empty


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


# ---------- the ZIP ----------

def cut(w, clip, content=None):
    clip = w.db.get(Clip, clip.id)
    clip.status, clip.clip_path, clip.clip_version = "cut", f"clips/{clip.id}_v1.mp4", 1
    with storage.open_write(clip.clip_path) as fh:
        fh.write(content or f"video-{clip.id}".encode())
    w.db.commit()
    return storage.local_path(clip.clip_path).read_bytes()


def open_zip(response) -> zipfile.ZipFile:
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip", response.text[:300]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.testzip() is None
    return archive


def tmp_files():
    return list((config.DATA_DIR / "tmp").glob("*"))


def test_the_zip_has_the_pdf_and_the_clips_numbered_like_the_rows(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    contents = {c.id: cut(w, c) for c in w.clips[:3]}
    edit(w, "ref", sa_id, f"down:{sheet(w, sa_id).rows[0].id}")  # rows: osobisty, kroki, blok
    submit(w, sa_id)
    r = w.c["coach"].get(f"/self-assessments/{sa_id}/zip")
    archive = open_zip(r)
    assert r.headers["content-disposition"] == 'attachment; filename="samoocena_2026-10-28_Legia-Wisla_CC.zip"'
    assert archive.namelist() == ["samoocena_2026-10-28_Legia-Wisla_CC.pdf", "klipy/01_osobisty.mp4",
                                  "klipy/02_kroki.mp4", "klipy/03_blok-szarza.mp4"]
    assert archive.read("klipy/01_osobisty.mp4") == contents[w.clips[1].id]
    assert archive.read("klipy/02_kroki.mp4") == contents[w.clips[0].id]
    assert archive.read("klipy/03_blok-szarza.mp4") == contents[w.clips[2].id]
    pdf = archive.read("samoocena_2026-10-28_Legia-Wisla_CC.pdf")
    assert pdf.startswith(b"%PDF") and "ARKUSZ SAMOOCENY RC 2026/27" in pdf_text(pdf)
    assert all(i.date_time == (2000, 1, 1, 0, 0, 0) for i in archive.infolist())
    assert tmp_files() == []


def test_rows_without_a_cut_file_are_skipped_and_listed_in_the_readme(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    edit(w, "ref", sa_id, "manual")
    manual = sheet(w, sa_id).rows[-1]
    edit(w, "ref", sa_id, **{f"time_{manual.id}": "Q1, 1:00", f"name_{manual.id}": "Faul pod koszem",
                             f"desc_{manual.id}": "Opis"})
    kept = cut(w, w.clips[0])
    cut(w, w.clips[2])  # a file that goes missing after the clip was cut
    storage.local_path(f"clips/{w.clips[2].id}_v1.mp4").unlink()
    submit(w, sa_id)
    w.db.delete(w.db.get(Clip, w.clips[1].id))
    w.db.commit()
    archive = open_zip(w.c["ref"].get(f"/self-assessments/{sa_id}/zip"))
    assert archive.namelist() == ["samoocena_2026-10-28_Legia-Wisla_CC.pdf", "klipy/01_kroki.mp4", "README.txt"]
    assert archive.read("klipy/01_kroki.mp4") == kept
    readme = archive.read("README.txt").decode()
    assert "2. osobisty — klip usunięty z platformy" in readme
    assert "3. blok / szarża — klip jeszcze nie został wycięty" in readme
    assert "4. Faul pod koszem — wiersz wpisany ręcznie" in readme
    assert "kroki" not in readme


def test_a_clip_that_is_not_cut_yet_is_skipped_too(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    archive = open_zip(w.c["ref"].get(f"/self-assessments/{sa_id}/zip"))
    assert archive.namelist() == ["samoocena_2026-10-28_Legia-Wisla_CC.pdf", "README.txt"]
    assert archive.read("README.txt").decode().count("klip jeszcze nie został wycięty") == 3


def test_a_sheet_with_every_clip_cut_has_no_readme(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    for clip in w.clips[:3]:
        cut(w, clip)
    submit(w, sa_id)
    assert "README.txt" not in open_zip(w.c["ref"].get(f"/self-assessments/{sa_id}/zip")).namelist()


def test_a_standalone_sheet_gives_a_zip_with_the_pdf_and_a_readme_only(w):
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    archive = open_zip(w.c["ref"].get(f"/self-assessments/{sa_id}/zip"))
    assert archive.namelist()[0].endswith(".pdf") and archive.namelist()[1:] == ["README.txt"]
    assert archive.read("README.txt").decode().count("wiersz wpisany ręcznie") == 3


def test_a_draft_has_no_zip_and_no_button(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    r = w.c["ref"].get(f"/self-assessments/{sa_id}/zip")
    assert r.status_code == 409 and "po wysłaniu" in r.text
    assert 'id="sa-zip"' not in w.c["ref"].get(f"/self-assessments/{sa_id}").text
    submit(w, sa_id)
    assert 'id="sa-zip"' in w.c["ref"].get(f"/self-assessments/{sa_id}").text
    post(w, "admin", f"/self-assessments/{sa_id}/reopen")
    assert w.c["ref"].get(f"/self-assessments/{sa_id}/zip").status_code == 409


def test_who_may_see_the_sheet_may_download_its_zip(w):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    for who in ("ref", "coach", "coach2", "admin"):
        assert w.c[who].get(f"/self-assessments/{sa_id}/zip").status_code == 200, who
    for who in ("ref2", "outsider"):
        assert w.c[who].get(f"/self-assessments/{sa_id}/zip").status_code == 404, who


def test_the_zip_needs_a_login(w, anon_client):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    submit(w, sa_id)
    assert anon_client.get(f"/self-assessments/{sa_id}/zip", follow_redirects=False).status_code in (303, 401)


@pytest.mark.parametrize("case,message", [("zajęte", "inne paczki"), ("brak miejsca", "nie ma teraz miejsca")])
def test_a_busy_or_full_server_answers_503_and_leaves_nothing_behind(w, monkeypatch, case, message):
    sa_id = open_sheet(w)
    complete(w, sa_id)
    cut(w, w.clips[0])
    submit(w, sa_id)
    if case == "zajęte":
        monkeypatch.setattr(config, "SHARE_ZIP_MAX_PARALLEL", 0)
    else:
        monkeypatch.setattr(storage, "free_bytes", lambda: 0)
    r = w.c["ref"].get(f"/self-assessments/{sa_id}/zip")
    assert r.status_code == 503 and message in r.text and "retry-after" in r.headers
    assert tmp_files() == [] and share._zips_running == 0


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
    # Run after today's local digest hour: computed in UTC, the test failed between local midnight and 07:00.
    run_at = max(NOW, digest.digest_time(NOW) + timedelta(minutes=1))
    digest.run_due(w.db, now=run_at, sender=sender,
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
    text = digest_text(w, w.u["coach"])
    assert text is None or "samoocenę" not in text


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


# ---------- standalone sheets (a match that is not in the system) ----------

HEADER = {"league": "Liga Amatorska", "match_date": "2026-11-07", "home_team": "Śląsk", "away_team": "Zagłębie",
          "main_referee": "Jan Kowalski", "assistant_referees": "Ewa Nowak, Piotr Wiśniewski"}


def new_standalone(w, who="ref"):
    r = post(w, who, "/self-assessments/new")
    return int(re.search(r"/self-assessments/(\d+)/edit", r.headers["location"]).group(1))


def add_manual_rows(w, sa_id, count=3, who="ref"):
    for _ in range(count):
        edit(w, who, sa_id, "manual")
    fields = {}
    for i, row in enumerate(sheet(w, sa_id).rows, start=1):
        if row.is_manual and not row.description:
            fields.update({f"time_{row.id}": f"Q{i}, 3:1{i}", f"name_{row.id}": f"Faul {i}",
                           f"desc_{row.id}": f"Opis {i}"})
    edit(w, who, sa_id, **fields)


def complete_standalone(w, who="ref"):
    sa_id = new_standalone(w, who)
    add_manual_rows(w, sa_id, who=who)
    edit(w, who, sa_id, **HEADER, **ANSWERS)
    return sa_id


def test_a_referee_creates_standalone_sheets_and_coach_or_admin_alone_cannot(w, make_client):
    sa_id = new_standalone(w, "outsider")  # needs no place in any crew
    sa = sheet(w, sa_id)
    assert (sa.match_id, sa.user_id, sa.status, sa.is_standalone) == (None, w.u["outsider"].id, "draft", True)
    assert w.c["outsider"].get(f"/self-assessments/{sa_id}/edit").status_code == 200
    for who in ("coach", "admin"):
        post(w, who, "/self-assessments/new", expect=(403,))
    both, _ = make_client("coach", "referee")
    assert both.post("/self-assessments/new", follow_redirects=False).status_code == 303
    assert w.db.query(SelfAssessment).count() == 2


def test_the_entry_point_is_on_the_list_page_for_referees_only(w):
    assert 'id="sa-new-standalone"' in w.c["ref"].get("/self-assessments").text
    assert 'id="sa-new-standalone"' in w.c["outsider"].get("/self-assessments").text
    assert 'id="sa-new-standalone"' not in w.c["coach"].get("/self-assessments").text
    assert 'id="sa-new-standalone"' not in w.c["admin"].get("/self-assessments").text


def test_one_user_may_have_several_standalone_sheets_but_one_per_match(w):
    first, second, third = (new_standalone(w) for _ in range(3))
    assert len({first, second, third}) == 3
    open_sheet(w)
    assert w.db.query(SelfAssessment).filter_by(user_id=w.u["ref"].id).count() == 4
    w.db.add(SelfAssessment(match_id=w.match.id, user_id=w.u["ref"].id))
    with pytest.raises(IntegrityError):
        w.db.flush()
    w.db.rollback()


def test_the_header_is_typed_and_stored_on_a_draft_that_may_be_incomplete(w):
    sa_id = new_standalone(w)
    edit(w, "ref", sa_id, league="  Liga   Amatorska ", home_team="Śląsk", match_date="2026-11-07")
    sa = sheet(w, sa_id)
    assert (sa.league, sa.home_team, sa.match_date.isoformat(), sa.away_team) == (
        "Liga Amatorska", "Śląsk", "2026-11-07", "")
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    assert 'name="league"' in page and 'value="Liga Amatorska"' in page and 'value="2026-11-07"' in page
    assert 'id="sa-picker"' not in page and "Dodaj klip z meczu" not in page
    edit(w, "ref", sa_id, match_date="")
    assert sheet(w, sa_id).match_date is None


def test_a_bad_date_or_too_long_header_is_refused_and_the_typed_text_stays(w):
    sa_id = new_standalone(w)
    r = edit(w, "ref", sa_id, expect=(422,), match_date="not-a-date", league="x" * 201)
    assert "Data meczu: wpisz poprawną datę." in r.text and "Liga: najwyżej 200 znaków" in r.text
    assert sheet(w, sa_id).league == ""


@pytest.mark.parametrize("missing", ["league", "match_date", "home_team", "away_team", "main_referee"])
def test_every_required_header_field_blocks_submitting(w, missing):
    sa_id = complete_standalone(w)
    edit(w, "ref", sa_id, **{missing: ""})
    r = submit(w, sa_id, expect=(422,))
    label = {"league": "Liga", "match_date": "Data meczu", "home_team": "Gospodarze", "away_team": "Goście",
             "main_referee": "Sędzia główny"}[missing]
    assert f"{label}: " in r.text and sheet(w, sa_id).status == "draft"


def test_the_assistants_are_optional(w):
    sa_id = complete_standalone(w)
    edit(w, "ref", sa_id, assistant_referees="")
    submit(w, sa_id)
    assert sheet(w, sa_id).status == "submitted"


def test_a_standalone_sheet_needs_three_rows_of_text(w):
    sa_id = new_standalone(w)
    edit(w, "ref", sa_id, **HEADER, **ANSWERS)
    add_manual_rows(w, sa_id, count=2)
    r = submit(w, sa_id, expect=(422,))
    assert "Dodaj co najmniej 3 klipy — teraz jest ich 2." in r.text
    add_manual_rows(w, sa_id, count=1)
    submit(w, sa_id)
    sa = sheet(w, sa_id)
    assert sa.status == "submitted" and [r.name_label for r in sa.rows] == ["Faul 1", "Faul 2", "Faul 3"]


@pytest.mark.parametrize("blank,message", [("name", "nazwę klipu"), ("desc", "opis")])
def test_every_manual_row_needs_a_name_and_a_description(w, blank, message):
    sa_id = complete_standalone(w)
    row = sheet(w, sa_id).rows[1]
    edit(w, "ref", sa_id, **{f"{blank}_{row.id}": " "})
    r = submit(w, sa_id, expect=(422,))
    assert f"Klip 2: wpisz {message}." in r.text
    assert sheet(w, sa_id).status == "draft"


def test_manual_rows_are_added_removed_and_moved_like_clip_rows(w):
    sa_id = new_standalone(w)
    add_manual_rows(w, sa_id)
    first, second, third = [r.id for r in sheet(w, sa_id).rows]
    edit(w, "ref", sa_id, f"down:{first}")
    assert [r.id for r in sheet(w, sa_id).rows] == [second, first, third]
    edit(w, "ref", sa_id, f"remove:{second}")
    rows = sheet(w, sa_id).rows
    assert [r.id for r in rows] == [first, third] and [r.position for r in rows] == [0, 1]
    assert rows[0].name_label == "Faul 1" and rows[0].is_manual
    edit(w, "ref", sa_id, "manual")
    assert len(sheet(w, sa_id).rows) == 3


def test_a_clip_cannot_be_added_to_a_standalone_sheet(w):
    sa_id = new_standalone(w)
    r = edit(w, "ref", sa_id, f"add:{w.clips[0].id}", expect=(422,))
    assert "Tego klipu nie ma w tym meczu." in r.text and sheet(w, sa_id).rows == []


def test_manual_rows_keep_typed_text_through_other_row_actions(w):
    sa_id = new_standalone(w)
    edit(w, "ref", sa_id, "manual")
    row = sheet(w, sa_id).rows[0]
    edit(w, "ref", sa_id, "manual", **{f"time_{row.id}": "Q2, 1:00", f"name_{row.id}": "Kroki"})
    assert (sheet(w, sa_id).rows[0].time_label, sheet(w, sa_id).rows[0].name_label) == ("", "Kroki")


def test_a_match_sheet_gets_manual_rows_too_and_they_count_toward_the_minimum(w):
    sa_id = open_sheet(w)
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    assert 'id="sa-add-manual"' in page and 'id="sa-picker"' in page and 'name="league"' not in page
    edit(w, "ref", sa_id, **ANSWERS)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    edit(w, "ref", sa_id, f"add:{w.clips[1].id}")
    edit(w, "ref", sa_id, "manual")
    sa = sheet(w, sa_id)
    edit(w, "ref", sa_id, **{f"desc_{r.id}": "Opis" for r in sa.rows},
         **{f"time_{sa.rows[2].id}": "Mecz wyjazdowy, 4:10", f"name_{sa.rows[2].id}": "Zasłona"})
    assert [r.is_manual for r in sheet(w, sa_id).rows] == [False, False, True]
    submit(w, sa_id)
    assert sheet(w, sa_id).status == "submitted"


def test_two_clips_and_no_manual_row_still_fail_the_minimum(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    edit(w, "ref", sa_id, "manual")
    r = submit(w, sa_id, expect=(422,))
    assert "teraz jest ich 2" in r.text and "Klip 2: wpisz nazwę klipu." in r.text
    assert "czas z nagrania" not in r.text


def test_a_manual_row_is_never_overwritten_by_the_snapshot_refresh(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    edit(w, "ref", sa_id, "manual")
    manual = sheet(w, sa_id).rows[1]
    edit(w, "ref", sa_id, **{f"time_{manual.id}": "Turniej, 2:00", f"name_{manual.id}": "Własny klip"})
    w.clips[0].category_id = category_named(w.db, "osobisty")  # the refresh now has something to change
    w.db.commit()
    for _ in range(2):
        edit(w, "ref", sa_id)  # a plain save and a save that posts no time or name at all
    rows = sheet(w, sa_id).rows
    assert (rows[1].time_label, rows[1].name_label, rows[1].is_manual) == ("", "Własny klip", True)
    assert rows[0].name_label == w.clips[0].category_label and not rows[0].is_manual
    edit(w, "ref", sa_id, "up:%d" % manual.id)
    assert sheet(w, sa_id).rows[0].name_label == "Własny klip"


def test_a_row_of_a_deleted_clip_is_not_manual_and_a_manual_row_is_not_marked_deleted(w):
    sa_id = open_sheet(w)
    edit(w, "ref", sa_id, f"add:{w.clips[0].id}")
    edit(w, "ref", sa_id, "manual")
    w.db.delete(w.db.get(Clip, w.clips[0].id))
    w.db.commit()
    gone, manual = sheet(w, sa_id).rows
    assert (gone.clip_id, gone.is_manual, manual.clip_id, manual.is_manual) == (None, False, None, True)
    page = w.c["ref"].get(f"/self-assessments/{sa_id}/edit").text
    assert page.count("klip został usunięty") == 1 and page.count('name="time_') == 0
    assert page.count('name="name_') == 1
    before = (gone.time_label, gone.name_label)
    edit(w, "ref", sa_id, **{f"time_{gone.id}": "ignored", f"name_{gone.id}": "ignored"})
    assert (sheet(w, sa_id).rows[0].time_label, sheet(w, sa_id).rows[0].name_label) == before


def test_a_standalone_draft_is_private_and_a_submitted_one_is_open_to_coaches_and_admins(w):
    sa_id = complete_standalone(w)
    urls = (f"/self-assessments/{sa_id}", f"/self-assessments/{sa_id}/edit", f"/self-assessments/{sa_id}/pdf")
    for who in ("ref2", "outsider", "coach", "coach2", "admin"):
        for url in urls:
            assert w.c[who].get(url).status_code == 404, (who, url)
    submit(w, sa_id)
    for who in ("ref", "coach", "coach2", "admin"):
        assert w.c[who].get(urls[0]).status_code == 200, who
        assert w.c[who].get(urls[2]).status_code == 200, who
    for who in ("ref2", "outsider"):
        assert w.c[who].get(urls[0]).status_code == 404 and w.c[who].get(urls[2]).status_code == 404
    assert w.c["coach"].post(f"/self-assessments/{sa_id}/edit", data={"action": "save"}).status_code == 403
    assert w.c["ref"].post(f"/self-assessments/{sa_id}/edit", data={"action": "save"}).status_code == 403


def test_submitting_locks_a_standalone_sheet_and_an_admin_reopens_it(w):
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    edit(w, "ref", sa_id, expect=(403,), league="Zmiana")
    assert sheet(w, sa_id).league == HEADER["league"]
    post(w, "admin", f"/self-assessments/{sa_id}/reopen")
    sa = sheet(w, sa_id)
    assert sa.status == "draft" and sa.submitted_at is not None
    edit(w, "ref", sa_id, league="Zmiana")
    assert sheet(w, sa_id).league == "Zmiana"


def test_the_author_deletes_a_standalone_draft_and_lands_on_the_list(w):
    sa_id = new_standalone(w)
    post(w, "ref2", f"/self-assessments/{sa_id}/delete", expect=(404,))
    r = post(w, "ref", f"/self-assessments/{sa_id}/delete")
    assert r.headers["location"] == "/self-assessments" and w.db.query(SelfAssessment).count() == 0


def test_a_standalone_sheet_is_not_on_any_match_card_and_not_tied_to_a_match(w):
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    for who in ("ref", "coach", "admin"):
        assert f'data-self-assessment="{sa_id}"' not in w.c[who].get(f"/matches/{w.match.id}").text
    post(w, "admin", f"/matches/{w.match.id}/delete")
    assert sheet(w, sa_id).status == "submitted"  # deleting a match leaves it alone
    assert "samooceny sędziów" not in w.c["admin"].get(f"/matches/{w.other.id}/delete").text


def test_the_list_page_shows_the_typed_teams_and_date_marked_as_outside_the_system(w):
    sa_id = complete_standalone(w)
    mine = w.c["ref"].get("/self-assessments").text
    assert "07.11.2026 · Śląsk – Zagłębie" in mine and "spoza systemu" in mine and "Liga Amatorska" in mine
    assert w.c["coach"].get("/self-assessments").text.count(f'data-self-assessment="{sa_id}"') == 0
    submit(w, sa_id)
    coach = w.c["coach"].get("/self-assessments").text
    assert f'data-self-assessment="{sa_id}"' in coach and "Śląsk – Zagłębie" in coach and "spoza systemu" in coach
    draft = new_standalone(w, "ref2")
    assert "bez daty · A – B" in w.c["ref2"].get("/self-assessments").text and draft


def test_the_report_shows_the_typed_header_and_rows(w):
    sa_id = complete_standalone(w)
    edit(w, "ref", sa_id, home_team="<b>Śląsk</b>")
    html = w.c["ref"].get(f"/self-assessments/{sa_id}").text
    for expected in ("Liga Amatorska", "07.11.2026", "Zagłębie", "Jan Kowalski", "Ewa Nowak, Piotr Wiśniewski",
                     "Faul 2", "Opis 3", "&lt;b&gt;Śląsk&lt;/b&gt;"):
        assert expected in html, expected
    assert "Q1, 3:11" not in html
    assert "<b>Śląsk</b>" not in html and html.count('class="sa-block"') == 6
    assert "Odtwórz" not in html and "SZKIC" in html


def test_the_pdf_has_the_typed_header_and_a_name_without_a_function(w):
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    r = w.c["coach"].get(f"/self-assessments/{sa_id}/pdf")
    assert r.headers["content-disposition"] == 'attachment; filename="samoocena_2026-11-07_Slask-Zaglebie.pdf"'
    text = pdf_text(r.content)
    for expected in ("Liga Amatorska", "07.11.2026", "Zagłębie", "Jan Kowalski", "Ewa Nowak", "Faul 1", "Opis 2"):
        assert expected in text, expected


def test_the_file_name_of_an_unfinished_standalone_sheet_has_no_empty_parts(w):
    sa_id = new_standalone(w)
    assert self_assessments.pdf_filename(sheet(w, sa_id)) == "samoocena.pdf"
    edit(w, "ref", sa_id, home_team="Śląsk")
    assert self_assessments.pdf_filename(sheet(w, sa_id)) == "samoocena_Slask.pdf"


def test_submitting_a_standalone_sheet_notifies_the_coaches_of_the_authors_groups(w):
    sa_id = complete_standalone(w)
    assert notes(w) == []
    submit(w, sa_id)
    [note] = notes(w)
    assert (note.recipient_id, note.actor_id, note.match_id, note.self_assessment_id) == (
        w.u["coach"].id, w.u["ref"].id, None, sa_id)
    bell = w.c["coach"].get("/notifications").text
    assert "wysłana samoocena" in bell and "Śląsk – Zagłębie" in bell and "Osoba ref" in bell
    assert post(w, "coach", f"/notifications/{note.id}/open").headers["location"] == f"/self-assessments/{sa_id}"
    assert notify.unread_count(w.db, w.u["coach"].id) == 0


def test_the_digest_lists_a_standalone_sheet_under_matches_outside_the_system(w, mailbox):
    linked = open_sheet(w)
    complete(w, linked)
    submit(w, linked)
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    text = digest_text(w, w.u["coach"])
    assert "Mecze spoza systemu" in text
    assert "Wysłano samoocenę sędziego: Osoba ref (07.11.2026 · Śląsk – Zagłębie)" in text
    assert f"https://klipy.example.pl/self-assessments/{sa_id}" in text
    assert text.index("Mecz 28.10.2026") < text.index("Mecze spoza systemu")  # its own block, after the matches
    assert f"/self-assessments/{linked}" in text


def test_the_digest_switch_also_hides_a_standalone_sheet(w, mailbox):
    sa_id = complete_standalone(w)
    submit(w, sa_id)
    w.db.add(EmailPreference(user_id=w.u["coach"].id, digest_enabled=True, self_assessment_submitted=False))
    w.db.commit()
    text = digest_text(w, w.u["coach"])
    assert text is None or "spoza systemu" not in text
