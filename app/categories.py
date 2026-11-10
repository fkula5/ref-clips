"""Conflicting aliases are rejected on save: the notes parser would silently pick the first category by
order.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Clip
from app.textutil import normalize

GROUPS = ["Faule", "Naruszenia", "Bez gwizdka", "Mechanika", "Inne"]
NAME_MAX, ALIAS_MAX, ALIASES_MAX = 100, 60, 1000
# The first word is matched against referee functions first, so such an alias would never fire.
RESERVED_ALIASES = {"cc", "u1", "u2"}


_HAS_WORD_CHAR = re.compile(r"[^\W_]")


def _meaningful(text: str) -> bool:
    return bool(_HAS_WORD_CHAR.search(normalize(text)))


class CategoryError(ValueError):
    status_code = 422


class CategoryInUseError(CategoryError):
    status_code = 409


def _group_rank(group: str) -> tuple[int, str]:
    return (GROUPS.index(group), "") if group in GROUPS else (len(GROUPS), normalize(group))


def ordered(db: Session) -> list[Category]:
    return sorted(db.scalars(select(Category)), key=lambda c: (_group_rank(c.group_name), c.sort, c.id))


def grouped(db: Session) -> list[tuple[str, list[Category]]]:
    found: dict[str, list[Category]] = {g: [] for g in GROUPS}
    for category in ordered(db):
        found.setdefault(category.group_name, []).append(category)
    return list(found.items())


def available_groups(db: Session) -> list[str]:
    extra = {c.group_name for c in db.scalars(select(Category))} - set(GROUPS)
    return [*GROUPS, *sorted(extra)]


def usage_counts(db: Session) -> dict[int, int]:
    return {cid: n for cid, n in db.execute(
        select(Clip.category_id, func.count()).where(Clip.category_id.is_not(None)).group_by(Clip.category_id))}


def renumber(db: Session) -> list[Category]:
    """Keeps groups contiguous: form lists group consecutive categories of one group."""
    items = ordered(db)
    for index, category in enumerate(items, start=1):
        category.sort = index * 10
    db.flush()
    return items


def clean_aliases(raw: str) -> list[str]:
    found: dict[str, str] = {}
    for part in (raw or "").replace("\n", ",").split(","):
        alias = " ".join(part.split())
        if not alias:
            continue
        key = normalize(alias)
        if not _meaningful(alias):
            raise CategoryError(f"Alias „{alias}” nie zawiera liter ani cyfr.")
        if len(alias) > ALIAS_MAX:
            raise CategoryError(f"Alias „{alias[:20]}…”: najwyżej {ALIAS_MAX} znaków.")
        if key in RESERVED_ALIASES:
            raise CategoryError(f"Alias „{alias}” jest zarezerwowany: CC, U1 i U2 oznaczają sędziów w notatkach.")
        found.setdefault(key, alias)
    return list(found.values())


def _check_fields(db: Session, name: str, group: str, aliases: list[str], own_id: int | None) -> str:
    name = " ".join((name or "").split())
    if not name or not _meaningful(name):
        raise CategoryError("Podaj nazwę kategorii.")
    if len(name) > NAME_MAX:
        raise CategoryError(f"Nazwa kategorii: najwyżej {NAME_MAX} znaków.")
    if group not in available_groups(db):
        raise CategoryError("Wybierz grupę ze słownika.")
    if len(", ".join(aliases)) > ALIASES_MAX:
        raise CategoryError(f"Aliasy: najwyżej {ALIASES_MAX} znaków łącznie.")
    if normalize(name) in RESERVED_ALIASES:
        raise CategoryError(f"Nazwa „{name}” jest zarezerwowana: CC, U1 i U2 oznaczają sędziów w notatkach.")
    # Inactive categories count too: activating one later would create the same conflict.
    taken: dict[str, str] = {}
    for other in db.scalars(select(Category).where(Category.id != own_id) if own_id else select(Category)):
        for text in (other.name, *other.alias_list):
            taken.setdefault(normalize(text), other.name)
    if normalize(name) in taken:
        raise CategoryError(f"Nazwa „{name}” koliduje z kategorią „{taken[normalize(name)]}” "
                            "(nazwy i aliasy porównujemy bez względu na wielkość liter i polskie znaki).")
    for alias in aliases:
        if normalize(alias) in taken:
            raise CategoryError(f"Alias „{alias}” jest już używany przez kategorię „{taken[normalize(alias)]}” — "
                                "parser notatek nie rozstrzygnie, którą wybrać.")
    return name


def create(db: Session, name: str, group: str, aliases: str) -> Category:
    alias_list = clean_aliases(aliases)
    name = _check_fields(db, name, group, alias_list, None)
    category = Category(group_name=group, name=name, aliases=", ".join(alias_list), is_active=True,
                        is_custom=False, sort=10 ** 6)  # last for now; renumber() places it in its group
    db.add(category)
    db.flush()
    renumber(db)
    db.commit()
    return category


def update(db: Session, category: Category, name: str, group: str, aliases: str) -> None:
    """Changing the group moves the category to the end of the new group."""
    alias_list = clean_aliases(aliases)
    name = _check_fields(db, name, group, alias_list, category.id)
    if group != category.group_name:
        category.sort = 10 ** 6
    category.name, category.group_name, category.aliases = name, group, ", ".join(alias_list)
    db.flush()
    renumber(db)
    db.commit()


def set_active(db: Session, category: Category, active: bool) -> None:
    if not active and category.is_custom:
        raise CategoryError("Kategorii „własna” nie można dezaktywować — klipy z własną nazwą by jej potrzebowały.")
    category.is_active = active
    db.commit()


def delete(db: Session, category: Category) -> None:
    """A used category can only be deactivated."""
    if category.is_custom:
        raise CategoryError("Kategorii „własna” nie można usunąć.")
    used = usage_counts(db).get(category.id, 0)
    if used:
        raise CategoryInUseError(
            f"Kategoria „{category.name}” jest użyta w klipach ({used}) — nie można jej usunąć, "
            "tylko dezaktywować (znika z wyboru, a istniejące klipy dalej ją pokazują).")
    db.delete(category)
    db.flush()
    renumber(db)
    db.commit()


def move(db: Session, category: Category, direction: str) -> None:
    if direction not in ("up", "down"):
        raise CategoryError("Nieznany kierunek przesunięcia.")
    siblings = [c for c in renumber(db) if c.group_name == category.group_name]
    index = siblings.index(category)
    other = index - 1 if direction == "up" else index + 1
    if 0 <= other < len(siblings):
        category.sort, siblings[other].sort = siblings[other].sort, category.sort
    db.commit()
