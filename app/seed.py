"""Aliases are read by the notes parser (case and Polish diacritics are ignored, except the one-letter
T/U/D, which must be capitals). The abbreviation "PTS" is deliberately not guessed.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Setting

# (group, [(name, comma-separated aliases, is_custom), ...])
DEFAULT_CATEGORIES: list[tuple[str, list[tuple[str, str, bool]]]] = [
    ("Faule", [
        ("osobisty", "faul osobisty, osobistego", False),
        ("w akcji rzutowej", "faul w akcji rzutowej, faul przy rzucie, faul rzutowy", False),
        ("blok / szarża", "blok, bloku, blokiem, szarża, szarza, szarży, szarzy, charge", False),
        ("niesportowy", "faul niesportowy, niesportowego, U", False),
        ("techniczny", "faul techniczny, technik, T", False),
        ("dyskwalifikujący", "dyskwalifikujacy, dyskwalifikacja, faul dyskwalifikujący, D", False),
    ]),
    ("Naruszenia", [
        ("kroki", "krok, przekroczenie, traveling", False),
        ("podwójny kozioł", "podwójne prowadzenie, podwojne prowadzenie, podwójne, double dribble", False),
        ("3 s", "3s, 3 sek, 3sek, 3 sekundy", False),
        ("5 s", "5s, 5 sek, 5sek, 5 sekund", False),
        ("8 s", "8s, 8 sek, 8sek, 8 sekund", False),
        ("24 s", "24s, 24 sek, 24sek, 24 sekundy", False),
        ("aut", "out, piłka na aut", False),
        ("goaltending / interferencja", "goaltending, interferencja, interference", False),
    ]),
    ("Bez gwizdka", [
        ("brak gwizdka (powinien być)", "brak gwizdka, bez gwizdka, nie gwizdnął, nie gwizdnęła, no call", False),
        ("gwizdek niepotrzebny", "niepotrzebny gwizdek, zbędny gwizdek, niepotrzebnie zagwizdał", False),
    ]),
    ("Mechanika", [
        ("pozycja / poruszanie się", "pozycja, pozycje, poruszanie się, poruszanie, pozycjonowanie", False),
        ("rotacja", "rotacje, rotacji", False),
        ("współpraca w zespole", "współpraca, wspolpraca, komunikacja", False),
        ("sygnalizacja", "sygnalizacji, sygnał, sygnalizowanie", False),
    ]),
    ("Inne", [
        ("inne", "", False),
        ("własna", "", True),
    ]),
]

DEFAULT_SETTINGS = {"retention_days": "30"}


def seed(db: Session) -> None:
    """Only when absent: admin changes are not overwritten."""
    if db.scalar(select(Category.id).limit(1)) is None:
        sort = 0
        for group, items in DEFAULT_CATEGORIES:
            for name, aliases, is_custom in items:
                sort += 10
                db.add(Category(group_name=group, name=name, aliases=aliases,
                                is_custom=is_custom, sort=sort))
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(Setting, key) is None:
            db.add(Setting(key=key, value=value))
    db.commit()
