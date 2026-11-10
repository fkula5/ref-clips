import re
from datetime import date, datetime
from pathlib import Path

import pytest

from app import config, timeutil
from app.web import env as app_env


@pytest.fixture()
def warsaw(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Warsaw")


def test_zima_to_plus_jeden_godzina(warsaw):
    assert timeutil.local(datetime(2026, 1, 15, 10, 30)) == "15.01.2026 11:30"


def test_lato_to_plus_dwie_godziny(warsaw):
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 12:30"


def test_przejscie_przez_polnoc_zmienia_date(warsaw):
    assert timeutil.local(datetime(2026, 1, 15, 23, 30)) == "16.01.2026 00:30"
    assert timeutil.local(datetime(2026, 7, 15, 22, 30)) == "16.07.2026 00:30"
    assert timeutil.local(datetime(2026, 12, 31, 23, 59), "%d.%m.%Y") == "01.01.2027"


def test_zmiana_czasu_wiosna_i_jesien(warsaw):
    # 2026-03-29: 01:00 UTC is 03:00 CEST (jump 02:00 -> 03:00); a moment earlier it is still CET.
    assert timeutil.local(datetime(2026, 3, 29, 0, 59)) == "29.03.2026 01:59"
    assert timeutil.local(datetime(2026, 3, 29, 1, 0)) == "29.03.2026 03:00"
    # 2026-10-25: 01:00 UTC is 02:00 CET (back from 03:00 CEST).
    assert timeutil.local(datetime(2026, 10, 25, 0, 59)) == "25.10.2026 02:59"
    assert timeutil.local(datetime(2026, 10, 25, 1, 0)) == "25.10.2026 02:00"


def test_pusta_wartosc_i_sama_data_nie_sa_przeliczane(warsaw):
    assert timeutil.local(None) == ""
    assert timeutil.local(date(2026, 7, 15), "%d.%m.%Y") == "15.07.2026"


def test_inna_strefa_z_konfiguracji(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "UTC")
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 10:30"


def test_bledna_strefa_wraca_do_warszawy(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Nie/Ma_Takiej")
    assert timeutil.local(datetime(2026, 7, 15, 10, 30)) == "15.07.2026 12:30"


def test_filtr_local_w_szablonach(warsaw):
    assert "local" in app_env.filters
    out = app_env.from_string('{{ t|local("%d.%m.%Y %H:%M") }}|{{ n|local("%d.%m.%Y") }}|{{ d|local("%d.%m.%Y") }}').render(
        t=datetime(2026, 7, 15, 22, 30), n=None, d=date(2026, 7, 15))
    assert out == "16.07.2026 00:30||15.07.2026"


def test_szablony_nie_uzywaja_strftime():
    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    offenders = [p.name for p in templates.glob("*.html") if re.search(r"strftime", p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_strona_meczu_pokazuje_czas_lokalny(db, make_client):
    from app.models import Comment
    from tests.helpers import make_match

    client, user = make_client("admin")
    match = make_match(db)
    db.add(Comment(match_id=match.id, author_id=user.id, body="Test", created_at=datetime(2026, 7, 15, 22, 30)))
    db.commit()
    page = client.get(f"/matches/{match.id}").text
    assert "16.07.2026 00:30" in page and "15.07.2026 22:30" not in page
