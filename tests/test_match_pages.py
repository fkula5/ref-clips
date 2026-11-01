"""Strona meczu, potwierdzenie usunięcia, podpowiedzi lig, błędy w formularzach i strona błędu."""
from datetime import datetime

from sqlalchemy import select

from app.models import Clip, Match, PeriodMark, User, Video
from tests.helpers import make_match, make_ready_video, make_user

BASE = {"date": "2026-10-28", "level": "II liga", "team_a_name": "Legia", "team_a_color": "białe",
        "team_b_name": "Wisła", "team_b_color": "ciemne"}


# --- strona meczu -------------------------------------------------------------------------
def test_match_detail_header(make_client, db):
    client, me = make_client("coach", name="Trener Tomasz")
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    match = make_match(db, officials=(("CC", ref), ("U1", "Ewa Druga"), ("U2", me)), created_by=me)
    match.team_a_color, match.team_b_color = "czerwone", "granatowe"
    db.commit()
    page = client.get(f"/matches/{match.id}").text
    for text in ("28.10.2026", "II liga", "Legia", "Wisła", "(czerwone)", "(granatowe)",
                 "Dodał(a)", "Trener Tomasz", "Rafał Sędzia", "Ewa Druga", "bez konta", "to Ty"):
        assert text in page, text
    assert "background: #d32f2f" in page and "background: #1a2a5a" in page      # kolory strojów
    assert page.count('class="has-account"') == 2                              # konta: Rafał i ja
    assert "<h2 id=\"nagrania\">Nagrania</h2>" in page and 'id="klipy"' in page
    assert 'id="komentarze"' in page                                            # miejsce na segment 6


def test_match_detail_buttons_depend_on_permissions(make_client, db):
    owner_client, owner = make_client("coach")
    other_client, _ = make_client("coach")
    admin_client, _ = make_client("admin")
    match = make_match(db, created_by=owner)
    url = f"/matches/{match.id}"
    for client, visible in ((owner_client, True), (admin_client, True), (other_client, False)):
        page = client.get(url).text
        assert (f'href="{url}/edit"' in page) is visible
        assert (f'href="{url}/delete"' in page) is visible


def test_match_detail_lists_clips_with_period_and_undescribed_mark(client, db):
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    match = make_match(db, officials=(("CC", ref), ("U1", "Ewa Druga")))
    video = make_ready_video(db, match)
    db.add_all([PeriodMark(video_id=video.id, period="Q1", time_sec=60),
                PeriodMark(video_id=video.id, period="Q2", time_sec=660)])
    done = Clip(match_id=match.id, video_id=video.id, time_sec=660 + 252, official_id=match.official("CC").id,
                described_at=datetime(2026, 10, 29), status="cut")
    pending = Clip(match_id=match.id, video_id=video.id, time_sec=100, official_id=match.official("U1").id)
    team = Clip(match_id=match.id, video_id=video.id, time_sec=30, whole_team=True, described_at=datetime(2026, 10, 29))
    db.add_all([done, pending, team])
    db.commit()
    page = client.get(f"/matches/{match.id}").text
    assert "Klipy (3, nieopisane: 1)" in page
    assert "Q2 · 4:12" in page                       # czas od początku kwarty (czas nagrania)
    assert "Q1 · 0:40" in page and "nieustalona" in page   # klip przed pierwszym znacznikiem
    assert "cały zespół" in page and "Rafał Sędzia" in page
    assert page.count("nieopisany") == 1             # tylko ten bez described_at
    for c in (done, pending, team):
        assert f'href="/clips/{c.id}"' in page
    assert "to nie jest zegar meczowy" in page


def test_match_detail_without_clips(client, db):
    match = make_match(db)
    assert "nie ma jeszcze klipów" in client.get(f"/matches/{match.id}").text


def test_match_detail_shows_state(client, db):
    match = make_match(db)
    assert "brak nagrania" in client.get(f"/matches/{match.id}").text
    make_ready_video(db, match)
    assert "brak znaczników kwart" in client.get(f"/matches/{match.id}").text


# --- usuwanie: potwierdzenie ----------------------------------------------------------------
def test_delete_confirmation_shows_counts_and_deletes_only_on_post(client, db):
    match = make_match(db)
    match_id = match.id
    v1, v2 = make_ready_video(db, match), make_ready_video(db, match)
    db.add_all([Clip(match_id=match.id, video_id=v1.id, time_sec=1, described_at=datetime(2026, 10, 29)),
                Clip(match_id=match.id, video_id=v1.id, time_sec=2),
                Clip(match_id=match.id, video_id=v2.id, time_sec=3)])
    db.commit()
    r = client.get(f"/matches/{match.id}/delete")
    assert r.status_code == 200
    assert "nagrania: <strong>2</strong>" in r.text and "klipy: <strong>3</strong>" in r.text
    assert "nieopisane: 2" in r.text
    assert f'action="/matches/{match.id}/delete"' in r.text and f'href="/matches/{match.id}"' in r.text
    assert db.get(Match, match_id) is not None                  # samo wejście na stronę nic nie usuwa
    assert client.post(f"/matches/{match_id}/delete", follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(Match, match_id) is None and db.query(Clip).count() == 0 and db.query(Video).count() == 0


def test_delete_confirmation_without_recordings(client, db):
    match = make_match(db)
    r = client.get(f"/matches/{match.id}/delete")
    assert "nagrania: <strong>0</strong>" in r.text and "klipy: <strong>0</strong>" in r.text
    assert "nieopisane" not in r.text


def test_delete_confirmation_permissions(make_client, db):
    owner_client, owner = make_client("referee")
    other_client, _ = make_client("coach")
    member_client, member = make_client("referee")
    match = make_match(db, officials=(("CC", owner), ("U1", member)), created_by=owner)
    assert owner_client.get(f"/matches/{match.id}/delete").status_code == 200
    assert other_client.get(f"/matches/{match.id}/delete").status_code == 403
    assert member_client.get(f"/matches/{match.id}/delete").status_code == 403   # w obsadzie, ale nie właściciel
    assert owner_client.get("/matches/9999/delete").status_code == 404


# --- podpowiedzi lig ------------------------------------------------------------------------
def test_level_datalist_has_distinct_levels_alphabetically(client, db):
    for level in ("II liga", "Juniorzy U18", "II liga", "Ekstraklasa", "", "Żaki"):
        make_match(db).level = level
        db.commit()
    page = client.get("/matches/new").text
    assert 'list="levels"' in page
    options = page.split('<datalist id="levels">')[1].split("</datalist>")[0]
    import re
    assert re.findall(r'<option value="([^"]+)">', options) == ["Ekstraklasa", "II liga", "Juniorzy U18", "Żaki"]
    assert 'name="level" list="levels"' in client.get("/matches/new").text


def test_level_datalist_is_available_in_edit_form_and_empty_without_matches(client, db):
    assert '<datalist id="levels"></datalist>' in client.get("/matches/new").text
    match = make_match(db)
    assert '<option value="II liga">' in client.get(f"/matches/{match.id}/edit").text


def test_known_levels_service(db):
    from app import services
    for level in ("b liga", "A liga", "a liga", " B liga "):
        db.add(Match(date=datetime(2026, 1, 1).date(), level=level))
    db.commit()
    assert services.known_levels(db) == ["A liga", "a liga", "B liga", "b liga"]


# --- błędy w formularzu meczu: komunikat i zachowane wartości ----------------------------------
def test_match_form_validation_error_keeps_values(client, db):
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    data = {**BASE, "date": "", "level": "Liga testowa", "team_a_color": "zielone",
            "cc_user": str(ref.id), "u1_name": "Ewa Druga", "u2_name": "Kuba"}
    r = client.post("/matches", data=data)
    assert r.status_code == 422
    assert 'role="alert">Podaj poprawną datę meczu.' in r.text
    for fragment in ('value="Liga testowa"', 'value="Legia"', 'value="zielone"', 'value="Wisła"',
                     f'<option value="{ref.id}" selected>', 'value="Ewa Druga"', 'value="Kuba"'):
        assert fragment in r.text, fragment
    assert db.query(Match).count() == 0


def test_match_form_missing_position_and_too_long_field(client, db):
    r = client.post("/matches", data={**BASE, "cc_name": "Jan Pierwszy"})
    assert r.status_code == 422 and "brakuje pozycji U1" in r.text and 'value="Jan Pierwszy"' in r.text
    r = client.post("/matches", data={**BASE, "level": "x" * 101, "cc_name": "A B", "u1_name": "C D"})
    assert r.status_code == 422 and "Liga: najwyżej 100 znaków" in r.text


def test_edit_form_validation_error_keeps_values_and_old_data_in_db(client, db):
    match = make_match(db)
    r = client.post(f"/matches/{match.id}", data={**BASE, "level": "Nowa liga", "date": "32.13.2026",
                                                    "cc_name": "A B", "u1_name": "C D"})
    assert r.status_code == 422 and "Podaj poprawną datę" in r.text
    assert 'value="Nowa liga"' in r.text and f'action="/matches/{match.id}"' in r.text
    db.expire_all()
    stored = db.get(Match, match.id)
    assert stored.level == "II liga" and stored.date.isoformat() == "2026-10-28"


def test_referee_not_in_crew_gets_form_with_message_not_bare_error(make_client, db):
    client, ref = make_client("referee", name="Rafał Sędzia")
    data = {**BASE, "level": "Liga testowa", "cc_name": "Jan Pierwszy", "u1_name": "Ewa Druga"}
    r = client.post("/matches", data=data)
    assert r.status_code == 403                                   # reguła zostaje, ale z formularzem
    assert "Jako sędzia możesz zapisać tylko mecz, w którego obsadzie jesteś" in r.text
    assert '<form method="post" action="/matches"' in r.text
    assert 'value="Liga testowa"' in r.text and 'value="Jan Pierwszy"' in r.text
    assert db.query(Match).count() == 0


def test_referee_editing_own_match_cannot_drop_self_form_shows_message(make_client, db):
    client, ref = make_client("referee", name="Rafał Sędzia")
    match = make_match(db, officials=(("CC", ref), ("U1", "Ewa Druga")), created_by=ref)
    r = client.post(f"/matches/{match.id}", data={**BASE, "cc_name": "Jan Pierwszy", "u1_name": "Ewa Druga"})
    assert r.status_code == 403 and "Jako sędzia możesz zapisać tylko mecz" in r.text
    assert 'value="Jan Pierwszy"' in r.text
    db.expire_all()
    assert db.get(Match, match.id).official("CC").user_id == ref.id


# --- błędy w formularzach panelu admina ---------------------------------------------------------
def test_admin_new_account_error_keeps_entered_values(admin, db):
    make_user(db, ["coach"], email="zajety@example.com", name="Zajęty")
    r = admin[0].post("/admin/users", data={"name": "Nowy Użytkownik", "email": "ZAJETY@example.com",
                                            "roles": ["coach", "admin"]})
    assert r.status_code == 422 and 'role="alert">Konto z tym adresem e-mail już istnieje.' in r.text
    assert 'name="name" required maxlength="100" value="Nowy Użytkownik"' in r.text
    assert 'value="ZAJETY@example.com"' in r.text
    assert 'value="coach" checked' in r.text and 'value="admin" checked' in r.text
    assert 'value="referee" checked' not in r.text.split("<h2>Konta")[0]    # domyślnie zaznaczony tylko na czystym formularzu


def test_admin_new_account_form_defaults_to_referee(admin):
    page = admin[0].get("/admin/users").text.split("<h2>Konta")[0]
    assert 'value="referee" checked' in page and 'value="coach" checked' not in page


def test_admin_role_change_error_keeps_chosen_roles(admin, db):
    admin_user = admin[1]
    other = make_user(db, ["coach"], email="c@example.com", name="Cezary Trener")
    r = admin[0].post(f"/admin/users/{admin_user.id}/roles", data={"roles": ["coach"]})   # zabiera sobie admina
    assert r.status_code == 422 and "co najmniej jeden aktywny administrator" in r.text
    row = next(x for x in r.text.split("<tr") if "admin@example.com" in x)
    assert 'value="coach" checked' in row and 'value="admin" checked' not in row   # nie wraca do zapisanych ról
    db.expire_all()
    assert "admin" in db.get(User, admin_user.id).roles and other.roles == {"coach"}


# --- strona błędu przy nawigacji ----------------------------------------------------------------
def test_error_page_for_missing_match_has_text_and_links(client):
    r = client.get("/matches/9999", headers={"Accept": "text/html", "Referer": "http://testserver/clips"})
    assert r.status_code == 404
    assert "<h1>Nie znaleziono</h1>" in r.text and "Nie ma takiego meczu" in r.text
    assert 'href="/clips"' in r.text and 'href="/"' in r.text           # powrót + lista meczów


def test_error_page_ignores_foreign_referer(client):
    r = client.get("/matches/9999", headers={"Accept": "text/html", "Referer": "http://evil.example/x"})
    assert "evil.example" not in r.text and "Wróć</a>" not in r.text and 'href="/"' in r.text


def test_error_page_403_for_forbidden_navigation(make_client, db):
    client, _ = make_client("referee")
    match = make_match(db, created_by=None)
    r = client.get(f"/matches/{match.id}/edit", headers={"Accept": "text/html"})
    assert r.status_code == 403 and "<h1>Brak dostępu</h1>" in r.text and "Brak uprawnień" in r.text


def test_unknown_page_and_bad_id_in_browser(client):
    r = client.get("/no/such/page", headers={"Accept": "text/html"})
    assert r.status_code == 404 and "Nie ma takiej strony" in r.text and "Not Found" not in r.text
    r = client.get("/matches/abc", headers={"Accept": "text/html"})
    assert r.status_code == 422 and "<h1>Nieprawidłowe dane</h1>" in r.text


def test_api_errors_stay_json(client):
    r = client.get("/api/videos/abc/state")
    assert r.status_code == 422 and "detail" in r.json()
    assert client.get("/api/videos/9999/state").status_code == 404
