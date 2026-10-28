"""Aplikacja FastAPI: ref-clips (wycinanie i analiza decyzji sędziowskich)."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles

from app import video as vid
from app.db import get_db
from app.initdb import init_db
from app.models import Job
from app.routers import clips, matches, tags, videos
from app.web import BASE


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ref-clips", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
for module in (matches, videos, clips, tags):
    app.include_router(module.router)


@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"ffmpeg": vid.ffmpeg_available(), "jobs": counts}
