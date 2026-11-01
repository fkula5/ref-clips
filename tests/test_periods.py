"""Znaczniki początków kwart: następna kwarta wg deklaracji zawartości, walidacja kolejności,
panel w odtwarzaczu, baner braku znaczników i ostrzeżenie przy zmianie deklaracji."""
import json
import re

import pytest
from sqlalchemy import select

from app import services
from app.models import PeriodMark, Video
from tests.helpers import make_match, make_ready_video
from tests.test_markers import init_state


def pm(period, t):
    return PeriodMark(period=period, time_sec=t)


def ready(db, content, duration=4000.0, match=None):
    video = make_ready_video(db, match or make_match(db), duration=duration)
    video.content = content
    db.commit()
    return video


def set_mark(client, video, t, period=None):
    body = {"time_sec": t, **({"period": period} if period else {})}
    return client.post(f"/api/videos/{video.id}/marks", json=body)


# --- next_period wg deklaracji ---------------------------------------------------------------
@pytest.mark.parametrize("content,marked,expected", [
    ("full", [], "Q1"),
    ("full", ["Q1"], "Q2"),
    ("full", ["Q1", "Q3"], "Q2"),
    ("full", ["Q1", "Q2", "Q3", "Q4"], "OT1"),
    ("full", ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"], None),
    ("Q1,Q2", [], "Q1"),
    ("Q1,Q2", ["Q1"], "Q2"),
    ("Q3,Q4", [], "Q3"),
    ("Q3,Q4", ["Q3"], "Q4"),
    ("Q2,Q4", ["Q4"], "Q2"),
    ("Q3,Q4", ["Q3", "Q4"], None),
    ("Q3", [], "Q3"),
    ("Q3", ["Q3"], "Q3"),      # jedna kwarta: Q przesuwa automatyczny znacznik
    ("OT1", ["OT1"], "OT1"),
    (None, [], "Q1"),
])
def test_next_period_follows_content_declaration(content, marked, expected):
    assert services.next_period([pm(p, i * 10) for i, p in enumerate(marked)], content) == expected


def test_allowed_and_required_periods():
    assert services.allowed_periods("full") == ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"]
    assert services.allowed_periods("Q2,Q3") == ["Q2", "Q3"] and services.allowed_periods("Q4") == ["Q4"]
    assert services.required_periods("full") == ["Q1", "Q2", "Q3", "Q4"]
    assert services.required_periods("Q2,Q3") == ["Q2", "Q3"] and services.required_periods("Q4") == []


# --- API: kolejna kwarta, dozwolone kwarty, kolejność -----------------------------------------
def test_default_period_for_full_match_then_overtime(client, db):
    video = ready(db, "full")
    got = [set_mark(client, video, t).json()["period"] for t in (10, 1000, 2000, 3000, 3500)]
    assert got == ["Q1", "Q2", "Q3", "Q4", "OT1"]


def test_default_period_for_several_quarters_only_declared(client, db):
    video = ready(db, "Q2,Q3")
    assert set_mark(client, video, 10).json()["period"] == "Q2"
    state = set_mark(client, video, 900).json()
    assert state["period"] == "Q3" and state["next_period"] is None and state["missing_periods"] == []
    r = set_mark(client, video, 1500)       # wszystkie kwarty mają znaczniki
    assert r.status_code == 422 and "Wszystkie kwarty" in r.json()["detail"]


def test_single_quarter_mark_moves_the_automatic_one(client, db):
    match = make_match(db)
    video = ready(db, "Q3", match=match)
    video.marks.append(pm("Q3", 0.0))
    db.commit()
    state = set_mark(client, video, 95).json()   # bez podania kwarty: przesuwa Q3
    assert state["period"] == "Q3" and [(m["period"], m["time_sec"]) for m in state["marks"]] == [("Q3", 95)]
    assert state["single_period"] is True
    mark_id = state["marks"][0]["id"]
    r = client.delete(f"/api/marks/{mark_id}")   # jedyna kwarta pliku zawsze ma znacznik
    assert r.status_code == 409 and "przesuń" in r.json()["detail"]


@pytest.mark.parametrize("content,period", [("Q3", "Q1"), ("Q1,Q2", "Q3"), ("Q1,Q2", "OT1"), ("full", "OT4")])
def test_period_outside_declaration_is_refused(client, db, content, period):
    video = ready(db, content)
    r = set_mark(client, video, 100, period)
    assert r.status_code == 422
    assert db.scalar(select(PeriodMark)) is None
    if period != "OT4":
        assert "deklaracji" in r.json()["detail"]


def test_full_match_allows_q1_to_q4_and_ot1_to_ot3(client, db):
    video = ready(db, "full")
    for i, period in enumerate(["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"]):
        assert set_mark(client, video, 100 + i * 100, period).status_code == 200, period


def test_periods_must_be_in_chronological_order(client, db):
    video = ready(db, "full")
    assert set_mark(client, video, 1000, "Q2").status_code == 200
    r = set_mark(client, video, 500, "Q3")           # Q3 przed Q2
    assert r.status_code == 422 and "Q3 nie może zaczynać się przed Q2" in r.json()["detail"]
    r = set_mark(client, video, 1000, "Q3")          # ten sam czas
    assert r.status_code == 422
    r = set_mark(client, video, 1500, "Q1")          # Q1 po Q2
    assert r.status_code == 422 and "Q1 nie może zaczynać się po Q2" in r.json()["detail"]
    assert set_mark(client, video, 400, "Q1").status_code == 200
    assert set_mark(client, video, 1800, "Q3").status_code == 200
    # przesuwanie istniejącej kwarty też pilnuje kolejności
    assert set_mark(client, video, 2000, "Q2").status_code == 422
    assert set_mark(client, video, 300, "Q2").status_code == 422
    assert set_mark(client, video, 1200, "Q2").status_code == 200


def test_one_mark_per_period_and_time_must_be_inside_recording(client, db):
    video = ready(db, "full", duration=600)
    first = set_mark(client, video, 100, "Q1").json()
    again = set_mark(client, video, 150, "Q1").json()      # ustaw ponownie = przesunięcie
    assert [(m["period"], m["time_sec"]) for m in again["marks"]] == [("Q1", 150)]
    assert again["marks"][0]["id"] == first["marks"][0]["id"]
    assert len(db.scalars(select(PeriodMark)).all()) == 1
    assert set_mark(client, video, 9000, "Q2").status_code == 422


def test_period_marks_permissions(make_client, db):
    ref_client, ref = make_client("referee")
    video = ready(db, "full", match=make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć"))))
    outsider, _ = make_client("referee")
    assert set_mark(outsider, video, 10).status_code == 403
    assert set_mark(ref_client, video, 10).status_code == 200


def test_state_lists_periods_with_marks(client, db):
    video = ready(db, "Q1,Q2")
    set_mark(client, video, 20, "Q2")
    state = client.get(f"/api/videos/{video.id}/state").json()
    assert [(p["period"], p["required"], bool(p["mark"])) for p in state["periods"]] == [
        ("Q1", True, False), ("Q2", True, True)]
    assert state["missing_periods"] == ["Q1"] and state["next_period"] == "Q1"
    assert state["content_label"] == "kwarty Q1, Q2"


# --- baner braku znaczników ---------------------------------------------------------------------
def test_banner_on_match_page_until_marks_are_set(client, db):
    match = make_match(db)
    video = ready(db, "Q1,Q2", match=match)
    page = client.get(f"/matches/{match.id}").text
    assert 'id="marks-banner"' in page and "Ustaw początki kwart, żeby klipy miały kwartę i czas" in page
    assert f'href="/videos/{video.id}#poczatki-kwart"' in page and "brakuje: Q1, Q2" in page
    assert "brakuje: Q1, Q2" in client.get(f"/matches/{match.id}/videos-panel").text   # odświeżany panel
    set_mark(client, video, 10, "Q1")
    assert "brakuje: Q2" in client.get(f"/matches/{match.id}").text
    set_mark(client, video, 900, "Q2")
    assert 'id="marks-banner"' not in client.get(f"/matches/{match.id}").text


def test_no_banner_for_single_quarter_converting_or_purged_video(client, db):
    match = make_match(db)
    single = ready(db, "Q2", match=match)
    converting = ready(db, "full", match=match)
    converting.status = "processing"
    purged = ready(db, "full", match=match)
    purged.proxy_path, purged.purged_at = None, services.utcnow()
    db.commit()
    assert single.id and 'id="marks-banner"' not in client.get(f"/matches/{match.id}").text


def test_banner_data_in_player(client, db):
    video = ready(db, "Q1,Q2")
    page = client.get(f"/videos/{video.id}").text
    assert "Ustaw początki kwart, żeby klipy miały kwartę i czas" in page
    assert init_state(page)["missing_periods"] == ["Q1", "Q2"]
    set_mark(client, video, 10, "Q1")
    set_mark(client, video, 500, "Q2")
    assert init_state(client.get(f"/videos/{video.id}").text)["missing_periods"] == []


# --- zmiana deklaracji: ostrzeżenie przed usunięciem znaczników ------------------------------------
def edit(client, video, **form):
    return client.post(f"/videos/{video.id}/update", data=form, follow_redirects=False)


def marked_video(db):
    video = ready(db, "full")
    for period, t in (("Q1", 10), ("Q2", 900), ("Q3", 1800), ("Q4", 2700)):
        video.marks.append(pm(period, t))
    db.commit()
    return video


def periods_of(db, video):
    db.expire_all()
    return sorted(m.period for m in db.get(Video, video.id).marks)


def test_changing_declaration_warns_before_removing_marks(client, db):
    video = marked_video(db)
    r = edit(client, video, content_kind="multi", periods=["Q1", "Q2"])
    assert r.status_code == 200      # formularz z ostrzeżeniem, nic nie zapisano
    assert "zmieni znaczniki" in r.text
    assert "Q3 (początek w 30:00)" in r.text and "Q4 (początek w 45:00)" in r.text and "Q1 (początek" not in r.text
    assert periods_of(db, video) == ["Q1", "Q2", "Q3", "Q4"]
    assert db.get(Video, video.id).content == "full"
    token = re.search(r'name="confirm_marks" value="([^"]*)"', r.text).group(1)
    # inne potwierdzenie (np. po zmianie wyboru) nie wystarcza
    assert edit(client, video, content_kind="multi", periods=["Q1", "Q2", "Q3"], confirm_marks=token).status_code == 200
    assert periods_of(db, video) == ["Q1", "Q2", "Q3", "Q4"]
    r = edit(client, video, content_kind="multi", periods=["Q1", "Q2"], confirm_marks=token)
    assert r.status_code == 303
    assert periods_of(db, video) == ["Q1", "Q2"] and db.get(Video, video.id).content == "Q1,Q2"


def test_confirmation_cannot_be_forged_without_the_warning(client, db):
    video = marked_video(db)
    assert edit(client, video, content_kind="multi", periods=["Q1", "Q2"], confirm_marks="1").status_code == 200
    assert periods_of(db, video) == ["Q1", "Q2", "Q3", "Q4"]


def test_switching_to_one_quarter_warns_about_the_other_marks(client, db):
    video = marked_video(db)
    r = edit(client, video, content_kind="Q2")
    assert r.status_code == 200 and "Q1 (początek w 0:10)" in r.text and "Q4 (początek" in r.text
    assert "Q2 (początek" not in r.text          # znacznik Q2 zostaje
    token = re.search(r'name="confirm_marks" value="([^"]*)"', r.text).group(1)
    assert edit(client, video, content_kind="Q2", confirm_marks=token).status_code == 303
    db.expire_all()
    assert [(m.period, m.time_sec) for m in db.get(Video, video.id).marks] == [("Q2", 900)]


def test_no_warning_when_nothing_is_removed(client, db):
    video = marked_video(db)
    assert edit(client, video, content_kind="full", label="Zmieniona").status_code == 303   # bez zmian
    assert periods_of(db, video) == ["Q1", "Q2", "Q3", "Q4"]
    # automatyczny znacznik 0:00 pliku z jedną kwartą znika bez ostrzeżenia
    single = ready(db, "full")
    assert edit(client, single, content_kind="Q2").status_code == 303
    assert edit(client, single, content_kind="multi", periods=["Q3", "Q4"]).status_code == 303
    assert periods_of(db, single) == []


def test_edit_form_keeps_choices_while_warning(client, db):
    video = marked_video(db)
    r = edit(client, video, content_kind="multi", periods=["Q1", "Q2"], label="Etykieta X")
    assert 'value="Etykieta X"' in r.text and 'value="Q1" checked' in r.text and 'value="Q3" checked' not in r.text
    assert "Potwierdzam" in r.text


def test_plan_content_change_unit(db):
    video = marked_video(db)
    plan = services.plan_content_change(video, "Q2,Q3")
    assert [m.period for m in plan.removed] == ["Q1", "Q4"] and plan.needs_confirmation
    assert not services.plan_content_change(video, "full").needs_confirmation
    plan = services.plan_content_change(ready(db, "full"), "Q3")
    assert plan.add_default == "Q3" and not plan.removed
