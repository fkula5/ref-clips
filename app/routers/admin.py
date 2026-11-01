"""Panel administratora: użytkownicy, role, linki zaproszeń i resetu hasła."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, config, permissions
from app.auth import require
from app.db import get_db
from app.models import User
from app.web import render

router = APIRouter(prefix="/admin")
admin_only = require(permissions.can_manage_users)


def _invite_url(request: Request, token: str) -> str:
    base = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    return f"{base}/set-password/{token}"


def _page(request: Request, db: Session, *, status_code: int = 200, error: str | None = None,
          invite_link: str | None = None, invite_for: User | None = None):
    users = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
    return render(request, "admin_users.html", status_code=status_code, users=users, error=error,
                  invite_link=invite_link, invite_for=invite_for)


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Nie ma takiego użytkownika")
    return user


@router.get("/users")
def users_page(request: Request, db: Session = Depends(get_db), _admin: User = admin_only):
    return _page(request, db)


@router.post("/users")
def create_user(request: Request, db: Session = Depends(get_db), admin: User = admin_only,
                email: str = Form(""), name: str = Form(""), roles: list[str] = Form(default=[])):
    """Zakłada konto bez hasła i pokazuje link zaproszenia (ważny 7 dni, jednorazowy)."""
    try:
        user = accounts.create_user(db, email=email, name=name, roles=roles)
    except accounts.AccountError as exc:
        return _page(request, db, status_code=422, error=str(exc))
    token = accounts.create_invite(db, user, "activate", admin)
    return _page(request, db, invite_link=_invite_url(request, token), invite_for=user)


@router.post("/users/{user_id}/roles")
def update_roles(request: Request, user_id: int, db: Session = Depends(get_db),
                 _admin: User = admin_only, roles: list[str] = Form(default=[])):
    user = _get_user(db, user_id)
    try:
        accounts.update_roles(db, user, roles)
    except accounts.AccountError as exc:
        return _page(request, db, status_code=422, error=str(exc))
    return _page(request, db)


@router.post("/users/{user_id}/active")
def set_active(request: Request, user_id: int, db: Session = Depends(get_db),
               _admin: User = admin_only, active: int = Form(0)):
    user = _get_user(db, user_id)
    try:
        accounts.set_active(db, user, bool(active))
    except accounts.AccountError as exc:
        return _page(request, db, status_code=422, error=str(exc))
    return _page(request, db)


@router.post("/users/{user_id}/invite")
def new_link(request: Request, user_id: int, db: Session = Depends(get_db),
             admin: User = admin_only):
    """Nowy link ustawienia hasła: aktywacja (konto bez hasła) albo reset (konto z hasłem)."""
    user = _get_user(db, user_id)
    if not user.is_active:
        return _page(request, db, status_code=422, error="Konto jest nieaktywne — najpierw je aktywuj.")
    purpose = "reset" if user.password_hash else "activate"
    token = accounts.create_invite(db, user, purpose, admin)
    return _page(request, db, invite_link=_invite_url(request, token), invite_for=user)
