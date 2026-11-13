"""Daily e-mail digest. One message per account per day, grouped by match, only when something happened.

Events 1 and 2 (clips described, matches created in the groups the recipient coaches) are computed from
the data when the digest is built and never touch the bell. Events 3-5 are read from the `Notification`
rows created in the window, read or not, so the recipient rules are exactly the bell's.

A run covers (last_digest_until, now]. The end is stored after every run, including one with nothing to
send, and a failed send stores nothing, so the next check retries with the same start. The window is
capped so that downtime or a long-off account does not produce a backlog.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import config, mail, notify, security
from app.models import (DIGEST_EVENTS, RATING_VERDICTS, Clip, Comment, EmailPreference, GroupMember, Match,
                        MatchOfficial, Notification, User)
from app.timeutil import local, local_tz, to_local, utcnow

log = logging.getLogger("digest")

COMMENT_KINDS = ("clip_comment", "match_comment")
RATING_KINDS = ("rating", "rating_changed")
SNIPPETS_PER_MATCH = 5
SNIPPET_MAX_CHARS = 140
SNIPPET_PAIRING_SECONDS = 10  # Comment.created_at is a whole second, the notification's is not
COACH_DEFAULTS = frozenset({"new_clips_in_groups", "new_match_in_groups", "comments_and_ratings", "group_added"})
REFEREE_DEFAULTS = frozenset({"comments_and_ratings", "sheet_published", "group_added"})
GROUP_EVENTS = ("new_clips_in_groups", "new_match_in_groups")  # only meaningful for someone who can coach a group

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates" / "email"),
                   autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


def default_for(roles) -> set[str]:
    """Roles add up; the admin role gives nothing by itself."""
    wanted: set[str] = set()
    if "coach" in roles:
        wanted |= COACH_DEFAULTS
    if "referee" in roles:
        wanted |= REFEREE_DEFAULTS
    return wanted


def enabled_events(user: User, pref: EmailPreference | None) -> set[str]:
    defaults = default_for(user.roles)
    enabled = set()
    for event in DIGEST_EVENTS:
        chosen = getattr(pref, event) if pref is not None else None
        if (event in defaults) if chosen is None else chosen:
            enabled.add(event)
    return enabled


def configurable_events(user: User) -> list[str]:
    """The switches the settings page shows: group events only to those who can coach a group."""
    can_coach = bool(user.roles & {"coach", "admin"})
    return [event for event in DIGEST_EVENTS if can_coach or event not in GROUP_EVENTS]


def get_pref(db: Session, user_id: int) -> EmailPreference:
    pref = db.get(EmailPreference, user_id)
    if pref is None:
        pref = EmailPreference(user_id=user_id, digest_enabled=True)
        db.add(pref)
        db.flush()
    return pref


def ensure_token(pref: EmailPreference) -> str:
    if not pref.unsubscribe_token:
        pref.unsubscribe_token = security.new_token()
    return pref.unsubscribe_token


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


@dataclass
class Snippet:
    text: str
    url: str


@dataclass
class Entry:
    text: str
    url: str | None = None
    snippets: list[Snippet] = field(default_factory=list)
    more: int = 0


@dataclass
class Section:
    title: str
    url: str | None
    entries: list[Entry]


@dataclass
class Digest:
    sections: list[Section]
    since: datetime
    until: datetime

    @property
    def empty(self) -> bool:
        return not self.sections


@dataclass
class _MatchBlock:
    match: Match
    new_match: bool = False
    clips: Counter = field(default_factory=Counter)
    comments: list[Notification] = field(default_factory=list)
    ratings: list[Notification] = field(default_factory=list)
    sheets: list[Notification] = field(default_factory=list)


def digest_time(now: datetime) -> datetime:
    """Today's DIGEST_HOUR in the local zone, as the naive UTC the database uses. 07:00 is never inside a
    DST gap, so no special handling is needed.
    """
    today = to_local(now).date()
    start = datetime.combine(today, time(config.DIGEST_HOUR), tzinfo=local_tz())
    return start.astimezone(UTC).replace(tzinfo=None)


def window_start(last: datetime | None, until: datetime) -> datetime:
    if last is None:
        return until - timedelta(hours=config.DIGEST_FIRST_WINDOW_HOURS)
    return max(last, until - timedelta(hours=config.DIGEST_MAX_WINDOW_HOURS))


def _coached_matches(user_id: int):
    """Matches whose crew includes a referee of a group the user coaches."""
    coached = select(GroupMember.group_id).where(GroupMember.user_id == user_id, GroupMember.role == "coach")
    return (select(MatchOfficial.match_id)
            .join(GroupMember, GroupMember.user_id == MatchOfficial.user_id)
            .where(GroupMember.role == "referee", GroupMember.group_id.in_(coached)))


def _first_words(text: str) -> str:
    words = text.split()
    shown = " ".join(words[:config.DIGEST_SNIPPET_WORDS])
    cut = len(words) > config.DIGEST_SNIPPET_WORDS or len(shown) > SNIPPET_MAX_CHARS
    return shown[:SNIPPET_MAX_CHARS].rstrip() + ("…" if cut else "")


def _comment_texts(db: Session, notes: list[Notification]) -> dict[int, str]:
    """Notification id -> text of the comment it announced. A notification does not point at its comment,
    so the comment is the nearest one by the same author on the same target; a deleted comment has no text.
    """
    if not notes:
        return {}
    slack = timedelta(seconds=SNIPPET_PAIRING_SECONDS)
    lo, hi = min(n.created_at for n in notes) - slack, max(n.created_at for n in notes) + slack
    clip_ids = {n.clip_id for n in notes if n.kind == "clip_comment"}
    match_ids = {n.match_id for n in notes if n.kind == "match_comment"}
    candidates = list(db.scalars(select(Comment).where(
        Comment.created_at >= lo, Comment.created_at <= hi, Comment.author_id.in_({n.actor_id for n in notes}),
        or_(Comment.clip_id.in_(clip_ids), Comment.match_id.in_(match_ids))).order_by(Comment.id)))
    found: dict[int, str] = {}
    used: set[int] = set()
    for note in notes:
        near = [c for c in candidates if c.id not in used and c.author_id == note.actor_id
                and (c.clip_id == note.clip_id if note.kind == "clip_comment" else c.match_id == note.match_id)
                and abs(c.created_at - note.created_at) <= slack]
        if near:
            best = min(near, key=lambda c: abs(c.created_at - note.created_at))
            used.add(best.id)
            found[note.id] = best.body
    return found


def _actor_name(note: Notification) -> str:
    return note.actor.name if note.actor else "Ktoś"


def collect(db: Session, user: User, pref: EmailPreference | None, since: datetime, until: datetime,
            base: str) -> Digest:
    events = enabled_events(user, pref)
    blocks: dict[int, _MatchBlock] = {}

    def block(match: Match) -> _MatchBlock:
        return blocks.setdefault(match.id, _MatchBlock(match))

    if "new_clips_in_groups" in events:
        clips = db.scalars(select(Clip).where(
            Clip.match_id.in_(_coached_matches(user.id)), Clip.described_at > since, Clip.described_at <= until,
            or_(Clip.described_by_id.is_(None), Clip.described_by_id != user.id))
            .options(selectinload(Clip.category), selectinload(Clip.match)))
        for clip in clips:
            block(clip.match).clips[clip.category_label or "bez kategorii"] += 1

    if "new_match_in_groups" in events:
        for match in db.scalars(select(Match).where(
                Match.id.in_(_coached_matches(user.id)), Match.created_at > since, Match.created_at <= until,
                or_(Match.created_by.is_(None), Match.created_by != user.id))):
            block(match).new_match = True

    kinds = []
    if "comments_and_ratings" in events:
        kinds += [*COMMENT_KINDS, *RATING_KINDS]
    if "sheet_published" in events:
        kinds.append("sheet_published")
    if "group_added" in events:
        kinds.append("group_added")
    notes = list(db.scalars(
        select(Notification).where(Notification.recipient_id == user.id, Notification.kind.in_(kinds),
                                   Notification.created_at > since, Notification.created_at <= until)
        .options(selectinload(Notification.actor), selectinload(Notification.match),
                 selectinload(Notification.group), selectinload(Notification.sheet))
        .order_by(Notification.id))) if kinds else []

    group_notes = []
    for note in notes:
        if note.kind == "group_added":
            group_notes.append(note)
        elif note.match is None:
            continue
        elif note.kind in COMMENT_KINDS:
            block(note.match).comments.append(note)
        elif note.kind in RATING_KINDS:
            block(note.match).ratings.append(note)
        else:
            block(note.match).sheets.append(note)

    texts = _comment_texts(db, [n for b in blocks.values() for n in b.comments])
    sections = [_section(b, texts, base) for b in sorted(
        blocks.values(), key=lambda b: (b.match.date, b.match.id), reverse=True)]
    if group_notes:
        sections.append(Section("Grupy", None, [_group_entry(n, base) for n in group_notes]))
    return Digest(sections, since, until)


def _section(b: _MatchBlock, texts: dict[int, str], base: str) -> Section:
    match, match_url = b.match, f"{base}/matches/{b.match.id}"
    entries = []
    if b.new_match:
        crew = ", ".join(o.label for o in match.officials) or "brak"
        entries.append(Entry(f"Nowy mecz: {match.title}, obsada: {crew}", match_url))
    if b.clips:
        total = sum(b.clips.values())
        parts = ", ".join(f"{n}× {name}" for name, n in sorted(b.clips.items(), key=lambda kv: (-kv[1], kv[0])))
        entries.append(Entry(f"{total} {plural(total, 'nowy klip', 'nowe klipy', 'nowych klipów')} ({parts})",
                             match_url))
    if b.comments or b.ratings:
        counts = []
        if b.comments:
            counts.append(f"{len(b.comments)} {plural(len(b.comments), 'komentarz', 'komentarze', 'komentarzy')}")
        if b.ratings:
            counts.append(f"{len(b.ratings)} {plural(len(b.ratings), 'ocena', 'oceny', 'ocen')}")
        snippets = []
        for note in sorted([*b.comments, *b.ratings], key=lambda n: n.id):
            if note.kind in RATING_KINDS:
                verdict = RATING_VERDICTS.get(note.verdict or "", "")
                verb = "zmienił(a) ocenę" if note.kind == "rating_changed" else "ocenił(a) klip"
                snippets.append(Snippet(f"{_actor_name(note)} {verb}: {verdict}", f"{base}{notify.target_url(note)}"))
            elif note.id in texts:
                snippets.append(Snippet(f"{_actor_name(note)}: „{_first_words(texts[note.id])}”",
                                        f"{base}{notify.target_url(note)}"))
        entries.append(Entry(", ".join(counts), match_url, snippets[:SNIPPETS_PER_MATCH],
                             max(0, len(snippets) - SNIPPETS_PER_MATCH)))
    for note in b.sheets:
        entries.append(Entry(f"Opublikowano arkusz oceny (szkoleniowiec: {_actor_name(note)})",
                             f"{base}{notify.target_url(note)}"))
    return Section(f"Mecz {match.title}", match_url, entries)


def _group_entry(note: Notification, base: str) -> Entry:
    names = ", ".join(m.user.name for m in note.group.coaches)
    label = plural(len(note.group.coaches), "szkoleniowiec", "szkoleniowcy", "szkoleniowcy")
    suffix = f" ({label}: {names})" if names else ""
    return Entry(f"Dodano Cię do grupy {note.group.name}{suffix}", f"{base}{notify.target_url(note)}")


def build_message(user: User, digest: Digest, base: str, token: str, *, test: bool = False) -> EmailMessage:
    unsubscribe = f"{base}/unsubscribe/{token}"
    context = {"user": user, "digest": digest, "test": test, "settings_url": f"{base}/settings/notifications",
               "unsubscribe_url": unsubscribe, "app_url": base,
               "period": f"{local(digest.since, '%d.%m.%Y %H:%M')} – {local(digest.until, '%d.%m.%Y %H:%M')}"}
    message = EmailMessage()
    sender_domain = config.MAIL_FROM.rsplit("@", 1)[-1] if "@" in config.MAIL_FROM else "localhost"
    message["From"] = Address(config.MAIL_FROM_NAME, addr_spec=config.MAIL_FROM or f"ref-clips@{sender_domain}")
    message["To"] = Address(user.name, addr_spec=user.email)
    message["Subject"] = f"{'[TEST] ' if test else ''}ref-clips: podsumowanie {local(digest.until, '%d.%m.%Y')}"
    message["Date"] = format_datetime(utcnow().replace(tzinfo=UTC))
    message["Message-ID"] = make_msgid(domain=sender_domain)
    message["Auto-Submitted"] = "auto-generated"
    message["List-Unsubscribe"] = f"<{unsubscribe}>"
    message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    # Quoted-printable keeps the body 7-bit, so it passes servers that do not offer 8BITMIME.
    message.set_content(_env.get_template("digest.txt").render(**context), cte="quoted-printable")
    message.add_alternative(_env.get_template("digest.html").render(**context), subtype="html",
                            cte="quoted-printable")
    return message


def base_url() -> str:
    return config.PUBLIC_URL or ("http://localhost:8000" if mail.is_dry_run() else "")


def disabled_reason() -> str | None:
    if mail.get_sender() is None:
        return mail.smtp_problem()
    return None if base_url() else "REFCLIPS_PUBLIC_URL is not set (links need it)"


def send_test(db: Session, user: User, sender: mail.Sender, base: str, now: datetime | None = None) -> bool:
    """For the admin's "send me a test" button: the last 24 hours, to the admin only, ignoring the schedule
    and the master switch, and without touching `last_digest_until`. Returns whether there was news; an
    empty digest is sent too, because the point is to see that delivery works.
    """
    until = now or utcnow()
    pref = get_pref(db, user.id)
    digest = collect(db, user, pref, until - timedelta(hours=config.DIGEST_FIRST_WINDOW_HOURS), until, base)
    token = ensure_token(pref)
    db.commit()
    sender.send(build_message(user, digest, base, token, test=True))
    return not digest.empty


def run_due(db: Session, *, now: datetime | None = None, sender: mail.Sender | None = None,
            base: str | None = None) -> int:
    """Sends the digests that are due; returns how many messages went out. Safe to call as often as you
    like: an account that already has a run recorded since today's DIGEST_HOUR is skipped.
    """
    now = now or utcnow()
    start = digest_time(now)
    if now < start:
        return 0
    sender = sender or mail.get_sender()
    if sender is None:
        return 0
    base = base if base is not None else base_url()
    if not base:
        mail.log_once("no-base-url", "E-mail digest is disabled: REFCLIPS_PUBLIC_URL is not set (links need it)")
        return 0
    due = list(db.scalars(
        select(User.id).outerjoin(EmailPreference, EmailPreference.user_id == User.id)
        .where(User.is_active.is_(True), User.password_hash.is_not(None),
               or_(EmailPreference.digest_enabled.is_(None), EmailPreference.digest_enabled.is_(True)),
               or_(EmailPreference.last_digest_until.is_(None), EmailPreference.last_digest_until < start))
        .order_by(User.id)))
    sent = failures = 0
    for user_id in due:
        try:
            user = db.get(User, user_id)
            pref = get_pref(db, user_id)
            digest = collect(db, user, pref, window_start(pref.last_digest_until, now), now, base)
            if not digest.empty:
                token = ensure_token(pref)
                db.commit()
                sender.send(build_message(user, digest, base, token))
                sent += 1
                failures = 0  # only a delivered message says the server works
            pref.last_digest_until = now
            db.commit()
        except Exception:  # noqa: BLE001 - one account's failure must not stop the others
            db.rollback()
            failures += 1
            log.warning("Digest for account %s failed; it will be retried at the next check", user_id,
                        exc_info=True)
            if failures >= config.DIGEST_ABORT_AFTER_FAILURES:
                log.warning("Digest: %d failures in a row, the rest waits for the next check", failures)
                break
    return sent
