from datetime import date

from app.models import Match, MatchReferee, Referee, Video
from app.storage import storage


def make_match(db, referees=("Filip", "Kasia")):
    match = Match(date=date(2026, 10, 28), level="II liga", team_a_name="Legia", team_a_color="białe",
                  team_b_name="Wisła", team_b_color="ciemne")
    for i, name in enumerate(referees):
        ref = Referee(name=name)
        match.referees.append(MatchReferee(referee=ref, role="crew_chief" if i == 0 else "umpire"))
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
