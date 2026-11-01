"""Aplikacja FastAPI: ref-clips (wycinanie i analiza decyzji sędziowskich)."""
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app import config, permissions
from app import video as vid
from app.auth import PROTECTED, PUBLIC, SessionRefreshMiddleware, require
from app.db import get_db
from app.initdb import init_db
from app.models import Job, User
from app.routers import admin, auth, clips, clips_v2, matches, videos
from app.web import BASE, render


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


# Bez publicznej dokumentacji API: każda strona poza logowaniem wymaga sesji.
app = FastAPI(title="ref-clips", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionRefreshMiddleware)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

# Poza logowaniem i ustawieniem hasła każda trasa wymaga sesji i tokenu CSRF (dla POST/DELETE).
app.include_router(auth.public_router, dependencies=PUBLIC)
app.include_router(auth.router, dependencies=PROTECTED)
app.include_router(admin.router, dependencies=PROTECTED)
app.include_router(matches.router, dependencies=PROTECTED)
app.include_router(videos.router, dependencies=PROTECTED)
if config.ENABLE_V2_FEATURES:  # przed clips: /clips/export.zip nie może trafić w /clips/{clip_id}
    app.include_router(clips_v2.router, dependencies=PROTECTED)
app.include_router(clips.router, dependencies=PROTECTED)


def _wants_page(request: Request) -> bool:
    """Nawigacja w przeglądarce (a nie API, HTMX ani pobieranie pliku)."""
    return (request.method == "GET" and not request.url.path.startswith("/api/")
            and "hx-request" not in request.headers)


def _is_browser_form(request: Request) -> bool:
    return ("text/html" in request.headers.get("accept", "") and "hx-request" not in request.headers
            and not request.url.path.startswith("/api/"))


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    """401 na stronie przekierowuje na logowanie; w API zostaje kod błędu (JSON)."""
    if exc.status_code == 401:
        if _wants_page(request):
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='/')}", status_code=303)
        headers = {"HX-Redirect": "/login"} if "hx-request" in request.headers else None
        return JSONResponse({"detail": exc.detail}, status_code=401, headers=headers)
    if _is_browser_form(request):
        return render(request, "error.html", status_code=exc.status_code, message=exc.detail)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.get("/api/status", dependencies=PROTECTED)
def status(db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"ffmpeg": vid.ffmpeg_available(), "jobs": counts}
