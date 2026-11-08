"""Worker: pętla wykonująca zadania z tabeli jobs. Uruchomienie: python -m app.worker"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import and_, case, exists, or_, select, update
from sqlalchemy.orm import Session

from app import config, health, retention, services, uploads, video as vid
from app.db import SessionLocal
from app.models import Clip, Job, Video
from app.storage import storage
from app.textutil import format_clock
from app.timeutil import utcnow

log = logging.getLogger("worker")
POLL_SECONDS = 2.0


def claim_next(db: Session) -> Job | None:
    """Pobiera oczekujące zadanie: najpierw cięcia (krótkie), potem konwersje, w obrębie typu
    najstarsze. Cięcie czeka, aż nagranie będzie gotowe."""
    ready_video = exists().where(and_(Video.id == Job.video_id, Video.status == "ready"))
    candidate = db.scalar(
        select(Job.id)
        .where(Job.status == "pending", or_(Job.type == "transcode", ready_video))
        .order_by(case((Job.type == "cut", 0), else_=1), Job.id).limit(1)
    )
    if candidate is None:
        return None
    claimed = db.execute(
        update(Job).where(Job.id == candidate, Job.status == "pending")
        .values(status="running", started_at=utcnow())
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

    proxy = storage.local_path(proxy_key)
    vid.transcode_to_proxy(src, proxy, video.duration, on_progress, src_fps=info.get("max_fps"))
    try:
        final = vid.verify_conversion(info, proxy)  # czas trwania wersji roboczej jest wiążący
    except vid.FFmpegError as exc:
        proxy.unlink(missing_ok=True)
        raise vid.FFmpegError(f"Wynik konwersji odrzucony: {exc}. Oryginał zostaje — można ponowić.") from exc
    video.duration = final["video_duration"] or final["duration"]
    video.fps = final["fps"] or video.fps
    video.proxy_path = proxy_key
    video.proxy_bytes = storage.size(proxy_key)
    original_key, video.original_path = video.original_path, None
    video.status = "ready"
    db.commit()
    try:  # retencja: oryginał znika po udanej konwersji i sprawdzeniu wyniku
        storage.delete(original_key)
    except OSError:
        log.warning("Nie udało się usunąć oryginału %s", original_key)


def run_cut(db: Session, job: Job) -> None:
    clip = db.get(Clip, job.clip_id)
    if clip is None:
        return
    video = clip.video
    if video.purged_at is not None or not video.proxy_path or not storage.exists(video.proxy_path):
        # np. nagranie usunięte (retencja, panel admina) między dodaniem znacznika a cięciem
        raise FileNotFoundError("Pełne nagranie zostało usunięte przed wycięciem klipu.")
    if video.duration is not None and clip.time_sec > video.duration + config.CUT_OUTSIDE_TOLERANCE:
        # np. moment z notatek wpisanych przy wgrywaniu, zanim znaliśmy długość nagrania
        raise ValueError(f"Moment poza nagraniem: {format_clock(clip.time_sec)} "
                         f"(nagranie trwa {format_clock(video.duration)})")
    start, end = services.clip_range(clip)
    version = clip.clip_version + 1
    key = f"clips/{clip.id}_v{version}.mp4"
    vid.cut_clip(storage.local_path(video.proxy_path), storage.local_path(key), start, end - start)
    old = clip.clip_path
    clip.clip_path, clip.clip_version = key, version
    clip.status, clip.error = "cut", None
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
        if job.type == "cut" and (clip := db.get(Clip, job.clip_id)):
            clip.status, clip.error = "error", job.error
    job.finished_at = utcnow()
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


def run_maintenance() -> None:
    """Okresowe sprzątanie (co godzinę, także zaraz po starcie): porzucone uploady (> 24 h bez
    aktywności), osierocone pliki klipów, stare wpisy o odrzuconych uploadach oraz retencja —
    usuwanie wersji roboczych po terminie, raz na dobę (`retention.run_if_due` pilnuje, żeby restart
    ani drugi worker nie uruchomił jej drugi raz). Błąd jednego kroku nie wstrzymuje pozostałych."""
    steps = (uploads.cleanup_stale, uploads.prune_rejections, retention.run_if_due,
             retention.cleanup_orphan_clips)
    for step in steps:
        try:
            with SessionLocal() as db:
                step(db)
        except Exception:  # noqa: BLE001
            log.exception("Sprzątanie: krok %s nie powiódł się", step.__name__)


def heartbeat_loop(stop: threading.Event, interval: float = config.WORKER_HEARTBEAT_SECONDS) -> None:
    """Odnawia znacznik życia (`/health`) co `interval` s do zatrzymania. Działa w osobnym wątku,
    bo konwersja ffmpeg blokuje pętlę główną nawet na godzinę. Błąd zapisu (np. zablokowana baza)
    nie zabija wątku; do logu trafia tylko pierwszy z serii błędów, żeby nie zasypywać dziennika."""
    failing = False
    while True:
        try:
            with SessionLocal() as db:
                health.record_heartbeat(db)
            if failing:
                log.info("Znacznik życia workera znów się zapisuje")
            failing = False
        except Exception:  # noqa: BLE001
            if not failing:
                log.warning("Nie udało się zapisać znacznika życia workera", exc_info=True)
            failing = True
        if stop.wait(interval):
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from app.initdb import init_db
    init_db()
    recover_interrupted()
    threading.Thread(target=heartbeat_loop, args=(threading.Event(),), name="heartbeat", daemon=True).start()
    warned_at = 0.0
    maintained_at = float("-inf")
    log.info("Worker uruchomiony")
    while True:
        try:
            if time.monotonic() - maintained_at >= config.UPLOAD_CLEANUP_SECONDS:
                maintained_at = time.monotonic()
                run_maintenance()
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
