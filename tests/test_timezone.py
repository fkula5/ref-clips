import re
from datetime import date, datetime
from pathlib import Path

import pytest

from app import config, timeutil
from app.web import env as app_env


@pytest.fixture()
def warsaw(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Warsaw")


def test_winter_is_plus_one_hour(warsaw):
    assert timeutil.local(datetime(2026, 1, 15, 10, 30)) == "15.01.2026 11:30"


def test_summer_is_plus_two_hours(warsaw):
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 12:30"


def test_crossing_midnight_changes_the_date(warsaw):
    assert timeutil.local(datetime(2026, 1, 15, 23, 30)) == "16.01.2026 00:30"
    assert timeutil.local(datetime(2026, 7, 15, 22, 30)) == "16.07.2026 00:30"
    assert timeutil.local(datetime(2026, 12, 31, 23, 59), "%d.%m.%Y") == "01.01.2027"


def test_dst_change_in_spring_and_autumn(warsaw):
    # 2026-03-29: 01:00 UTC is 03:00 CEST (jump 02:00 -> 03:00); a moment earlier it is still CET.
    assert timeutil.local(datetime(2026, 3, 29, 0, 59)) == "29.03.2026 01:59"
    assert timeutil.local(datetime(2026, 3, 29, 1, 0)) == "29.03.2026 03:00"
    # 2026-10-25: 01:00 UTC is 02:00 CET (back from 03:00 CEST).
    assert timeutil.local(datetime(2026, 10, 25, 0, 59)) == "25.10.2026 02:59"
    assert timeutil.local(datetime(2026, 10, 25, 1, 0)) == "25.10.2026 02:00"


def test_empty_value_and_a_plain_date_are_not_converted(warsaw):
    assert timeutil.local(None) == ""
    assert timeutil.local(date(2026, 7, 15), "%d.%m.%Y") == "15.07.2026"


def test_another_timezone_from_config(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "UTC")
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 10:30"


def test_invalid_timezone_falls_back_to_warsaw(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Nie/Ma_Takiej")
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 12:30"


def test_local_filter_in_templates(warsaw):
    assert "local" in app_env.filters
    out = app_env.from_string('{{ t|local("%d.%m.%Y %H:%M") }}|{{ n|local("%d.%m.%Y") }}|{{ d|local("%d.%m.%Y") }}').render(
        t=datetime(2026, 7, 15, 22, 30), n=None, d=date(2026, 7, 15))
    assert out == "16.07.2026 00:30||15.07.2026"


def test_templates_do_not_use_strftime():
    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    offenders = [p.name for p in templates.glob("*.html") if re.search(r"strftime", p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_match_page_shows_local_time(db, make_client):
    from app.models import Comment
    from tests.helpers import make_match

    client, user = make_client("admin")
    match = make_match(db)
    db.add(Comment(match_id=match.id, author_id=user.id, body="Test", created_at=datetime(2026, 7, 15, 22, 30)))
    db.commit()
    page = client.get(f"/matches/{match.id}").text
    assert "16.07.2026 00:30" in page and "15.07.2026 22:30" not in page
