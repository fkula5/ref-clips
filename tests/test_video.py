"""Testy wideo. Część pracuje na prawdziwym ffmpeg (pomijana, gdy go brak)."""
import subprocess
from datetime import date

import pytest
from sqlalchemy import select

from app import config, services, video as vid
from app.models import Clip, Match, MatchOfficial, PeriodMark, Video
from tests.conftest import needs_ffmpeg
from tests.helpers import make_match, tus_upload


# --- czyste funkcje (bez ffmpeg) -------------------------------------------------
def test_clip_bounds_default_margins():
    assert services.clip_bounds(174, 15, 15, 600) == (159, 189)
    assert config.DEFAULT_MARGIN_BEFORE == config.DEFAULT_MARGIN_AFTER == 15


def test_clip_bounds_clamped_to_recording():
    assert services.clip_bounds(4, 10, 10, 600) == (0, 14)
    assert services.clip_bounds(595, 10, 10, 600) == (585, 600)
    start, end = services.clip_bounds(600, 10, 10, 600)
    assert (start, end) == (590, 600)
    assert services.clip_bounds(50, 10, 10, None) == (40, 60)


def test_commands_have_expected_flags():
    from pathlib import Path
    cmd = vid.build_cut_command("ffmpeg", Path("in.mp4"), Path("out.mp4"), 12.5, 20)
    assert cmd.index("-ss") < cmd.index("-i")  # szybkie szukanie + re-encode = dokładne cięcie
    assert "libx264" in cmd and "+faststart" in cmd
    tc = vid.build_transcode_command("ffmpeg", Path("in.mov"), Path("out.mp4"))
    assert "libx264" in tc and "aac" in tc and "+faststart" in tc
    assert any("min(720,ih)" in a for a in tc) and "-force_key_frames" in tc


def test_clip_filename(db):
    from app.models import Category
    match = Match(date=date(2026, 10, 28), team_a_name="A", team_b_name="B", level="III liga")
    video = Video(match=match, status="ready", duration=900)
    clip = Clip(match=match, video=video, time_sec=174)
    clip.official = MatchOfficial(function="CC", name="Filip Kowalski")
    clip.category = Category(group_name="Bez gwizdka", name="brak gwizdka (powinien być)")
    assert services.clip_filename(clip) == "III-liga_Kowalski_brak-gwizdka-powinien-byc.mp4"
    clip.whole_team, clip.category = True, None
    assert services.clip_filename(clip) == "III-liga_zespol.mp4"
    clip.official, clip.whole_team = None, False
    assert services.clip_filename(clip) == "III-liga.mp4"
    match.level = ""
    assert services.clip_filename(clip) == "klip.mp4"


def test_worker_waits_when_ffmpeg_missing(db, monkeypatch):
    from app import worker
    from tests.helpers import make_match
    match = make_match(db)
    video = Video(match_id=match.id, status="queued", original_path="uploads/x.mp4")
    db.add(video)
    db.flush()
    services.enqueue(db, "transcode", video_id=video.id)
    db.commit()
    monkeypatch.setattr(vid, "ffmpeg_bin", lambda: None)
    assert worker.run_once() is False
    db.refresh(video)
    assert video.status == "queued"


def test_worker_pipeline_with_fake_ffmpeg(db, monkeypatch):
    """Cały przepływ zadań (transcode -> cut) z podstawionymi funkcjami ffmpeg."""
    from app import worker
    from app.storage import storage
    from tests.helpers import make_match

    calls = []
    monkeypatch.setattr(vid, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(vid, "probe", lambda p: {"duration": 120.0, "video_duration": 120.0, "fps": 25.0, "width": 1280,
                                                 "height": 720, "has_audio": True})

    def fake_transcode(src, dst, duration, on_progress=None, src_fps=None):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"proxy")

    def fake_cut(src, dst, start, duration):
        calls.append((start, duration))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"clip")

    monkeypatch.setattr(vid, "transcode_to_proxy", fake_transcode)
    monkeypatch.setattr(vid, "cut_clip", fake_cut)

    match = make_match(db)
    video = Video(match_id=match.id, status="queued", original_path="uploads/in.mp4")
    db.add(video)
    db.flush()
    services.enqueue(db, "transcode", video_id=video.id)
    # klip utworzony przed końcem konwersji: cięcie ma poczekać na gotowe nagranie
    clip = services.create_clip(db, video, None, time_sec=5)
    db.commit()

    assert worker.run_once() is True       # transcode
    assert worker.run_once() is True       # cut
    assert worker.run_once() is False
    db.refresh(video)
    db.refresh(clip)
    assert video.status == "ready" and video.duration == 120.0
    assert video.original_path is None  # po udanej konwersji oryginał jest usuwany
    assert clip.status == "cut" and storage.exists(clip.clip_path)
    assert calls == [(0, 20)]  # początek obcięty do 0: 0..20 s (5 s + margines 15 s)

    services.queue_cut(db, clip)       # korekta -> nowa wersja, stary plik usunięty
    clip.margin_before, clip.margin_after = 3, 4
    db.commit()
    old = clip.clip_path
    assert worker.run_once() is True
    db.refresh(clip)
    assert clip.clip_version == 2 and clip.clip_path != old and not storage.exists(old)
    assert calls[-1] == (2, 7)


# --- prawdziwy ffmpeg ------------------------------------------------------------
def _make_source(path, seconds=20, size="320x240", rate=25, brightness_steps=True):
    """Wideo, którego jasność rośnie co sekundę (lum = 16 + 10*floor(t)), z dźwiękiem."""
    ff = vid.ffmpeg_bin()
    if brightness_steps:
        src = f"color=c=gray:s={size}:r={rate}:d={seconds},geq=lum='16+10*floor(T)':cb=128:cr=128"
    else:
        src = f"testsrc=duration={seconds}:size={size}:rate={rate}"
    subprocess.run(
        [ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", src,
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "50", "-c:a", "aac", "-shortest", str(path)],
        check=True)
    return path


def _luma_of_second(sec: int) -> float:
    """Jasność (po konwersji limited->full range do 'gray') klatki z danej sekundy źródła."""
    return (16 + 10 * sec - 16) * 255 / 219


def _first_frame_luma(path) -> float:
    out = subprocess.run(
        [vid.ffmpeg_bin(), "-loglevel", "error", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    assert len(out) == 64
    return sum(out) / len(out)


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    return _make_source(tmp_path_factory.mktemp("src") / "source.mp4")


@needs_ffmpeg
def test_probe(source):
    info = vid.probe(source)
    assert info["duration"] == pytest.approx(20, abs=0.2)
    assert (info["width"], info["height"]) == (320, 240)
    assert info["fps"] == pytest.approx(25, abs=0.1) and info["has_audio"]


@needs_ffmpeg
def test_transcode_to_proxy_720p_with_keyframes(tmp_path):
    big = _make_source(tmp_path / "big.mp4", seconds=6, size="1920x1080", rate=30, brightness_steps=False)
    proxy = tmp_path / "proxy.mp4"
    progress = []
    vid.transcode_to_proxy(big, proxy, 6, progress.append)
    info = vid.probe(proxy)
    assert info["height"] == 720 and info["width"] == 1280
    assert info["duration"] == pytest.approx(6, abs=0.3) and info["has_audio"]
    streams = subprocess.run(
        [vid.ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", str(proxy)], capture_output=True, text=True).stdout.strip()
    assert streams == "h264"
    keyframes = subprocess.run(
        [vid.ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(proxy)],
        capture_output=True, text=True).stdout.split()
    assert len(keyframes) >= 5  # klatka kluczowa mniej więcej co sekundę
    head = proxy.read_bytes()[:4096]
    assert b"moov" in head  # +faststart: metadane na początku pliku
    assert not list(tmp_path.glob("*.part.mp4"))


@needs_ffmpeg
def test_transcode_does_not_upscale(tmp_path, source):
    proxy = tmp_path / "proxy.mp4"
    vid.transcode_to_proxy(source, proxy, 20)
    assert vid.probe(proxy)["height"] == 240


@needs_ffmpeg
def test_cut_clip_length_and_start_frame(tmp_path, source):
    clip = tmp_path / "clip.mp4"
    vid.cut_clip(source, clip, start=6.2, duration=8.0)
    info = vid.probe(clip)
    assert info["duration"] == pytest.approx(8.0, abs=0.25)
    # pierwsza klatka pochodzi z sekundy 6 źródła (a nie np. 5 albo 7)
    assert _first_frame_luma(clip) == pytest.approx(_luma_of_second(6), abs=4)


@needs_ffmpeg
def test_cut_clip_clamped_at_recording_start_and_end(tmp_path, source):
    duration = vid.probe(source)["duration"]
    start, end = services.clip_bounds(4, 10, 10, duration)
    clip = tmp_path / "start.mp4"
    vid.cut_clip(source, clip, start, end - start)
    assert vid.probe(clip)["duration"] == pytest.approx(14, abs=0.25)
    assert _first_frame_luma(clip) < _luma_of_second(2) / 2  # klatka z początku nagrania (sekunda 0-1)

    start, end = services.clip_bounds(duration - 3, 10, 10, duration)
    clip = tmp_path / "end.mp4"
    vid.cut_clip(source, clip, start, end - start)
    assert vid.probe(clip)["duration"] == pytest.approx(13, abs=0.3)
    assert _first_frame_luma(clip) == pytest.approx(_luma_of_second(int(start)), abs=4)


@needs_ffmpeg
def test_cut_failure_leaves_no_partial_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(vid.FFmpegError):
        vid.cut_clip(bad, tmp_path / "out.mp4", 0, 5)
    assert list(tmp_path.glob("out*")) == []


@needs_ffmpeg
def test_end_to_end_upload_transcode_cut(client, db, source):
    """Upload przez API -> worker (konwersja, cięcie) -> pobranie klipu o długości 30 s."""
    from app import worker
    from app.storage import storage
    from tests.helpers import make_match

    match = make_match(db)
    tus_upload(client, match.id, source.read_bytes(), chunk=1024 * 1024)
    vid_id = db.scalar(select(Video.id))
    original = db.get(Video, vid_id).original_path
    assert storage.exists(original)
    assert worker.run_once() is True
    db.expire_all()
    assert db.get(Video, vid_id).original_path is None and not storage.exists(original)  # oryginał usunięty
    state = client.get(f"/api/videos/{vid_id}/state").json()
    assert state["duration"] == pytest.approx(20, abs=0.3)
    assert client.get(f"/videos/{vid_id}/stream", headers={"Range": "bytes=0-99"}).status_code == 206

    client.post(f"/api/videos/{vid_id}/marks", json={"time_sec": 0})
    c = client.post(f"/api/videos/{vid_id}/quick-clip", json={"time_sec": 9, "text": "CC kroki"}).json()["clip"]
    assert worker.run_once() is True
    clip = client.get(f"/clips/{c['id']}/download")
    assert clip.status_code == 200 and clip.content[4:8] == b"ftyp"
    assert "II-liga_Kowalski_kroki.mp4" in clip.headers["content-disposition"]
    # klip 0..24 s (9 +/- 15, obcięty do początku i do końca nagrania 20 s)
    out = db.get(Clip, c["id"])
    db.refresh(out)
    assert vid.probe(storage.local_path(out.clip_path))["duration"] == pytest.approx(20, abs=0.3)


@needs_ffmpeg
def test_default_clip_is_30_seconds_in_the_middle_of_a_recording(client, db, tmp_path):
    """Znacznik w środku nagrania: 15 s przed i 15 s po daje klip ok. 30 s."""
    from app import worker
    from app.storage import storage
    from tests.helpers import make_match

    long_source = _make_source(tmp_path / "long.mp4", seconds=50)
    match = make_match(db)
    tus_upload(client, match.id, long_source.read_bytes())
    vid_id = db.scalar(select(Video.id))
    assert worker.run_once() is True
    c = client.post(f"/api/videos/{vid_id}/quick-clip", json={"time_sec": 25, "text": ""}).json()["clip"]
    assert worker.run_once() is True
    out = db.get(Clip, c["id"])
    db.refresh(out)
    assert vid.probe(storage.local_path(out.clip_path))["duration"] == pytest.approx(30, abs=0.4)
