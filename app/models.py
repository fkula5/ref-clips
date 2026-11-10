"""Value dictionaries (roles, functions, statuses) are plain strings; consistency is enforced by CHECK
constraints.
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

USER_ROLES = {"admin": "administrator", "coach": "szkoleniowiec", "referee": "sędzia"}
OFFICIAL_FUNCTIONS = {"CC": "CC (pierwszy)", "U1": "U1 (drugi)", "U2": "U2 (trzeci)"}
INVITE_PURPOSES = {"activate": "aktywacja konta", "reset": "reset hasła"}
VIDEO_STATUSES = {
    "uploading": "wgrywanie",
    "queued": "w kolejce do konwersji",
    "processing": "konwersja",
    "ready": "gotowe",
    "error": "błąd",
}
CLIP_STATUSES = {"new": "nowy", "queued": "w kolejce do cięcia", "cut": "wycięty", "error": "błąd cięcia"}
RATING_VERDICTS = {"correct": "prawidłowa", "incorrect": "nieprawidłowa", "debatable": "dyskusyjna"}
PERIODS = ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"]
SHEET_DIFFICULTIES = {"latwy": "łatwy", "normalny": "normalny", "trudny": "trudny"}
SHEET_STATUSES = {"draft": "szkic", "published": "opublikowany"}
NOTIFICATION_KINDS = {
    "rating": "nowa ocena klipu", "rating_changed": "zmieniona ocena klipu",
    "clip_comment": "komentarz do klipu", "match_comment": "komentarz do meczu",
    "sheet_published": "opublikowany arkusz oceny",
}


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # always lowercase
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None until activation
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    role_rows: Mapped[list[UserRole]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="UserRole.role")

    @property
    def roles(self) -> set[str]:
        return {r.role for r in self.role_rows}

    def set_roles(self, roles) -> None:
        wanted = set(roles)
        self.role_rows = [r for r in self.role_rows if r.role in wanted]
        have = {r.role for r in self.role_rows}
        self.role_rows.extend(UserRole(role=r) for r in sorted(wanted - have))


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint(_in("role", USER_ROLES), name="role_valid"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)


class AuthSession(Base):
    """Only the hash of the cookie token is stored."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship(lazy="joined")


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (CheckConstraint(_in("purpose", INVITE_PURPOSES), name="purpose_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    level: Mapped[str] = mapped_column(String(100), default="")
    team_a_name: Mapped[str] = mapped_column(String(100), default="")
    team_a_color: Mapped[str] = mapped_column(String(50), default="białe")
    team_b_name: Mapped[str] = mapped_column(String(100), default="")
    team_b_color: Mapped[str] = mapped_column(String(50), default="ciemne")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    officials: Mapped[list[MatchOfficial]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="MatchOfficial.function")
    videos: Mapped[list[Video]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Video.id")
    clips: Mapped[list[Clip]] = relationship(
        back_populates="match", cascade="all, delete-orphan")
    comments: Mapped[list[Comment]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Comment.id")
    sheets: Mapped[list[Sheet]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Sheet.id")

    @property
    def teams(self) -> str:
        a = self.team_a_name or self.team_a_color or "A"
        b = self.team_b_name or self.team_b_color or "B"
        return f"{a} – {b}"

    def _title(self, date_text: str) -> str:
        return f"{date_text} · {self.teams}"

    @property
    def title(self) -> str:
        return self._title(self.date.strftime("%d.%m.%Y"))

    @property
    def export_title(self) -> str:
        """The title with the ISO date: the CSV export keeps its machine format."""
        return self._title(self.date.isoformat())

    def official(self, function: str) -> MatchOfficial | None:
        return next((o for o in self.officials if o.function == function), None)


class MatchOfficial(Base):
    """Crew slot: an account (user_id) or a typed name (name)."""
    __tablename__ = "match_officials"
    __table_args__ = (
        UniqueConstraint("match_id", "function"),
        CheckConstraint(_in("function", OFFICIAL_FUNCTIONS), name="function_valid"),
        CheckConstraint(
            "(user_id IS NOT NULL AND name IS NULL) OR (user_id IS NULL AND name IS NOT NULL)",
            name="user_or_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    function: Mapped[str] = mapped_column(String(2))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str | None] = mapped_column(String(100))

    match: Mapped[Match] = relationship(back_populates="officials")
    user: Mapped[User | None] = relationship()

    @property
    def display_name(self) -> str:
        return self.user.name if self.user else (self.name or "")

    @property
    def label(self) -> str:
        return f"{self.function} · {self.display_name}"


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(100), default="")
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    original_path: Mapped[str | None] = mapped_column(String(500))  # relative to DATA_DIR
    proxy_path: Mapped[str | None] = mapped_column(String(500))  # relative to DATA_DIR
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    # Draft size, set after conversion (lazily backfilled for older rows) so the admin panel does not
    # stat files on every request.
    proxy_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    # File contents: "full" (whole match) or comma-separated quarters, e.g. "Q1,Q2".
    content: Mapped[str] = mapped_column(String(50), default="full")
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime)

    match: Mapped[Match] = relationship(back_populates="videos")
    marks: Mapped[list[PeriodMark]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="PeriodMark.time_sec")
    clips: Mapped[list[Clip]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Clip.time_sec")
    jobs: Mapped[list[Job]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Job.id")

    @property
    def display_name(self) -> str:
        return self.label or self.original_filename or f"Nagranie {self.id}"

    @property
    def latest_job(self) -> Job | None:
        transcodes = [j for j in self.jobs if j.type == "transcode"]
        return transcodes[-1] if transcodes else None


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    offset_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    # Notes for the file (one line = one moment); turned into clips when the upload finishes.
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class UploadRejection(Base):
    __tablename__ = "upload_rejections"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    free_bytes: Mapped[int] = mapped_column(BigInteger)

    user: Mapped[User | None] = relationship()


class PeriodMark(Base):
    __tablename__ = "period_marks"
    __table_args__ = (UniqueConstraint("video_id", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(10))
    time_sec: Mapped[float] = mapped_column(Float)

    video: Mapped[Video] = relationship(back_populates="marks")


class Category(Base):
    """Aliases (comma-separated) are read by the notes parser."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=100)

    @property
    def alias_list(self) -> list[str]:
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class Clip(Base):
    """`described_at = None` means undescribed."""
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    official_id: Mapped[int | None] = mapped_column(ForeignKey("match_officials.id", ondelete="SET NULL"))
    whole_team: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    custom_category: Mapped[str | None] = mapped_column(String(100))
    time_sec: Mapped[float] = mapped_column(Float)
    margin_before: Mapped[float] = mapped_column(Float, default=15.0)
    margin_after: Mapped[float] = mapped_column(Float, default=15.0)
    description: Mapped[str] = mapped_column(Text, default="")
    described_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="new")
    clip_path: Mapped[str | None] = mapped_column(String(500))  # relative to DATA_DIR
    clip_version: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    match: Mapped[Match] = relationship(back_populates="clips")
    video: Mapped[Video] = relationship(back_populates="clips")
    official: Mapped[MatchOfficial | None] = relationship()
    category: Mapped[Category | None] = relationship()
    author: Mapped[User | None] = relationship()
    comments: Mapped[list[Comment]] = relationship(
        back_populates="clip", cascade="all, delete-orphan", order_by="Comment.id")
    ratings: Mapped[list[Rating]] = relationship(
        back_populates="clip", cascade="all, delete-orphan", order_by="Rating.id")

    @property
    def is_described(self) -> bool:
        return self.described_at is not None

    @property
    def category_label(self) -> str:
        if self.category is None:
            return self.custom_category or ""
        if self.category.is_custom and self.custom_category:
            return self.custom_category
        return self.category.name

    @property
    def official_label(self) -> str:
        if self.whole_team:
            return "cały zespół"
        return self.official.label if self.official else ""


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("clip_id", "coach_id"),
        CheckConstraint(_in("verdict", RATING_VERDICTS), name="verdict_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    coach_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    clip: Mapped[Clip] = relationship(back_populates="ratings")
    coach: Mapped[User] = relationship()


class Comment(Base):
    """Exactly one of match_id / clip_id is set."""
    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(
            "(match_id IS NOT NULL AND clip_id IS NULL) OR (match_id IS NULL AND clip_id IS NOT NULL)",
            name="match_or_clip"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[int | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)

    match: Mapped[Match | None] = relationship(back_populates="comments")
    clip: Mapped[Clip | None] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class SheetElement(Base):
    """A sheet copies the name when it is created (`SheetRow.name`), so renaming, deactivating or
    deleting an element never changes existing sheets.
    """
    __tablename__ = "sheet_elements"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)


class Sheet(Base):
    """The header is read from the match; elements and official columns are copies taken at creation."""
    __tablename__ = "sheets"
    __table_args__ = (
        UniqueConstraint("match_id", "coach_id"),
        CheckConstraint(_in("status", SHEET_STATUSES), name="status_valid"),
        CheckConstraint("difficulty IS NULL OR " + _in("difficulty", SHEET_DIFFICULTIES), name="difficulty_valid"),
        CheckConstraint("status = 'draft' OR difficulty IS NOT NULL", name="published_has_difficulty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    coach_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    result: Mapped[str] = mapped_column(String(50), default="", server_default="")
    difficulty: Mapped[str | None] = mapped_column(String(10))
    crew_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())  # set in code, only on content change
    published_at: Mapped[datetime | None] = mapped_column(DateTime)

    match: Mapped[Match] = relationship(back_populates="sheets")
    coach: Mapped[User] = relationship()
    columns: Mapped[list[SheetColumn]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="SheetColumn.position")
    rows: Mapped[list[SheetRow]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="SheetRow.position")

    @property
    def is_published(self) -> bool:
        return self.status == "published"

    @property
    def edited_after_publishing(self) -> bool:
        return self.published_at is not None and self.updated_at > self.published_at


class SheetColumn(Base):
    """Function and name are copies because the crew may change later."""
    __tablename__ = "sheet_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    function: Mapped[str] = mapped_column(String(2))
    official_name: Mapped[str] = mapped_column(String(100), default="")
    overall: Mapped[str] = mapped_column(Text, default="", server_default="")
    recommendation: Mapped[str] = mapped_column(Text, default="", server_default="")

    sheet: Mapped[Sheet] = relationship(back_populates="columns")

    @property
    def label(self) -> str:
        return f"{self.function} · {self.official_name}"


class SheetRow(Base):
    """`element_id` only tells whether a dictionary element is in use (only an unused element can be
    deleted).
    """
    __tablename__ = "sheet_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    element_id: Mapped[int | None] = mapped_column(ForeignKey("sheet_elements.id", ondelete="SET NULL"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))

    sheet: Mapped[Sheet] = relationship(back_populates="rows")
    cells: Mapped[list[SheetCell]] = relationship(cascade="all, delete-orphan")


class SheetCell(Base):
    __tablename__ = "sheet_cells"
    # Deleting a sheet removes its columns (and, through ON DELETE CASCADE, their cells) before the ORM
    # deletes the cells itself; a DELETE that finds the row already gone is expected.
    __mapper_args__ = {"confirm_deleted_rows": False}

    row_id: Mapped[int] = mapped_column(ForeignKey("sheet_rows.id", ondelete="CASCADE"), primary_key=True)
    column_id: Mapped[int] = mapped_column(
        ForeignKey("sheet_columns.id", ondelete="CASCADE"), primary_key=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")


class ShareLink(Base):
    """Only the SHA-256 hash of the code is stored; the creator sees the code once. Validity is always
    bounded (`expires_at`).
    """
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    items: Mapped[list[ShareLinkClip]] = relationship(
        back_populates="link", cascade="all, delete-orphan", order_by="ShareLinkClip.position")


class ShareLinkClip(Base):
    """`position` (from 1) is stable and goes into public URLs instead of the clip id; deleting a clip
    (ON DELETE CASCADE) does not renumber the rest.
    """
    __tablename__ = "share_link_clips"
    __table_args__ = (UniqueConstraint("link_id", "position"),)

    link_id: Mapped[int] = mapped_column(ForeignKey("share_links.id", ondelete="CASCADE"), primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer)

    link: Mapped[ShareLink] = relationship(back_populates="items")
    clip: Mapped[Clip] = relationship()


class Notification(Base):
    """Created in the transaction of the event. Deleting the target match, clip or sheet deletes its
    notifications (a link to it would lead nowhere); deleting a comment or rating leaves them. `match_id`
    is always set, `clip_id` for clip kinds, `sheet_id` for sheets, `verdict` for ratings.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(_in("kind", NOTIFICATION_KINDS), name="kind_valid"),
        CheckConstraint("verdict IS NULL OR " + _in("verdict", RATING_VERDICTS), name="verdict_valid"),
        Index("ix_notifications_unread", "recipient_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[int | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    verdict: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
    match: Mapped[Match] = relationship()
    clip: Mapped[Clip | None] = relationship()
    sheet: Mapped[Sheet | None] = relationship()

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    clip_id: Mapped[int | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    video: Mapped[Video | None] = relationship(back_populates="jobs")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
