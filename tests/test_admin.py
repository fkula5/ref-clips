import re

from sqlalchemy import func, select

from app.models import Invite, User
from tests.helpers import make_user


def test_users_list_shows_accounts_and_link_status(admin, db):
    make_user(db, ["coach"], email="a@example.com", name="Anna Trener")
    make_user(db, ["referee"], email="b@example.com", name="Bartek Nowy", password=False)
    make_user(db, ["referee"], email="c@example.com", name="Celina Stara", active=False)
    page = admin[0].get("/admin/users").text
    for text in ("Anna Trener", "Bartek Nowy", "czeka na ustawienie hasła", "nieaktywne", "Link resetu hasła"):
        assert text in page


def test_create_user_shows_link_once(admin, db):
    r = admin[0].post("/admin/users", data={"name": "  Jan   Kowalski ", "email": " Jan@Example.COM ",
                                            "roles": ["referee", "coach"]})
    assert r.status_code == 200
    assert re.search(r'value="http://testserver/set-password/[\w-]+"', r.text)
    user = db.scalar(select(User).where(User.email == "jan@example.com"))
    assert user.name == "Jan Kowalski" and user.roles == {"referee", "coach"} and user.password_hash is None
    assert db.scalar(select(Invite)).purpose == "activate"
    assert "set-password/" not in admin[0].get("/admin/users").text


def test_create_user_uses_public_url_setting(admin, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PUBLIC_URL", "https://klipy.example.pl")
    r = admin[0].post("/admin/users", data={"name": "X Y", "email": "x@example.com", "roles": ["coach"]})
    assert 'value="https://klipy.example.pl/set-password/' in r.text


def test_create_user_validation(admin, db):
    make_user(db, ["coach"], email="zajety@example.com")
    cases = [
        ({"name": "A B", "email": "zly-adres", "roles": ["coach"]}, "e-mail"),
        ({"name": "", "email": "a@example.com", "roles": ["coach"]}, "imię"),
        ({"name": "A B", "email": "a@example.com", "roles": []}, "rolę"),
        ({"name": "A B", "email": "a@example.com", "roles": ["superadmin"]}, "Nieznana rola"),
        ({"name": "A B", "email": "ZAJETY@example.com", "roles": ["coach"]}, "już istnieje"),
    ]
    for data, fragment in cases:
        r = admin[0].post("/admin/users", data=data)
        assert r.status_code == 422 and fragment in r.text, data
    assert db.query(User).filter(User.email != "admin@example.com").count() == 1


def test_update_roles_sums_multiple_roles(admin, make_client, db):
    client, user = make_client("referee")
    r = admin[0].post(f"/admin/users/{user.id}/roles", data={"roles": ["referee", "coach"]})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(User, user.id).roles == {"referee", "coach"}
    assert client.get("/matches/new").status_code == 200
    assert admin[0].post(f"/admin/users/{user.id}/roles", data={"roles": []}).status_code == 422


def test_cannot_remove_or_deactivate_last_admin(admin, db):
    client, me = admin
    r = client.post(f"/admin/users/{me.id}/roles", data={"roles": ["coach"]})
    assert r.status_code == 422 and "co najmniej jeden aktywny administrator" in r.text
    r = client.post(f"/admin/users/{me.id}/active", data={"active": "0"})
    assert r.status_code == 422
    db.expire_all()
    assert db.get(User, me.id).roles == {"admin"} and db.get(User, me.id).is_active
    other = make_user(db, ["admin"], email="drugi@example.com")
    assert client.post(f"/admin/users/{me.id}/roles", data={"roles": ["coach"]}).status_code == 200
    assert other.is_active


def test_deactivate_and_reactivate(admin, anon_client, make_client, db):
    client, user = make_client("coach", email="ktos@example.com")
    assert admin[0].post(f"/admin/users/{user.id}/active", data={"active": "0"}).status_code == 200
    db.expire_all()
    assert not db.get(User, user.id).is_active
    assert admin[0].post(f"/admin/users/{user.id}/active", data={"active": "1"}).status_code == 200
    db.expire_all()
    assert db.get(User, user.id).is_active
    assert admin[0].post("/admin/users/9999/active", data={"active": "0"}).status_code == 404


def test_inactive_user_not_offered_in_crew_form(admin, db):
    make_user(db, ["referee"], email="a@example.com", name="Aktywny Sędzia")
    make_user(db, ["referee"], email="n@example.com", name="Nieaktywny Sędzia", active=False)
    make_user(db, ["coach"], email="t@example.com", name="Tylko Trener")
    page = admin[0].get("/matches/new").text
    assert "Aktywny Sędzia" in page and "Nieaktywny Sędzia" not in page and "Tylko Trener" not in page


def _invite_count(db):
    return db.scalar(select(func.count()).select_from(Invite))


def test_create_user_redirects_and_link_is_shown_once_without_token_in_url(admin, db):
    client = admin[0]
    r = client.post("/admin/users", data={"name": "Jan Nowak", "email": "jan@example.com", "roles": ["coach"]},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/users"
    assert "set-password" not in r.text and "set-password" not in str(r.url)
    cookie = r.headers["set-cookie"].lower()
    assert "path=/admin/users" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "max-age=60" in cookie
    assert "set-password" not in r.headers["location"] and "?" not in r.headers["location"]
    first = client.get("/admin/users")
    assert first.status_code == 200 and re.search(r'value="http://testserver/set-password/[\w-]+"', first.text)
    assert first.headers["cache-control"] == "no-store" and "Jan Nowak" in first.text
    assert "refclips_invite=" in first.headers["set-cookie"] and "Max-Age=0" in first.headers["set-cookie"]
    again = client.get("/admin/users")
    assert "set-password/" not in again.text and "cache-control" not in again.headers
    assert _invite_count(db) == 1


def test_invite_link_works_and_new_invite_redirects_too(admin, make_client, anon_client, db):
    client = admin[0]
    _, user = make_client("referee", email="ref@example.com")
    r = client.post(f"/admin/users/{user.id}/invite", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/users" and "set-password" not in r.text
    page = client.get("/admin/users").text
    link = re.search(r'value="http://testserver(/set-password/[\w-]+)"', page).group(1)
    assert anon_client.get(link).status_code == 200
    assert "set-password/" not in client.get("/admin/users").text
    assert anon_client.get(link).status_code == 200


def test_invite_cookie_is_read_only_on_users_page_and_garbage_is_ignored(admin, db):
    client = admin[0]
    client.post("/admin/users", data={"name": "Jan Nowak", "email": "jan@example.com", "roles": ["coach"]},
                follow_redirects=False)
    # the cookie path is /admin/users: other admin pages do not get it, so they do not consume it
    assert "set-password/" not in client.get("/admin/categories").text
    assert re.search(r"set-password/[\w-]+", client.get("/admin/users").text)
    for value in ("<script>alert(1)</script>", "999.", f"9999.{'a' * 43}", "../../x"):
        client.cookies.set("refclips_invite", value, path="/admin/users")
        r = client.get("/admin/users")
        assert r.status_code == 200 and "set-password/" not in r.text and "<script>alert(1)</script>" not in r.text


def test_invite_for_inactive_or_validation_error_stays_without_redirect(admin, make_client, db):
    client = admin[0]
    _, user = make_client("referee", email="ref@example.com")
    admin[0].post(f"/admin/users/{user.id}/active", data={"active": "0"})
    r = client.post(f"/admin/users/{user.id}/invite", follow_redirects=False)
    assert r.status_code == 422 and "nieaktywne" in r.text
    r = client.post("/admin/users", data={"name": "", "email": "x@example.com", "roles": ["coach"]},
                    follow_redirects=False)
    assert r.status_code == 422 and "refclips_invite" not in r.headers.get("set-cookie", "")


def test_users_notice_is_flashed_once_and_html_is_escaped(admin, make_client, db):
    client = admin[0]
    _, user = make_client("referee", name="Ala <b>Kot</b>")
    r = client.post(f"/admin/users/{user.id}/roles", data={"roles": ["coach"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/users"
    page = client.get("/admin/users")
    assert 'id="admin-notice"' in page.text and "Zapisano role: Ala &lt;b&gt;Kot&lt;/b&gt;." in page.text
    assert "<b>Kot</b>" not in page.text
    assert 'id="admin-notice"' not in client.get("/admin/users").text
    client.cookies.set("refclips_flash", "%3Cscript%3Ealert(1)%3C%2Fscript%3E", path="/admin")
    page = client.get("/admin/users").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page


def test_admin_removing_own_admin_role_is_redirected_home(admin, db):
    client, me = admin
    make_user(db, ["admin"], email="drugi@example.com")
    r = client.post(f"/admin/users/{me.id}/roles", data={"roles": ["coach"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_user_post_routes_still_require_csrf(admin, db):
    client = admin[0]
    del client.headers["X-CSRF-Token"]
    assert client.post("/admin/users", data={"name": "A B", "email": "a@example.com", "roles": ["coach"]},
                       follow_redirects=False).status_code == 403
    assert _invite_count(db) == 0
