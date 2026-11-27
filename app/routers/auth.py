from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app import accounts, auth, config, password_reset
from app.db import get_db
from app.models import INVITE_PURPOSES
from app.web import render

public_router = APIRouter()
router = APIRouter()

THROTTLE_MESSAGE = (f"Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za "
                    f"{config.LOGIN_WINDOW_MINUTES} minut.")


RESET_THROTTLE_MESSAGE = (f"Zbyt wiele próśb o reset hasła. Spróbuj ponownie za "
                          f"{config.RESET_IP_WINDOW_MINUTES} minut.")
TOKEN_THROTTLE_MESSAGE = (f"Zbyt wiele prób z nieprawidłowymi linkami. Spróbuj ponownie za "
                          f"{config.TOKEN_MISS_WINDOW_MINUTES} minut.")


def safe_next(target: str) -> str:
    """Only local paths. Rejects control characters, whitespace and backslash (browsers strip tab/CR/LF
    from URLs, so "/<TAB>/evil.com" would become "//evil.com") and anything with a host or scheme.
    """
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in target):
        return "/"
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return "/"
    return target


@public_router.get("/login")
def login_page(request: Request, next: str = "", ok: int = 0):
    return render(request, "login.html", next=safe_next(next) if next else "", ok=bool(ok),
                  error=None, email="")


@public_router.post("/login")
def login(request: Request, db: Session = Depends(get_db), email: str = Form(""),
          password: str = Form(""), next: str = Form("")):
    try:
        user = accounts.authenticate(db, email, password, auth.client_ip(request))
    except accounts.LoginThrottled:
        return render(request, "login.html", status_code=429, next=next, ok=False,
                      error=THROTTLE_MESSAGE, email=email)
    except accounts.InvalidCredentials:
        return render(request, "login.html", status_code=401, next=next, ok=False,
                      error="Nieprawidłowy e-mail lub hasło.", email=email)
    accounts.end_session(db, request.cookies.get(config.SESSION_COOKIE))
    token = accounts.create_session(db, user)
    response = RedirectResponse(safe_next(next), status_code=303)
    auth.set_session_cookie(response, token)
    return response


@public_router.get("/forgot-password")
def forgot_password_page(request: Request, sent: int = 0):
    return render(request, "forgot_password.html", sent=bool(sent), error=None, email="")


@public_router.post("/forgot-password")
def forgot_password(request: Request, background: BackgroundTasks, db: Session = Depends(get_db),
                    email: str = Form(""), contact_url: str = Form("")):
    """Whatever happens to the request (no such account, inactive, limits, honeypot) the answer is the same
    redirect; only a malformed address and the per-IP limit are told apart, and neither depends on accounts.
    """
    neutral = RedirectResponse("/forgot-password?sent=1", status_code=303)
    json_requested = request.headers.get("accept") == "application/json"
    if json_requested:
        neutral = JSONResponse({"sent": True, "minutes": config.PASSWORD_RESET_MINUTES},
                               headers={"Cache-Control": "no-store"})
    if contact_url.strip():  # the honeypot: a human never sees this field
        return neutral
    address = accounts.normalize_email(email)
    if not accounts.valid_email(address):
        if json_requested:
            return JSONResponse({"detail": "Podaj poprawny adres e-mail."}, status_code=422)
        return render(request, "forgot_password.html", status_code=422, sent=False, email=email[:255],
                      error="Podaj poprawny adres e-mail.")
    try:
        pending = password_reset.request_reset(db, address, auth.client_ip(request))
    except password_reset.ResetThrottled:
        if json_requested:
            return JSONResponse({"detail": RESET_THROTTLE_MESSAGE}, status_code=429,
                                headers={"Retry-After": str(config.RESET_IP_WINDOW_MINUTES * 60)})
        response = render(request, "forgot_password.html", status_code=429, sent=False, email=email[:255],
                          error=RESET_THROTTLE_MESSAGE)
        response.headers["Retry-After"] = str(config.RESET_IP_WINDOW_MINUTES * 60)
        return response
    if pending is not None:
        background.add_task(password_reset.deliver, pending)
    return neutral


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    accounts.end_session(db, request.cookies.get(config.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


def _token_page(request: Request, **context):
    """A page with a token in the URL: it must not leak via Referer (no link or resource) and must not
    be cached.
    """
    if request.headers.get("accept") == "application/json":
        invite = context.get("invite")
        status = context.get("status_code", 200)
        payload = ({"email": invite.user.email, "name": invite.user.name, "purpose": context.get("purpose", "")}
                   if invite is not None and status == 200 else {
                       "detail": context.get("error") or context.get("throttle_message") or "Link jest nieprawidłowy lub wygasł.",
                   })
        response = JSONResponse(payload, status_code=status)
    else:
        response = render(request, "set_password.html", **context)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def _usable_invite(request: Request, db: Session, token: str):
    """The invite, or the page to answer with. Unusable links are counted per IP (the tokens are 256-bit,
    so this only caps the noise); a throttled address is refused before the token is even looked at.
    """
    ip = auth.client_ip(request)
    if password_reset.token_throttled(db, ip):
        response = _token_page(request, status_code=429, invite=None, error=None, throttled=True,
                               throttle_message=TOKEN_THROTTLE_MESSAGE)
        response.headers["Retry-After"] = str(config.TOKEN_MISS_WINDOW_MINUTES * 60)
        return response
    invite = accounts.find_invite(db, token)
    if invite is None:
        password_reset.note_token_miss(db, ip)
        return _token_page(request, status_code=410, invite=None, error=None)
    return invite


@public_router.get("/set-password/{token}")
def set_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    invite = _usable_invite(request, db, token)
    if isinstance(invite, Response):
        return invite
    return _token_page(request, invite=invite, error=None, purpose=INVITE_PURPOSES[invite.purpose])


@public_router.post("/set-password/{token}")
def set_password(request: Request, token: str, db: Session = Depends(get_db),
                 password: str = Form(""), password2: str = Form("")):
    invite = _usable_invite(request, db, token)
    if isinstance(invite, Response):
        return invite
    error = None
    if password != password2:
        error = "Hasła nie są takie same."
    else:
        try:
            accounts.redeem_invite(db, invite, password)
        except accounts.AccountError as exc:
            error = str(exc)
    if error:
        return _token_page(request, status_code=422, invite=invite, error=error,
                           purpose=INVITE_PURPOSES[invite.purpose])
    if request.headers.get("accept") == "application/json":
        return Response(status_code=204, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return RedirectResponse("/login?ok=1", status_code=303)
