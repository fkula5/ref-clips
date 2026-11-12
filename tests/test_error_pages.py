from datetime import timedelta

from app import config
from app.models import AuthSession
from app.timeutil import utcnow

HTML = {"Accept": "text/html"}


def test_unknown_route_shows_the_header_and_matches_button_to_a_logged_in_user(make_client):
    client, user = make_client("coach", name="Cezary Trener")
    for path in ("/groups/1/coachs", "/no/such/page"):
        r = client.get(path, headers=HTML)
        assert r.status_code == 404 and "Nie ma takiej strony" in r.text
        assert "Cezary Trener" in r.text and 'href="/groups"' in r.text
        assert 'href="/">Lista meczów</a>' in r.text and "Zaloguj się" not in r.text


def test_unknown_route_for_an_anonymous_visitor_offers_login(anon_client):
    r = anon_client.get("/groups/1/coachs", headers=HTML)
    assert r.status_code == 404 and "Nie ma takiej strony" in r.text
    assert 'href="/login">Zaloguj się</a>' in r.text and "Lista meczów" not in r.text
    assert 'class="who"' not in r.text


def test_validation_errors_raised_before_auth_also_know_the_user(make_client):
    client, _ = make_client("coach", name="Cezary Trener")
    r = client.get("/matches/abc", headers=HTML)
    assert r.status_code == 422 and "Cezary Trener" in r.text and "Lista meczów" in r.text


def test_an_expired_or_inactive_session_is_treated_as_anonymous(make_client, db):
    client, user = make_client("coach", name="Cezary Trener")
    db.query(AuthSession).update({"expires_at": utcnow() - timedelta(minutes=1)})
    db.commit()
    assert "Zaloguj się" in client.get("/no/such/page", headers=HTML).text
    db.query(AuthSession).update({"expires_at": utcnow() + timedelta(days=5)})
    user.is_active = False
    db.commit()
    assert "Zaloguj się" in client.get("/no/such/page", headers=HTML).text


def test_an_error_page_does_not_extend_the_session(make_client, db):
    client, _ = make_client("coach")
    soon = utcnow() + timedelta(days=1)  # a normal page would extend this one
    db.query(AuthSession).update({"expires_at": soon})
    db.commit()
    r = client.get("/no/such/page", headers=HTML)
    assert config.SESSION_COOKIE not in r.headers.get("set-cookie", "")
    db.expire_all()
    assert db.query(AuthSession).one().expires_at == soon


def test_share_links_stay_the_same_plain_page_for_everyone(make_client, anon_client):
    client, _ = make_client("coach", name="Cezary Trener")
    logged_in = client.get("/s/nieistniejacy-kod", headers=HTML)
    anonymous = anon_client.get("/s/nieistniejacy-kod", headers=HTML)
    assert logged_in.status_code == anonymous.status_code == 404
    assert logged_in.text == anonymous.text and "Cezary Trener" not in logged_in.text
    assert "set-cookie" not in logged_in.headers
