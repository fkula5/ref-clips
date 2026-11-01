"""Stan meczu wyliczany z nagrań: czyste funkcje, bez bazy."""
from datetime import datetime

import pytest

from app import services
from app.models import PeriodMark, Video


def video(status="ready", content="full", marks=(), purged=False, id=1) -> Video:
    v = Video(id=id, status=status, content=content,
              purged_at=datetime(2026, 11, 1) if purged else None)
    v.marks = [PeriodMark(period=p, time_sec=i * 600) for i, p in enumerate(marks)]
    return v


def code(*videos, queue=None) -> str:
    return services.match_state(videos, queue).code


def test_no_videos():
    state = services.match_state([])
    assert state.code == "none" and state.label == "brak nagrania"


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_converting(status):
    state = services.match_state([video(status)])
    assert state.code == "converting" and state.label == "konwersja"


def test_converting_shows_queue_position_or_progress():
    queued = services.match_state([video("queued", id=5)], {5: 3})
    assert queued.detail == "pozycja w kolejce: 3"
    assert services.match_state([video("queued", id=5)]).detail == ""             # brak zadania
    assert services.match_state([video("processing", id=5)], {5: 1}).detail == "w toku"
    best = services.match_state([video("queued", id=1), video("queued", id=2)], {1: 4, 2: 2})
    assert best.detail == "pozycja w kolejce: 2"


def test_uploading():
    assert services.match_state([video("uploading")]).label == "wgrywanie"


def test_conversion_error():
    state = services.match_state([video("error")])
    assert state.code == "error" and state.label == "błąd konwersji"


def test_error_wins_over_converting_and_ready():
    assert code(video("ready", marks=("Q1", "Q2", "Q3", "Q4")), video("error", id=2), video("queued", id=3)) == "error"


def test_converting_wins_over_missing_marks():
    assert code(video("ready"), video("queued", id=2)) == "converting"


def test_ready_full_match_without_marks_needs_marks():
    state = services.match_state([video("ready", "full")])
    assert state.code == "no_marks" and state.label == "brak znaczników kwart"


def test_undeclared_content_is_treated_as_full_match():
    for content in ("", None, "cokolwiek"):
        assert code(video("ready", content)) == "no_marks"
    assert code(video("ready", "", marks=("Q1", "Q2", "Q3", "Q4"))) == "ready"


def test_full_match_with_partial_marks_is_incomplete():
    assert code(video("ready", "full", marks=("Q1", "Q2", "Q3"))) == "no_marks"
    assert code(video("ready", "full", marks=("Q1", "Q2", "Q3", "Q4"))) == "ready"
    assert code(video("ready", "full", marks=("Q1", "Q2", "Q3", "Q4", "OT1"))) == "ready"


def test_multi_quarter_file_needs_marks_for_declared_quarters_only():
    assert code(video("ready", "Q1,Q2")) == "no_marks"
    assert code(video("ready", "Q1,Q2", marks=("Q1",))) == "no_marks"
    assert code(video("ready", "Q1,Q2", marks=("Q1", "Q2"))) == "ready"
    assert code(video("ready", "Q3,Q4", marks=("Q3", "Q4"))) == "ready"     # nie wymaga Q1/Q2


def test_single_quarter_file_does_not_need_marks():
    assert code(video("ready", "Q2")) == "ready"
    assert code(video("ready", "OT1")) == "ready"


def test_missing_marks_in_any_ready_video_counts():
    q1 = video("ready", "Q1", id=1)
    q2q3 = video("ready", "Q2,Q3", id=2)
    assert code(q1, q2q3) == "no_marks"
    q2q3.marks = [PeriodMark(period="Q2", time_sec=0), PeriodMark(period="Q3", time_sec=600)]
    assert code(q1, q2q3) == "ready"


def test_ready():
    assert services.match_state([video("ready", "full", marks=("Q1", "Q2", "Q3", "Q4"))]).label == "gotowy"


def test_purged_full_recording():
    state = services.match_state([video("ready", purged=True)])
    assert state.code == "purged" and state.label == "pełne nagranie usunięte"


def test_purged_video_is_not_asked_for_marks_but_other_videos_decide():
    purged = video("ready", "full", purged=True, id=1)
    assert code(purged, video("ready", "Q1", id=2)) == "ready"
    assert code(purged, video("ready", "Q1,Q2", id=2)) == "no_marks"
    assert code(purged, video("ready", purged=True, id=2)) == "purged"


def test_declared_and_missing_periods():
    assert services.declared_periods("full") is None
    assert services.declared_periods("Q2, q1") == ["Q1", "Q2"]
    assert services.declared_periods("Q1,XX") == ["Q1"]
    assert services.missing_periods("full", ["Q1", "Q2"]) == ["Q3", "Q4"]
    assert services.missing_periods("Q1,Q2", ["Q2"]) == ["Q1"]
    assert services.missing_periods("Q4", []) == []


def test_transcode_queue_positions(db):
    from app.models import Job, Match
    from datetime import date
    match = Match(date=date(2026, 10, 1))
    db.add(match)
    db.flush()
    vids = [Video(match_id=match.id, status="queued") for _ in range(4)]
    db.add_all(vids)
    db.flush()
    db.add_all([Job(type="transcode", status="pending", video_id=vids[0].id),
                Job(type="transcode", status="running", video_id=vids[1].id),
                Job(type="transcode", status="pending", video_id=vids[2].id),
                Job(type="transcode", status="done", video_id=vids[3].id),
                Job(type="cut", status="pending", video_id=vids[3].id)])
    db.commit()
    assert services.transcode_queue(db) == {vids[1].id: 1, vids[0].id: 2, vids[2].id: 3}
