"""deploy.sh pipes this file into `python -` of the running container, so it works on images that
predate this module; use only stable parts of the app.
Exit code: 0 idle, 1 busy (first line starts with ZAJĘTE), 2 check failed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Clip, Job, UploadSession, Video
from app.timeutil import utcnow

ACTIVE_UPLOAD_MINUTES = 10
GB = 1024 ** 3
MB = 1024 ** 2

JOB_NAMES = {"transcode": "konwersja", "cut": "wycinanie klipu"}


def _size(value: int) -> str:
    text = f"{value / GB:.1f} GB" if value >= GB else f"{value / MB:.0f} MB"
    return text.replace(".", ",")


def _ago(moment: datetime, now: datetime) -> str:
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "przed chwilą"
    return f"{seconds // 60} min temu"


def _job_target(db: Session, job: Job) -> str:
    if job.type == "transcode" and (video := db.get(Video, job.video_id)):
        name = video.original_filename or video.label
        return f"nagrania #{video.id}" + (f" ({name})" if name else "")
    if job.type == "cut" and (clip := db.get(Clip, job.clip_id)):
        return f"#{clip.id}"
    return f"#{job.id}"


def busy_items(db: Session, now: datetime | None = None,
               active_minutes: int = ACTIVE_UPLOAD_MINUTES) -> list[str]:
    now = now or utcnow()
    items: list[str] = []

    since = now - timedelta(minutes=active_minutes)
    for up in db.scalars(select(UploadSession).where(
            UploadSession.offset_bytes < UploadSession.size_bytes, UploadSession.updated_at >= since)
            .order_by(UploadSession.updated_at.desc())):
        items.append(f"upload {up.filename or '(bez nazwy)'} — {_size(up.offset_bytes)}/{_size(up.size_bytes)}, "
                     f"ostatnia aktywność {_ago(up.updated_at, now)}")

    for job in db.scalars(select(Job).where(Job.status == "running").order_by(Job.id)):
        percent = round((job.progress or 0) * 100)
        items.append(f"{JOB_NAMES.get(job.type, job.type)} {_job_target(db, job)} — {percent}%")

    waiting: dict[str, int] = {}
    for job in db.scalars(select(Job).where(Job.status == "pending")):
        if job.type == "cut":
            clip = db.get(Clip, job.clip_id)
            video = clip.video if clip else None
            if video is None or video.purged_at is not None or video.status not in ("ready", "queued", "processing"):
                continue  # the worker never picks up cutting for an errored or deleted recording
        waiting[job.type] = waiting.get(job.type, 0) + 1
    if waiting:
        parts = ", ".join(f"{JOB_NAMES.get(kind, kind)} ×{count}" for kind, count in sorted(waiting.items()))
        items.append(f"w kolejce: {sum(waiting.values())} {_zadan(sum(waiting.values()))} ({parts})")
    return items


def _zadan(count: int) -> str:
    if count == 1:
        return "zadanie"
    return "zadania" if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else "zadań"


def idle_uploads(db: Session, now: datetime | None = None, active_minutes: int = ACTIVE_UPLOAD_MINUTES) -> int:
    since = (now or utcnow()) - timedelta(minutes=active_minutes)
    return len(db.scalars(select(UploadSession.id).where(
        UploadSession.offset_bytes < UploadSession.size_bytes, UploadSession.updated_at < since)).all())


def main() -> int:
    try:
        with SessionLocal() as db:
            items, idle = busy_items(db), idle_uploads(db)
    except Exception as exc:  # noqa: BLE001
        print(f"BŁĄD sprawdzania zajętości: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if items:
        print("ZAJĘTE — trwa:")
        for item in items:
            print(f"  - {item}")
    else:
        print("Wolne — nic nie trwa.")
    if idle:
        print(f"(niedokończone uploady bez aktywności od ponad {ACTIVE_UPLOAD_MINUTES} min: {idle} — "
              "nie blokują; wznowią się po wdrożeniu)")
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
