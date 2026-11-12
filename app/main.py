import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app import config, health, logfilter, permissions, watch
from app import video as vid
from app.auth import PROTECTED, PUBLIC, SessionRefreshMiddleware, attach_user_if_missing, require
from app.privacy import SharePrivacyHeadersMiddleware
from app.db import SessionLocal, get_db
from app.initdb import init_db
from app.models import Job, User
from app.routers import (admin, auth, clips, clips_v2, describe, feedback, groups, matches, notifications,
                         scoresheets, share, share_links, sheets, training_sets, uploads, videos, watch as watch_routes)
from app.web import BASE, back_url, render


logfilter.install()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    sweeper = asyncio.create_task(watch.sweep_forever())
    yield
    sweeper.cancel()


# No public API docs: every page except login needs a session.
app = FastAPI(title="ref-clips", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionRefreshMiddleware)
app.add_middleware(SharePrivacyHeadersMiddleware)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

app.include_router(auth.public_router, dependencies=PUBLIC)
app.include_router(share.router)  # no session or CSRF: read-only public links
app.include_router(auth.router, dependencies=PROTECTED)
app.include_router(admin.router, dependencies=PROTECTED)
app.include_router(matches.router, dependencies=PROTECTED)
app.include_router(describe.router, dependencies=PROTECTED)
app.include_router(videos.router, dependencies=PROTECTED)
app.include_router(uploads.router, dependencies=PROTECTED)
if config.ENABLE_V2_FEATURES:  # before clips: /clips/export.zip must not match /clips/{clip_id}
    app.include_router(clips_v2.router, dependencies=PROTECTED)
app.include_router(clips.router, dependencies=PROTECTED)
app.include_router(feedback.router, dependencies=PROTECTED)
app.include_router(share_links.router, dependencies=PROTECTED)
app.include_router(sheets.router, dependencies=PROTECTED)
app.include_router(scoresheets.router, dependencies=PROTECTED)
app.include_router(notifications.router, dependencies=PROTECTED)
app.include_router(groups.router, dependencies=PROTECTED)
app.include_router(training_sets.router, dependencies=PROTECTED)
app.include_router(watch_routes.router, dependencies=PROTECTED)
app.include_router(watch_routes.ws_router)


def _wants_page(request: Request) -> bool:
    return (request.method == "GET" and not request.url.path.startswith("/api/")
            and "hx-request" not in request.headers)


def _is_browser_form(request: Request) -> bool:
    return ("text/html" in request.headers.get("accept", "") and "hx-request" not in request.headers
            and not request.url.path.startswith("/api/"))


ERROR_HEADINGS = {403: "Brak dostępu", 404: "Nie znaleziono", 405: "Nieobsługiwana operacja",
                  413: "Plik za duży", 422: "Nieprawidłowe dane"}
ERROR_MESSAGES = {404: "Nie ma takiej strony lub została usunięta.",
                  405: "Ta operacja nie jest dostępna pod tym adresem.",
                  422: "Przesłane dane są niepoprawne. Wróć i sprawdź formularz."}


def error_page(request: Request, status_code: int, detail: str | None = None):
    generic = not detail or detail in ("Not Found", "Method Not Allowed")
    message = ERROR_MESSAGES.get(status_code, "Nie można wykonać operacji.") if generic else detail
    with SessionLocal() as db:  # open while rendering: the header reads the user's lazy attributes
        attach_user_if_missing(request, db)
        return render(request, "error.html", status_code=status_code, message=message,
                      heading=ERROR_HEADINGS.get(status_code, "Nie można wykonać operacji"),
                      back_url=back_url(request))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/s/"):  # public links: always the same plain page, no cookies
        return share.gone_response(request)
    if _is_browser_form(request):
        return error_page(request, 422)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/s/"):  # public links: every error (404, 405) looks the same
        return share.gone_response(request)
    if exc.status_code == 401:
        if _wants_page(request):
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='/')}", status_code=303)
        headers = {"HX-Redirect": "/login"} if "hx-request" in request.headers else None
        return JSONResponse({"detail": exc.detail}, status_code=401, headers=headers)
    if _is_browser_form(request):
        return error_page(request, exc.status_code, str(exc.detail))
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    """Public: no login or CSRF. Only names and states, never paths, numbers or exceptions."""
    checks = health.run_checks()
    ok = health.is_healthy(checks)
    body = {"status": "ok"} if ok else {"status": "error", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503, headers={"Cache-Control": "no-store"})


@app.get("/api/status", dependencies=PROTECTED)
def status(db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"ffmpeg": vid.ffmpeg_available(), "jobs": counts}
