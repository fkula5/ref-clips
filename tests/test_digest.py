import logging
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from app import config, digest, feedback, groups, mail, notify, worker
from app.models import (Clip, Comment, EmailPreference, GroupMember, Match, Notification, Sheet, TrainingGroup)
from tests.helpers import (category_named, make_match, make_ready_video, make_user, mark_periods)

NOW = datetime(2026, 11, 13, 6, 30)  # 07:30 in Warsaw (CET)
BASE = "https://klipy.example.pl"


class Boom(Exception):
    pass


class FailFor:
    """A sender that fails for the listed addresses (or for everyone) and records the rest."""

    def __init__(self, *addresses):
        self.addresses, self.sent = set(addresses), []

    def send(self, message):
        address = message["To"].addresses[0].addr_spec
        if not self.addresses or address in self.addresses:
            raise Boom(address)
        self.sent.append(message)


def hours_ago(h, now=NOW):
    return now - timedelta(hours=h)


def text_of(message) -> str:
    return message.get_body(("plain",)).get_content()


def html_of(message) -> str:
    return message.get_body(("html",)).get_content()


def mail_to(outbox, email):
    found = [m for m in outbox if m["To"].addresses[0].addr_spec == email]
    assert len(found) <= 1, "more than one digest for one account"
    return found[0] if found else None


@pytest.fixture()
def w(db, mailbox):
    """`coach` leads group A, whose referee `ref` is the CC of the match; `coach2` leads group B with
    `ref2`, who is not in the match; `outsider` is a coach without a group. The match was created two hours
    before NOW by nobody in particular.
    """
    people = {
        "coach": make_user(db, ("coach",), email="coach@example.com", name="Cezary Trener"),
        "coach2": make_user(db, ("coach",), email="coach2@example.com", name="Daria Trenerka"),
        "outsider": make_user(db, ("coach",), email="outsider@example.com", name="Olek Obcy"),
        "ref": make_user(db, ("referee",), email="ref@example.com", name="Roman Sędzia"),
        "ref2": make_user(db, ("referee",), email="ref2@example.com", name="Rafał Drugi"),
        "admin": make_user(db, ("admin",), email="admin@example.com", name="Adam Admin"),
    }
    group_a, group_b = TrainingGroup(name="Grupa A"), TrainingGroup(name="Grupa B")
    group_a.members += [GroupMember(user_id=people["coach"].id, role="coach"),
                        GroupMember(user_id=people["ref"].id, role="referee")]
    group_b.members += [GroupMember(user_id=people["coach2"].id, role="coach"),
                        GroupMember(user_id=people["ref2"].id, role="referee")]
    db.add_all([group_a, group_b])
    db.commit()
    match = make_match(db, officials=(("CC", people["ref"]), ("U1", "Wpisany Sędzia")))
    match.created_at = hours_ago(2)
    db.commit()
    video = mark_periods(db, make_ready_video(db, match))

    class World:
        pass

    world = World()
    world.db, world.u, world.match, world.video, world.groups = db, people, match, video, (group_a, group_b)
    world.outbox = mailbox
    return world


def add_clip(w, hours=1, *, by=None, category="kroki", match=None, described=True):
    clip = Clip(match_id=(match or w.match).id, video_id=w.video.id, time_sec=10,
                category_id=category_named(w.db, category) if category else None,
                described_at=hours_ago(hours) if described else None, described_by_id=by.id if by else None)
    w.db.add(clip)
    w.db.commit()
    return clip


def settle(w, hours=1):
    """The notification and comment rows get a fixed time (the creating code uses the real clock)."""
    w.db.execute(update(Notification).values(created_at=hours_ago(hours)))
    w.db.execute(update(Comment).values(created_at=hours_ago(hours)))
    w.db.commit()


def run(w, now=NOW, sender=None, base=BASE):
    sender = sender or mail.MemorySender()
    mail.OUTBOX.clear()
    sent = digest.run_due(w.db, now=now, sender=sender, base=base)
    return sent


def pref_of(w, user):
    return w.db.get(EmailPreference, user.id)


# ---------- defaults and preferences ----------

def test_defaults_by_role():
    assert digest.default_for({"coach"}) == {"new_clips_in_groups", "new_match_in_groups", "comments_and_ratings",
                                             "group_added"}
    assert digest.default_for({"referee"}) == {"comments_and_ratings", "sheet_published", "group_added"}
    assert digest.default_for({"admin"}) == set()
    assert digest.default_for({"admin", "coach"}) == digest.default_for({"coach"})
    assert digest.default_for({"coach", "referee"}) == set(digest.DIGEST_EVENTS)


def test_chosen_switch_beats_the_default_and_null_follows_the_roles(w):
    coach = w.u["coach"]
    pref = EmailPreference(user_id=coach.id, digest_enabled=True, group_added=False, sheet_published=True)
    assert digest.enabled_events(coach, pref) == {"new_clips_in_groups", "new_match_in_groups",
                                                  "comments_and_ratings", "sheet_published"}
    assert digest.enabled_events(coach, None) == digest.default_for({"coach"})


def test_only_coaches_and_admins_see_the_group_switches(w):
    assert digest.configurable_events(w.u["ref"]) == ["comments_and_ratings", "sheet_published", "group_added"]
    assert digest.configurable_events(w.u["coach"]) == list(digest.DIGEST_EVENTS)
    assert digest.configurable_events(w.u["admin"]) == list(digest.DIGEST_EVENTS)


# ---------- event 1: new described clips ----------

def test_group_coach_gets_one_line_per_match_with_counts_per_category(w):
    for category in ("kroki", "kroki", "osobisty"):
        add_clip(w, category=category)
    run(w)
    message = mail_to(w.outbox, "coach@example.com")
    text = text_of(message)
    assert "3 nowe klipy (2× kroki, 1× osobisty)" in text
    assert f"{BASE}/matches/{w.match.id}" in text
    assert "Mecz 28.10.2026 · Legia – Wisła" in text
    assert mail_to(w.outbox, "coach2@example.com") is None  # a coach of another group
    assert mail_to(w.outbox, "outsider@example.com") is None
    assert mail_to(w.outbox, "ref@example.com") is None  # referees do not get clip news by default


def test_clip_line_pluralises_like_polish(w):
    add_clip(w)
    run(w)
    assert "1 nowy klip (1× kroki)" in text_of(mail_to(w.outbox, "coach@example.com"))
    for _ in range(4):
        add_clip(w)
    w.db.get(EmailPreference, w.u["coach"].id).last_digest_until = None
    w.db.commit()
    run(w)
    assert "5 nowych klipów (5× kroki)" in text_of(mail_to(w.outbox, "coach@example.com"))


def test_clips_described_by_the_recipient_undescribed_or_outside_the_window_are_left_out(w):
    add_clip(w, by=w.u["coach"])
    add_clip(w, described=False)
    add_clip(w, hours=30)  # before the first 24 h window
    add_clip(w, by=w.u["ref"])
    run(w)
    text = text_of(mail_to(w.outbox, "coach@example.com"))
    assert "1 nowy klip" in text
    assert mail_to(w.outbox, "coach2@example.com") is None


def test_a_clip_without_a_recorded_describer_counts(w):
    add_clip(w, by=None, category=None)
    run(w)
    assert "1 nowy klip (1× bez kategorii)" in text_of(mail_to(w.outbox, "coach@example.com"))


def test_matches_of_other_groups_do_not_leak_into_a_coachs_digest(w):
    other = make_match(w.db, officials=(("CC", w.u["ref2"]),))
    other.created_at = hours_ago(1)
    w.match.created_at = hours_ago(100)
    w.db.commit()
    add_clip(w, match=other)
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None
    assert "1 nowy klip" in text_of(mail_to(w.outbox, "coach2@example.com"))


# ---------- event 2: new match ----------

def test_group_coach_hears_about_a_new_match_with_its_crew(w):
    run(w)
    text = text_of(mail_to(w.outbox, "coach@example.com"))
    assert "Nowy mecz: 28.10.2026 · Legia – Wisła, obsada: CC · Roman Sędzia, U1 · Wpisany Sędzia" in text
    assert f"{BASE}/matches/{w.match.id}" in text
    assert mail_to(w.outbox, "coach2@example.com") is None


def test_the_creator_is_not_told_about_their_own_match(w):
    w.match.created_by = w.u["coach"].id
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None


def test_a_match_without_a_group_referee_in_the_crew_is_not_reported(w):
    typed_only = make_match(w.db, officials=(("CC", "Wpisany Sędzia"),))
    typed_only.created_at = hours_ago(1)
    w.db.commit()
    w.match.created_at = hours_ago(100)
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None


def test_one_section_per_match_newest_match_first(w):
    newer = make_match(w.db, officials=(("CC", w.u["ref"]),))
    newer.date = w.match.date.replace(day=30)
    newer.created_at = hours_ago(1)
    w.db.commit()
    add_clip(w, match=newer)
    add_clip(w)
    run(w)
    text = text_of(mail_to(w.outbox, "coach@example.com"))
    assert text.count("Mecz ") == 2
    assert text.index("30.10.2026") < text.index("28.10.2026")


# ---------- events 3-5: from notifications ----------

def comment_on_clip(w, who, body, clip):
    comment = feedback.create_comment(w.db, w.u[who].id, body, clip_id=clip.id)
    w.db.commit()
    return comment


def test_comments_and_ratings_are_summarised_per_match_with_the_first_words(w):
    clip = add_clip(w, by=w.u["coach"])
    clip.author_id = w.u["coach"].id
    w.db.commit()
    comment_on_clip(w, "coach2", "Jeden dwa trzy cztery pięć sześć siedem osiem dziewięć dziesięć jedenaście "
                                 "dwanaście trzynaście czternaście", clip)
    comment_on_clip(w, "coach2", "Krótki", clip)
    w.db.add(Comment(match_id=w.match.id, author_id=w.u["coach2"].id, body="O meczu"))
    w.db.flush()
    notify.comment_added(w.db, w.db.query(Comment).filter(Comment.match_id == w.match.id).one())
    from app.models import Rating
    rating = Rating(clip_id=clip.id, coach_id=w.u["coach2"].id, verdict="incorrect", comment="")
    w.db.add(rating)
    w.db.flush()
    notify.rating_saved(w.db, rating, w.u["coach2"].id, changed=False)
    w.db.commit()
    settle(w)
    run(w)
    text = text_of(mail_to(w.outbox, "ref@example.com"))
    assert "3 komentarze, 1 ocena" in text
    assert "Daria Trenerka: „Jeden dwa trzy cztery pięć sześć siedem osiem dziewięć dziesięć jedenaście dwanaście…”" in text
    assert "Daria Trenerka: „Krótki”" in text
    assert "Daria Trenerka ocenił(a) klip: nieprawidłowa" in text
    assert f"{BASE}/clips/{clip.id}#komentarze" in text
    assert f"{BASE}/clips/{clip.id}#oceny" in text
    assert f"{BASE}/matches/{w.match.id}#komentarze" in text
    coach_text = text_of(mail_to(w.outbox, "coach@example.com"))  # the clip's author hears about it too
    assert "komentarze" in coach_text
    assert mail_to(w.outbox, "coach2@example.com") is None  # the actor never reads about their own actions
    assert mail_to(w.outbox, "outsider@example.com") is None


def test_read_notifications_still_count(w):
    clip = add_clip(w, by=w.u["coach"])
    comment_on_clip(w, "coach2", "Przeczytany", clip)
    settle(w)
    w.db.execute(update(Notification).values(read_at=hours_ago(0.5)))
    w.db.commit()
    run(w)
    assert "1 komentarz" in text_of(mail_to(w.outbox, "ref@example.com"))


def test_a_deleted_comment_is_counted_without_its_text(w):
    clip = add_clip(w, by=w.u["coach"])
    comment = comment_on_clip(w, "coach2", "Zaraz usunięty", clip)
    settle(w)
    w.db.delete(comment)
    w.db.commit()
    run(w)
    text = text_of(mail_to(w.outbox, "ref@example.com"))
    assert "1 komentarz" in text and "Zaraz usunięty" not in text


def test_a_comment_is_paired_with_its_notification_despite_whole_second_timestamps(w):
    clip = add_clip(w, by=w.u["coach"])
    comment_on_clip(w, "coach2", "Pierwszy", clip)
    comment_on_clip(w, "coach2", "Drugi", clip)
    base = hours_ago(1)
    for comment, note, offset in zip(w.db.query(Comment).order_by(Comment.id),
                                     w.db.query(Notification).filter(Notification.recipient_id == w.u["ref"].id)
                                     .order_by(Notification.id), (0, 3)):
        comment.created_at = base.replace(microsecond=0) + timedelta(seconds=offset)
        note.created_at = comment.created_at + timedelta(microseconds=700_000)
    w.db.commit()
    run(w)
    text = text_of(mail_to(w.outbox, "ref@example.com"))
    assert text.index("„Pierwszy”") < text.index("„Drugi”")


def publish_sheet_for(w):
    sheet = Sheet(match_id=w.match.id, coach_id=w.u["coach"].id, status="published", difficulty="normalny",
                  published_at=hours_ago(1))
    w.db.add(sheet)
    w.db.flush()
    notify.sheet_published(w.db, sheet)
    w.db.commit()
    settle(w)
    return sheet


def test_published_sheet_is_reported_to_the_crew_only(w):
    sheet = publish_sheet_for(w)
    run(w)
    text = text_of(mail_to(w.outbox, "ref@example.com"))
    assert "Opublikowano arkusz oceny (szkoleniowiec: Cezary Trener)" in text
    assert f"{BASE}/sheets/{sheet.id}" in text
    assert "arkusz" not in text_of(mail_to(w.outbox, "coach@example.com"))  # the author is the actor


def test_being_added_to_a_group_names_the_coaches(w):
    groups.add_member(w.db, w.groups[0], w.u["ref2"].id, "referee", w.u["coach"])
    settle(w)
    run(w)
    text = text_of(mail_to(w.outbox, "ref2@example.com"))
    assert "Dodano Cię do grupy Grupa A (szkoleniowiec: Cezary Trener)" in text
    assert f"{BASE}/groups" in text


def test_several_coaches_make_the_label_plural(w):
    w.groups[0].members.append(GroupMember(user_id=w.u["outsider"].id, role="coach"))
    w.db.commit()
    groups.add_member(w.db, w.groups[0], w.u["ref2"].id, "referee", w.u["admin"])
    settle(w)
    run(w)
    assert "(szkoleniowcy: Cezary Trener, Olek Obcy)" in text_of(mail_to(w.outbox, "ref2@example.com"))


def test_events_are_not_added_to_the_bell(w):
    before = w.db.query(Notification).count()
    add_clip(w)
    w.db.commit()
    run(w)
    assert w.db.query(Notification).count() == before


# ---------- who gets anything ----------

def test_inactive_and_passwordless_accounts_get_nothing(w):
    add_clip(w)
    w.u["coach"].is_active = False
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None
    w.u["coach"].is_active = True
    w.u["coach"].password_hash = None
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None
    assert pref_of(w, w.u["coach"]) is None  # not even a run is recorded for them


def test_master_switch_off_sends_nothing(w):
    add_clip(w)
    w.db.add(EmailPreference(user_id=w.u["coach"].id, digest_enabled=False))
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None


def test_switched_off_events_are_left_out_and_the_rest_stays(w):
    add_clip(w)
    w.db.add(EmailPreference(user_id=w.u["coach"].id, digest_enabled=True, new_clips_in_groups=False))
    w.db.commit()
    run(w)
    text = text_of(mail_to(w.outbox, "coach@example.com"))
    assert "nowy klip" not in text and "Nowy mecz" in text


def test_a_switch_turned_on_beyond_the_role_defaults_takes_effect(w):
    w.match.created_at = hours_ago(100)
    other = make_match(w.db, officials=(("CC", w.u["coach"]),))
    other.created_at = hours_ago(100)
    sheet = Sheet(match_id=other.id, coach_id=w.u["coach2"].id, status="published", difficulty="normalny",
                  published_at=hours_ago(1))
    w.db.add(sheet)
    w.db.flush()
    notify.sheet_published(w.db, sheet)
    w.db.commit()
    settle(w)
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None  # coaches do not get sheet news by default
    w.db.get(EmailPreference, w.u["coach"].id).sheet_published = True
    w.db.get(EmailPreference, w.u["coach"].id).last_digest_until = None
    w.db.commit()
    run(w)
    assert "Opublikowano arkusz oceny (szkoleniowiec: Daria Trenerka)" in text_of(mail_to(w.outbox, "coach@example.com"))


def test_an_admin_gets_what_the_other_roles_give_and_what_they_switch_on(w):
    add_clip(w)
    admin = w.u["admin"]
    w.groups[0].members.append(GroupMember(user_id=admin.id, role="coach"))
    w.db.commit()
    run(w)
    assert mail_to(w.outbox, "admin@example.com") is None  # the admin role alone brings nothing, even as a group coach
    pref = pref_of(w, admin)
    pref.new_clips_in_groups, pref.last_digest_until = True, None
    w.db.commit()
    run(w)
    text = text_of(mail_to(w.outbox, "admin@example.com"))
    assert "1 nowy klip" in text and "Nowy mecz" not in text
    pref.new_clips_in_groups, pref.last_digest_until = None, None
    admin.set_roles({"admin", "coach"})
    w.db.commit()
    run(w)
    text = text_of(mail_to(w.outbox, "admin@example.com"))
    assert "1 nowy klip" in text and "Nowy mecz" in text


# ---------- schedule and window ----------

@pytest.mark.parametrize("day,before,at", [
    (datetime(2026, 7, 15), (4, 59), (5, 0)),    # CEST: 07:00 is 05:00 UTC
    (datetime(2026, 11, 13), (5, 59), (6, 0)),   # CET: 07:00 is 06:00 UTC
    (datetime(2026, 3, 29), (4, 59), (5, 0)),    # the day clocks go forward (at 01:00 UTC)
    (datetime(2026, 10, 25), (5, 59), (6, 0)),   # the day clocks go back
])
def test_digest_time_follows_07_00_in_warsaw_across_dst(day, before, at):
    start = digest.digest_time(day.replace(hour=12))
    assert start == day.replace(hour=at[0], minute=at[1])
    assert digest.digest_time(day.replace(hour=before[0], minute=before[1])) == start


def test_nothing_is_sent_before_07_00_local_and_it_is_sent_after(w):
    add_clip(w)
    assert run(w, now=datetime(2026, 11, 13, 5, 59)) == 0
    assert w.outbox == [] and pref_of(w, w.u["coach"]) is None
    assert run(w, now=datetime(2026, 11, 13, 6, 0)) == 1


def test_summer_time_changes_the_utc_moment(w):
    add_clip(w, hours=1, match=w.match)
    summer_0459 = datetime(2026, 7, 15, 4, 59)
    w.db.execute(update(Clip).values(described_at=summer_0459 - timedelta(hours=1)))
    w.match.created_at = summer_0459 - timedelta(hours=3)
    w.db.commit()
    assert run(w, now=summer_0459) == 0
    assert run(w, now=datetime(2026, 7, 15, 5, 0)) == 1


def test_a_run_is_recorded_and_not_repeated_the_same_day(w):
    add_clip(w)
    assert run(w) == 1
    assert pref_of(w, w.u["coach"]).last_digest_until == NOW
    assert run(w, now=NOW + timedelta(hours=3)) == 0  # later the same day, even with news
    assert run(w, now=NOW + timedelta(minutes=5)) == 0


def test_the_next_day_covers_only_what_came_after_the_previous_run(w):
    add_clip(w, hours=1)
    run(w)
    tomorrow = NOW + timedelta(days=1)
    w.db.add(Clip(match_id=w.match.id, video_id=w.video.id, time_sec=20, described_at=NOW + timedelta(hours=2)))
    w.db.commit()
    assert run(w, now=tomorrow) == 1
    text = text_of(mail_to(w.outbox, "coach@example.com"))
    assert "1 nowy klip" in text
    assert "Nowy mecz" not in text  # reported the day before


def test_window_is_open_at_the_start_and_closed_at_the_end(w):
    boundary_in, boundary_out = NOW, NOW + timedelta(seconds=1)
    prev = hours_ago(5)
    w.db.add(EmailPreference(user_id=w.u["coach"].id, digest_enabled=True, last_digest_until=prev))
    w.match.created_at = hours_ago(30)  # out of the picture
    w.db.add_all([Clip(match_id=w.match.id, video_id=w.video.id, time_sec=1, described_at=prev),
                  Clip(match_id=w.match.id, video_id=w.video.id, time_sec=2, described_at=boundary_in),
                  Clip(match_id=w.match.id, video_id=w.video.id, time_sec=3, described_at=boundary_out)])
    w.db.commit()
    run(w)
    assert "1 nowy klip" in text_of(mail_to(w.outbox, "coach@example.com"))  # only the one at exactly NOW


def test_first_run_covers_24_hours_and_a_long_gap_is_capped_at_48(w):
    w.match.created_at = hours_ago(100)
    add_clip(w, hours=25)
    run(w)
    assert mail_to(w.outbox, "coach@example.com") is None
    assert pref_of(w, w.u["coach"]).last_digest_until == NOW  # recorded although nothing was sent
    pref = pref_of(w, w.u["coach"])
    pref.last_digest_until = NOW - timedelta(days=10)
    w.db.commit()
    add_clip(w, hours=36)  # 60 h before the second run: beyond the 48 h cap
    add_clip(w, hours=16)  # 40 h before it: inside
    run(w, now=NOW + timedelta(days=1))
    assert "1 nowy klip" in text_of(mail_to(w.outbox, "coach@example.com"))
    assert digest.window_start(None, NOW) == NOW - timedelta(hours=24)
    assert digest.window_start(NOW - timedelta(days=9), NOW) == NOW - timedelta(hours=48)
    assert digest.window_start(NOW - timedelta(hours=5), NOW) == NOW - timedelta(hours=5)


def test_nothing_to_report_sends_no_mail_but_records_the_run(w):
    w.match.created_at = hours_ago(100)
    w.db.commit()
    assert run(w) == 0
    assert w.outbox == []
    assert pref_of(w, w.u["coach"]).last_digest_until == NOW
    assert pref_of(w, w.u["ref"]).last_digest_until == NOW


# ---------- failures ----------

def test_a_failed_send_keeps_the_window_and_the_next_check_retries_without_losing_news(w):
    add_clip(w)
    sender = FailFor("coach@example.com")
    assert digest.run_due(w.db, now=NOW, sender=sender, base=BASE) == 0
    assert pref_of(w, w.u["coach"]).last_digest_until is None
    later = NOW + timedelta(minutes=5)
    assert run(w, now=later) == 1
    assert "1 nowy klip" in text_of(mail_to(w.outbox, "coach@example.com"))
    assert pref_of(w, w.u["coach"]).last_digest_until == later


def test_one_accounts_failure_does_not_block_the_others(w):
    add_clip(w)
    publish_sheet_for(w)
    sender = FailFor("coach@example.com")
    assert digest.run_due(w.db, now=NOW, sender=sender, base=BASE) == 1
    assert [m["To"].addresses[0].addr_spec for m in sender.sent] == ["ref@example.com"]
    assert pref_of(w, w.u["ref"]).last_digest_until == NOW
    assert pref_of(w, w.u["coach"]).last_digest_until is None


def test_a_dead_server_is_not_hammered_for_every_account(w):
    for i in range(6):
        user = make_user(w.db, ("coach",), email=f"extra{i}@example.com", name=f"Extra {i}")
        w.groups[0].members.append(GroupMember(user_id=user.id, role="coach"))
    w.db.commit()
    attempts = []

    class Dead:
        def send(self, message):
            attempts.append(message)
            raise Boom

    assert digest.run_due(w.db, now=NOW, sender=Dead(), base=BASE) == 0
    assert len(attempts) == config.DIGEST_ABORT_AFTER_FAILURES


def test_without_a_sender_or_a_public_address_the_digest_is_off_and_logged_once(w, monkeypatch, caplog):
    add_clip(w)
    monkeypatch.setattr(config, "MAIL_MODE", "")
    monkeypatch.setattr(config, "SMTP_HOST", "")
    caplog.set_level(logging.WARNING, logger="mail")
    for _ in range(3):
        assert digest.run_due(w.db, now=NOW) == 0
    assert [r.getMessage() for r in caplog.records].count(
        "E-mail digest is disabled: REFCLIPS_SMTP_HOST is not set") == 1
    assert pref_of(w, w.u["coach"]) is None  # nothing recorded: the news waits for a working setup
    monkeypatch.setattr(config, "MAIL_MODE", "memory")
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    monkeypatch.setattr(mail, "is_dry_run", lambda: False)
    assert digest.run_due(w.db, now=NOW) == 0
    assert any("REFCLIPS_PUBLIC_URL" in r.getMessage() for r in caplog.records)


# ---------- the message ----------

def test_message_headers_and_parts(w):
    add_clip(w)
    run(w)
    message = mail_to(w.outbox, "coach@example.com")
    token = pref_of(w, w.u["coach"]).unsubscribe_token
    assert message["List-Unsubscribe"] == f"<{BASE}/unsubscribe/{token}>"
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message["From"].addresses[0].addr_spec == "klipy@example.pl"
    assert message["Subject"] == "ref-clips: podsumowanie 13.11.2026"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in message.iter_parts()] == ["text/plain", "text/html"]
    for body in (text_of(message), html_of(message)):
        assert f"{BASE}/settings/notifications" in body
        assert f"{BASE}/unsubscribe/{token}" in body
    assert len(token) == 43
    raw = bytes(message)
    assert raw.isascii()  # quoted-printable and encoded headers: safe for servers without 8BITMIME


def test_user_text_is_escaped_in_the_html_part(w):
    evil = '<script>alert("x")</script> & \'q\''
    w.u["coach2"].name = evil
    w.groups[1].name = evil
    w.db.commit()
    clip = add_clip(w, by=w.u["coach"])
    comment_on_clip(w, "coach2", evil, clip)
    w.match.officials[1].name = evil
    w.db.commit()
    settle(w)
    run(w)
    html = html_of(mail_to(w.outbox, "ref@example.com"))
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&#34;x&#34;" in html or "&quot;x&quot;" in html
    html_coach = html_of(mail_to(w.outbox, "coach@example.com"))
    assert "<script>" not in html_coach
    assert evil in text_of(mail_to(w.outbox, "ref@example.com"))  # plain text is not HTML


def test_html_escapes_the_recipients_own_name_and_group_names(w):
    w.u["ref2"].name = "<img src=x onerror=alert(1)>"
    w.groups[0].name = 'G"><b>'
    w.db.commit()
    groups.add_member(w.db, w.groups[0], w.u["ref2"].id, "referee", w.u["coach"])
    settle(w)
    run(w)
    message = mail_to(w.outbox, "ref2@example.com")
    html = html_of(message)
    assert "<img" not in html and "<b>" not in html
    assert "&lt;img" in html
    assert message["To"].addresses[0].addr_spec == "ref2@example.com"


# ---------- the test send ----------

def test_test_digest_covers_24_hours_ignores_schedule_and_does_not_move_the_window(w):
    add_clip(w, hours=5)
    pref = EmailPreference(user_id=w.u["coach"].id, digest_enabled=False, last_digest_until=hours_ago(2))
    w.db.add(pref)
    w.db.commit()
    sender = mail.MemorySender()
    mail.OUTBOX.clear()
    assert digest.send_test(w.db, w.u["coach"], sender, BASE, now=datetime(2026, 11, 13, 3, 0)) is True
    message = mail_to(mail.OUTBOX, "coach@example.com")
    assert message["Subject"].startswith("[TEST] ")
    assert "1 nowy klip" in text_of(message)
    assert pref_of(w, w.u["coach"]).last_digest_until == hours_ago(2)
    assert pref_of(w, w.u["coach"]).digest_enabled is False


def test_empty_test_digest_is_still_sent(w):
    w.match.created_at = hours_ago(100)
    w.db.commit()
    sender = mail.MemorySender()
    mail.OUTBOX.clear()
    assert digest.send_test(w.db, w.u["admin"], sender, BASE, now=NOW) is False
    assert "wiadomość testowa" in text_of(mail_to(mail.OUTBOX, "admin@example.com"))


# ---------- senders ----------

def test_file_mode_writes_eml_files_under_the_data_dir(w, monkeypatch):
    monkeypatch.setattr(config, "MAIL_MODE", "file")
    add_clip(w)
    digest.run_due(w.db, now=NOW, base=BASE)
    files = list((config.DATA_DIR / "outbox").glob("*.eml"))
    assert len(files) == 1
    assert b"List-Unsubscribe-Post: List-Unsubscribe=One-Click" in files[0].read_bytes()
    for f in files:
        f.unlink()


@pytest.mark.parametrize("security,port,ssl_class", [("starttls", 587, False), ("ssl", 465, True), ("none", 25, False)])
def test_smtp_sender_follows_the_security_mode(w, monkeypatch, security, port, ssl_class):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, context=None):
            calls.append(("connect", type(self).__name__, host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            calls.append(("quit",))

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message, from_addr, to_addrs):
            calls.append(("send", from_addr, to_addrs))

    class FakeSMTPSSL(FakeSMTP):
        pass

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTPSSL)
    for name, value in (("SMTP_HOST", "smtp.example.com"), ("SMTP_PORT", port), ("SMTP_SECURITY", security),
                        ("SMTP_USER", "user"), ("SMTP_PASSWORD", "pw")):
        monkeypatch.setattr(config, name, value)
    add_clip(w)
    monkeypatch.setattr(config, "MAIL_MODE", "")
    digest.run_due(w.db, now=NOW, base=BASE)
    kinds = [c[0] for c in calls]
    assert calls[0][1] == ("FakeSMTPSSL" if ssl_class else "FakeSMTP") and calls[0][2:4] == ("smtp.example.com", port)
    assert ("starttls" in kinds) == (security == "starttls")
    assert ("login", "user", "pw") in calls
    assert ("send", "klipy@example.pl", ["coach@example.com"]) in calls
    assert kinds[-1] == "quit"


def test_smtp_problems_are_named(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    assert "SMTP_HOST" in mail.smtp_problem()
    monkeypatch.setattr(config, "SMTP_HOST", "h")
    monkeypatch.setattr(config, "MAIL_FROM", "not-an-address")
    assert "MAIL_FROM" in mail.smtp_problem()
    monkeypatch.setattr(config, "MAIL_FROM", "a@b.pl")
    monkeypatch.setattr(config, "SMTP_SECURITY", "tls1")
    assert "SECURITY" in mail.smtp_problem()
    monkeypatch.setattr(config, "SMTP_SECURITY", "ssl")
    assert mail.smtp_problem() is None


# ---------- worker ----------

def test_the_worker_thread_checks_once_per_interval_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(digest, "run_due", lambda db: calls.append(db))
    stop = threading.Event()
    stop.set()
    worker.digest_loop(stop, interval=0)
    assert len(calls) == 1


def test_the_worker_thread_survives_a_failing_check(monkeypatch, caplog):
    def boom(db):
        raise RuntimeError("db locked")

    monkeypatch.setattr(digest, "run_due", boom)
    stop = threading.Event()
    stop.set()
    worker.digest_loop(stop, interval=0)
    assert "nie powiodło" in caplog.text
