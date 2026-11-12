import logging

from app import accounts, logfilter
from tests.helpers import make_user


def _invite_token(db):
    user = make_user(db, ("referee",), email="nowy@example.com", name="Nowy", password=False)
    return accounts.create_invite(db, user, "activate", None)


def test_redact_replaces_only_the_token():
    assert logfilter.redact("GET /set-password/abc123_-XYZ HTTP/1.1") == "GET /set-password/[ukryty] HTTP/1.1"
    assert logfilter.redact('"/set-password/abc?x=1"') == '"/set-password/[ukryty]?x=1"'
    assert logfilter.redact("/login?next=/matches/1") == "/login?next=/matches/1"


def test_redact_hides_watch_room_ids_in_both_the_page_and_the_socket_path():
    assert logfilter.redact("GET /watch/aB3_-xyz HTTP/1.1") == "GET /watch/[ukryty] HTTP/1.1"
    assert logfilter.redact('"/ws/watch/aB3_-xyz" [accepted]') == '"/ws/watch/[ukryty]" [accepted]'
    assert logfilter.redact("/videos/5 /api/videos/5/watch") == "/videos/5 /api/videos/5/watch"


def test_redact_hides_the_share_link_code_and_keeps_the_rest_of_the_path():
    code = "aB3_-" * 8 + "xyz"
    assert logfilter.redact(f"GET /s/{code} HTTP/1.1") == "GET /s/[ukryty] HTTP/1.1"
    assert logfilter.redact(f"/s/{code}/clips/2/file?x=1") == "/s/[ukryty]/clips/2/file?x=1"
    assert logfilter.redact(f'Referer: "https://klipy.example.pl/s/{code}/zip"') == 'Referer: "https://klipy.example.pl/s/[ukryty]/zip"'
    assert logfilter.redact("/static/app.css /clips/5/file /admin/users") == "/static/app.css /clips/5/file /admin/users"
    assert logfilter.redact("GET /sets/3/clips/5 /sets /s") == "GET /sets/3/clips/5 /sets /s"  # training sets carry no secret


def test_uvicorn_access_log_hides_the_token(caplog):
    logfilter.install()
    logfilter.install()
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


def test_set_password_page_does_not_pass_the_token_on(anon_client, db):
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
