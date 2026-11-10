"""Snapshots: when a sheet is created, element names (rows) and the officials' function and display name
(columns) are copied into it, so later changes to the dictionary or the crew never change it.
Posted form fields that are missing are left untouched, so a stale form can never wipe stored text.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config, notify, permissions, sheet_elements
from app.models import SHEET_DIFFICULTIES, Match, Sheet, SheetCell, SheetColumn, SheetRow, User
from app.timeutil import utcnow

FUNCTION_ORDER = {"CC": 0, "U1": 1, "U2": 2}


class SheetError(Exception):
    status_code = 422

    def __init__(self, *errors: str):
        super().__init__(" ".join(errors))
        self.errors = list(errors)


def cell_key(row: SheetRow, column: SheetColumn) -> str:
    return f"cell_{row.id}_{column.id}"


def overall_key(column: SheetColumn) -> str:
    return f"overall_{column.id}"


def recommendation_key(column: SheetColumn) -> str:
    return f"recommendation_{column.id}"


def visible_to(user: User, match: Match) -> list[Sheet]:
    found = [s for s in match.sheets if permissions.can_view_sheet(user, s)]
    return sorted(found, key=lambda s: (s.coach_id != user.id, s.published_at or s.created_at, s.id))


def grid(sheet: Sheet) -> list[tuple[SheetRow, list[SheetCell]]]:
    rows = []
    for row in sheet.rows:
        by_column = {cell.column_id: cell for cell in row.cells}
        rows.append((row, [by_column.get(column.id) or SheetCell(row_id=row.id, column_id=column.id, text="")
                           for column in sheet.columns]))
    return rows


def form_values(sheet: Sheet) -> dict[str, str]:
    values = {"result": sheet.result, "difficulty": sheet.difficulty or "", "crew_note": sheet.crew_note}
    for column in sheet.columns:
        values[overall_key(column)] = column.overall
        values[recommendation_key(column)] = column.recommendation
    for row, cells in grid(sheet):
        for column, cell in zip(sheet.columns, cells):
            values[cell_key(row, column)] = cell.text
    return values


def texts(sheet: Sheet) -> Iterator[str]:
    for row, cells in grid(sheet):
        for cell in cells:
            yield cell.text
    for column in sheet.columns:
        yield column.overall
        yield column.recommendation
    yield sheet.crew_note


def empty_count(sheet: Sheet) -> tuple[int, int]:
    all_texts = list(texts(sheet))
    return sum(1 for t in all_texts if not t.strip()), len(all_texts)


def _crew(match: Match) -> list[tuple[str, str]]:
    return sorted(((o.function, o.display_name) for o in match.officials), key=lambda p: FUNCTION_ORDER[p[0]])


def crew_changes(sheet: Sheet) -> list[str]:
    crew = {name: function for function, name in _crew(sheet.match)}
    columns = {c.official_name: c for c in sheet.columns}
    changes = [f"nowy w obsadzie: {function} · {name}" for name, function in crew.items() if name not in columns]
    changes += [f"zmieniona funkcja: {name} ({column.function} → {crew[name]})"
                for name, column in columns.items() if name in crew and crew[name] != column.function]
    changes += [f"nie ma już w obsadzie: {column.label}" for name, column in columns.items() if name not in crew]
    return changes


def _own(db: Session, match_id: int, coach_id: int) -> Sheet | None:
    return db.scalar(select(Sheet).where(Sheet.match_id == match_id, Sheet.coach_id == coach_id))


def _new_cells(db: Session, rows: list[SheetRow], columns: list[SheetColumn]) -> None:
    db.add_all(SheetCell(row_id=row.id, column_id=column.id, text="") for row in rows for column in columns)


def create(db: Session, match: Match, coach: User) -> tuple[Sheet, bool]:
    """The unique constraint (match, coach) decides a race of two requests: the loser gets the winner's
    sheet.
    """
    existing = _own(db, match.id, coach.id)
    if existing is not None:
        return existing, False
    if not match.officials:
        raise SheetError("Ten mecz nie ma obsady — najpierw wpisz sędziów (Edytuj mecz).")
    now = utcnow()
    sheet = Sheet(match_id=match.id, coach_id=coach.id, created_at=now, updated_at=now)
    sheet.columns = [SheetColumn(position=i, function=function, official_name=name)
                     for i, (function, name) in enumerate(_crew(match))]
    sheet.rows = [SheetRow(position=i, element_id=e.id, name=e.name)
                  for i, e in enumerate(sheet_elements.ordered(db, active_only=True))]
    db.add(sheet)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = _own(db, match.id, coach.id)
        if winner is None:
            raise
        return winner, False
    _new_cells(db, sheet.rows, sheet.columns)
    db.flush()
    return sheet, True


def _text(raw: str | None, label: str, limit: int, errors: list[str]) -> str | None:
    """The limit is counted after normalising line endings."""
    if raw is None:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > limit:
        errors.append(f"{label}: najwyżej {limit} znaków (jest {len(text)}).")
    return text


def _validate(sheet: Sheet, posted: dict[str, str], publish: bool) -> dict[str, str]:
    """Raises SheetError listing every problem (nothing is changed)."""
    errors: list[str] = []
    clean: dict[str, str] = {}
    limit = config.TEXT_MAX_CHARS

    def put(key: str, label: str, max_chars: int = limit) -> None:
        value = _text(posted.get(key), label, max_chars, errors)
        if value is not None:
            clean[key] = value

    put("result", "Wynik", config.SHEET_RESULT_MAX_CHARS)
    put("crew_note", "Uwaga o parze sędziowskiej")
    for column in sheet.columns:
        put(overall_key(column), f"Ocena ogólna, {column.label}")
        put(recommendation_key(column), f"Rekomendacja, {column.label}")
    for row in sheet.rows:
        for column in sheet.columns:
            put(cell_key(row, column), f"{row.name}, {column.label}")
    difficulty = posted.get("difficulty", sheet.difficulty or "").strip()
    clean["difficulty"] = difficulty
    if difficulty and difficulty not in SHEET_DIFFICULTIES:
        errors.append("Stopień trudności: wybierz łatwy, normalny albo trudny.")
    elif not difficulty and (publish or sheet.is_published):
        errors.append("Wybierz stopień trudności — bez niego arkusza nie można opublikować.")
    if errors:
        raise SheetError(*errors)
    return clean


def _apply(sheet: Sheet, clean: dict[str, str]) -> bool:
    changed = False

    def set_attr(obj, attr: str, value: str | None) -> None:
        nonlocal changed
        if value is not None and getattr(obj, attr) != value:
            setattr(obj, attr, value)
            changed = True

    set_attr(sheet, "result", clean.get("result"))
    set_attr(sheet, "crew_note", clean.get("crew_note"))
    if sheet.difficulty != (clean["difficulty"] or None):
        sheet.difficulty = clean["difficulty"] or None
        changed = True
    for column in sheet.columns:
        set_attr(column, "overall", clean.get(overall_key(column)))
        set_attr(column, "recommendation", clean.get(recommendation_key(column)))
    for row, cells in grid(sheet):
        for column, cell in zip(sheet.columns, cells):
            value = clean.get(cell_key(row, column))
            if cell in row.cells:
                set_attr(cell, "text", value)
            elif value:
                row.cells.append(SheetCell(column_id=column.id, text=value))
                changed = True
    return changed


def save(db: Session, sheet: Sheet, posted: dict[str, str], *, publish: bool = False) -> bool:
    """`updated_at` moves only when the content changed, because "changed <date>" is shown from it."""
    clean = _validate(sheet, posted, publish)
    changed = _apply(sheet, clean)
    now = utcnow()
    if publish and not sheet.is_published:
        sheet.status, sheet.published_at, sheet.updated_at = "published", now, now
        notify.sheet_published(db, sheet)
        return True
    if changed:
        sheet.updated_at = now
    return False


def _has_text(sheet: Sheet, column: SheetColumn) -> bool:
    if column.overall.strip() or column.recommendation.strip():
        return True
    return any(cell.text.strip() for row in sheet.rows for cell in row.cells if cell.column_id == column.id)


def refresh_crew(db: Session, sheet: Sheet) -> list[str]:
    """A column of someone who left the crew is removed only if it holds no text; written text is never
    dropped.
    """
    notes: list[str] = []
    crew = {name: function for function, name in _crew(sheet.match)}
    columns = {c.official_name: c for c in sheet.columns}
    for name, function in crew.items():
        if name in columns:
            columns[name].function = function
    fresh = [SheetColumn(sheet_id=sheet.id, position=0, function=function, official_name=name)
             for name, function in crew.items() if name not in columns]
    db.add_all(fresh)
    for name, column in columns.items():
        if name in crew:
            continue
        if _has_text(sheet, column):
            notes.append(f"Zostawiono kolumnę {column.label}, bo zawiera tekst — usuń ten tekst i odśwież obsadę "
                         "ponownie, żeby ją usunąć.")
        else:
            for row in sheet.rows:
                row.cells = [cell for cell in row.cells if cell.column_id != column.id]
            db.delete(column)
    db.flush()
    _new_cells(db, sheet.rows, fresh)
    db.flush()
    db.expire_all()
    kept = sorted(sheet.columns, key=lambda c: (c.official_name not in crew, FUNCTION_ORDER[c.function], c.id))
    for position, column in enumerate(kept):
        column.position = position
    sheet.updated_at = utcnow()
    db.flush()
    return notes
