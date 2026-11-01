"""Logowanie, wylogowanie i ustawienie hasła z linku (zaproszenie / reset)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import accounts, auth, config
from app.db import get_db
from app.models import INVITE_PURPOSES
from app.web import render

# Bez logowania: formularz logowania i ustawienie hasła (CSRF przez ciasteczko).
public_router = APIRouter()
# Wylogowanie wymaga sesji.
router = APIRouter()

THROTTLE_MESSAGE = (f"Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za "
                    f"{config.LOGIN_WINDOW_MINUTES} minut.")


def safe_next(target: str) -> str:
    """Dopuszcza tylko adresy lokalne (bez przekierowania na obcą domenę)."""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


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


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    accounts.end_session(db, request.cookies.get(config.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


@public_router.get("/set-password/{token}")
def set_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    invite = accounts.find_invite(db, token)
    if invite is None:
        return render(request, "set_password.html", status_code=410, invite=None, error=None)
    return render(request, "set_password.html", invite=invite, error=None,
                  purpose=INVITE_PURPOSES[invite.purpose])


@public_router.post("/set-password/{token}")
def set_password(request: Request, token: str, db: Session = Depends(get_db),
                 password: str = Form(""), password2: str = Form("")):
    invite = accounts.find_invite(db, token)
    if invite is None:
        return render(request, "set_password.html", status_code=410, invite=None, error=None)
    error = None
    if password != password2:
        error = "Hasła nie są takie same."
    else:
        try:
            accounts.redeem_invite(db, invite, password)
        except accounts.AccountError as exc:
            error = str(exc)
    if error:
        return render(request, "set_password.html", status_code=422, invite=invite, error=error,
                      purpose=INVITE_PURPOSES[invite.purpose])
    return RedirectResponse("/login?ok=1", status_code=303)
