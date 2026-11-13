import re
from datetime import datetime, timedelta

import pytest

from app import config, digest, mail, notify
from sqlalchemy import update

from app.models import Comment, EmailPreference, Notification
from tests.helpers import make_match, make_user

URL = "/settings/notifications"


def pref(db, user):
    db.expire_all()
    return db.get(EmailPreference, user.id)


def boxes(html: str) -> dict[str, bool]:
    return {name: bool(flag) for name, flag in re.findall(r'name="(\w+)" value="1" (checked)?', html)}


# ---------- settings page ----------

def test_the_settings_page_needs_a_login(anon_client):
    r = anon_client.get(URL, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, f"/login?next={URL}")
    assert anon_client.post(URL, data={}, follow_redirects=False).status_code == 401


def test_page_shows_role_defaults_and_only_the_switches_that_apply(make_client):
    coach, _ = make_client("coach")
    referee, _ = make_client("referee")
    assert boxes(coach.get(URL).text) == {
        "digest_enabled": True, "new_clips_in_groups": True, "new_match_in_groups": True,
        "comments_and_ratings": True, "sheet_published": False, "group_added": True}
    assert boxes(referee.get(URL).text) == {
        "digest_enabled": True, "comments_and_ratings": True, "sheet_published": True, "group_added": True}


def test_the_header_links_to_the_settings(make_client):
    client, _ = make_client("referee")
    assert f'<a href="{URL}">Ustawienia powiadomień</a>' in client.get("/").text


def test_saving_stores_exactly_what_was_ticked(db, make_client):
    client, user = make_client("coach")
    r = client.post(URL, data={"digest_enabled": "1", "comments_and_ratings": "1", "sheet_published": "1"},
                    follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, URL)
    saved = pref(db, user)
    assert (saved.digest_enabled, saved.new_clips_in_groups, saved.new_match_in_groups, saved.comments_and_ratings,
            saved.sheet_published, saved.group_added) == (True, False, False, True, True, False)
    page = client.get(URL)
    assert "Zapisano ustawienia powiadomień." in page.text
    assert boxes(page.text) == {"digest_enabled": True, "new_clips_in_groups": False, "new_match_in_groups": False,
                                "comments_and_ratings": True, "sheet_published": True, "group_added": False}


def test_master_switch_is_remembered_separately_from_the_events(db, make_client):
    client, user = make_client("referee")
    client.post(URL, data={"comments_and_ratings": "1"})
    saved = pref(db, user)
    assert saved.digest_enabled is False and saved.comments_and_ratings is True
    assert boxes(client.get(URL).text)["digest_enabled"] is False


def test_a_referee_cannot_change_the_switches_the_page_did_not_show(db, make_client):
    client, user = make_client("referee")
    client.post(URL, data={"digest_enabled": "1", "new_clips_in_groups": "1", "new_match_in_groups": "1"})
    saved = pref(db, user)
    assert saved.new_clips_in_groups is None and saved.new_match_in_groups is None


def test_everybody_edits_only_their_own_settings(db, make_client):
    first, one = make_client("coach")
    second, two = make_client("coach")
    first.post(URL, data={"digest_enabled": "1"})
    assert pref(db, two) is None
    assert pref(db, one).group_added is False


def test_saving_needs_the_csrf_token(db, make_client):
    client, user = make_client("coach")
    del client.headers["X-CSRF-Token"]
    assert client.post(URL, data={"digest_enabled": "1"}).status_code == 403
    assert client.post(f"{URL}/test").status_code == 403
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post(URL, data={"digest_enabled": "1"}).status_code == 403
    assert pref(db, user) is None


def test_the_form_carries_the_csrf_field(make_client):
    client, _ = make_client("coach")
    assert re.search(r'<form method="post" action="/settings/notifications".*?name="csrf_token"', client.get(URL).text, re.S)


# ---------- admin test button ----------

def test_only_an_admin_sees_and_may_use_the_test_button(make_client, mailbox):
    admin, _ = make_client("admin")
    coach, _ = make_client("coach")
    assert "Wyślij mi testowe podsumowanie" in admin.get(URL).text
    assert "Wyślij mi testowe podsumowanie" not in coach.get(URL).text
    assert coach.post(f"{URL}/test").status_code == 403
    assert mailbox == []


def test_the_test_button_sends_to_the_admins_own_address_and_leaves_the_window_alone(db, make_client, mailbox):
    admin, user = make_client("admin", email="szef@example.com")
    r = admin.post(f"{URL}/test")
    assert r.status_code == 200
    assert "Wysłano wiadomość testową na adres szef@example.com." in r.text
    assert len(mailbox) == 1 and mailbox[0]["To"].addresses[0].addr_spec == "szef@example.com"
    assert mailbox[0]["Subject"].startswith("[TEST] ")
    assert pref(db, user).last_digest_until is None
    assert pref(db, user).unsubscribe_token  # the footer link works


def test_the_test_button_reports_a_failed_send_to_the_admin(make_client, mailbox, monkeypatch):
    class Broken:
        def send(self, message):
            raise ConnectionRefusedError("smtp.example.com:587 odmawia połączenia")

    monkeypatch.setattr(mail, "get_sender", lambda: Broken())
    admin, _ = make_client("admin")
    r = admin.post(f"{URL}/test")
    assert r.status_code == 502
    assert "ConnectionRefusedError: smtp.example.com:587 odmawia połączenia" in r.text


def test_the_test_button_explains_when_mail_is_not_configured(make_client, mailbox, monkeypatch):
    monkeypatch.setattr(config, "MAIL_MODE", "")
    monkeypatch.setattr(config, "SMTP_HOST", "")
    admin, _ = make_client("admin")
    page = admin.get(URL).text
    assert "Wysyłka maili jest wyłączona: REFCLIPS_SMTP_HOST is not set." in page
    r = admin.post(f"{URL}/test")
    assert r.status_code == 503 and "nie jest skonfigurowana" in r.text
    assert mailbox == []


# ---------- unsubscribe ----------

@pytest.fixture()
def subscriber(db):
    user = make_user(db, ("referee",), email="odbiorca@example.com", name="Odbiorca")
    row = digest.get_pref(db, user.id)
    token = digest.ensure_token(row)
    db.commit()
    return user, token


def unsubscribe_url(token):
    return f"/unsubscribe/{token}"


def test_get_shows_a_confirmation_and_changes_nothing(db, anon_client, subscriber):
    user, token = subscriber
    for method in (anon_client.get, anon_client.head):
        r = method(unsubscribe_url(token))
        assert r.status_code == 200
    r = anon_client.get(unsubscribe_url(token))
    assert f'<form method="post" action="/unsubscribe/{token}">' in r.text
    assert "Wyłączyć wszystkie maile?" in r.text
    assert pref(db, user).digest_enabled is True


def test_post_switches_the_digest_off_without_a_session_or_csrf_token(db, anon_client, subscriber):
    user, token = subscriber
    r = anon_client.post(unsubscribe_url(token))
    assert r.status_code == 200 and "Maile wyłączone" in r.text
    assert pref(db, user).digest_enabled is False
    assert anon_client.post(unsubscribe_url(token)).status_code == 200  # idempotent
    assert "Maile wyłączone" in anon_client.get(unsubscribe_url(token)).text


def test_the_one_click_post_of_a_mail_client_works(db, anon_client, subscriber):
    user, token = subscriber
    r = anon_client.post(unsubscribe_url(token), content="List-Unsubscribe=One-Click",
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    assert pref(db, user).digest_enabled is False


def test_unsubscribing_keeps_the_event_choices(db, anon_client, subscriber):
    user, token = subscriber
    row = pref(db, user)
    row.group_added = False
    db.commit()
    anon_client.post(unsubscribe_url(token))
    assert pref(db, user).group_added is False


@pytest.mark.parametrize("mutate", [
    lambda t: t[:-1] + ("A" if t[-1] != "A" else "B"),   # one character changed
    lambda t: t[:-1],                                    # truncated
    lambda t: t + "x",
    lambda t: "A" * 43,
    lambda t: t.lower() if t != t.lower() else t.upper(),
    lambda t: "../" + t,
    lambda t: " " + t,
])
def test_a_tampered_token_is_refused_on_get_and_post(db, anon_client, subscriber, mutate):
    user, token = subscriber
    bad = mutate(token)
    assert bad != token
    for method in (anon_client.get, anon_client.post):
        r = method(unsubscribe_url(bad))
        assert r.status_code in (404, 405) or "Link jest nieprawidłowy" in r.text
        assert r.status_code != 200
    assert pref(db, user).digest_enabled is True


def test_the_page_never_reveals_who_the_token_belongs_to_and_is_not_cached(anon_client, subscriber):
    user, token = subscriber
    r = anon_client.get(unsubscribe_url(token))
    assert user.name not in r.text and user.email not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in r.headers["x-robots-tag"]
    assert "rc_session" not in r.headers.get("set-cookie", "") and "csrf" not in r.headers.get("set-cookie", "")


def test_a_logged_in_visitor_does_not_use_their_session_on_the_unsubscribe_page(db, make_client, subscriber):
    other, _ = make_client("coach", name="Ktoś Zalogowany")
    r = other.get(unsubscribe_url(subscriber[1]))
    assert "Ktoś Zalogowany" not in r.text


RUN_AT = datetime(2026, 11, 13, 6, 30)  # 07:30 in Warsaw


def news_for(db, user):
    """A comment on a match the user is in the crew of: the bell (and so the digest) has something for them."""
    match = make_match(db, officials=(("CC", user),))
    comment = Comment(match_id=match.id, author_id=make_user(db, ("coach",), email="x@example.com").id, body="Hej")
    db.add(comment)
    db.flush()
    notify.comment_added(db, comment)
    db.execute(update(Notification).values(created_at=RUN_AT - timedelta(hours=1)))
    db.commit()


def test_after_unsubscribing_the_scheduled_digest_stops(db, anon_client, subscriber):
    user, token = subscriber
    anon_client.post(unsubscribe_url(token))
    news_for(db, user)
    assert digest.run_due(db, now=RUN_AT, sender=mail.MemorySender(), base="https://klipy.example.pl") == 0


def test_the_mail_links_to_a_working_unsubscribe_page(db, anon_client, subscriber, mailbox):
    user, token = subscriber
    news_for(db, user)
    assert digest.run_due(db, now=RUN_AT, base="https://klipy.example.pl") == 1
    link = re.search(r"<https://klipy\.example\.pl(/unsubscribe/[\w-]+)>", mailbox[0]["List-Unsubscribe"])
    assert link[1] == unsubscribe_url(token)
    assert anon_client.post(link[1]).status_code == 200
    assert pref(db, user).digest_enabled is False
