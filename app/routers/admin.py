"""Panel administratora: użytkownicy i role (linki zaproszeń, reset hasła), słownik kategorii,
retencja i zajętość dysku."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, categories, config, disk, flash, permissions, retention, services
from app.auth import require
from app.db import get_db
from app.models import Category, User, Video
from app.web import render

router = APIRouter(prefix="/admin")
admin_only = require(permissions.can_manage_users)
categories_admin = require(permissions.can_manage_categories)
retention_admin = require(permissions.can_manage_retention)


def render_admin(request: Request, db: Session, template: str, status_code: int = 200,
                 notice: str | None = None, **context):
    """Strona panelu z zakładkami i banerem o uploadach odrzuconych z braku miejsca (ostatnie dni).
    Komunikat po udanym zapisie (PRG: POST -> 303 -> GET) dochodzi jednorazowym ciasteczkiem."""
    response = render(request, template, status_code=status_code, notice=notice or flash.read_notice(request),
                      rejected_count=len(disk.recent_rejections(db)), warn_days=config.REJECTION_WARN_DAYS,
                      **context)
    flash.clear_notice(request, response)
    return response


@router.get("")
def admin_home(_admin: User = admin_only):
    return RedirectResponse("/admin/users", status_code=303)


def _invite_url(request: Request, token: str) -> str:
    base = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    return f"{base}/set-password/{token}"


def _page(request: Request, db: Session, *, status_code: int = 200, error: str | None = None,
          invite_link: str | None = None, invite_for: User | None = None, notice: str | None = None,
          new_values: dict | None = None, roles_edit: dict[int, set[str]] | None = None):
    """Strona kont. Przy błędzie formularza zachowuje wpisane wartości: `new_values` (nowe konto)
    albo `roles_edit` (role wybrane w wierszu konta, którego zapis się nie udał). Link zaproszenia
    (`invite_link`) pokazuje jednorazowo, z `Cache-Control: no-store`."""
    if invite_link is None and request.method == "GET" and (pending := flash.read_invite(request)):
        # link zaproszenia po przekierowaniu (POST /admin/users, /invite): z ciasteczka, tylko raz
        invite_for = db.get(User, pending[0])
        invite_link = _invite_url(request, pending[1]) if invite_for else None
    users = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
    response = render_admin(request, db, "admin_users.html", status_code=status_code, users=users, error=error,
                            invite_link=invite_link, invite_for=invite_for, notice=notice,
                            new_values=new_values or {"name": "", "email": "", "roles": ["referee"]},
                            roles_edit=roles_edit or {})
    flash.clear_invite(request, response)  # przeczytane (albo nieprzydatne) — nigdy drugi raz
    if invite_link:
        response.headers["Cache-Control"] = "no-store"
    return response


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
    """Zakłada konto bez hasła i przekierowuje (303) na listę kont, gdzie jednorazowo pokazuje link
    zaproszenia (ważny 7 dni, jednorazowy). Token czeka w krótkotrwałym ciasteczku, nie w adresie."""
    try:
        user = accounts.create_user(db, email=email, name=name, roles=roles)
    except accounts.AccountError as exc:
        db.rollback()
        return _page(request, db, status_code=422, error=str(exc),
                     new_values={"name": name, "email": email, "roles": roles})
    token = accounts.create_invite(db, user, "activate", admin)
    return flash.redirect_with_invite("/admin/users", user.id, token)


@router.post("/users/{user_id}/roles")
def update_roles(request: Request, user_id: int, db: Session = Depends(get_db),
                 admin: User = admin_only, roles: list[str] = Form(default=[])):
    user = _get_user(db, user_id)
    try:
        accounts.update_roles(db, user, roles)
    except accounts.AccountError as exc:
        db.rollback()
        return _page(request, db, status_code=422, error=str(exc), roles_edit={user_id: set(roles)})
    if not permissions.can_manage_users(admin):  # administrator odebrał rolę sobie: lista kont jest już zamknięta
        return flash.redirect_with_notice("/")
    return flash.redirect_with_notice("/admin/users", f"Zapisano role: {user.name}.")


@router.post("/users/{user_id}/active")
def set_active(request: Request, user_id: int, db: Session = Depends(get_db),
               _admin: User = admin_only, active: int = Form(0)):
    user = _get_user(db, user_id)
    try:
        accounts.set_active(db, user, bool(active))
    except accounts.AccountError as exc:
        return _page(request, db, status_code=422, error=str(exc))
    return flash.redirect_with_notice(
        "/admin/users", f"Konto {user.name} jest teraz {'aktywne' if user.is_active else 'nieaktywne'}.")


@router.post("/users/{user_id}/invite")
def new_link(request: Request, user_id: int, db: Session = Depends(get_db),
             admin: User = admin_only):
    """Nowy link ustawienia hasła: aktywacja (konto bez hasła) albo reset (konto z hasłem). Poprzedni
    niewykorzystany link traci ważność już przy tym żądaniu, więc odświeżenie strony po przekierowaniu
    (GET) niczego nie generuje ponownie."""
    user = _get_user(db, user_id)
    if not user.is_active:
        return _page(request, db, status_code=422, error="Konto jest nieaktywne — najpierw je aktywuj.")
    purpose = "reset" if user.password_hash else "activate"
    token = accounts.create_invite(db, user, purpose, admin)
    return flash.redirect_with_invite("/admin/users", user.id, token)


# --- słownik kategorii ---------------------------------------------------------------------
def _get_category(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Nie ma takiej kategorii")
    return category


def _categories_page(request: Request, db: Session, *, status_code: int = 200, error: str | None = None,
                     notice: str | None = None, new_values: dict | None = None,
                     edit_values: dict[int, dict] | None = None):
    """Lista kategorii w grupach. Po błędzie zachowuje wpisane wartości: `new_values` (nowa kategoria)
    albo `edit_values` (wiersz, którego zapis się nie udał)."""
    return render_admin(
        request, db, "admin_categories.html", status_code=status_code, error=error, notice=notice,
        groups=categories.grouped(db), group_names=categories.available_groups(db),
        used=categories.usage_counts(db),
        new_values=new_values or {"name": "", "group": categories.GROUPS[0], "aliases": ""},
        edit_values=edit_values or {})


@router.get("/categories")
def categories_page(request: Request, db: Session = Depends(get_db), _admin: User = categories_admin):
    return _categories_page(request, db)


@router.post("/categories")
def create_category(request: Request, db: Session = Depends(get_db), _admin: User = categories_admin,
                    name: str = Form(""), group: str = Form(""), aliases: str = Form("")):
    try:
        category = categories.create(db, name, group, aliases)
    except categories.CategoryError as exc:
        db.rollback()
        return _categories_page(request, db, status_code=exc.status_code, error=str(exc),
                                new_values={"name": name, "group": group, "aliases": aliases})
    return flash.redirect_with_notice("/admin/categories", f"Dodano kategorię „{category.name}”.")


@router.post("/categories/{category_id}/update")
def update_category(request: Request, category_id: int, db: Session = Depends(get_db),
                    _admin: User = categories_admin, name: str = Form(""), group: str = Form(""),
                    aliases: str = Form("")):
    category = _get_category(db, category_id)
    try:
        categories.update(db, category, name, group, aliases)
    except categories.CategoryError as exc:
        db.rollback()
        return _categories_page(request, db, status_code=exc.status_code, error=str(exc),
                                edit_values={category_id: {"name": name, "group": group, "aliases": aliases}})
    return flash.redirect_with_notice("/admin/categories", f"Zapisano kategorię „{category.name}”.")


@router.post("/categories/{category_id}/active")
def set_category_active(request: Request, category_id: int, db: Session = Depends(get_db),
                        _admin: User = categories_admin, active: int = Form(0)):
    category = _get_category(db, category_id)
    try:
        categories.set_active(db, category, bool(active))
    except categories.CategoryError as exc:
        db.rollback()
        return _categories_page(request, db, status_code=exc.status_code, error=str(exc))
    return flash.redirect_with_notice("/admin/categories", f"Kategoria „{category.name}” jest teraz "
                                                           f"{'aktywna' if category.is_active else 'nieaktywna'}.")


@router.post("/categories/{category_id}/move")
def move_category(request: Request, category_id: int, db: Session = Depends(get_db),
                  _admin: User = categories_admin, direction: str = Form("")):
    category = _get_category(db, category_id)
    try:
        categories.move(db, category, direction)
    except categories.CategoryError as exc:
        db.rollback()
        return _categories_page(request, db, status_code=exc.status_code, error=str(exc))
    return flash.redirect_with_notice("/admin/categories")


@router.post("/categories/{category_id}/delete")
def delete_category(request: Request, category_id: int, db: Session = Depends(get_db),
                    _admin: User = categories_admin):
    category = _get_category(db, category_id)
    name = category.name
    try:
        categories.delete(db, category)
    except categories.CategoryError as exc:
        db.rollback()
        return _categories_page(request, db, status_code=exc.status_code, error=str(exc))
    return flash.redirect_with_notice("/admin/categories", f"Usunięto kategorię „{name}”.")


# --- retencja i dysk -----------------------------------------------------------------------
def _retention_page(request: Request, db: Session, *, status_code: int = 200, error: str | None = None,
                    notice: str | None = None, days_value: str | None = None):
    last_run, last_summary = retention.last_run(db)
    return render_admin(
        request, db, "admin_retention.html", status_code=status_code, error=error, notice=notice,
        days=services.retention_days(db), days_value=days_value, days_min=config.RETENTION_DAYS_MIN,
        days_max=config.RETENTION_DAYS_MAX, usage=disk.usage(db), rows=disk.video_rows(db),
        rejections=disk.recent_rejections(db),
        last_run=last_run, last_summary=last_summary)


@router.get("/retention")
def retention_page(request: Request, db: Session = Depends(get_db), _admin: User = retention_admin):
    return _retention_page(request, db)


@router.post("/retention")
def save_retention(request: Request, db: Session = Depends(get_db), _admin: User = retention_admin,
                   days: str = Form(""), recalculate: int = Form(0)):
    """Zmienia `retention_days`. Domyślnie dotyczy tylko nowych nagrań; „przelicz” ustawia termin
    istniejących nagrań na datę wgrania + nowa liczba dni."""
    try:
        value = retention.parse_retention_days(days)
    except retention.RetentionError as exc:
        return _retention_page(request, db, status_code=422, error=str(exc), days_value=days)
    change = retention.set_retention_days(db, value, bool(recalculate))
    notice = f"Zapisano: pełne nagranie jest przechowywane {value} dni od wgrania (dotyczy nowych nagrań)."
    if recalculate:
        notice = (f"Zapisano: {value} dni. Przeliczono termin {change.recalculated} istniejących nagrań"
                  + (f"; {change.overdue} jest już po nowym terminie i zostanie usunięte przy najbliższym "
                     "sprzątaniu (workera)." if change.overdue else "."))
    return flash.redirect_with_notice("/admin/retention", notice)


@router.post("/videos/{video_id}/purge")
def purge_video(request: Request, video_id: int, db: Session = Depends(get_db), _admin: User = retention_admin):
    """Ręczne usunięcie pełnego nagrania przed terminem (klipy zostają). Nie w trakcie konwersji
    i nie, gdy klipy z tego nagrania czekają na wycięcie — wtedy 409 z wyjaśnieniem. Sukces: 303 na
    listę z komunikatem."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Nie ma takiego nagrania")
    name = f"{video.match.title} — {video.display_name}"
    try:
        retention.purge_video(db, video)
    except retention.PurgeError as exc:
        db.rollback()
        return _retention_page(request, db, status_code=409, error=f"Nie usunięto nagrania „{name}”: {exc}")
    return flash.redirect_with_notice("/admin/retention", f"Usunięto pełne nagranie „{name}”. Klipy zostają.")
