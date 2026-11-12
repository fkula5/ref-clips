"""Training sets: curated clips with the coach's own notes. Every coach and admin edits every set;
referees only view. Referee names are hidden in a set's views unless the set's `show_names` is on:
only the crew function (CC / U1 / U2) is shown then, and the same goes for the download file name.
Sets only collect clips: they never change a clip, and deleting a clip removes it from sets.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config, feedback, groups, services, share
from app.models import Clip, TrainingGroup, TrainingSet, TrainingSetClip, TrainingSetGroup, User
from app.pagination import Page, paginate

NAME_MAX = 100
DESCRIPTION_MAX = 1000
WHOLE_TEAM = "cały zespół"


class SetError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SetRow:
    training_set: TrainingSet
    clips: int


def _clean(name: str, description: str) -> tuple[str, str]:
    name, description = name.strip(), description.strip()
    if not name:
        raise SetError("Podaj nazwę zestawu.")
    if len(name) > NAME_MAX:
        raise SetError(f"Nazwa zestawu: najwyżej {NAME_MAX} znaków.")
    if len(description) > DESCRIPTION_MAX:
        raise SetError(f"Opis zestawu: najwyżej {DESCRIPTION_MAX} znaków.")
    return name, description


def clean_note(raw: str) -> str:
    try:
        return feedback.clean_text(raw, label="Notatka", required=False)
    except feedback.FeedbackError as exc:
        raise SetError(str(exc)) from None


def _with_counts():
    counts = (select(TrainingSetClip.set_id.label("set_id"), func.count().label("n"))
              .group_by(TrainingSetClip.set_id).subquery())
    return select(TrainingSet, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.set_id == TrainingSet.id)


def _by_name(query):
    return query.order_by(func.lower(TrainingSet.name), TrainingSet.id)


def list_sets(db: Session, requested: int = 1) -> tuple[list[SetRow], Page]:
    size = config.SET_PAGE_SIZE
    pager = paginate(db.scalar(select(func.count()).select_from(TrainingSet)) or 0, requested, size)
    rows = db.execute(_by_name(_with_counts()).options(
        selectinload(TrainingSet.pins).selectinload(TrainingSetGroup.group)).limit(size).offset(pager.offset))
    return [SetRow(s, n) for s, n in rows], pager


def pinned_sets(db: Session, group_ids: list[int]) -> dict[int, list[SetRow]]:
    """The sets pinned to each of the groups, by name."""
    found: dict[int, list[SetRow]] = {}
    rows = db.execute(_by_name(_with_counts().add_columns(TrainingSetGroup.group_id)
                               .join(TrainingSetGroup, TrainingSetGroup.set_id == TrainingSet.id)
                               .where(TrainingSetGroup.group_id.in_(group_ids))))
    for training_set, n, group_id in rows:
        found.setdefault(group_id, []).append(SetRow(training_set, n))
    return found


def create_set(db: Session, creator: User, name: str, description: str = "") -> TrainingSet:
    name, description = _clean(name, description)
    training_set = TrainingSet(name=name, description=description, created_by=creator.id)
    db.add(training_set)
    db.flush()
    return training_set


def update_set(db: Session, training_set: TrainingSet, name: str, description: str, show_names: bool) -> None:
    training_set.name, training_set.description = _clean(name, description)
    training_set.show_names = show_names
    db.commit()


def delete_set(db: Session, training_set: TrainingSet) -> None:
    db.delete(training_set)
    db.commit()


def items_of(db: Session, training_set: TrainingSet) -> list[TrainingSetClip]:
    return list(db.scalars(
        select(TrainingSetClip).where(TrainingSetClip.set_id == training_set.id)
        .options(selectinload(TrainingSetClip.clip).selectinload(Clip.match),
                 selectinload(TrainingSetClip.clip).selectinload(Clip.official),
                 selectinload(TrainingSetClip.clip).selectinload(Clip.category))
        .order_by(TrainingSetClip.position, TrainingSetClip.clip_id)))


def _renumber(items: list[TrainingSetClip]) -> None:
    for position, item in enumerate(items, start=1):
        item.position = position


def _int(raw: str) -> int | None:
    raw = raw.strip()
    return int(raw) if raw.isascii() and raw.isdecimal() and len(raw) <= 12 else None


def _require_ready(clip: Clip) -> None:
    if not share.has_file(clip):
        raise SetError("Do zestawu można dodać tylko wycięty klip "
                       "(ten jeszcze się wycina albo cięcie się nie udało).", 409)


def add_clip(db: Session, training_set: TrainingSet, clip: Clip) -> TrainingSetClip:
    _require_ready(clip)
    if db.get(TrainingSetClip, (training_set.id, clip.id)) is not None:
        raise SetError(f"Ten klip jest już w zestawie „{training_set.name}”.", 409)
    last = db.scalar(select(func.max(TrainingSetClip.position)).where(TrainingSetClip.set_id == training_set.id))
    item = TrainingSetClip(set_id=training_set.id, clip_id=clip.id, position=(last or 0) + 1)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:  # added twice at once, or the clip was deleted meanwhile
        db.rollback()
        raise SetError(f"Nie udało się dodać klipu do zestawu „{training_set.name}” — spróbuj jeszcze raz.",
                       409) from None
    return item


def add_clip_to(db: Session, user: User, clip: Clip, set_id: str, new_name: str) -> TrainingSet:
    """An existing set (`set_id`) or a new one (`new_name`), not both. A new set is created only when the
    clip can be added, in one transaction.
    """
    new_name = new_name.strip()
    if new_name and set_id.strip():
        raise SetError("Wybierz istniejący zestaw albo wpisz nazwę nowego — nie oba naraz.")
    _require_ready(clip)
    if new_name:
        training_set = create_set(db, user, new_name)
    else:
        found = db.get(TrainingSet, _int(set_id)) if _int(set_id) is not None else None
        if found is None:
            raise SetError("Wybierz zestaw z listy albo wpisz nazwę nowego.")
        training_set = found
    add_clip(db, training_set, clip)
    db.commit()
    return training_set


def locate(items: list[TrainingSetClip], clip_id: int) -> int | None:
    return next((i for i, item in enumerate(items) if item.clip_id == clip_id), None)


def _item(db: Session, training_set: TrainingSet, clip_id: int) -> TrainingSetClip:
    item = db.get(TrainingSetClip, (training_set.id, clip_id))
    if item is None:
        raise SetError("Tego klipu nie ma w zestawie.", 404)
    return item


def move_clip(db: Session, training_set: TrainingSet, clip_id: int, direction: str) -> None:
    if direction not in ("up", "down"):
        raise SetError("Nieznany kierunek przesunięcia.")
    _item(db, training_set, clip_id)
    items = list(training_set.items)
    index = locate(items, clip_id)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]
        _renumber(items)
        db.commit()


def remove_clip(db: Session, training_set: TrainingSet, clip_id: int) -> None:
    item = _item(db, training_set, clip_id)
    training_set.items.remove(item)
    _renumber(training_set.items)
    db.commit()


def set_note(db: Session, training_set: TrainingSet, clip_id: int, raw: str) -> None:
    note = clean_note(raw)
    _item(db, training_set, clip_id).note = note
    db.commit()


def pin(db: Session, training_set: TrainingSet, group_id: str) -> TrainingGroup:
    group = db.get(TrainingGroup, _int(group_id)) if _int(group_id) is not None else None
    if group is None:
        raise SetError("Wybierz grupę z listy.")
    if any(p.group_id == group.id for p in training_set.pins):
        raise SetError(f"Zestaw jest już przypięty do grupy „{group.name}”.", 409)
    training_set.pins.append(TrainingSetGroup(group_id=group.id))
    db.commit()
    return group


def unpin(db: Session, training_set: TrainingSet, group_id: int) -> TrainingGroup:
    pinned = next((p for p in training_set.pins if p.group_id == group_id), None)
    if pinned is None:
        raise SetError("Zestaw nie jest przypięty do tej grupy.", 404)
    group = pinned.group
    training_set.pins.remove(pinned)
    db.commit()
    return group


def unpinned_groups(db: Session, training_set: TrainingSet) -> list[TrainingGroup]:
    pinned = {p.group_id for p in training_set.pins}
    return [g for g in groups.all_groups(db) if g.id not in pinned]


@dataclass
class Choice:
    id: int
    name: str
    has_clip: bool


def choices_for(db: Session, clip: Clip) -> list[Choice]:
    """Every set, flagged when it already holds the clip (the clip page offers the rest)."""
    holding = set(db.scalars(select(TrainingSetClip.set_id).where(TrainingSetClip.clip_id == clip.id)))
    rows = db.execute(_by_name(select(TrainingSet.id, TrainingSet.name)))
    return [Choice(i, name, i in holding) for i, name in rows]


def official_text(clip: Clip, show_names: bool) -> str:
    if clip.whole_team:
        return WHOLE_TEAM
    if clip.official is None:
        return ""
    return clip.official_label if show_names else clip.official.function


def filename(clip: Clip, training_set: TrainingSet) -> str:
    return services.clip_filename(clip, function_only=not training_set.show_names)
