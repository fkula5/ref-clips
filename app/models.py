"""Model danych. Od początku pod wielu użytkowników (autor, rola, widoczność)."""
from __future__ import annotations

import datetime as dt
from datetime import datetime

from sqlalchemy import (Column, Date, DateTime, Float, ForeignKey, Integer, String,
                        Table, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# --- słowniki wartości (przechowywane jako zwykłe napisy) ---------------------
USER_ROLES = {"referee": "sędzia", "coach": "szkoleniowiec", "admin": "admin"}
MATCH_ROLES = {"crew_chief": "Sędzia główny (R)", "umpire": "Sędzia pomocniczy (U)"}
VIDEO_SOURCES = {"upload": "Plik", "veo": "Veo", "phone": "Telefon", "youtube": "YouTube"}
VIDEO_STATUSES = {
    "uploading": "wgrywanie",
    "queued": "w kolejce do konwersji",
    "processing": "konwersja",
    "ready": "gotowe",
    "error": "błąd",
}
RATINGS = {"correct": "poprawna", "incorrect": "błędna", "doubtful": "wątpliwa", "discuss": "do omówienia"}
VISIBILITIES = {"private": "prywatny", "group": "grupa", "library": "biblioteka"}
DECISION_STATUSES = {"new": "nowy", "queued": "w kolejce do cięcia", "cut": "wycięty", "error": "błąd cięcia"}
PERIODS = ["Q1", "Q2", "Q3", "Q4", "OT1", "OT2", "OT3"]

decision_tags = Table(
    "decision_tags",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Referee(Base):
    """Sędzia jako osoba (może być powiązany z kontem użytkownika w etapie 2)."""
    __tablename__ = "referees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    level: Mapped[str] = mapped_column(String(100), default="")
    team_a_name: Mapped[str] = mapped_column(String(100), default="")
    team_a_color: Mapped[str] = mapped_column(String(50), default="białe")
    team_b_name: Mapped[str] = mapped_column(String(100), default="")
    team_b_color: Mapped[str] = mapped_column(String(50), default="ciemne")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    referees: Mapped[list[MatchReferee]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="MatchReferee.id")
    videos: Mapped[list[Video]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Video.id")
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="match", cascade="all, delete-orphan")

    @property
    def title(self) -> str:
        a = self.team_a_name or self.team_a_color or "A"
        b = self.team_b_name or self.team_b_color or "B"
        return f"{self.date.isoformat()} · {a} – {b}"

    def team_label(self, key: str | None) -> str:
        if key == "a":
            return self.team_a_name or self.team_a_color
        if key == "b":
            return self.team_b_name or self.team_b_color
        return ""


class MatchReferee(Base):
    __tablename__ = "match_referees"
    __table_args__ = (UniqueConstraint("match_id", "referee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    referee_id: Mapped[int] = mapped_column(ForeignKey("referees.id"))
    role: Mapped[str] = mapped_column(String(20), default="umpire")

    match: Mapped[Match] = relationship(back_populates="referees")
    referee: Mapped[Referee] = relationship()


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(20), default="upload")
    label: Mapped[str] = mapped_column(String(100), default="")
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    original_path: Mapped[str | None] = mapped_column(String(500))  # względem DATA_DIR
    proxy_path: Mapped[str | None] = mapped_column(String(500))     # względem DATA_DIR
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match: Mapped[Match] = relationship(back_populates="videos")
    marks: Mapped[list[PeriodMark]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="PeriodMark.time_sec")
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Decision.time_sec")
    jobs: Mapped[list[Job]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Job.id")

    @property
    def display_name(self) -> str:
        return self.label or self.original_filename or f"Nagranie {self.id}"

    @property
    def latest_job(self) -> Job | None:
        transcodes = [j for j in self.jobs if j.type == "transcode"]
        return transcodes[-1] if transcodes else None


class PeriodMark(Base):
    """Początek kwarty (Q1..Q4, OT*) w czasie nagrania."""
    __tablename__ = "period_marks"
    __table_args__ = (UniqueConstraint("video_id", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(10))
    time_sec: Mapped[float] = mapped_column(Float)

    video: Mapped[Video] = relationship(back_populates="marks")


class Tag(Base):
    """Słownik tagów; aliasy rozdzielone przecinkami (używane przez parser notatek)."""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=100)

    @property
    def alias_list(self) -> list[str]:
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class Decision(Base):
    """Decyzja sędziowska = klip."""
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    referee_id: Mapped[int | None] = mapped_column(ForeignKey("referees.id"))
    team: Mapped[str | None] = mapped_column(String(1))  # "a" / "b"
    time_sec: Mapped[float] = mapped_column(Float)
    margin_before: Mapped[float] = mapped_column(Float, default=10.0)
    margin_after: Mapped[float] = mapped_column(Float, default=10.0)
    description: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="new")
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    clip_path: Mapped[str | None] = mapped_column(String(500))  # względem DATA_DIR
    clip_version: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    match: Mapped[Match] = relationship(back_populates="decisions")
    video: Mapped[Video] = relationship(back_populates="decisions")
    referee: Mapped[Referee | None] = relationship()
    author: Mapped[User | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=decision_tags, order_by="Tag.sort, Tag.name")
    comments: Mapped[list[Comment]] = relationship(
        back_populates="decision", cascade="all, delete-orphan", order_by="Comment.id")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    at_sec: Mapped[float | None] = mapped_column(Float)  # moment w klipie
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    decision: Mapped[Decision] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))  # transcode / cut / download
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/done/error
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    error: Mapped[str | None] = mapped_column(Text)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    video: Mapped[Video | None] = relationship(back_populates="jobs")
