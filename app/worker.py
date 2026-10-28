"""Worker: pętla wykonująca zadania z tabeli jobs. Uruchomienie: python -m app.worker"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app import services, video as vid
from app.db import SessionLocal
from app.models import Decision, Job, Video
from app.storage import storage

log = logging.getLogger("worker")
POLL_SECONDS = 2.0


def claim_next(db: Session) -> Job | None:
    """Pobiera najstarsze oczekujące zadanie. Cięcie czeka, aż nagranie będzie gotowe."""
    ready_video = exists().where(and_(Video.id == Job.video_id, Video.status == "ready"))
    candidate = db.scalar(
        select(Job.id)
        .where(Job.status == "pending", or_(Job.type == "transcode", ready_video))
        .order_by(Job.id).limit(1)
    )
    if candidate is None:
        return None
    claimed = db.execute(
        update(Job).where(Job.id == candidate, Job.status == "pending")
        .values(status="running", started_at=datetime.now())
    )
    db.commit()
    return db.get(Job, candidate) if claimed.rowcount else None


def run_transcode(db: Session, job: Job) -> None:
    video = db.get(Video, job.video_id)
    video.status = "processing"
    db.commit()
    src = storage.local_path(video.original_path)
    info = vid.probe(src)
    video.duration, video.fps = info["duration"], info["fps"]
    db.commit()

    proxy_key = f"proxies/{video.id}.mp4"
    last = [0.0]

    def on_progress(value: float) -> None:
        if time.monotonic() - last[0] > 1.5:
            last[0] = time.monotonic()
            job.progress = value
            db.commit()

    vid.transcode_to_proxy(src, storage.local_path(proxy_key), video.duration, on_progress)
    final = vid.probe(storage.local_path(proxy_key))  # czas trwania wersji roboczej jest wiążący
    video.duration, video.fps = final["duration"] or video.duration, final["fps"] or video.fps
    video.proxy_path = proxy_key
    video.status = "ready"


def run_cut(db: Session, job: Job) -> None:
    decision = db.get(Decision, job.decision_id)
    if decision is None:
        return
    video = decision.video
    start, end = services.decision_bounds(decision)
    version = decision.clip_version + 1
    key = f"clips/{decision.id}_v{version}.mp4"
    vid.cut_clip(storage.local_path(video.proxy_path), storage.local_path(key), start, end - start)
    old = decision.clip_path
    decision.clip_path, decision.clip_version = key, version
    decision.status, decision.error = "cut", None
    db.flush()
    if old and old != key:
        storage.delete(old)


HANDLERS = {"transcode": run_transcode, "cut": run_cut}


def process_job(db: Session, job: Job) -> None:
    try:
        HANDLERS[job.type](db, job)
        job.status, job.progress, job.error = "done", 1.0, None
    except Exception as exc:  # noqa: BLE001 - błąd zadania nie może zabić workera
        log.exception("Zadanie %s nie powiodło się", job.id)
        db.rollback()
        job = db.get(Job, job.id)
        job.status, job.error = "error", str(exc)[:2000]
        if job.type == "transcode" and (video := db.get(Video, job.video_id)):
            video.status, video.error = "error", job.error
        if job.type == "cut" and (decision := db.get(Decision, job.decision_id)):
            decision.status, decision.error = "error", job.error
    job.finished_at = datetime.now()
    db.commit()


def run_once() -> bool:
    """Wykonuje jedno zadanie, jeśli jest dostępne. Zwraca True, gdy coś zrobiono."""
    if not vid.ffmpeg_available():
        return False  # zadania czekają w kolejce, aż ffmpeg będzie zainstalowany
    with SessionLocal() as db:
        job = claim_next(db)
        if job is None:
            return False
        log.info("Zadanie %s (%s)", job.id, job.type)
        process_job(db, job)
        return True


def recover_interrupted() -> None:
    """Zadania przerwane przez zatrzymanie workera wracają do kolejki."""
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "running")):
            job.status, job.progress = "pending", 0.0
            if job.type == "transcode" and (video := db.get(Video, job.video_id)):
                video.status = "queued"
        db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from app.initdb import init_db
    init_db()
    recover_interrupted()
    warned_at = 0.0
    log.info("Worker uruchomiony")
    while True:
        try:
            if run_once():
                continue
            if not vid.ffmpeg_available() and time.monotonic() - warned_at > 60:
                warned_at = time.monotonic()
                log.warning("Brak ffmpeg — uruchom: sudo apt install ffmpeg (zadania czekają)")
        except Exception:  # noqa: BLE001
            log.exception("Błąd pętli workera")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
