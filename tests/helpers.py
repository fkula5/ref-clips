from datetime import date
from functools import lru_cache

from app import security
from app.models import Match, MatchOfficial, User, Video
from app.storage import storage

PASSWORD = "correct-horse-battery"


@lru_cache(maxsize=1)
def password_hash() -> str:
    """Jeden hash argon2 na cały przebieg testów (hashowanie jest celowo wolne)."""
    return security.hash_password(PASSWORD)


def make_user(db, roles=("referee",), email="user@example.com", name="Użytkownik", *,
              password=True, active=True) -> User:
    user = User(email=email, name=name, is_active=active,
                password_hash=password_hash() if password else None)
    user.set_roles(roles)
    db.add(user)
    db.commit()
    return user


def make_match(db, officials=(("CC", "Filip Kowalski"), ("U1", "Kasia Żółć")), created_by=None):
    """Mecz z obsadą: pozycja to (funkcja, User) albo (funkcja, wpisane imię i nazwisko)."""
    match = Match(date=date(2026, 10, 28), level="II liga", team_a_name="Legia", team_a_color="białe",
                  team_b_name="Wisła", team_b_color="ciemne",
                  created_by=created_by.id if created_by else None)
    for function, who in officials:
        if isinstance(who, User):
            match.officials.append(MatchOfficial(function=function, user_id=who.id))
        else:
            match.officials.append(MatchOfficial(function=function, name=who))
    db.add(match)
    db.commit()
    return match


def make_ready_video(db, match, duration=600.0, content=b"fakevideo"):
    """Nagranie już po konwersji (bez ffmpeg): plik 'wersji roboczej' to zwykłe bajty."""
    video = Video(match_id=match.id, label="Całość", status="ready", duration=duration, fps=25)
    db.add(video)
    db.commit()
    key = f"proxies/{video.id}.mp4"
    with storage.open_write(key) as fh:
        fh.write(content)
    video.proxy_path = key
    db.commit()
    return video
