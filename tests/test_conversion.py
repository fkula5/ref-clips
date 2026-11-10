import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app import config, services, video as vid, worker
from app.models import Job, Video
from app.storage import storage
from tests.conftest import needs_ffmpeg
from tests.helpers import make_match, make_ready_video, tus_upload
from tests.test_video import _make_source


def new_video(db, match, **kw):
    video = Video(match_id=match.id, **kw)
    db.add(video)
    db.flush()
    return video


def test_cut_jobs_take_priority_over_transcode(db):
    match = make_match(db)
    waiting = new_video(db, match, status="queued", original_path="uploads/a.mp4")
    services.enqueue(db, "transcode", video_id=waiting.id)
    ready = make_ready_video(db, match)
    clip = services.create_clip(db, ready, None, time_sec=30)
    db.commit()
    first = worker.claim_next(db)
    assert first.type == "cut" and first.clip_id == clip.id
    second = worker.claim_next(db)
    assert second.type == "transcode" and second.video_id == waiting.id
    assert worker.claim_next(db) is None


def test_cut_still_waits_for_ready_video(db):
    match = make_match(db)
    converting = new_video(db, match, status="processing", original_path="uploads/a.mp4")
    clip = services.create_clip(db, converting, None, time_sec=30)
    db.commit()
    assert worker.claim_next(db) is None
    assert clip.status == "queued"


def test_transcode_command_caps_fps_only_when_needed():
    src, dst = Path("in.mp4"), Path("out.mp4")
    vf = lambda cmd: cmd[cmd.index("-vf") + 1]
    assert "fps=30" in vf(vid.build_transcode_command("ffmpeg", src, dst, 60))
    assert "fps=30" in vf(vid.build_transcode_command("ffmpeg", src, dst, 50))
    for fps in (None, 24, 25, 29.97, 30):
        assert "fps=" not in vf(vid.build_transcode_command("ffmpeg", src, dst, fps)), fps
    cmd = vid.build_transcode_command("ffmpeg", src, dst, 60)
    assert cmd[cmd.index("-preset") + 1] == "veryfast" and cmd[cmd.index("-crf") + 1] == "23"
    assert "min(720,ih)" in vf(cmd) and "+faststart" in cmd


def test_ffmpeg_runs_with_lowered_priority(monkeypatch):
    cmd = vid._low_priority(["ffmpeg", "-i", "x"])
    assert cmd[1:3] == ["-n", "10"] and cmd[0].endswith("nice") and cmd[3:] == ["ffmpeg", "-i", "x"]
    monkeypatch.setattr(config, "FFMPEG_NICE", 5)
    assert vid._low_priority(["ffmpeg"])[2] == "5"
    monkeypatch.setattr(config, "FFMPEG_NICE", 0)
    assert vid._low_priority(["ffmpeg"]) == ["ffmpeg"]


def test_niced_child_really_has_lower_priority():
    out = subprocess.run(vid._low_priority(["nice"]), capture_output=True, text=True, check=True).stdout
    assert int(out) >= 10


def _fps_of(path) -> float:
    return vid.probe(path)["fps"]


@needs_ffmpeg
def test_transcode_limits_60fps_to_30_and_keeps_lower_rates(tmp_path):
    src60 = _make_source(tmp_path / "s60.mp4", seconds=4, rate=60, brightness_steps=False)
    info = vid.probe(src60)
    assert info["max_fps"] == pytest.approx(60, abs=0.1)
    out = tmp_path / "o60.mp4"
    vid.transcode_to_proxy(src60, out, 4, src_fps=info["max_fps"])
    assert _fps_of(out) <= 30.5
    assert vid.probe(out)["duration"] == pytest.approx(4, abs=0.3)

    src25 = _make_source(tmp_path / "s25.mp4", seconds=4, rate=25, brightness_steps=False)
    out25 = tmp_path / "o25.mp4"
    vid.transcode_to_proxy(src25, out25, 4, src_fps=vid.probe(src25)["max_fps"])
    assert _fps_of(out25) == pytest.approx(25, abs=0.1)


def _ff(*args):
    subprocess.run([vid.ffmpeg_bin(), "-y", "-loglevel", "error", *args], check=True)


def _convert(src, dst):
    vid.transcode_to_proxy(src, dst, vid.probe(src)["duration"], src_fps=vid.probe(src)["max_fps"])
    return dst


@needs_ffmpeg
def test_verify_conversion_tolerance_and_streams(tmp_path):
    src = _make_source(tmp_path / "s.mp4", seconds=4)
    info = vid.probe(src)
    assert vid.verify_conversion(info, src)["duration"] == pytest.approx(4, abs=0.2)
    assert vid.verify_tolerance(10) == 2 and vid.verify_tolerance(3600) == 36
    vid.verify_conversion({**info, "video_duration": info["video_duration"] + 1.9}, src)
    with pytest.raises(vid.FFmpegError, match="różni się"):
        vid.verify_conversion({**info, "video_duration": info["video_duration"] + 2.5}, src)
    with pytest.raises(vid.FFmpegError):
        vid.verify_conversion({**info, "video_duration": None}, src)
    audio_only = tmp_path / "a.m4a"
    _ff("-f", "lavfi", "-i", "sine=duration=4", str(audio_only))
    with pytest.raises(vid.FFmpegError, match="wideo"):
        vid.verify_conversion(info, audio_only)


@needs_ffmpeg
def test_verify_accepts_audio_longer_than_video(tmp_path):
    """Phone: audio 3 s longer than the video must not invalidate a correct conversion."""
    src = tmp_path / "long_audio.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=13",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src))
    info = vid.probe(src)
    assert info["video_duration"] == pytest.approx(10, abs=0.2) and info["duration"] == pytest.approx(13, abs=0.3)
    proxy = _convert(src, tmp_path / "p.mp4")
    assert vid.verify_conversion(info, proxy)["video_duration"] == pytest.approx(10, abs=0.3)


@needs_ffmpeg
def test_verify_accepts_nonzero_start_time(tmp_path):
    src = tmp_path / "offset.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-output_ts_offset", "37.5", str(src))
    start = float(subprocess.run([vid.ffprobe_bin(), "-v", "error", "-show_entries", "format=start_time",
                                  "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout)
    assert start > 30
    info = vid.probe(src)
    proxy = _convert(src, tmp_path / "p.mp4")
    assert vid.verify_conversion(info, proxy)["video_duration"] == pytest.approx(8, abs=0.3)


@needs_ffmpeg
def test_verify_rejects_truncated_result(tmp_path):
    src = _make_source(tmp_path / "s.mp4", seconds=10)
    info = vid.probe(src)
    proxy = _convert(src, tmp_path / "p.mp4")
    half = tmp_path / "half.mp4"
    _ff("-i", str(proxy), "-t", "5", "-c", "copy", str(half))
    with pytest.raises(vid.FFmpegError, match="różni się"):
        vid.verify_conversion(info, half)


@pytest.fixture(scope="module")
def short_source(tmp_path_factory):
    return _make_source(tmp_path_factory.mktemp("conv") / "short.mp4", seconds=6, brightness_steps=False)


@needs_ffmpeg
def test_full_flow_tus_upload_worker_ready_original_removed(client, db, short_source):
    match = make_match(db)
    tus_upload(client, match.id, short_source.read_bytes(), chunk=300_000, content="Q2", label="Q2")
    video = db.scalar(select(Video))
    original = video.original_path
    assert video.status == "queued" and storage.exists(original)

    assert worker.run_once() is True
    db.expire_all()
    video = db.get(Video, video.id)
    assert video.status == "ready" and video.error is None
    assert video.original_path is None and not storage.exists(original)
    assert storage.exists(video.proxy_path) and video.duration == pytest.approx(6, abs=0.3)
    assert video.proxy_bytes == storage.size(video.proxy_path) > 0
    assert video.expires_at is not None and video.content == "Q2"
    assert vid.probe(storage.local_path(video.proxy_path))["height"] == 240
    r = client.get(f"/videos/{video.id}/stream", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100


@needs_ffmpeg
def test_mismatched_result_keeps_original_and_retry_works(client, db, short_source, monkeypatch):
    match = make_match(db)
    tus_upload(client, match.id, short_source.read_bytes())
    video = db.scalar(select(Video))
    original = video.original_path

    real = vid.transcode_to_proxy

    def truncating(src, dst, duration, on_progress=None, src_fps=None):
        real(src, dst, duration, on_progress, src_fps)
        short = dst.with_name("short.mp4")  # a result half as long => duration mismatch
        subprocess.run([vid.ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(dst), "-t", "2",
                        "-c", "copy", str(short)], check=True)
        short.replace(dst)

    monkeypatch.setattr(vid, "transcode_to_proxy", truncating)
    assert worker.run_once() is True
    db.expire_all()
    video = db.get(Video, video.id)
    assert video.status == "error" and "Oryginał zostaje" in video.error
    assert video.original_path == original and storage.exists(original)
    assert video.proxy_path is None and not storage.exists(f"proxies/{video.id}.mp4")
    assert "Ponów konwersję" in client.get(f"/matches/{match.id}").text

    monkeypatch.setattr(vid, "transcode_to_proxy", real)
    r = client.post(f"/videos/{video.id}/retry", follow_redirects=False)
    assert r.status_code == 303
    assert worker.run_once() is True
    db.expire_all()
    video = db.get(Video, video.id)
    assert video.status == "ready" and video.original_path is None and not storage.exists(original)


@needs_ffmpeg
def test_failed_transcode_keeps_original(client, db):
    match = make_match(db)
    tus_upload(client, match.id, b"to nie jest wideo" * 100)
    video = db.scalar(select(Video))
    assert worker.run_once() is True
    db.expire_all()
    video = db.get(Video, video.id)
    assert video.status == "error" and storage.exists(video.original_path)


def test_retry_without_original_is_refused_with_clear_message(client, db):
    match = make_match(db)
    video = new_video(db, match, status="error", error="coś poszło nie tak", original_path=None)
    db.commit()
    r = client.post(f"/videos/{video.id}/retry", follow_redirects=False)
    assert r.status_code == 409 and "Oryginał został już usunięty" in r.json()["detail"]
    page = client.get(f"/matches/{match.id}").text
    assert "ponowna konwersja jest niemożliwa" in page and "Ponów konwersję" not in page
    r = client.post(f"/videos/{video.id}/retry", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 409 and "Oryginał został już usunięty" in r.text


def test_retry_only_after_error(client, db):
    match = make_match(db)
    video = new_video(db, match, status="queued", original_path="uploads/x.mp4")
    db.commit()
    assert client.post(f"/videos/{video.id}/retry", follow_redirects=False).status_code == 409
    assert db.scalar(select(Job)) is None


def test_retry_with_missing_original_file_is_refused(client, db):
    match = make_match(db)
    video = new_video(db, match, status="error", original_path="uploads/zniknal.mp4")
    db.commit()
    assert client.post(f"/videos/{video.id}/retry", follow_redirects=False).status_code == 409
