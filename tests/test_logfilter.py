"""Tokeny zaproszeń nie wyciekają do logów ani przez nagłówek Referer."""
import logging

from app import accounts, logfilter
from tests.helpers import make_user


def _invite_token(db):
    user = make_user(db, ("referee",), email="nowy@example.com", name="Nowy", password=False)
    return accounts.create_invite(db, user, "activate", None)


def test_redact_podmienia_tylko_token():
    assert logfilter.redact("GET /set-password/abc123_-XYZ HTTP/1.1") == "GET /set-password/[ukryty] HTTP/1.1"
    assert logfilter.redact('"/set-password/abc?x=1"') == '"/set-password/[ukryty]?x=1"'
    assert logfilter.redact("/login?next=/matches/1") == "/login?next=/matches/1"


def test_dziennik_dostepu_uvicorna_ukrywa_token(caplog):
    logfilter.install()
    logfilter.install()   # idempotentne
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, logfilter.RedactTokens) for f in access.filters) == 1
    seen = []

    class Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    caplog.set_level(logging.INFO, logger="uvicorn.access")
    handler = Collect()
    access.addHandler(handler)
    try:
        access.info('%s - "%s %s HTTP/%s" %d', "172.18.0.5:41234", "GET",
                    "/set-password/SEKRETNY_TOKEN_123", "1.1", 200)
    finally:
        access.removeHandler(handler)
    assert seen == ['172.18.0.5:41234 - "GET /set-password/[ukryty] HTTP/1.1" 200']


def test_strona_ustawienia_hasla_nie_przekazuje_tokenu_dalej(anon_client, db):
    token = _invite_token(db)
    for url, status in ((f"/set-password/{token}", 200), ("/set-password/zly-token", 410)):
        r = anon_client.get(url)
        assert r.status_code == status
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["cache-control"] == "no-store"
    csrf = anon_client.cookies.get("rc_csrf")
    r = anon_client.post(f"/set-password/{token}",
                         data={"password": "a", "password2": "b", "csrf_token": csrf})
    assert r.status_code == 422 and r.headers["referrer-policy"] == "no-referrer"
