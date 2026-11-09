"""Wspólne elementy warstwy webowej: szablony, filtry, widoki JSON."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from app import clip_list, config, feedback, retention, services
from app.auth import set_anon_csrf_cookie
from app import models as m
from app import permissions
from app import video as vid
from app.security import new_token
from app.textutil import format_clock, normalize
from app.timeutil import local as local_time

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
env = templates.env
env.filters["clock"] = format_clock
# Daty i godziny z bazy (UTC) pokazujemy w strefie z konfiguracji: {{ x.created_at|local("%d.%m.%Y %H:%M") }}.
env.filters["local"] = local_time


def human_bytes(value: int | float | None) -> str:
    """Rozmiar po polsku: „512 B”, „1,3 GB”."""
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.1f}".replace(".", ",") + f" {unit}"


env.filters["filesize"] = human_bytes


# Kolory strojów wpisywane ręcznie: rozpoznajemy początek nazwy (np. „czerwone”, „Czerwony”).
COLOR_STEMS = {
    "bial": "#ffffff", "czerw": "#d32f2f", "nieb": "#1e6fd9", "granat": "#1a2a5a", "ziel": "#2e9d4a",
    "zolt": "#f2c500", "pomaran": "#f28c00", "czarn": "#111111", "ciemn": "#2b2f3a", "szar": "#9aa0aa",
    "fiolet": "#7b3fa0", "bordow": "#7b1f2e", "rozow": "#ec6fa0", "jasn": "#e6e9f0",
    "turkus": "#1fb5b0", "braz": "#6d4c2f",
}


def color_hex(name: str | None) -> str:
    """Kolor CSS dla nazwy koloru strojów albo pusty napis, gdy nazwy nie rozpoznajemy."""
    key = normalize(name or "")
    return next((hex_ for stem, hex_ in COLOR_STEMS.items() if key.startswith(stem)), "")


@pass_context
def csrf_input(context) -> Markup:
    """Ukryte pole z tokenem CSRF do formularzy: {{ csrf_input() }}."""
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(
        escape(context.get("csrf_token", "")))


env.globals.update(
    ffmpeg_ok=vid.ffmpeg_available,
    ffmpeg_message=config.FFMPEG_MISSING_MESSAGE,
    csrf_input=csrf_input,
    perm=permissions,
    USER_ROLES=m.USER_ROLES, OFFICIAL_FUNCTIONS=m.OFFICIAL_FUNCTIONS,
    RATING_VERDICTS=m.RATING_VERDICTS, RATING_CHOICES=clip_list.RATING_CHOICES,
    TEXT_MAX_CHARS=config.TEXT_MAX_CHARS, rating_edited=feedback.is_edited,
    VIDEO_STATUSES=m.VIDEO_STATUSES, CLIP_STATUSES=m.CLIP_STATUSES, PERIODS=m.PERIODS,
    period_for=lambda c: services.period_for(c.video.marks, c.time_sec),
    period_label=lambda c: services.period_label(c.video.marks, c.time_sec),
    period_short=lambda c: services.period_short(c.video.marks, c.time_sec),
    color_hex=color_hex,
    category_groups=services.category_groups,
    is_proposal=services.is_proposal,
    describe_block=services.describe_block,
    content_label=services.content_label,
    missing_periods_of=lambda v: (services.missing_periods(v.content, (mk.period for mk in v.marks))
                                  if v.status == "ready" and v.purged_at is None else []),
    NOTES_MAX_CHARS=config.NOTES_MAX_CHARS, NOTES_MAX_LINES=config.NOTES_MAX_LINES,
    max_upload_gb=lambda: config.UPLOAD_MAX_BYTES / config.GB,
    upload_chunk_bytes=config.UPLOAD_CHUNK_BYTES,
    expiry_note=retention.expiry_note, video_expiry_note=retention.video_expiry_note,
    clip_bounds=services.clip_range,
    DEFAULT_MARGIN=config.DEFAULT_MARGIN_BEFORE,
)


def render(request: Request, name: str, status_code: int = 200, **context):
    """Renderuje szablon z użytkownikiem i tokenem CSRF.

    Zalogowany dostaje token swojej sesji; niezalogowany (strony logowania) token z ciasteczka,
    które ustawiamy przy pierwszym wyświetleniu formularza."""
    user = getattr(request.state, "user", None)
    anon_cookie = None
    if user is not None:
        csrf_token = request.state.session.csrf_token
    else:
        csrf_token = request.cookies.get(config.CSRF_COOKIE) or new_token()
        if csrf_token != request.cookies.get(config.CSRF_COOKIE):
            anon_cookie = csrf_token
    response = templates.TemplateResponse(
        request, name, {"user": user, "csrf_token": csrf_token, **context}, status_code=status_code)
    if anon_cookie:
        set_anon_csrf_cookie(response, anon_cookie)
    return response


def is_htmx(request: Request) -> bool:
    """Żądanie wysłane przez HTMX (odświeżanie fragmentu, a nie nawigacja). Odtworzenie strony z historii
    (wstecz przy braku kopii w pamięci HTMX) też ma nagłówek HX-Request, ale podmienia całe body, więc
    traktujemy je jak zwykłą nawigację."""
    return "hx-request" in request.headers and "hx-history-restore-request" not in request.headers


def back_url(request: Request) -> str | None:
    """Adres poprzedniej strony z nagłówka Referer, tylko z tego samego serwisu (inaczej None)."""
    referer = urlsplit(request.headers.get("referer", ""))
    if not referer.netloc or referer.netloc != request.url.netloc or not referer.path.startswith("/"):
        return None
    target = referer.path + (f"?{referer.query}" if referer.query else "")
    current = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return None if target == current else target


def clip_json(c: m.Clip) -> dict:
    start, end = services.clip_range(c)
    position = services.period_position(c.video.marks, c.time_sec)
    return {
        "id": c.id,
        "video_id": c.video_id,
        "time_sec": c.time_sec,
        "clock": format_clock(c.time_sec),
        "period": position[0] if position else None,
        "period_clock": format_clock(position[1]) if position else None,  # od początku kwarty
        "official": c.official_label or None,
        "category": c.category_label or None,
        "described": c.is_described,
        "description": c.description,
        "status": c.status,
        "error": c.error,
        "clip_start": start,
        "clip_end": end,
    }


def mark_json(mark: m.PeriodMark) -> dict:
    return {"id": mark.id, "period": mark.period, "time_sec": mark.time_sec,
            "clock": format_clock(mark.time_sec)}


def file_response(path: Path, media_type: str = "video/mp4", download_name: str | None = None):
    """Plik z obsługą HTTP Range (Starlette FileResponse zwraca 206 dla nagłówka Range)."""
    kwargs = {}
    if download_name:
        kwargs = {"filename": download_name, "content_disposition_type": "attachment"}
    return FileResponse(path, media_type=media_type, **kwargs)
