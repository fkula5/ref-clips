"""Uprawnienia: jedno miejsce z regułami (czyste funkcje, bez dostępu do bazy).

Każda funkcja odpowiada wierszowi tabeli „Role i uprawnienia” ze specyfikacji. Role sumują się:
wystarczy, że jedna z ról użytkownika daje prawo. Trasy wywołują te funkcje przez
`auth.require(...)` (serwer zawsze sprawdza), a szablony tylko ukrywają niedostępne przyciski.

`user` to obiekt z polami `id`, `is_active` i `roles` (zbiór nazw ról); obiekty meczów, klipów
itd. to modele z `app.models`.
"""
from __future__ import annotations

from collections.abc import Iterable

ADMIN, COACH, REFEREE = "admin", "coach", "referee"


def _has(user, *roles: str) -> bool:
    return user is not None and bool(user.roles & set(roles))


def is_official(user, match) -> bool:
    """Czy użytkownik jest w obsadzie meczu: liczy się wyłącznie pozycja powiązana z kontem."""
    return user is not None and any(o.user_id == user.id for o in match.officials)


def _staff_or_official(user, match) -> bool:
    """Administrator i szkoleniowiec: każdy mecz; sędzia: tylko mecz, w którym jest w obsadzie."""
    return _has(user, ADMIN, COACH) or (_has(user, REFEREE) and is_official(user, match))


# --- zarządzanie ----------------------------------------------------------------
def can_manage_users(user) -> bool:
    """Zarządzanie kontami i przypisywanie ról."""
    return _has(user, ADMIN)


def can_manage_categories(user) -> bool:
    """Zarządzanie słownikiem kategorii."""
    return _has(user, ADMIN)


# --- przeglądanie i komentowanie ------------------------------------------------
def can_view(user) -> bool:
    """Przeglądanie wszystkich meczów i klipów: każdy zalogowany, aktywny użytkownik."""
    return user is not None and bool(user.is_active)


def can_comment(user) -> bool:
    """Komentowanie meczów i klipów: wszyscy zalogowani."""
    return can_view(user)


def can_edit_comment(user, comment) -> bool:
    """Edycja komentarza: tylko autor."""
    return can_view(user) and comment.author_id == user.id


def can_delete_comment(user, comment) -> bool:
    """Usunięcie komentarza: autor albo administrator."""
    return can_view(user) and (_has(user, ADMIN) or comment.author_id == user.id)


# --- mecze i nagrania -----------------------------------------------------------
def can_create_match(user) -> bool:
    """Wgrywanie meczów i wpisanie obsady (wejście do formularza): każda z trzech ról.

    Sędzia może zapisać tylko mecz ze sobą w obsadzie, patrz `can_save_match`."""
    return _has(user, ADMIN, COACH, REFEREE)


def can_save_match(user, official_user_ids: Iterable[int | None]) -> bool:
    """Zapis meczu z daną obsadą (id kont na pozycjach). Użytkownik, który jest tylko
    sędzią, musi sam być w obsadzie."""
    if not can_create_match(user):
        return False
    if _has(user, ADMIN, COACH):
        return True
    return user.id in set(official_user_ids)


def can_upload_to_match(user, match) -> bool:
    """Wgrywanie nagrań, znaczniki kwart i obsada istniejącego meczu."""
    return _staff_or_official(user, match)


def can_edit_match(user, match) -> bool:
    """Edycja i usuwanie meczu: administrator wszystko, pozostali tylko własne mecze."""
    return _has(user, ADMIN) or (_has(user, COACH, REFEREE) and match.created_by == user.id)


def can_delete_match(user, match) -> bool:
    return can_edit_match(user, match)


def can_delete_video(user, video) -> bool:
    """Usunięcie nagrania: administrator, właściciel meczu albo osoba, która je wgrała."""
    if _has(user, ADMIN):
        return True
    return _has(user, COACH, REFEREE) and user.id in (video.created_by, video.match.created_by)


# --- klipy ----------------------------------------------------------------------
def can_manage_clips(user, match) -> bool:
    """Tworzenie i opisywanie klipów w meczu."""
    return _staff_or_official(user, match)


def can_describe_clip(user, clip) -> bool:
    return can_manage_clips(user, clip.match)


def can_delete_clip(user, clip) -> bool:
    """Usunięcie klipu: administrator wszystkie, szkoleniowiec i sędzia tylko własne."""
    return _has(user, ADMIN) or (_has(user, COACH, REFEREE) and clip.author_id == user.id)


# --- oceny ----------------------------------------------------------------------
def can_rate(user) -> bool:
    """Ocena klipu: tylko rola szkoleniowca (sama rola administratora nie wystarcza)."""
    return _has(user, COACH)


def can_edit_rating(user, rating) -> bool:
    """Zmiana lub usunięcie oceny: jej autor (szkoleniowiec) albo administrator."""
    return _has(user, ADMIN) or (_has(user, COACH) and rating.coach_id == user.id)


def can_delete_rating(user, rating) -> bool:
    return can_edit_rating(user, rating)
