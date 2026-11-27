"""Load fictional basketball data into a local Ref Clips database on demand."""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session
from weasyprint import HTML

from app import config, notify, self_assessments, services, sheets, video
from app.db import SessionLocal
from app.models import (Category, Clip, Comment, GroupMember, League, Match, MatchOfficial,
                        MatchScoresheet, PeriodMark, Rating, TrainingGroup, TrainingSet,
                        TrainingSetClip, TrainingSetGroup, User, Video)
from app.storage import storage
from app.timeutil import utcnow

LEAGUE = "Liga szkoleniowa DEMO"
TEAMS = ("Sokoły DEMO", "Wilki DEMO")
COACH_EMAIL = "trener-refclips-demo@example.test"
WIDTH, HEIGHT, FPS, DURATION = 960, 540, 24, 46


def render_recording(output: Path) -> None:
    court = Image.new("RGB", (WIDTH, HEIGHT), "#10261f")
    draw = ImageDraw.Draw(court)
    wood, paint, line = "#dca665", "#ce8a4b", "#fff1d6"
    draw.rounded_rectangle((32, 82, 928, 514), 13, fill=wood)
    for x in range(49, 910, 28):
        draw.line((x, 104, x, 492), fill="#d29a5b", width=1)
    for box in ((51, 103, 909, 492), (51, 229, 208, 366), (752, 229, 909, 366)):
        draw.rectangle(box, fill=paint if box[1] == 229 else None, outline=line, width=3)
    draw.line((480, 103, 480, 492), fill=line, width=3)
    for x in (208, 480, 752):
        draw.circle((x, 298), 56, outline=line, width=3)
    draw.arc((-130, 127, 327, 469), -90, 90, fill=line, width=3)
    draw.arc((633, 127, 1090, 469), 90, 270, fill=line, width=3)
    for x in (81, 879):
        draw.circle((x, 298), 13, outline="#a14027", width=4)

    ui = ImageFont.load_default(size=19)
    score = ImageFont.load_default(size=27)
    number_font = ImageFont.load_default(size=12)
    draw.text((36, 17), "REF CLIPS / DEMO", font=score, fill="#f9f5e9")
    draw.text((37, 50), "Symulacja szkoleniowa", font=ui, fill="#a8c6b6")
    draw.text((368, 27), "SOKOLY  24 : 22  WILKI", font=score, fill="#f9f5e9")
    starters = ((145, 184), (256, 273), (282, 400), (440, 186), (490, 355))
    encoder = [
        config.FFMPEG_PATH, "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}",
        "-framerate", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", str(output),
    ]
    with subprocess.Popen(encoder, stdin=subprocess.PIPE) as process:
        for frame_number in range(FPS * DURATION):
            second = frame_number / FPS
            picture = court.copy()
            frame = ImageDraw.Draw(picture)
            progress = (1 + math.sin(second * 0.44 - math.pi / 2)) / 2
            attack = 275 * progress
            frame.text((807, 27), f"Q{1 + int(second >= 23)}  {max(0, 23 - int(second % 23)):02d}s",
                       font=score, fill="#eac88e")
            players = []
            for index, (x, y) in enumerate(starters):
                x += attack + 31 * math.sin(second * 1.1 + index * 1.8)
                y += 38 * math.cos(second * 0.81 + index)
                players.append((x, y))
                for dx, dy, color, number in ((0, 0, "#134f72", index + 4), (48, 28, "#963b48", index + 10)):
                    position = (x + dx, y + dy)
                    frame.circle(position, 15, fill=color, outline="#fdf5e5", width=2)
                    frame.text(position, str(number), anchor="mm", font=number_font, fill="white")
            phase = second / 2.4
            index, mix = int(phase) % len(players), phase % 1
            start, end = players[index], players[(index + 1) % len(players)]
            x = start[0] + (end[0] - start[0]) * mix
            y = start[1] + (end[1] - start[1]) * mix - 19 * math.sin(math.pi * mix)
            frame.circle((x + 9, y - 9), 7, fill="#ffac43", outline="#583123", width=2)
            process.stdin.write(picture.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("FFmpeg nie zapisał nagrania demo.")


def coach_account(db: Session) -> User:
    coach = db.scalar(select(User).where(User.email == COACH_EMAIL))
    if coach is None:
        coach = User(email=COACH_EMAIL, name="Alicja Zielińska (demo)", is_active=True)
        coach.set_roles(["coach"])
        db.add(coach)
        db.flush()
    return coach


def make_matches(db: Session, referee: User) -> Match:
    if db.scalar(select(League.id).where(League.name == LEAGUE)) is None:
        db.add(League(name=LEAGUE))
    today = date.today()
    games = []
    for days, teams in ((0, TEAMS), (4, ("Orły DEMO", "Sokoły DEMO")),
                        (8, ("Wilki DEMO", "Żubry DEMO"))):
        games.append(Match(
            date=today - timedelta(days=days), team_a_name=teams[0], team_b_name=teams[1],
            team_a_color="granatowe", team_b_color="bordowe", level=LEAGUE, created_by=referee.id,
            officials=[
                MatchOfficial(function="CC", user=referee),
                MatchOfficial(function="U1", name="Marek Kłos (demo)"),
                MatchOfficial(function="U2", name="Ewa Lis (demo)"),
            ],
        ))
    db.add_all(games)
    db.flush()
    return games[0]


def make_clips(db: Session, match: Match, referee: User, recording: Video) -> list[Clip]:
    clips = []
    scenes = (
        (7, "aut", "Piłka zagrana przy linii bocznej. Porównaj ustawienie sędziego z kierunkiem podania."),
        (17, "współpraca w zespole", "Szybka zmiana strony ataku. Zwróć uwagę na podział obserwacji."),
        (31, "pozycja / poruszanie się", "Obrona przesuwa się po podaniu. Wybierz miejsce dające lepszy kąt widzenia."),
    )
    for time, category, description in scenes:
        category_id = db.scalar(select(Category.id).where(Category.name == category))
        clip = services.create_clip(db, recording, referee, time_sec=time,
                                    official_id=match.officials[0].id, category_id=category_id,
                                    description=description, margin_before=3, margin_after=4, cut=False)
        clip.described_at, clip.described_by_id = utcnow(), referee.id
        clips.append(clip)
    services.create_clip(db, recording, referee, time_sec=40, margin_before=3, margin_after=4, cut=False)
    return clips


def add_training_and_feedback(db: Session, match: Match, referee: User, coach: User, clips: list[Clip]) -> None:
    group = TrainingGroup(
        name="Akademia sędziów DEMO", description="Grupa do ćwiczeń z mechaniki i pracy zespołu.",
        created_by=coach.id, members=[
            GroupMember(user=coach, role="coach"), GroupMember(user=referee, role="referee"),
        ],
    )
    training_set = TrainingSet(
        name="Pozycja i współpraca DEMO", description="Trzy sytuacje do samodzielnego omówienia.",
        created_by=coach.id, pins=[TrainingSetGroup(group=group)],
        items=[TrainingSetClip(clip=clip, position=index, note="Zatrzymaj obraz i zaproponuj ustawienie.")
               for index, clip in enumerate(clips, 1)],
    )
    rating = Rating(clip=clips[0], coach=coach, verdict="correct",
                    comment="Dobry kąt obserwacji przy linii bocznej.")
    comment = Comment(clip=clips[0], author=coach,
                      body="Po podaniu warto utrzymać w polu widzenia obrońcę.")
    match_comment = Comment(match=match, author=coach,
                            body="Na omówieniu porównamy ustawienie w obu kwartach.")
    db.add_all([training_set, rating, comment, match_comment])
    db.flush()
    notify.group_added(db, group, referee.id, coach.id)
    notify.rating_saved(db, rating, coach.id, changed=False)
    notify.comment_added(db, comment)
    notify.comment_added(db, match_comment)

    sheet, _ = sheets.create(db, match, coach)
    values = {"result": "24 : 22", "difficulty": "normalny", "crew_note": "Dobra komunikacja po zmianie strony."}
    if sheet.rows:
        values[sheets.cell_key(sheet.rows[0], sheet.columns[0])] = "Czytelny kąt obserwacji i spokojna reakcja."
    sheets.save(db, sheet, values, publish=True)

    assessment, _ = self_assessments.get_or_create(db, match, referee)
    for clip in clips:
        self_assessments.save(db, assessment, {}, [], action=f"add:{clip.id}")
    self_assessments.save(db, assessment, {
        "opinion": "Dobrze współpracowaliśmy po zmianie strony ataku.",
        "good": "Zachowam spokojną komunikację przy decyzjach na linii.",
        "bad": "Po podaniach na obwód chcę szybciej zmieniać kąt obserwacji.",
    }, [], action="submit")


def copy_media(source: Path, key: str, created: list[str]) -> int:
    destination = storage.local_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as target:
        created.append(key)
        with source.open("rb") as stream:
            shutil.copyfileobj(stream, target)
    return destination.stat().st_size


def demo_paths(match: Match) -> list[str]:
    return [
        f"Mecz /matches/{match.id}",
        *(f"Nagranie /recordings/{recording.id}" for recording in match.videos),
        *(f"Klip /clips/{clip.id}" for clip in match.clips),
    ]


def seed_demo(email: str) -> tuple[bool, list[str]]:
    with SessionLocal() as db:
        referee = db.scalar(select(User).where(User.email == email.strip().lower(), User.is_active))
        if referee is None or "referee" not in referee.roles:
            raise SystemExit("Podaj adres aktywnego konta testowego z rolą sędziego.")
        existing = db.scalar(select(Match).where(
            Match.level == LEAGUE, Match.team_a_name == TEAMS[0], Match.team_b_name == TEAMS[1],
        ))
        if existing is not None:
            return False, demo_paths(existing)

        created: list[str] = []
        try:
            with TemporaryDirectory(dir=config.DATA_DIR) as temporary:
                folder = Path(temporary)
                master = folder / "demo.mp4"
                render_recording(master)
                coach = coach_account(db)
                match = make_matches(db, referee)
                recording = Video(
                    match=match, original_filename="symulacja-demo.mp4", label="Symulacja meczu · Q1 i Q2",
                    status="ready", content="Q1,Q2", fps=FPS, duration=DURATION, created_by=referee.id,
                    marks=[PeriodMark(period="Q1", time_sec=0), PeriodMark(period="Q2", time_sec=23)],
                )
                db.add(recording)
                db.flush()
                recording.proxy_path = f"proxies/{recording.id}.mp4"
                recording.proxy_bytes = recording.size_bytes = copy_media(master, recording.proxy_path, created)
                clips = make_clips(db, match, referee, recording)
                for clip in clips:
                    cut = folder / f"clip-{clip.id}.mp4"
                    start, end = services.clip_range(clip)
                    video.cut_clip(master, cut, start, end - start)
                    clip.clip_path, clip.clip_version, clip.status = f"clips/{clip.id}_v1.mp4", 1, "cut"
                    copy_media(cut, clip.clip_path, created)
                add_training_and_feedback(db, match, referee, coach, clips)

                protocol = folder / "protokol.pdf"
                HTML(string="<meta charset=utf-8><h1>Protokół demonstracyjny</h1>"
                            "<p>Sokoły DEMO – Wilki DEMO</p><p>Wynik 24 : 22</p>"
                            "<p>Symulacja do szkolenia sędziów.</p>").write_pdf(protocol)
                key = f"scoresheets/demo-{match.id}.pdf"
                size = copy_media(protocol, key, created)
                db.add(MatchScoresheet(match=match, path=key, original_filename="Protokół DEMO.pdf",
                                       content_type="application/pdf", size_bytes=size, uploaded_by=referee.id))
            db.commit()
        except BaseException:
            db.rollback()
            for key in created:
                storage.delete(key)
            raise
        return True, demo_paths(match)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--referee", required=True, help="E-mail istniejącego konta testowego")
    args = parser.parse_args()
    created, paths = seed_demo(args.referee)
    print("Utworzono dane demo." if created else "Dane demo już istnieją.")
    print(*paths, sep="\n")
