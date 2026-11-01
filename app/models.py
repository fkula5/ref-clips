"""Model danych (rozdział 4 planu technicznego).

Wartości słownikowe (role, funkcje, statusy) są zwykłymi napisami; spójność pilnują
ograniczenia CHECK w bazie.
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# --- słowniki wartości --------------------------------------------------------
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


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# --- konta --------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # zawsze małymi literami
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None do czasu aktywacji
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
    """Sesja logowania; w bazie tylko hash tokenu z ciasteczka."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship(lazy="joined")


class Invite(Base):
    """Jednorazowy link ustawienia hasła (aktywacja konta albo reset)."""
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
    """Nieudane próby logowania (limit 5 / 15 min na konto i na adres IP)."""
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, index=True)


# --- mecze --------------------------------------------------------------------
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

    @property
    def title(self) -> str:
        a = self.team_a_name or self.team_a_color or "A"
        b = self.team_b_name or self.team_b_color or "B"
        return f"{self.date.isoformat()} · {a} – {b}"

    def official(self, function: str) -> MatchOfficial | None:
        return next((o for o in self.officials if o.function == function), None)


class MatchOfficial(Base):
    """Pozycja w obsadzie: konto (user_id) albo wpisane imię i nazwisko (name)."""
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


# --- nagrania -----------------------------------------------------------------
class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(100), default="")
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    original_path: Mapped[str | None] = mapped_column(String(500))  # względem DATA_DIR
    proxy_path: Mapped[str | None] = mapped_column(String(500))     # względem DATA_DIR
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    # Zawartość pliku: "full" (cały mecz) albo kwarty po przecinku, np. "Q1" lub "Q1,Q2".
    content: Mapped[str] = mapped_column(String(50), default="full")
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # koniec retencji pełnego nagrania
    purged_at: Mapped[datetime | None] = mapped_column(DateTime)   # kiedy usunięto pełne nagranie

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
    """Wznawialne wgrywanie (tus) — używane od segmentu 3."""
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    offset_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    # Notatki do pliku (jedna linia = jeden moment); zamieniane na klipy po zakończeniu wgrywania.
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PeriodMark(Base):
    """Początek kwarty (Q1..Q4, OT*) w czasie nagrania."""
    __tablename__ = "period_marks"
    __table_args__ = (UniqueConstraint("video_id", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(10))
    time_sec: Mapped[float] = mapped_column(Float)

    video: Mapped[Video] = relationship(back_populates="marks")


# --- słownik kategorii, klipy, oceny, komentarze -------------------------------
class Category(Base):
    """Kategoria klipu z grupą; aliasy (po przecinku) czyta parser notatek."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)  # „własna”: nazwa wpisywana ręcznie
    sort: Mapped[int] = mapped_column(Integer, default=100)

    @property
    def alias_list(self) -> list[str]:
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class Clip(Base):
    """Klip wycinany ze znacznika. `described_at = None` oznacza klip nieopisany."""
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    official_id: Mapped[int | None] = mapped_column(ForeignKey("match_officials.id", ondelete="SET NULL"))
    whole_team: Mapped[bool] = mapped_column(Boolean, default=False)  # „cały zespół”
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    custom_category: Mapped[str | None] = mapped_column(String(100))  # nazwa dla kategorii „własna”
    time_sec: Mapped[float] = mapped_column(Float)  # moment znacznika w czasie nagrania
    margin_before: Mapped[float] = mapped_column(Float, default=15.0)
    margin_after: Mapped[float] = mapped_column(Float, default=15.0)
    description: Mapped[str] = mapped_column(Text, default="")
    described_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="new")
    clip_path: Mapped[str | None] = mapped_column(String(500))  # względem DATA_DIR
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
    """Ocena szkoleniowca; jedna na parę (klip, szkoleniowiec). Interfejs: segment 6."""
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
    """Komentarz do meczu (match_id) albo do klipu (clip_id) — dokładnie jedno z nich."""
    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(
            "(match_id IS NOT NULL AND clip_id IS NULL) OR (match_id IS NULL AND clip_id IS NOT NULL)",
            name="match_or_clip"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    clip_id: Mapped[int | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)

    match: Mapped[Match | None] = relationship(back_populates="comments")
    clip: Mapped[Clip | None] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


# --- kolejka zadań i ustawienia --------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))  # transcode / cut (dalej: retention, cleanup)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/done/error
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
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
