"""Logowanie, sesje, CSRF, zaproszenia, reset hasła i wymóg zalogowania."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import accounts, auth, config, security
from app.main import app
from app.models import AuthSession, Invite, LoginAttempt, User
from app.timeutil import utcnow
from tests.conftest import login_client
from tests.helpers import PASSWORD, make_match, make_user


def login_form(client):
    """Pobiera stronę logowania (ustawia ciasteczko CSRF) i zwraca token do formularza."""
    r = client.get("/login")
    assert r.status_code == 200
    return client.cookies.get(config.CSRF_COOKIE)


def do_login(client, email, password=PASSWORD, **extra):
    token = login_form(client)
    return client.post("/login", data={"email": email, "password": password, "csrf_token": token,
                                       **extra}, follow_redirects=False)


# --- logowanie ---------------------------------------------------------------------
def test_login_page_is_public(anon_client):
    r = anon_client.get("/login")
    assert r.status_code == 200 and "Logowanie" in r.text and 'name="csrf_token"' in r.text


def test_login_ok_sets_secure_cookie_and_hashes_token(anon_client, db):
    make_user(db, ["coach"], email="jan@example.com")
    r = do_login(anon_client, "  Jan@Example.com ")  # e-mail bez względu na wielkość liter i spacje
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert config.SESSION_COOKIE in cookie and "HttpOnly" in cookie
    assert "SameSite=lax" in cookie and "Secure" not in cookie  # lokalnie po http musi działać
    token = anon_client.cookies.get(config.SESSION_COOKIE)
    session = db.scalar(select(AuthSession))
    assert session.token_hash == security.hash_token(token) != token
    assert session.expires_at > utcnow() + timedelta(days=29)
    assert anon_client.get("/").status_code == 200


def test_cookie_secure_flag_is_configurable(anon_client, db, monkeypatch):
    make_user(db, email="jan@example.com")
    token = login_form(anon_client)  # ciasteczko CSRF jeszcze bez Secure (test działa po http)
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    r = anon_client.post("/login", data={"email": "jan@example.com", "password": PASSWORD,
                                         "csrf_token": token}, follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


def test_login_wrong_password_and_unknown_user_look_the_same(anon_client, db):
    make_user(db, email="jan@example.com")
    bad_pass = do_login(anon_client, "jan@example.com", "zle-haslo-123")
    unknown = do_login(anon_client, "nikt@example.com", "zle-haslo-123")
    assert bad_pass.status_code == unknown.status_code == 401
    assert "Nieprawidłowy e-mail lub hasło" in bad_pass.text and "Nieprawidłowy e-mail lub hasło" in unknown.text
    assert config.SESSION_COOKIE not in anon_client.cookies
    assert db.scalar(select(AuthSession)) is None


def test_inactive_user_cannot_log_in(anon_client, db):
    make_user(db, email="jan@example.com", active=False)
    assert do_login(anon_client, "jan@example.com").status_code == 401


def test_user_without_password_cannot_log_in(anon_client, db):
    make_user(db, email="jan@example.com", password=False)
    assert do_login(anon_client, "jan@example.com", "").status_code == 401


def test_login_throttled_per_account(anon_client, db):
    make_user(db, email="jan@example.com")
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        assert do_login(anon_client, "jan@example.com", "zle-haslo-123").status_code == 401
    # szósta próba jest odrzucona, nawet z poprawnym hasłem
    r = do_login(anon_client, "jan@example.com")
    assert r.status_code == 429 and "Zbyt wiele" in r.text
    assert db.query(LoginAttempt).count() == config.LOGIN_MAX_ATTEMPTS  # zablokowane próby nie przedłużają blokady
    # po upływie okna można się zalogować
    for attempt in db.scalars(select(LoginAttempt)):
        attempt.attempted_at = utcnow() - timedelta(minutes=config.LOGIN_WINDOW_MINUTES + 1)
    db.commit()
    assert do_login(anon_client, "jan@example.com").status_code == 303


def test_login_throttled_per_ip(anon_client, db):
    make_user(db, email="jan@example.com")
    for i in range(config.LOGIN_MAX_ATTEMPTS):
        do_login(anon_client, f"nikt{i}@example.com", "zle-haslo-123")
    assert do_login(anon_client, "jan@example.com").status_code == 429  # inny e-mail, ten sam adres IP


def test_throttle_ignores_other_ip(db):
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        db.add(LoginAttempt(email="jan@example.com", ip="1.1.1.1", attempted_at=utcnow()))
    db.commit()
    assert accounts.is_throttled(db, "jan@example.com", "2.2.2.2")  # to samo konto
    assert not accounts.is_throttled(db, "kto@example.com", "2.2.2.2")
    assert accounts.is_throttled(db, "kto@example.com", "1.1.1.1")  # ten sam IP


@pytest.mark.parametrize("target,expected", [
    ("/ok?a=1", "/ok?a=1"), ("/", "/"), ("/clips?match_id=3&x=y", "/clips?match_id=3&x=y"),
    ("/\t/evil.com", "/"), ("/\n/evil.com", "/"), ("/\r/evil.com", "/"), ("//evil.com", "/"),
    ("/\\evil.com", "/"), ("https://evil.com", "/"), ("http:evil.com", "/"), (" /x", "/"),
    ("/x ", "/"), ("\t/x", "/"), ("/\u00a0/evil.com", "/"), ("evil.com", "/"), ("", "/"),
    ("/a\x00b", "/"),
])
def test_safe_next(target, expected):
    from app.routers.auth import safe_next
    assert safe_next(target) == expected


def test_login_does_not_redirect_through_whitespace_trick(anon_client, db):
    make_user(db, email="jan@example.com")
    r = do_login(anon_client, "jan@example.com", next="/\t/evil.com")
    assert r.headers["location"] == "/"
    assert anon_client.get("/login?next=/%09/evil.com").text.count("evil.com") == 0


def test_successful_login_clears_failure_counter_for_that_email(anon_client, db):
    make_user(db, email="jan@example.com")
    for _ in range(config.LOGIN_MAX_ATTEMPTS - 1):
        do_login(anon_client, "jan@example.com", "zle-haslo-123")
    assert do_login(anon_client, "jan@example.com").status_code == 303
    assert db.query(LoginAttempt).filter_by(email="jan@example.com").count() == 0
    anon_client.cookies.delete(config.SESSION_COOKIE)
    assert do_login(anon_client, "jan@example.com", "zle-haslo-123").status_code == 401  # 1 błąd po sukcesie, bez blokady
    assert not accounts.is_throttled(db, "jan@example.com", "1.2.3.4")


def test_successful_login_keeps_ip_failures(db):
    make_user(db, email="jan@example.com")
    db.add(LoginAttempt(email="inny@example.com", ip="9.9.9.9", attempted_at=utcnow()))
    db.add(LoginAttempt(email="jan@example.com", ip="9.9.9.9", attempted_at=utcnow()))
    db.commit()
    accounts.authenticate(db, "jan@example.com", PASSWORD, "9.9.9.9")
    assert [a.email for a in db.scalars(select(LoginAttempt))] == ["inny@example.com"]


def test_login_redirects_only_to_local_next(anon_client, db):
    make_user(db, email="jan@example.com")
    assert do_login(anon_client, "jan@example.com", next="/clips?match_id=1").headers["location"] == "/clips?match_id=1"
    for evil in ("https://evil.example/", "//evil.example/x", "/\\evil.example"):
        anon_client.cookies.delete(config.SESSION_COOKIE)
        assert do_login(anon_client, "jan@example.com", next=evil).headers["location"] == "/"


def test_logout_ends_session(make_client, db):
    client, _ = make_client("coach")
    token = client.cookies.get(config.SESSION_COOKIE)
    assert client.get("/").status_code == 200
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert db.scalar(select(AuthSession).where(AuthSession.token_hash == security.hash_token(token))) is None
    client.cookies.set(config.SESSION_COOKIE, token)  # stary token po wylogowaniu nie działa
    assert client.get("/", follow_redirects=False).status_code == 303


def test_expired_session_is_rejected(make_client, db):
    client, _ = make_client("coach")
    session = db.scalar(select(AuthSession))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/api/status").status_code == 401


def test_session_is_refreshed_with_new_cookie(make_client, db):
    client, _ = make_client("coach")
    session = db.scalar(select(AuthSession))
    session.expires_at = utcnow() + timedelta(days=5)
    db.commit()
    r = client.get("/")
    assert config.SESSION_COOKIE in r.headers.get("set-cookie", "")
    db.refresh(session)
    assert session.expires_at > utcnow() + timedelta(days=29)
    # świeża sesja nie jest odnawiana przy każdym żądaniu
    assert config.SESSION_COOKIE not in client.get("/").headers.get("set-cookie", "")


def test_deactivated_user_loses_session(make_client, admin, db):
    client, user = make_client("coach")
    assert client.get("/").status_code == 200
    r = admin[0].post(f"/admin/users/{user.id}/active", data={"active": "0"})
    assert r.status_code == 200
    assert client.get("/api/status").status_code == 401
    assert db.scalar(select(AuthSession).where(AuthSession.user_id == user.id)) is None


# --- wymóg zalogowania --------------------------------------------------------------
def test_pages_redirect_to_login_and_api_returns_401(anon_client):
    r = anon_client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
    r = anon_client.get("/clips?match_id=3", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/clips%3Fmatch_id%3D3"
    r = anon_client.get("/api/status")
    assert r.status_code == 401 and r.json()["detail"]
    r = anon_client.get("/api/videos/1/state", follow_redirects=False)
    assert r.status_code == 401
    r = anon_client.post("/matches", data={"date": "2026-10-28"}, follow_redirects=False)
    assert r.status_code == 401
    r = anon_client.get("/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.status_code == 401 and r.headers["hx-redirect"] == "/login"


PUBLIC_PATHS = {"/login", "/set-password/{token}", "/health"}


def test_every_route_requires_login_except_public_ones(anon_client):
    """Przegląd wszystkich tras aplikacji bez sesji: poza logowaniem i statykami żadna nie
    może odpowiedzieć 200/4xx innym niż 401 ani przekierowaniem na /login."""
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if path in PUBLIC_PATHS:
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        for method in operations:
            r = anon_client.request(method.upper(), concrete, follow_redirects=False)
            assert r.status_code in (401, 303), f"{method} {path} -> {r.status_code}"
            if r.status_code == 303:
                assert r.headers["location"].startswith("/login"), f"{method} {path}"
            checked += 1
    assert checked > 25


def test_static_files_are_public(anon_client):
    assert anon_client.get("/static/app.css").status_code == 200
    assert anon_client.get("/static/vendor/htmx-2.0.4.min.js").status_code == 200  # HTMX lokalnie, bez CDN


def test_api_docs_are_not_exposed(anon_client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anon_client.get(path, follow_redirects=False).status_code == 404


# --- CSRF ---------------------------------------------------------------------------
def test_csrf_missing_or_wrong_token_is_rejected(make_client, db):
    client, _ = make_client("admin")
    good = client.headers.pop("X-CSRF-Token")
    match = make_match(db)
    url = f"/matches/{match.id}/delete"
    assert client.post(url).status_code == 403
    assert client.post(url, headers={"X-CSRF-Token": "zly-token"}).status_code == 403
    assert client.post(url, data={"csrf_token": "zly-token"}).status_code == 403
    assert client.post("/api/videos/1/marks", json={"time_sec": 1}).status_code == 403
    assert db.get(type(match), match.id) is not None
    # prawidłowy token w nagłówku (HTMX, fetch) albo w polu formularza
    assert client.post(url, headers={"X-CSRF-Token": good}, follow_redirects=False).status_code == 303
    db.expunge_all()  # sesja testu nie trzyma już usuniętego meczu
    match2 = make_match(db)
    assert client.post(f"/matches/{match2.id}/delete", data={"csrf_token": good},
                       follow_redirects=False).status_code == 303


def test_csrf_token_is_bound_to_session(make_client, db):
    a, _ = make_client("admin")
    b, _ = make_client("admin")
    match = make_match(db)
    r = a.post(f"/matches/{match.id}/delete", headers={"X-CSRF-Token": b.headers["X-CSRF-Token"]})
    assert r.status_code == 403


def test_csrf_login_form_requires_cookie_token(anon_client, db):
    make_user(db, email="jan@example.com")
    login_form(anon_client)
    r = anon_client.post("/login", data={"email": "jan@example.com", "password": PASSWORD})
    assert r.status_code == 403
    r = anon_client.post("/login", data={"email": "jan@example.com", "password": PASSWORD,
                                         "csrf_token": "cudzy"})
    assert r.status_code == 403
    assert config.SESSION_COOKIE not in anon_client.cookies


def test_forms_and_htmx_carry_csrf_token(make_client):
    client, _ = make_client("admin")
    token = client.headers["X-CSRF-Token"]
    page = client.get("/admin/users").text
    assert page.count(f'name="csrf_token" value="{token}"') >= 3
    assert f'hx-headers=\'{{"X-CSRF-Token": "{token}"}}\'' in page
    assert f'<meta name="csrf-token" content="{token}">' in page


# --- zaproszenia i reset hasła --------------------------------------------------------
def invite_link(admin_client, **form):
    r = admin_client.post("/admin/users", data={"roles": ["referee"], **form})
    assert r.status_code == 200, r.text
    return re.search(r'value="([^"]*/set-password/[^"]+)"', r.text).group(1)


def set_password(anon_client, link, password=PASSWORD, password2=None):
    path = "/" + link.split("/", 3)[3]
    anon_client.get(path)
    return anon_client.post(path, data={"password": password, "password2": password2 or password,
                                        "csrf_token": anon_client.cookies.get(config.CSRF_COOKIE)},
                            follow_redirects=False)


def test_invite_is_single_use(admin, anon_client, db):
    link = invite_link(admin[0], name="Nowy Sędzia", email="Nowy@Example.com")
    user = db.scalar(select(User).where(User.email == "nowy@example.com"))
    assert user.password_hash is None and user.roles == {"referee"}
    raw_token = link.rsplit("/", 1)[1]
    assert db.scalar(select(Invite)).token_hash == security.hash_token(raw_token) != raw_token  # w bazie tylko hash
    page = anon_client.get("/" + link.split("/", 3)[3])
    assert page.status_code == 200 and "Nowy Sędzia" in page.text
    r = set_password(anon_client, link)
    assert r.status_code == 303 and r.headers["location"] == "/login?ok=1"
    assert do_login(anon_client, "nowy@example.com").status_code == 303
    # drugie użycie tego samego linku
    assert anon_client.get("/" + link.split("/", 3)[3]).status_code == 410
    anon_client.cookies.clear()
    assert set_password(anon_client, link, "inne-haslo-12345").status_code == 410
    assert do_login(anon_client, "nowy@example.com", "inne-haslo-12345").status_code == 401


def test_invite_expires_after_seven_days(admin, anon_client, db):
    link = invite_link(admin[0], name="Nowy", email="nowy@example.com")
    invite = db.scalar(select(Invite))
    assert timedelta(days=6, hours=23) < invite.expires_at - utcnow() <= timedelta(days=7)
    invite.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert anon_client.get("/" + link.split("/", 3)[3]).status_code == 410
    assert set_password(anon_client, link).status_code == 410
    assert db.scalar(select(User).where(User.email == "nowy@example.com")).password_hash is None


def test_set_password_validation(admin, anon_client, db):
    link = invite_link(admin[0], name="Nowy", email="nowy@example.com")
    assert set_password(anon_client, link, "krotkie").status_code == 422
    assert set_password(anon_client, link, PASSWORD, "inne-haslo-12345").status_code == 422
    assert db.scalar(select(User).where(User.email == "nowy@example.com")).password_hash is None
    assert set_password(anon_client, link).status_code == 303  # link nadal działa po błędach


def test_set_password_requires_csrf_cookie(admin, anon_client):
    link = invite_link(admin[0], name="Nowy", email="nowy@example.com")
    path = "/" + link.split("/", 3)[3]
    r = anon_client.post(path, data={"password": PASSWORD, "password2": PASSWORD})
    assert r.status_code == 403


def test_unknown_invite_token(anon_client):
    assert anon_client.get("/set-password/niema-takiego").status_code == 410


def test_new_invite_invalidates_previous_one(admin, anon_client, db):
    first = invite_link(admin[0], name="Nowy", email="nowy@example.com")
    user = db.scalar(select(User).where(User.email == "nowy@example.com"))
    r = admin[0].post(f"/admin/users/{user.id}/invite")
    second = re.search(r'value="([^"]*/set-password/[^"]+)"', r.text).group(1)
    assert first != second
    assert anon_client.get("/" + first.split("/", 3)[3]).status_code == 410
    assert anon_client.get("/" + second.split("/", 3)[3]).status_code == 200


def test_password_reset_link(admin, anon_client, make_client, db):
    victim, user = make_client("coach", email="ofiara@example.com")
    assert victim.get("/").status_code == 200
    r = admin[0].post(f"/admin/users/{user.id}/invite")
    link = re.search(r'value="([^"]*/set-password/[^"]+)"', r.text).group(1)
    assert db.scalar(select(Invite)).purpose == "reset"
    assert set_password(anon_client, link, "nowe-haslo-98765").status_code == 303
    assert victim.get("/api/status").status_code == 401  # stare sesje wygasają po resecie
    assert do_login(anon_client, "ofiara@example.com", PASSWORD).status_code == 401
    assert do_login(anon_client, "ofiara@example.com", "nowe-haslo-98765").status_code == 303


def test_inactive_user_invite_does_not_work(admin, anon_client, db):
    link = invite_link(admin[0], name="Nowy", email="nowy@example.com")
    user = db.scalar(select(User).where(User.email == "nowy@example.com"))
    admin[0].post(f"/admin/users/{user.id}/active", data={"active": "0"})
    assert anon_client.get("/" + link.split("/", 3)[3]).status_code == 410
    assert admin[0].post(f"/admin/users/{user.id}/invite").status_code == 422


def test_no_public_registration(anon_client):
    for path in ("/register", "/signup", "/users/new"):
        assert anon_client.get(path, follow_redirects=False).status_code in (303, 404)
    assert anon_client.post("/admin/users", data={"email": "x@example.com", "name": "X",
                                                  "roles": ["admin"]}).status_code == 401


# --- create_admin ---------------------------------------------------------------------
def test_create_admin_command(db, monkeypatch, anon_client):
    from app import create_admin
    monkeypatch.setattr(create_admin, "init_db", lambda: None)
    argv = ["--email", "Szef@Example.com", "--name", "Szef Admin", "--password", "bardzo-dlugie-haslo"]
    assert create_admin.main(argv) == 0
    user = db.scalar(select(User).where(User.email == "szef@example.com"))
    assert user.roles == {"admin"} and user.is_active
    assert do_login(anon_client, "szef@example.com", "bardzo-dlugie-haslo").status_code == 303
    # ponowne uruchomienie: ustawia nowe hasło, nie dubluje konta
    assert create_admin.main([*argv[:-1], "inne-bardzo-dlugie-haslo"]) == 0
    db.expire_all()
    assert db.query(User).count() == 1
    assert security.verify_password(user.password_hash, "inne-bardzo-dlugie-haslo")
    assert create_admin.main([*argv[:-1], "krotkie"]) == 1


def test_create_admin_prompts(db, monkeypatch):
    from app import create_admin
    monkeypatch.setattr(create_admin, "init_db", lambda: None)
    answers = iter(["admin@example.com", "Ala Admin"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "hasło-z-pytania-123")
    assert create_admin.main([]) == 0
    assert db.scalar(select(User).where(User.email == "admin@example.com")).name == "Ala Admin"


# --- adres klienta za reverse proxy (Caddy) -----------------------------------------
def _request(headers: dict, peer="172.18.0.5"):
    from starlette.requests import Request
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                    "client": (peer, 5000)})


def test_client_ip_ignores_forwarded_header_without_trust_proxy(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    assert auth.client_ip(_request({"X-Forwarded-For": "203.0.113.7"})) == "172.18.0.5"


def test_client_ip_uses_address_added_by_proxy(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert auth.client_ip(_request({"X-Forwarded-For": "203.0.113.7"})) == "203.0.113.7"
    assert auth.client_ip(_request({"X-Forwarded-For": "2001:db8::1"})) == "2001:db8::1"


def test_client_ip_cannot_be_spoofed_by_client_prefix(monkeypatch):
    """Klient podstawia własny wpis; proxy dopisuje prawdziwy adres na końcu — liczy się ostatni."""
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert auth.client_ip(_request({"X-Forwarded-For": "1.2.3.4, 198.51.100.9"})) == "198.51.100.9"


def test_client_ip_falls_back_to_peer_for_missing_or_invalid_header(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert auth.client_ip(_request({})) == "172.18.0.5"
    assert auth.client_ip(_request({"X-Forwarded-For": "nie-adres"})) == "172.18.0.5"
