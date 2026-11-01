import base64
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


# --- klient tus ---------------------------------------------------------------------
TUS = {"Tus-Resumable": "1.0.0"}


def tus_metadata(**values) -> str:
    """Nagłówek Upload-Metadata: klucz + base64(wartość)."""
    return ",".join(f"{k} {base64.b64encode(str(v).encode()).decode()}" for k, v in values.items())


def tus_create(client, match_id, size, filename="mecz.mp4", **meta):
    """POST tworzący upload (odpowiedź, bez sprawdzania statusu)."""
    return client.post("/uploads/", headers={**TUS, "Upload-Length": str(size),
                                             "Upload-Metadata": tus_metadata(filename=filename, match_id=match_id, **meta)})


def tus_patch(client, url, offset, data):
    return client.patch(url, content=data, headers={**TUS, "Upload-Offset": str(offset),
                                                    "Content-Type": "application/offset+octet-stream"})


def tus_upload(client, match_id, data: bytes, filename="mecz.mp4", chunk=None, **meta) -> str:
    """Pełne wgranie pliku protokołem tus (opcjonalnie w kawałkach). Zwraca adres uploadu."""
    r = tus_create(client, match_id, len(data), filename, **meta)
    assert r.status_code == 201, r.text
    url = r.headers["Location"]
    offset = 0
    while offset < len(data):
        part = data[offset:offset + (chunk or len(data))]
        r = tus_patch(client, url, offset, part)
        assert r.status_code == 204, r.text
        offset = int(r.headers["Upload-Offset"])
    return url
