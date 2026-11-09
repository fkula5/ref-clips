"""Qualifier assessment sheet: snapshots, visibility (404 instead of 403 for those who must not know),
validation without losing text, publishing, crew refresh, deletion and the admin element dictionary."""
import re
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import sheet_elements, sheets
from app.models import MatchOfficial, Sheet, SheetCell, SheetColumn, SheetElement, SheetRow
from tests.helpers import SHEET_ELEMENT_NAMES, make_match
from tests.test_sheet_elements import names


@pytest.fixture()
def world(db, make_client):
    """Match with CC = a referee account and U1 = a typed name; two coaches, an admin, a crew referee, an outsider."""
    crew_client, crew = make_client("referee", name="Sędzia Z Obsady")
    out_client, _ = make_client("referee", name="Sędzia Spoza Obsady")
    coach_client, coach = make_client("coach", name="Trener Autor")
    other_client, other = make_client("coach", name="Trener Inny")
    admin_client, _ = make_client("admin", name="Szef")
    match = make_match(db, officials=(("CC", crew), ("U1", "Kasia Żółć")), created_by=coach)
    return dict(crew=crew_client, crew_user=crew, outsider=out_client, coach=coach_client, coach_user=coach,
                other=other_client, other_user=other, admin=admin_client, match=match)


def open_sheet(w, who="coach"):
    r = w[who].post(f"/matches/{w['match'].id}/sheets", follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(re.search(r"/sheets/(\d+)/edit", r.headers["location"])[1])


def load(db, sheet_id) -> Sheet:
    db.expire_all()
    return db.get(Sheet, sheet_id)


def form(db, sheet_id, text="", **extra) -> dict:
    """Posted form: `text` in every comment field (and overall/recommendation), plus overrides by field name."""
    data = {k: text for k in sheets.form_values(load(db, sheet_id)) if k not in ("result", "difficulty")}
    return {"result": "", "difficulty": "", **data, **extra}


def publish(w, db, sheet_id, who="coach", **extra):
    data = form(db, sheet_id, difficulty="normalny", result="78:65", **extra)
    return w[who].post(f"/sheets/{sheet_id}/edit", data={**data, "action": "publish"}, follow_redirects=False)


def set_crew(db, match_id, *crew):
    """Replaces the crew of the match with (function, typed name) pairs."""
    db.query(MatchOfficial).filter_by(match_id=match_id).delete()
    db.add_all(MatchOfficial(match_id=match_id, function=f, name=n) for f, n in crew)
    db.commit()
    db.expire_all()


def cell_field(sheet, element, official):
    row = next(r for r in sheet.rows if r.name == element)
    col = next(c for c in sheet.columns if official in c.label)
    return sheets.cell_key(row, col)


# --- creating and the unique constraint -------------------------------------------------------
def test_open_creates_snapshot_once_and_reopens_the_same_sheet(world, db):
    first = open_sheet(world)
    assert open_sheet(world) == first   # opening again edits the existing sheet
    sheet = load(db, first)
    assert [r.name for r in sheet.rows] == SHEET_ELEMENT_NAMES
    assert [c.label for c in sheet.columns] == ["CC · Sędzia Z Obsady", "U1 · Kasia Żółć"]
    assert db.scalar(select(func.count()).select_from(SheetCell)) == 20 and sheet.status == "draft"
    assert open_sheet(world, "other") != first   # another coach gets their own sheet
    assert db.scalar(select(func.count()).select_from(Sheet)) == 2


def test_unique_constraint_decides_a_race_and_blocks_duplicates(world, db, monkeypatch):
    sheet, created = sheets.create(db, world["match"], world["coach_user"])
    db.commit()
    assert created
    with pytest.raises(IntegrityError):   # the database refuses a second sheet of the same coach
        db.add(Sheet(match_id=world["match"].id, coach_id=world["coach_user"].id))
        db.flush()
    db.rollback()
    real, lookups = sheets._own, iter([None])   # the first lookup misses: another request created the sheet meanwhile
    monkeypatch.setattr(sheets, "_own", lambda *a: next(lookups, 1) or real(*a))
    again, created = sheets.create(db, world["match"], world["coach_user"])
    assert again.id == sheet.id and not created
    assert db.scalar(select(func.count()).select_from(Sheet)) == 1


def test_match_without_crew_cannot_have_a_sheet(world, db):
    db.query(MatchOfficial).delete()
    db.commit()
    r = world["coach"].post(f"/matches/{world['match'].id}/sheets")
    assert r.status_code == 422 and "obsady" in r.text and db.query(Sheet).count() == 0


# --- visibility -------------------------------------------------------------------------------
@pytest.mark.parametrize("who,draft_status,published_status", [
    ("coach", 200, 200), ("other", 404, 200), ("admin", 404, 200), ("crew", 404, 200), ("outsider", 404, 404)])
def test_who_can_see_a_sheet(world, db, who, draft_status, published_status):
    sheet_id = open_sheet(world)
    assert world[who].get(f"/sheets/{sheet_id}").status_code == draft_status
    assert publish(world, db, sheet_id).status_code == 303
    assert world[who].get(f"/sheets/{sheet_id}").status_code == published_status


def test_a_hidden_sheet_looks_exactly_like_a_missing_one(world, db):
    sheet_id = open_sheet(world)
    publish(world, db, sheet_id)
    missing = world["outsider"].get("/sheets/99999")
    for method, url in (("get", f"/sheets/{sheet_id}"), ("get", f"/sheets/{sheet_id}/edit"),
                        ("post", f"/sheets/{sheet_id}/edit"), ("get", f"/sheets/{sheet_id}/delete"),
                        ("post", f"/sheets/{sheet_id}/delete")):
        r = getattr(world["outsider"], method)(url)
        assert (r.status_code, r.text) == (missing.status_code, missing.text) == (404, missing.text), url
    assert load(db, sheet_id) is not None


def test_match_card_shows_only_what_the_user_may_see(world, db):
    sheet_id = open_sheet(world)
    page = lambda who: world[who].get(f"/matches/{world['match'].id}").text   # noqa: E731
    listed = lambda who: f'data-sheet="{sheet_id}"' in page(who)   # noqa: E731
    assert listed("coach") and "szkic" in page("coach") and "Wypełnij arkusz" not in page("coach")
    assert not listed("other") and "Wypełnij arkusz" in page("other")   # a draft is private
    for who in ("crew", "outsider", "admin"):
        assert not listed(who) and "Wypełnij arkusz" not in page(who), who
    assert 'id="arkusz"' not in page("outsider")   # no card at all: nothing hints at a sheet
    publish(world, db, sheet_id)
    for who in ("crew", "other", "admin", "coach"):
        assert listed(who) and "opublikowany" in page(who), who
    assert not listed("outsider") and 'id="arkusz"' not in page("outsider")


# --- saving: nothing typed is lost ---------------------------------------------------------------
@pytest.mark.parametrize("override,message", [
    ({"cell": "x" * 5001}, "najwyżej 5000 znaków (jest 5001)"),
    ({"result": "y" * 51}, "Wynik: najwyżej 50 znaków"),
    ({"difficulty": "bardzo"}, "Stopień trudności"),
])
def test_validation_error_rerenders_everything_typed(world, db, override, message):
    sheet_id = open_sheet(world)
    sheet = load(db, sheet_id)
    key = cell_field(sheet, "Mechanika", "CC")
    data = form(db, sheet_id, text="Ważna notatka", crew_note="Uwaga o parze", result="3:2")
    data[key] = override.pop("cell", "Długi tekst, którego nie wolno zgubić")
    data.update(override)
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={**data, "action": "save"})
    assert r.status_code == 422 and message in r.text
    assert data[key] in r.text and "Uwaga o parze" in r.text and r.text.count("Ważna notatka") >= 5
    assert 'data-unsaved="1"' in r.text   # the page knows the typed text is not stored yet
    sheet = load(db, sheet_id)
    assert sheet.crew_note == "" and sheet.result == ""   # nothing was stored


def test_save_stores_normalised_text_and_ignores_missing_fields(world, db):
    sheet_id = open_sheet(world)
    key = cell_field(load(db, sheet_id), "Mechanika", "CC")
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={key: "  Pierwsza\r\nDruga  ", "action": "save"},
                            follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/sheets/{sheet_id}/edit"
    _, row_id, column_id = key.split("_")
    assert db.get(SheetCell, (int(row_id), int(column_id))).text == "Pierwsza\nDruga"
    # a stale or partial form (fields missing) never wipes stored text
    world["coach"].post(f"/sheets/{sheet_id}/edit", data={"crew_note": "Nowa", "action": "save"})
    assert "Pierwsza\nDruga" in world["coach"].get(f"/sheets/{sheet_id}/edit").text


def test_save_flash_notice_is_shown_once(world, db):
    sheet_id = open_sheet(world)
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "save"})   # follows 303
    assert "Zapisano szkic." in r.text
    assert "Zapisano szkic." not in world["coach"].get(f"/sheets/{sheet_id}/edit").text


# --- publishing -------------------------------------------------------------------------------
def test_publishing_needs_a_difficulty_and_reports_empty_fields(world, db):
    sheet_id = open_sheet(world)
    key = cell_field(load(db, sheet_id), "Mechanika", "CC")
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "publish", key: "Tekst", "difficulty": ""})
    assert r.status_code == 422 and "Wybierz stopień trudności" in r.text and "Tekst" in r.text
    assert load(db, sheet_id).status == "draft"
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "publish", key: "Tekst", "difficulty": "trudny"})
    assert r.status_code == 200 and "Opublikowano arkusz. Puste pola: 24 z 25." in r.text   # 20 cells + 4 overall/recommendation + the note
    sheet = load(db, sheet_id)
    assert sheet.status == "published" and sheet.difficulty == "trudny" and not sheet.edited_after_publishing
    assert "trudny" in r.text and "Trener Autor" in r.text


def test_author_can_correct_a_published_sheet_and_the_change_is_marked(world, db):
    sheet_id = open_sheet(world)
    publish(world, db, sheet_id)
    sheet = load(db, sheet_id)
    sheet.published_at = datetime(2026, 7, 1, 22, 30)   # stored in UTC, shown in Polish time
    sheet.updated_at = sheet.published_at
    db.commit()
    assert "02.07.2026 00:30" in world["coach"].get(f"/sheets/{sheet_id}").text
    assert "zmieniono" not in world["coach"].get(f"/sheets/{sheet_id}").text
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"crew_note": "Poprawka", "action": "save"})
    assert r.status_code == 200 and "Zapisano zmiany" in r.text and "Poprawka" in r.text
    assert "zmieniono" in r.text
    # a published sheet keeps its difficulty
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"difficulty": "", "action": "save"})
    assert r.status_code == 422 and load(db, sheet_id).difficulty == "normalny"
    # an identical save is not a change
    sheet = load(db, sheet_id)
    before = sheet.updated_at
    world["coach"].post(f"/sheets/{sheet_id}/edit", data={"crew_note": "Poprawka", "action": "save"})
    assert load(db, sheet_id).updated_at == before


# --- snapshots ---------------------------------------------------------------------------------
def test_sheet_survives_dictionary_and_crew_changes(world, db):
    sheet_id = open_sheet(world)
    key = cell_field(load(db, sheet_id), "Mechanika", "CC")
    publish(world, db, sheet_id, **{key: "Dobra mechanika"})
    world["coach"].get(f"/sheets/{sheet_id}")   # consumes the one-time notice
    before = world["coach"].get(f"/sheets/{sheet_id}").text
    # the dictionary: rename, deactivate, add
    mech = db.scalar(select(SheetElement).where(SheetElement.name == "Mechanika"))
    sheet_elements.rename(db, mech, "Mechanika sędziowania")
    sheet_elements.set_active(db, db.scalar(select(SheetElement).where(SheetElement.name == "Przywództwo")), False)
    sheet_elements.create(db, "Nowy element")
    # the crew: the CC is replaced and the match renamed teams stay as they are
    set_crew(db, world["match"].id, ("CC", "Ktoś Zupełnie Inny"), ("U1", "Kasia Żółć"))
    after = world["coach"].get(f"/sheets/{sheet_id}").text
    assert after == before
    assert "Mechanika sędziowania" not in after and "Dobra mechanika" in after and "Sędzia Z Obsady" in after
    # a sheet started now reflects the new dictionary and crew
    new = load(db, open_sheet(world, "other"))
    assert "Mechanika sędziowania" in [r.name for r in new.rows] and "Przywództwo" not in [r.name for r in new.rows]
    assert "Nowy element" in [r.name for r in new.rows] and new.columns[0].official_name == "Ktoś Zupełnie Inny"


def test_draft_crew_refresh_adds_columns_and_never_drops_text(world, db):
    sheet_id = open_sheet(world)
    sheet = load(db, sheet_id)
    mech_cc = cell_field(sheet, "Mechanika", "CC")
    mech_u1 = cell_field(sheet, "Mechanika", "U1")
    world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "save", mech_cc: "Tekst CC"})   # CC has text; U1 empty
    set_crew(db, world["match"].id, ("CC", "Nowy Sędzia"), ("U2", "Trzeci"))
    page = world["coach"].get(f"/sheets/{sheet_id}/edit").text
    assert "Obsada meczu zmieniła się" in page and "Odśwież obsadę" in page
    r = world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "refresh", mech_u1: "Wpisane tuż przed odświeżeniem"})
    sheet = load(db, sheet_id)
    labels = [c.label for c in sheet.columns]
    # the typed text was saved first, so the U1 column kept it and stayed; CC text stayed too (that official left)
    assert "Odświeżono obsadę" in r.text and "Zostawiono kolumnę CC · Sędzia Z Obsady" in r.text
    assert labels[:2] == ["CC · Nowy Sędzia", "U2 · Trzeci"] or "CC · Nowy Sędzia" in labels
    assert "CC · Sędzia Z Obsady" in labels and "U1 · Kasia Żółć" in labels
    texts = [c.text for row in sheet.rows for c in row.cells]
    assert "Tekst CC" in texts and "Wpisane tuż przed odświeżeniem" in texts
    # once the leftover columns are emptied, a refresh removes them
    data = {k: "" for k in sheets.form_values(sheet) if k.startswith(("cell_", "overall_", "recommendation_"))}
    world["coach"].post(f"/sheets/{sheet_id}/edit", data={**data, "action": "refresh"})
    assert [c.label for c in load(db, sheet_id).columns] == ["CC · Nowy Sędzia", "U2 · Trzeci"]
    assert db.scalar(select(func.count()).select_from(SheetCell)) == 20   # 10 rows x 2 columns, nothing orphaned


def test_published_sheet_has_no_crew_refresh(world, db):
    sheet_id = open_sheet(world)
    publish(world, db, sheet_id)
    set_crew(db, world["match"].id, ("CC", "Nowy Sędzia"))
    page = world["coach"].get(f"/sheets/{sheet_id}/edit").text
    assert "Odśwież obsadę" not in page
    world["coach"].post(f"/sheets/{sheet_id}/edit", data={"action": "refresh"})
    assert [c.label for c in load(db, sheet_id).columns] == ["CC · Sędzia Z Obsady", "U1 · Kasia Żółć"]


# --- editing and deleting by others ----------------------------------------------------------------
def test_only_the_author_edits_and_deletion_rules(world, db):
    sheet_id = open_sheet(world)
    publish(world, db, sheet_id)
    for who in ("other", "admin", "crew"):   # may see it, may not edit it
        assert world[who].get(f"/sheets/{sheet_id}/edit").status_code == 403, who
        assert world[who].post(f"/sheets/{sheet_id}/edit", data={"crew_note": "Cudze", "action": "save"}).status_code == 403
    assert world["coach"].get(f"/sheets/{sheet_id}/delete").status_code == 403   # author, but already published
    assert world["coach"].post(f"/sheets/{sheet_id}/delete").status_code == 403
    assert load(db, sheet_id).crew_note == ""
    r = world["admin"].post(f"/sheets/{sheet_id}/delete")   # admin may delete at any time
    assert r.status_code == 200 and "Usunięto arkusz" in r.text and db.query(Sheet).count() == 0


def test_author_deletes_a_draft_after_confirmation_and_match_delete_cascades(world, db):
    sheet_id = open_sheet(world)
    assert "Tak, usuń arkusz" in world["coach"].get(f"/sheets/{sheet_id}/delete").text
    assert world["other"].post(f"/sheets/{sheet_id}/delete").status_code == 404   # not their draft
    assert world["admin"].get(f"/sheets/{sheet_id}/delete").status_code == 200    # admin: any time, even a draft
    assert world["coach"].post(f"/sheets/{sheet_id}/delete").status_code == 200
    assert db.query(Sheet).count() == db.query(SheetRow).count() == db.query(SheetCell).count() == 0
    open_sheet(world)
    assert world["admin"].post(f"/matches/{world['match'].id}/delete", follow_redirects=False).status_code == 303
    assert db.query(Sheet).count() == db.query(SheetColumn).count() == db.query(SheetCell).count() == 0


@pytest.mark.parametrize("method,url", [("post", "/matches/{m}/sheets"), ("post", "/sheets/{s}/edit"),
                                        ("post", "/sheets/{s}/delete"), ("post", "/admin/sheet-elements")])
def test_state_changing_routes_require_csrf(world, db, method, url):
    sheet_id = open_sheet(world)
    who = "admin" if "admin" in url else "coach"
    r = getattr(world[who], method)(url.format(m=world["match"].id, s=sheet_id), headers={"X-CSRF-Token": ""})
    assert r.status_code == 403 and "CSRF" in r.text
    assert load(db, sheet_id) is not None


# --- admin: the element dictionary -------------------------------------------------------------------
def test_used_element_can_only_be_deactivated(client, world, db):
    open_sheet(world)
    element = db.scalar(select(SheetElement).where(SheetElement.name == "Mechanika"))
    r = client.post(f"/admin/sheet-elements/{element.id}/delete")
    assert r.status_code == 409 and "jest użyty w arkuszach (1)" in r.text
    assert "Mechanika" in names(db)
    client.post(f"/admin/sheet-elements/{element.id}/active", data={"active": "0"})
    assert db.query(SheetRow).filter(SheetRow.name == "Mechanika").count() == 1   # the sheet still has it


def test_published_sheet_protects_the_match_from_its_creator_but_not_from_an_admin(world, db, make_client):
    creator_client, creator = make_client("referee", name="Sędzia Twórca")
    world["match"].created_by = creator.id
    db.commit()
    match_id = world["match"].id
    other_draft = open_sheet(world, "other")
    assert "arkusze oceny" not in creator_client.get(f"/matches/{match_id}/delete").text    # a draft stays hidden
    assert publish(world, db, open_sheet(world)).status_code == 303
    assert creator_client.get(f"/matches/{match_id}/delete").status_code == 403
    assert world["admin"].get(f"/matches/{match_id}/delete").status_code == 200
    assert load(db, other_draft) is not None
