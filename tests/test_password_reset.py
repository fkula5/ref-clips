import logging
import re
from datetime import timedelta
from email import message_from_bytes, policy

import pytest
from sqlalchemy import select

from app import accounts, config, mail, password_reset, security
from app.models import AuthSession, Invite, LoginAttempt, PasswordResetRequest
from app.timeutil import utcnow
from tests.helpers import PASSWORD, make_user
from tests.test_auth import do_login

NEUTRAL = "Jeśli konto o tym adresie istnieje, wysłaliśmy na nie link do ustawienia nowego hasła. Link jest ważny 60 minut."
NEW_PASSWORD = "nowe-haslo-98765"


def forgot(client, email="jan@example.com", ip=None, **extra):
    """Posts the form the way a browser does: the CSRF cookie comes from displaying it."""
    client.get("/forgot-password")
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post("/forgot-password", data={"email": email, "csrf_token": client.cookies.get(config.CSRF_COOKIE),
                                                 **extra}, headers=headers, follow_redirects=False)


def link_in(message) -> str:
    return re.search(r"https://klipy\.example\.pl(/set-password/[\w-]+)", message.get_body(("plain",)).get_content()).group(1)


def use_link(client, path, password=NEW_PASSWORD):
    client.get(path)
    return client.post(path, data={"password": password, "password2": password,
                                   "csrf_token": client.cookies.get(config.CSRF_COOKIE)}, follow_redirects=False)


@pytest.fixture()
def by_proxy(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", True)


def age_requests(db, minutes):
    for row in db.scalars(select(PasswordResetRequest)):
        row.requested_at -= timedelta(minutes=minutes)
    db.commit()


def test_forgot_password_form_has_csrf_honeypot_and_a_way_back(anon_client):
    r = anon_client.get("/forgot-password")
    assert r.status_code == 200
    assert 'name="csrf_token"' in r.text and 'name="email"' in r.text and 'name="contact_url"' in r.text
    assert 'href="/login"' in r.text and "Wróć do logowania" in r.text


def test_login_page_links_to_the_reset_form(anon_client):
    page = anon_client.get("/login").text
    assert 'href="/forgot-password"' in page and "Nie pamiętasz hasła?" in page


def test_answer_is_identical_for_existing_unknown_and_inactive_accounts(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    make_user(db, email="off@example.com", active=False)
    answers = []
    for email in ("jan@example.com", "nikt@example.com", "off@example.com", "  JAN@example.com "):
        r = forgot(anon_client, email, ip=None)
        followed = anon_client.get(r.headers["location"])
        answers.append((r.status_code, r.headers["location"], followed.status_code, followed.text,
                        sorted(k for k in r.headers if k not in ("date",))))
        age_requests(db, 10)  # clear the per-address cooldown between the tries
    assert len({repr(a) for a in answers}) == 1
    assert answers[0][:2] == (303, "/forgot-password?sent=1") and NEUTRAL in answers[0][3]
    assert [m["To"].addresses[0].addr_spec for m in mailbox] == ["jan@example.com", "jan@example.com"]


def test_only_an_active_existing_account_gets_a_mail_in_file_mode(anon_client, db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAIL_MODE", "file")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://klipy.example.pl")
    make_user(db, email="jan@example.com")
    make_user(db, email="off@example.com", active=False)
    for email in ("nikt@example.com", "off@example.com"):
        assert forgot(anon_client, email).status_code == 303
    assert not list((tmp_path / "outbox").glob("*.eml"))
    forgot(anon_client, "jan@example.com")
    (eml,) = (tmp_path / "outbox").glob("*.eml")
    assert message_from_bytes(eml.read_bytes(), policy=policy.default)["To"].addresses[0].addr_spec == "jan@example.com"


def test_mail_content(anon_client, db, mailbox):
    make_user(db, email="jan@example.com", name="Jan Kowalski")
    forgot(anon_client)
    (message,) = mailbox
    assert message["Subject"] == "ref-clips — ustawienie nowego hasła"
    text = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    path = link_in(message)
    for body in (text, html):
        assert f"https://klipy.example.pl{path}" in body and "60 minut" in body and "tylko raz" in body
        assert "Jeśli to nie Ty prosiłeś(-aś) o zmianę hasła, zignoruj tę wiadomość — Twoje hasło się nie zmieni." in body
    assert "Jan Kowalski" in text


def test_mail_is_built_and_sent_outside_the_request_logic(db, mailbox):
    """request_reset only decides and prepares; the sending is the background task's job."""
    make_user(db, email="jan@example.com")
    pending = password_reset.request_reset(db, "jan@example.com", "1.2.3.4")
    assert pending is not None and mailbox == []
    password_reset.deliver(pending)
    assert len(mailbox) == 1
    assert password_reset.request_reset(db, "nikt@example.com", "1.2.3.4") is None


def test_unknown_account_is_recorded_like_a_known_one_but_without_a_link(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    forgot(anon_client, "nikt@example.com")
    assert db.query(Invite).count() == 0
    (row,) = db.scalars(select(PasswordResetRequest))
    assert row.kind == "reset" and row.mailed is False
    forgot(anon_client, "jan@example.com")
    assert db.query(Invite).count() == 1 and db.query(PasswordResetRequest).count() == 2


def test_table_holds_a_hash_of_the_address_not_the_address(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    forgot(anon_client, " Jan@Example.com ")
    row = db.scalar(select(PasswordResetRequest))
    assert row.email_key == security.hash_token("jan@example.com") and "jan" not in row.email_key


@pytest.mark.parametrize("email", ["", "   ", "bez-malpy", "a@b", "a b@example.com", "x" * 250 + "@example.com"])
def test_malformed_address_gets_a_validation_message_and_is_not_recorded(anon_client, db, mailbox, email):
    r = forgot(anon_client, email)
    assert r.status_code == 422 and "Podaj poprawny adres e-mail." in r.text and NEUTRAL not in r.text
    assert db.query(PasswordResetRequest).count() == 0 and mailbox == []


def test_link_sets_the_password_ends_sessions_and_clears_the_login_throttle(anon_client, make_client, db, mailbox):
    victim, user = make_client("coach", email="jan@example.com")
    assert victim.get("/").status_code == 200
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        do_login(anon_client, "jan@example.com", "zle-haslo-123")
    assert do_login(anon_client, "jan@example.com").status_code == 429
    other = LoginAttempt(email="inny@example.com", ip="9.9.9.9", attempted_at=utcnow())
    db.add(other)
    db.commit()
    forgot(anon_client)
    path = link_in(mailbox[0])
    assert db.scalar(select(Invite)).purpose == "reset"
    r = use_link(anon_client, path)
    assert r.status_code == 303 and r.headers["location"] == "/login?ok=1"
    assert "Hasło zostało ustawione" in anon_client.get("/login?ok=1").text
    assert victim.get("/api/status").status_code == 401 and db.query(AuthSession).count() == 0
    assert db.query(LoginAttempt).filter_by(email="jan@example.com").count() == 0
    assert db.query(LoginAttempt).filter_by(email="inny@example.com").count() == 1
    assert do_login(anon_client, "jan@example.com", NEW_PASSWORD).status_code == 303
    assert do_login(anon_client, "jan@example.com", PASSWORD).status_code == 401


def test_link_is_valid_for_60_minutes(anon_client, db, mailbox, monkeypatch):
    make_user(db, email="jan@example.com")
    forgot(anon_client)
    path = link_in(mailbox[0])
    invite = db.scalar(select(Invite))
    assert timedelta(minutes=59) < invite.expires_at - utcnow() <= timedelta(minutes=60)
    assert anon_client.get(path).status_code == 200
    later = utcnow() + timedelta(minutes=61)
    monkeypatch.setattr(accounts, "utcnow", lambda: later)
    assert anon_client.get(path).status_code == 410
    assert use_link(anon_client, path).status_code == 410
    assert db.scalar(select(Invite)).used_at is None


def test_link_is_single_use(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    forgot(anon_client)
    path = link_in(mailbox[0])
    assert use_link(anon_client, path).status_code == 303
    assert anon_client.get(path).status_code == 410
    assert use_link(anon_client, path, "inne-haslo-12345").status_code == 410
    assert do_login(anon_client, "jan@example.com", NEW_PASSWORD).status_code == 303


def test_a_newer_link_invalidates_the_older_one(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    forgot(anon_client)
    age_requests(db, config.RESET_EMAIL_COOLDOWN_MINUTES + 1)
    forgot(anon_client)
    first, second = (link_in(m) for m in mailbox)
    assert first != second
    assert anon_client.get(first).status_code == 410
    assert anon_client.get(second).status_code == 200


def test_the_mail_link_is_the_only_one_with_the_short_lifetime(admin, db):
    user = make_user(db, email="jan@example.com")
    accounts.create_invite(db, user, "reset", admin[1])
    assert db.scalar(select(Invite)).expires_at - utcnow() > timedelta(days=6)


def test_per_address_cooldown_and_hourly_cap(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    forgot(anon_client)
    r = forgot(anon_client)  # at once again: still neutral, but nothing goes out
    assert r.status_code == 303 and r.headers["location"] == "/forgot-password?sent=1"
    assert len(mailbox) == 1
    for _ in range(config.RESET_EMAIL_MAX_PER_HOUR - 1):
        age_requests(db, config.RESET_EMAIL_COOLDOWN_MINUTES + 1)
        forgot(anon_client)
    assert len(mailbox) == config.RESET_EMAIL_MAX_PER_HOUR
    age_requests(db, config.RESET_EMAIL_COOLDOWN_MINUTES + 1)
    assert forgot(anon_client).status_code == 303
    assert len(mailbox) == config.RESET_EMAIL_MAX_PER_HOUR  # four in 3 x 6 minutes: the cap holds
    age_requests(db, 60)
    forgot(anon_client)
    assert len(mailbox) == config.RESET_EMAIL_MAX_PER_HOUR + 1


def test_a_refused_request_does_not_count_as_a_mail(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    for _ in range(4):
        forgot(anon_client)
    assert len(mailbox) == 1
    assert db.query(PasswordResetRequest).filter_by(mailed=True).count() == 1


def test_per_ip_limit_answers_429_and_records_nothing_more(anon_client, db, mailbox, by_proxy):
    for i in range(config.RESET_IP_MAX_REQUESTS):
        assert forgot(anon_client, f"nikt{i}@example.com", ip="5.5.5.5").status_code == 303
    rows = db.query(PasswordResetRequest).count()
    make_user(db, email="jan@example.com")
    r = forgot(anon_client, "jan@example.com", ip="5.5.5.5")
    assert r.status_code == 429 and "Zbyt wiele próśb" in r.text and NEUTRAL not in r.text
    assert r.headers["retry-after"] == str(config.RESET_IP_WINDOW_MINUTES * 60)
    assert db.query(PasswordResetRequest).count() == rows and mailbox == []
    assert forgot(anon_client, "jan@example.com", ip="6.6.6.6").status_code == 303 and len(mailbox) == 1
    age_requests(db, config.RESET_IP_WINDOW_MINUTES + 1)
    assert forgot(anon_client, "nikt@example.com", ip="5.5.5.5").status_code == 303


def test_ip_limit_answer_does_not_depend_on_the_account(anon_client, db, mailbox, by_proxy):
    make_user(db, email="jan@example.com")
    for i in range(config.RESET_IP_MAX_REQUESTS):
        forgot(anon_client, f"nikt{i}@example.com", ip="5.5.5.5")
    known = forgot(anon_client, "jan@example.com", ip="5.5.5.5")
    unknown = forgot(anon_client, "nikt@example.com", ip="5.5.5.5")
    assert known.status_code == unknown.status_code == 429


def test_global_cap_sends_nothing_stays_neutral_and_warns_once(anon_client, db, mailbox, caplog, by_proxy):
    make_user(db, email="jan@example.com")
    make_user(db, email="ola@example.com")
    for i in range(config.RESET_GLOBAL_MAX_PER_HOUR):
        db.add(PasswordResetRequest(kind="reset", email_key=f"k{i}", ip="8.8.8.8", mailed=True,
                                    requested_at=utcnow() - timedelta(minutes=10)))
    db.commit()
    with caplog.at_level(logging.WARNING):
        for email, ip in (("jan@example.com", "1.1.1.1"), ("ola@example.com", "2.2.2.2")):
            r = forgot(anon_client, email, ip=ip)
            assert r.status_code == 303 and r.headers["location"] == "/forgot-password?sent=1"
    assert mailbox == [] and db.query(Invite).count() == 0
    assert len([r for r in caplog.records if "limit is reached" in r.getMessage()]) == 1
    age_requests(db, 60)
    forgot(anon_client, "jan@example.com", ip="1.1.1.1")
    assert len(mailbox) == 1


def test_old_rows_are_pruned(anon_client, db, mailbox):
    db.add(PasswordResetRequest(kind="reset", email_key="x", ip="1.1.1.1", mailed=True,
                                requested_at=utcnow() - timedelta(hours=config.RESET_KEEP_HOURS + 1)))
    db.add(PasswordResetRequest(kind="token_miss", ip="1.1.1.1", requested_at=utcnow() - timedelta(hours=1)))
    db.commit()
    forgot(anon_client, "nikt@example.com")
    assert sorted(r.kind for r in db.scalars(select(PasswordResetRequest))) == ["reset", "token_miss"]
    assert db.query(PasswordResetRequest).filter_by(email_key="x").count() == 0


def test_honeypot_gets_the_neutral_answer_and_sends_nothing(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    r = forgot(anon_client, contact_url="http://spam.example")
    assert r.status_code == 303 and r.headers["location"] == "/forgot-password?sent=1"
    assert mailbox == [] and db.query(Invite).count() == 0 and db.query(PasswordResetRequest).count() == 0


def test_csrf_is_required(anon_client, db, mailbox):
    make_user(db, email="jan@example.com")
    anon_client.get("/forgot-password")
    assert anon_client.post("/forgot-password", data={"email": "jan@example.com"}).status_code == 403
    assert anon_client.post("/forgot-password", data={"email": "jan@example.com", "csrf_token": "cudzy"}).status_code == 403
    anon_client.cookies.clear()
    assert anon_client.post("/forgot-password", data={"email": "jan@example.com", "csrf_token": "x"}).status_code == 403
    assert mailbox == [] and db.query(PasswordResetRequest).count() == 0


def test_without_smtp_or_public_url_nothing_is_sent_but_the_answer_is_the_same(anon_client, db, mailbox, monkeypatch, caplog):
    make_user(db, email="jan@example.com")
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    monkeypatch.setattr(config, "MAIL_MODE", "")
    monkeypatch.setattr(config, "SMTP_HOST", "")
    with caplog.at_level(logging.WARNING):
        r = forgot(anon_client)
    assert r.status_code == 303 and r.headers["location"] == "/forgot-password?sent=1"
    assert mailbox == [] and db.query(Invite).count() == 0
    assert any("not sent" in rec.getMessage() for rec in caplog.records)

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.pl")  # a sender, but no public address
    monkeypatch.setattr(config, "MAIL_FROM", "klipy@example.pl")
    mail._logged.clear()
    with caplog.at_level(logging.WARNING):
        assert forgot(anon_client).status_code == 303
    assert mailbox == [] and db.query(Invite).count() == 0
    assert any("REFCLIPS_PUBLIC_URL" in rec.getMessage() for rec in caplog.records)


def test_logs_hold_a_masked_address_and_no_token(anon_client, db, mailbox, caplog):
    make_user(db, email="anna@example.com")
    with caplog.at_level(logging.DEBUG):
        forgot(anon_client, "anna@example.com")
        forgot(anon_client, "nikt.nieznany@example.com")
    path = link_in(mailbox[0])
    token = path.rsplit("/", 1)[1]
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "a***@example.com" in text
    assert "anna@example.com" not in text and "nikt.nieznany" not in text and token not in text


def test_failed_delivery_is_logged_without_the_address_or_error_text(db, caplog):
    class Broken:
        def send(self, message):
            raise OSError("550 <anna@example.com> rejected")

    pending = password_reset.PendingMail(Broken(), "Anna", "anna@example.com", "https://x.example/set-password/tok")
    with caplog.at_level(logging.INFO):
        password_reset.deliver(pending)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "a***@example.com" in text and "OSError" in text and "anna@example.com" not in text and "tok" not in text


@pytest.mark.parametrize("email,masked", [("anna@example.com", "a***@example.com"), ("x@y.pl", "x***@y.pl"),
                                          ("brak", "***")])
def test_mask_email(email, masked):
    assert password_reset.mask_email(email) == masked


def test_unusable_links_are_throttled_per_ip(anon_client, db, mailbox, by_proxy):
    user = make_user(db, email="jan@example.com")
    for i in range(config.TOKEN_MISS_MAX):
        assert anon_client.get(f"/set-password/bledny{i}", headers={"X-Forwarded-For": "5.5.5.5"}).status_code == 410
    rows = db.query(PasswordResetRequest).count()
    blocked = anon_client.get("/set-password/jeszcze-jeden", headers={"X-Forwarded-For": "5.5.5.5"})
    assert blocked.status_code == 429 and "Zbyt wiele prób" in blocked.text
    assert blocked.headers["referrer-policy"] == "no-referrer" and blocked.headers["retry-after"] == "900"
    assert db.query(PasswordResetRequest).count() == rows  # a blocked request adds nothing
    token = accounts.create_invite(db, user, "reset", None)
    path = f"/set-password/{token}"
    assert anon_client.get(path, headers={"X-Forwarded-For": "5.5.5.5"}).status_code == 429  # even a good one
    anon_client.get(path, headers={"X-Forwarded-For": "6.6.6.6"})
    post = anon_client.post(path, data={"password": NEW_PASSWORD, "password2": NEW_PASSWORD,
                                        "csrf_token": anon_client.cookies.get(config.CSRF_COOKIE)},
                            headers={"X-Forwarded-For": "5.5.5.5"})
    assert post.status_code == 429
    assert anon_client.get(path, headers={"X-Forwarded-For": "6.6.6.6"}).status_code == 200
    age_requests(db, config.TOKEN_MISS_WINDOW_MINUTES + 1)
    assert anon_client.get(path, headers={"X-Forwarded-For": "5.5.5.5"}).status_code == 200


def test_bad_passwords_on_a_valid_link_do_not_count_as_misses(anon_client, db):
    user = make_user(db, email="jan@example.com")
    path = f"/set-password/{accounts.create_invite(db, user, 'reset', None)}"
    for _ in range(config.TOKEN_MISS_MAX + 2):
        assert use_link(anon_client, path, "krotkie").status_code == 422
    assert use_link(anon_client, path).status_code == 303


def test_reset_requests_do_not_count_toward_the_set_password_throttle(anon_client, db, mailbox):
    for i in range(config.RESET_IP_MAX_REQUESTS):
        forgot(anon_client, f"nikt{i}@example.com")
    assert anon_client.get("/set-password/niema").status_code == 410
    assert db.query(PasswordResetRequest).filter_by(kind="token_miss").count() == 1


def test_expired_link_page_points_to_a_new_request(anon_client):
    page = anon_client.get("/set-password/niema").text
    assert 'href="/forgot-password"' in page and "60 minut" in page and "7 dni" in page
