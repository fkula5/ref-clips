from sqlalchemy import select

from app import leagues
from app.models import League, Match, SelfAssessment
from tests.helpers import make_league, make_match, make_user


def lg(db, name) -> League:
    db.expire_all()
    return db.scalar(select(League).where(League.name == name))


def names(db) -> list[str]:
    db.expire_all()
    return [league.name for league in leagues.ordered(db)]


def post(client, path, **data):
    return client.post(path, data=data)


def add(client, name):
    return post(client, "/admin/leagues", name=name)


def test_page_lists_leagues_with_usage_counts(client, db):
    make_league(db, "Ekstraklasa", active=False)
    make_match(db)
    make_match(db)
    page = client.get("/admin/leagues").text
    assert "<h1>Ligi</h1>" in page and 'href="/admin/leagues"' in page
    assert 'data-league="II liga"' in page and 'data-league="Ekstraklasa"' in page
    row = page.split('data-league="II liga"')[1].split("</tr>")[0]
    assert '<td data-label="Mecze">2</td>' in row and "aktywna" in row and "Usuń" not in row
    row = page.split('data-league="Ekstraklasa"')[1].split("</tr>")[0]
    assert '<td data-label="Mecze">0</td>' in row and "nieaktywna" in row and "Usuń" in row


def test_empty_list_message(client, db):
    db.query(League).delete()
    db.commit()
    assert "Brak lig" in client.get("/admin/leagues").text


def test_add_league_appends_and_trims(client, db):
    r = add(client, "  III   liga ")
    assert r.status_code == 200 and "Dodano ligę „III liga”" in r.text
    assert names(db) == ["II liga", "III liga"]
    assert [league.position for league in leagues.ordered(db)] == [10, 20]
    assert lg(db, "III liga").is_active


def test_name_validation_and_uniqueness_ignores_case_and_polish_letters(client, db):
    make_league(db, "Żaki")
    for name, fragment in [("", "Podaj nazwę"), ("   ", "Podaj nazwę"), ("x" * 101, "najwyżej 100"),
                           ("ii LIGA", "już istnieje"), ("zaki", "już istnieje"), (" ŻAKI ", "już istnieje")]:
        r = add(client, name)
        assert r.status_code in (409, 422) and fragment in r.text, name
    assert names(db) == ["II liga", "Żaki"]
    assert 'value="zaki"' in add(client, "zaki").text


def test_coach_may_manage_leagues(make_client, db):
    client, _ = make_client("coach")
    assert "Dodano ligę" in add(client, "Liga trenera").text
    league = lg(db, "Liga trenera")
    assert "Zapisano ligę „Liga trenera 2”" in post(client, f"/admin/leagues/{league.id}/update", name="Liga trenera 2").text
    post(client, f"/admin/leagues/{league.id}/active", active="0")
    assert not lg(db, "Liga trenera 2").is_active
    assert "Usunięto ligę" in post(client, f"/admin/leagues/{league.id}/delete").text
    assert lg(db, "Liga trenera 2") is None


def test_referee_cannot_change_leagues(make_client, db):
    client, _ = make_client("referee")
    assert client.get("/admin/leagues").status_code == 403
    assert add(client, "Nie").status_code == 403
    assert post(client, "/admin/leagues/1/delete").status_code == 403
    assert names(db) == ["II liga"]


def test_unknown_league_is_404(client):
    for path in ("update", "active", "move", "delete"):
        assert post(client, f"/admin/leagues/9999/{path}", name="x").status_code == 404


def test_rename_propagates_to_matches_and_standalone_self_assessments(client, db):
    user = make_user(db, ("referee",), email="s@example.com")
    league = lg(db, "II liga")
    first, second = make_match(db), make_match(db)
    other = make_match(db)
    other.level = "III liga"
    db.add_all([SelfAssessment(match_id=None, user_id=user.id, league="II liga"),
                SelfAssessment(match_id=None, user_id=user.id, league="Inna")])
    db.commit()
    r = post(client, f"/admin/leagues/{league.id}/update", name="  Druga   liga ")
    assert r.status_code == 200 and "Zapisano ligę „Druga liga” (zmieniono mecze: 2)" in r.text
    db.expire_all()
    assert [db.get(Match, m.id).level for m in (first, second, other)] == ["Druga liga", "Druga liga", "III liga"]
    assert sorted(s.league for s in db.query(SelfAssessment)) == ["Druga liga", "Inna"]
    assert names(db) == ["Druga liga"]


def test_rename_with_only_a_case_change_is_not_a_collision(client, db):
    match = make_match(db)
    league = lg(db, "II liga")
    assert "Zapisano ligę „II Liga”" in post(client, f"/admin/leagues/{league.id}/update", name="II Liga").text
    db.expire_all()
    assert names(db) == ["II Liga"] and db.get(Match, match.id).level == "II Liga"


def test_rename_validation_keeps_the_typed_name(client, db):
    league = lg(db, "II liga")
    r = post(client, f"/admin/leagues/{league.id}/update", name="")
    assert r.status_code == 422 and "Podaj nazwę ligi" in r.text
    r = post(client, f"/admin/leagues/{league.id}/update", name="y" * 101)
    assert r.status_code == 422 and "najwyżej 100" in r.text
    assert names(db) == ["II liga"]


def test_renaming_to_an_existing_league_needs_the_merge_confirmation(client, db):
    make_league(db, "2 liga")
    old = lg(db, "2 liga")
    match = make_match(db)
    match.level = "2 liga"
    db.commit()
    r = post(client, f"/admin/leagues/{old.id}/update", name="ii LIGA")
    assert r.status_code == 409 and "już istnieje" in r.text and 'value="ii LIGA"' in r.text
    db.expire_all()
    assert names(db) == ["II liga", "2 liga"] and db.get(Match, match.id).level == "2 liga"


def test_merge_moves_matches_and_standalone_sheets_and_deletes_the_renamed_league(client, db):
    user = make_user(db, ("referee",), email="s@example.com")
    make_league(db, "2 liga")
    make_league(db, "III liga")
    old = lg(db, "2 liga")
    moved = [make_match(db), make_match(db)]
    for match in moved:
        match.level = "2 liga"
    stays = make_match(db)
    stays.level = "III liga"
    db.add(SelfAssessment(match_id=None, user_id=user.id, league="2 liga"))
    db.commit()
    r = post(client, f"/admin/leagues/{old.id}/update", name="ii liga", merge="1")
    assert r.status_code == 200 and "Połączono z ligą „II liga” — przeniesiono mecze: 2." in r.text
    db.expire_all()
    assert names(db) == ["II liga", "III liga"]
    assert [x.position for x in leagues.ordered(db)] == [10, 20]
    assert [db.get(Match, m.id).level for m in (*moved, stays)] == ["II liga", "II liga", "III liga"]
    assert db.query(SelfAssessment).one().league == "II liga"


def test_merge_flag_without_a_collision_is_an_ordinary_rename(client, db):
    league = lg(db, "II liga")
    assert "Zapisano ligę „Nowa”" in post(client, f"/admin/leagues/{league.id}/update", name="Nowa", merge="1").text
    assert names(db) == ["Nowa"]


def test_delete_is_blocked_while_matches_use_the_league(client, db):
    make_match(db)
    league = lg(db, "II liga")
    r = post(client, f"/admin/leagues/{league.id}/delete")
    assert r.status_code == 409 and "jest użyta w meczach (1)" in r.text and "tylko dezaktywować" in r.text
    assert names(db) == ["II liga"]


def test_delete_unused_league_renumbers(client, db):
    make_league(db, "A")
    make_league(db, "B")
    assert "Usunięto ligę „A”" in post(client, f"/admin/leagues/{lg(db, 'A').id}/delete").text
    assert [(x.name, x.position) for x in leagues.ordered(db)] == [("II liga", 10), ("B", 20)]


def test_deactivate_and_activate(client, db):
    league = lg(db, "II liga")
    assert "Liga „II liga” jest teraz nieaktywna" in post(client, f"/admin/leagues/{league.id}/active", active="0").text
    assert not lg(db, "II liga").is_active and leagues.active_names(db) == []
    assert "jest teraz aktywna" in post(client, f"/admin/leagues/{league.id}/active", active="1").text
    assert leagues.active_names(db) == ["II liga"]


def test_deactivating_does_not_touch_matches(client, db):
    match = make_match(db)
    post(client, f"/admin/leagues/{lg(db, 'II liga').id}/active", active="0")
    db.expire_all()
    assert db.get(Match, match.id).level == "II liga"


def test_reorder_up_and_down_changes_the_form_order(client, db):
    make_league(db, "B")
    make_league(db, "C")
    c = lg(db, "C")
    post(client, f"/admin/leagues/{c.id}/move", direction="up")
    assert names(db) == ["II liga", "C", "B"]
    post(client, f"/admin/leagues/{c.id}/move", direction="up")
    post(client, f"/admin/leagues/{c.id}/move", direction="up")  # already first: stays
    assert names(db) == ["C", "II liga", "B"]
    post(client, f"/admin/leagues/{c.id}/move", direction="down")
    assert names(db) == ["II liga", "C", "B"]
    assert leagues.active_names(db) == ["II liga", "C", "B"]
    assert post(client, f"/admin/leagues/{c.id}/move", direction="sideways").status_code == 422
    assert [x.position for x in leagues.ordered(db)] == [10, 20, 30]


def test_confirm_attributes_are_json_strings(client, db):
    from tests.test_inline_js import EVIL, confirm_arguments
    make_league(db, EVIL)
    page = client.get("/admin/leagues").text
    assert f"Usunąć ligę „{EVIL}”?" in confirm_arguments(page)
    assert "<img src=x" not in page
