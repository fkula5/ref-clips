"""A sheet copies the element name at creation, so none of these operations changes an existing sheet.
"Used" means referenced by at least one sheet row; a used element can only be deactivated.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import SheetElement, SheetRow
from app.textutil import normalize


class SheetElementError(ValueError):
    status_code = 422


class SheetElementInUseError(SheetElementError):
    status_code = 409


def ordered(db: Session, *, active_only: bool = False) -> list[SheetElement]:
    query = select(SheetElement).order_by(SheetElement.sort, SheetElement.id)
    if active_only:
        query = query.where(SheetElement.is_active)
    return list(db.scalars(query))


def usage_counts(db: Session) -> dict[int, int]:
    return {eid: n for eid, n in db.execute(
        select(SheetRow.element_id, func.count()).where(SheetRow.element_id.is_not(None))
        .group_by(SheetRow.element_id))}


def renumber(db: Session) -> list[SheetElement]:
    """Gaps of 10, so swapping two neighbours is always possible."""
    items = ordered(db)
    for index, element in enumerate(items, start=1):
        element.sort = index * 10
    db.flush()
    return items


def _clean_name(db: Session, name: str, own_id: int | None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise SheetElementError("Podaj nazwę elementu.")
    if len(name) > config.SHEET_ELEMENT_NAME_MAX_CHARS:
        raise SheetElementError(f"Nazwa elementu: najwyżej {config.SHEET_ELEMENT_NAME_MAX_CHARS} znaków.")
    for other in ordered(db):
        if other.id != own_id and normalize(other.name) == normalize(name):
            raise SheetElementError(f"Element „{other.name}” już istnieje "
                                    "(nazwy porównujemy bez względu na wielkość liter i polskie znaki).")
    return name


def create(db: Session, name: str) -> SheetElement:
    element = SheetElement(name=_clean_name(db, name, None), is_active=True, sort=10 ** 6)
    db.add(element)
    db.flush()
    renumber(db)
    db.commit()
    return element


def rename(db: Session, element: SheetElement, name: str) -> None:
    element.name = _clean_name(db, name, element.id)
    db.commit()


def set_active(db: Session, element: SheetElement, active: bool) -> None:
    element.is_active = active
    db.commit()


def delete(db: Session, element: SheetElement) -> None:
    used = usage_counts(db).get(element.id, 0)
    if used:
        raise SheetElementInUseError(
            f"Element „{element.name}” jest użyty w arkuszach ({used}) — nie można go usunąć, tylko dezaktywować "
            "(znika z nowych arkuszy, a istniejące dalej go pokazują).")
    db.delete(element)
    db.flush()
    renumber(db)
    db.commit()


def move(db: Session, element: SheetElement, direction: str) -> None:
    if direction not in ("up", "down"):
        raise SheetElementError("Nieznany kierunek przesunięcia.")
    items = renumber(db)
    index = items.index(element)
    other = index - 1 if direction == "up" else index + 1
    if 0 <= other < len(items):
        element.sort, items[other].sort = items[other].sort, element.sort
    db.commit()
