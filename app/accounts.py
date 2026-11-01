"""Konta, logowanie, sesje i zaproszenia (logika bez FastAPI)."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import config, security
from app.models import USER_ROLES, AuthSession, Invite, LoginAttempt, User
from app.timeutil import utcnow

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """Błąd walidacji widoczny dla administratora (komunikat po polsku)."""


class InvalidCredentials(Exception):
    pass


class LoginThrottled(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> str | None:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Hasło musi mieć co najmniej {config.MIN_PASSWORD_LENGTH} znaków."
    if len(password) > 256:
        return "Hasło jest zbyt długie (maks. 256 znaków)."
    return None


# --- logowanie z limitem prób -----------------------------------------------------
def is_throttled(db: Session, email: str, ip: str) -> bool:
    """Limit nieudanych prób w oknie czasowym — osobno na konto i na adres IP."""
    since = utcnow() - timedelta(minutes=config.LOGIN_WINDOW_MINUTES)
    for column, value in ((LoginAttempt.email, email), (LoginAttempt.ip, ip)):
        count = db.scalar(select(func.count()).select_from(LoginAttempt)
                          .where(column == value, LoginAttempt.attempted_at >= since))
        if count >= config.LOGIN_MAX_ATTEMPTS:
            return True
    return False


def authenticate(db: Session, email: str, password: str, ip: str) -> User:
    email = normalize_email(email)[:255]
    if is_throttled(db, email, ip):
        raise LoginThrottled
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.password_hash and user.is_active:
        ok = security.verify_password(user.password_hash, password)
    else:
        security.verify_password(security.dummy_hash(), password)  # wyrównanie czasu odpowiedzi
        ok = False
    if not ok:
        now = utcnow()
        db.execute(delete(LoginAttempt).where(
            LoginAttempt.attempted_at < now - timedelta(minutes=config.LOGIN_WINDOW_MINUTES)))
        db.add(LoginAttempt(email=email, ip=ip, attempted_at=now))
        db.commit()
        raise InvalidCredentials
    # udane logowanie zeruje licznik błędów tego konta (licznik adresu IP zostaje)
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
    db.commit()
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
        db.commit()
    return user


# --- sesje ------------------------------------------------------------------------
def create_session(db: Session, user: User) -> str:
    """Zakłada sesję i zwraca token do ciasteczka (w bazie zostaje tylko jego hash)."""
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    token = security.new_token()
    db.add(AuthSession(user_id=user.id, token_hash=security.hash_token(token),
                       csrf_token=security.new_token(),
                       expires_at=now + timedelta(days=config.SESSION_DAYS)))
    db.commit()
    return token


def get_session(db: Session, token: str | None) -> AuthSession | None:
    """Ważna sesja aktywnego użytkownika albo None."""
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == security.hash_token(token)))
    if session is None or session.expires_at <= utcnow() or not session.user.is_active:
        return None
    return session


def refresh_session(db: Session, session: AuthSession) -> bool:
    """Przedłuża sesję do pełnych 30 dni (najwyżej raz na dobę). True, gdy przedłużono."""
    now = utcnow()
    if session.expires_at - now > timedelta(days=config.SESSION_DAYS) - timedelta(days=1):
        return False
    session.expires_at = now + timedelta(days=config.SESSION_DAYS)
    db.commit()
    return True


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == security.hash_token(token)))
        db.commit()


def end_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


# --- zaproszenia i reset hasła ------------------------------------------------------
def create_invite(db: Session, user: User, purpose: str, created_by: User | None) -> str:
    """Nowy jednorazowy link (ważny 7 dni). Wcześniejsze niewykorzystane linki tracą ważność."""
    now = utcnow()
    for old in db.scalars(select(Invite).where(Invite.user_id == user.id, Invite.used_at.is_(None))):
        old.used_at = now
    token = security.new_token()
    db.add(Invite(user_id=user.id, token_hash=security.hash_token(token), purpose=purpose,
                  expires_at=now + timedelta(days=config.INVITE_DAYS),
                  created_by=created_by.id if created_by else None))
    db.commit()
    return token


def find_invite(db: Session, token: str) -> Invite | None:
    """Link ważny: istnieje, nie był użyty, nie wygasł, konto jest aktywne."""
    invite = db.scalar(select(Invite).where(Invite.token_hash == security.hash_token(token)))
    if (invite is None or invite.used_at is not None or invite.expires_at <= utcnow()
            or not invite.user.is_active):
        return None
    return invite


def redeem_invite(db: Session, invite: Invite, password: str) -> None:
    """Ustawia hasło z linku, zużywa link i wylogowuje konto ze starych sesji."""
    error = validate_password(password)
    if error:
        raise AccountError(error)
    user = invite.user
    user.password_hash = security.hash_password(password)
    invite.used_at = utcnow()
    end_all_sessions(db, user.id)
    db.commit()


# --- zarządzanie kontami (administrator) --------------------------------------------
def _clean_roles(roles) -> set[str]:
    wanted = set(roles)
    if not wanted:
        raise AccountError("Wybierz co najmniej jedną rolę.")
    if not wanted <= set(USER_ROLES):
        raise AccountError("Nieznana rola.")
    return wanted


def _active_admins_except(db: Session, user_id: int) -> int:
    admins = db.scalars(select(User).where(User.is_active.is_(True), User.id != user_id)).all()
    return sum(1 for u in admins if "admin" in u.roles)


def create_user(db: Session, *, email: str, name: str, roles, password: str | None = None) -> User:
    email, name = normalize_email(email), " ".join(name.split())
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise AccountError("Podaj poprawny adres e-mail.")
    if not name:
        raise AccountError("Podaj imię i nazwisko.")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AccountError("Konto z tym adresem e-mail już istnieje.")
    user = User(email=email, name=name[:100])
    user.set_roles(_clean_roles(roles))
    if password is not None:
        user.password_hash = security.hash_password(password)
    db.add(user)
    db.commit()
    return user


def update_roles(db: Session, user: User, roles) -> None:
    wanted = _clean_roles(roles)
    if "admin" in user.roles and "admin" not in wanted and user.is_active \
            and _active_admins_except(db, user.id) == 0:
        raise AccountError("Musi zostać co najmniej jeden aktywny administrator.")
    user.set_roles(wanted)
    db.commit()


def set_active(db: Session, user: User, active: bool) -> None:
    if not active and "admin" in user.roles and user.is_active \
            and _active_admins_except(db, user.id) == 0:
        raise AccountError("Musi zostać co najmniej jeden aktywny administrator.")
    user.is_active = active
    if not active:
        end_all_sessions(db, user.id)
    db.commit()


def ensure_admin(db: Session, *, email: str, name: str, password: str) -> tuple[User, bool]:
    """Dla polecenia create_admin: zakłada administratora albo nadaje rolę istniejącemu
    kontu i ustawia hasło. Zwraca (konto, czy nowe)."""
    error = validate_password(password)
    if error:
        raise AccountError(error)
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return create_user(db, email=email, name=name, roles=["admin"], password=password), True
    user.set_roles(user.roles | {"admin"})
    user.password_hash = security.hash_password(password)
    user.is_active = True
    db.commit()
    return user, False
