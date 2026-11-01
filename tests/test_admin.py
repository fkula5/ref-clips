"""Panel administratora: użytkownicy, role, dezaktywacja, linki."""
import re

from sqlalchemy import select

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
    assert "set-password/" not in admin[0].get("/admin/users").text  # po odświeżeniu linku nie widać


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
    # uprawnienia sumują się od razu (nowa rola działa na istniejącej sesji)
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
    # z drugim administratorem można
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
