"""Dane początkowe: domyślny użytkownik i słownik tagów."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tag, User

DEFAULT_TAGS: list[tuple[str, str]] = [
    ("PTS", ""),
    ("U", ""),
    ("T", ""),
    ("D", ""),
    ("kroki", "krok, przekroczenie, bieg"),
    ("podwójne", "podwojne prowadzenie, podwójne prowadzenie, dwutakt"),
    ("3s", "3 s, 3 sek, 3sek, 3 sekundy"),
    ("5s", "5 s, 5 sek, 5sek, 5 sekund"),
    ("8s", "8 s, 8 sek, 8sek, 8 sekund"),
    ("24s", "24 s, 24 sek, 24sek, 24 sekundy"),
    ("aut", "out, piłka na aut"),
    ("blok", "bloku, blokiem"),
    ("szarża", "szarza, szarży, szarzy, charge"),
    ("faul", "faula, faulu"),
    ("brak gwizdka", "bez gwizdka, nie gwizdnął, nie gwizdnela, no call"),
]


def seed(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is None:
        db.add(User(name="Ja", role="admin"))
    if db.scalar(select(Tag.id).limit(1)) is None:
        for i, (name, aliases) in enumerate(DEFAULT_TAGS):
            db.add(Tag(name=name, aliases=aliases, sort=i * 10))
    db.commit()
