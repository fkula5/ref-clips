"""Lista meczów: filtry (GET), „tylko moje”, stan, liczniki klipów, paginacja, wąski ekran."""
import re
from datetime import date, datetime

from app.models import Clip, Job, Match, MatchOfficial, PeriodMark, Video
from tests.helpers import make_ready_video, make_user


def add_match(db, day, *, level="II liga", name=None, crew=(), created_by=None) -> Match:
    """Mecz z unikalną nazwą drużyny (do rozpoznawania wierszy); crew: (funkcja, User | nazwisko)."""
    match = Match(date=day, level=level, team_a_name=name or f"Drużyna {day.isoformat()}", team_b_name="Rywal",
                  created_by=created_by.id if created_by else None)
    for function, who in crew:
        match.officials.append(MatchOfficial(function=function, user_id=getattr(who, "id", None),
                                             name=None if hasattr(who, "id") else who))
    db.add(match)
    db.commit()
    return match


def ids(response) -> list[int]:
    """Id meczów w kolejności z tabeli (linki w kolumnie „Mecz”)."""
    return [int(i) for i in re.findall(r'<td data-label="Mecz"[^>]*><a href="/matches/(\d+)"', response.text)]


def get(client, **params):
    r = client.get("/", params={k: v for k, v in params.items() if v is not None})
    assert r.status_code == 200
    return r


def test_list_is_sorted_by_date_descending(client, db):
    old = add_match(db, date(2026, 1, 5))
    new = add_match(db, date(2026, 10, 5))
    mid = add_match(db, date(2026, 6, 5))
    assert ids(get(client)) == [new.id, mid.id, old.id]


def test_empty_state_messages(client, db):
    assert "Nie ma jeszcze żadnego meczu" in get(client).text
    add_match(db, date(2026, 5, 1))
    assert "Brak meczów dla wybranych filtrów" in get(client, level="Nieistniejąca").text


def test_filter_by_date_range(client, db):
    a = add_match(db, date(2026, 3, 1))
    b = add_match(db, date(2026, 4, 10))
    c = add_match(db, date(2026, 5, 20))
    assert ids(get(client, date_from="2026-04-01")) == [c.id, b.id]
    assert ids(get(client, date_to="2026-04-10")) == [b.id, a.id]                  # granice włącznie
    assert ids(get(client, date_from="2026-04-10", date_to="2026-04-10")) == [b.id]
    assert ids(get(client, date_from="2026-06-01")) == []
    r = get(client, date_from="2026-04-01")
    assert 'name="date_from" value="2026-04-01"' in r.text                          # filtr zostaje w formularzu


def test_invalid_date_is_ignored_with_message(client, db):
    a = add_match(db, date(2026, 3, 1))
    r = get(client, date_from="wczoraj", date_to="2026-13-45")
    assert ids(r) == [a.id] and r.text.count("Niepoprawna data") == 2


def test_filter_by_level(client, db):
    a = add_match(db, date(2026, 3, 1), level="II liga")
    b = add_match(db, date(2026, 3, 2), level="Juniorzy U18")
    assert ids(get(client, level="Juniorzy U18")) == [b.id]
    assert ids(get(client, level="II liga")) == [a.id]
    r = get(client)
    assert ">Juniorzy U18</option>" in r.text and ">II liga</option>" in r.text
    assert 'value="Juniorzy U18" selected' in get(client, level="Juniorzy U18").text


def test_filter_by_referee_account_and_typed_name(client, db):
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    with_account = add_match(db, date(2026, 3, 1), crew=[("CC", ref), ("U1", "Ewa Druga")])
    typed = add_match(db, date(2026, 3, 2), crew=[("CC", "Jan Pierwszy"), ("U1", "Ewa Druga")])
    other = add_match(db, date(2026, 3, 3), crew=[("CC", "Kuba Trzeci"), ("U1", "Zenon Czwarty")])
    assert ids(get(client, person=f"u{ref.id}")) == [with_account.id]
    assert ids(get(client, person="njan pierwszy")) == [typed.id]
    assert ids(get(client, person="newa druga")) == [typed.id, with_account.id]
    assert other.id not in ids(get(client, person="newa druga"))
    page = get(client).text
    for label in ("Rafał Sędzia", "Jan Pierwszy", "Ewa Druga"):
        assert f">{label}</option>" in page


def test_referee_filter_treats_typed_name_and_account_of_same_person_as_one(client, db):
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    old = add_match(db, date(2026, 1, 1), crew=[("CC", "rafal sedzia"), ("U1", "X Y")])   # zanim miał konto
    new = add_match(db, date(2026, 2, 1), crew=[("CC", ref), ("U1", "X Y")])
    assert ids(get(client, person=f"u{ref.id}")) == [new.id, old.id]
    page = get(client).text
    assert page.count(">Rafał Sędzia</option>") == 1 and "rafal sedzia</option>" not in page


def test_only_mine_shows_matches_where_i_am_in_crew_or_created(make_client, db):
    me_client, me = make_client("coach", name="Ja Trener")
    _, other = make_client("coach", name="Inny")
    in_crew = add_match(db, date(2026, 3, 1), crew=[("CC", me), ("U1", "A B")], created_by=other)
    created = add_match(db, date(2026, 3, 2), crew=[("CC", "C D"), ("U1", "E F")], created_by=me)
    both = add_match(db, date(2026, 3, 3), crew=[("CC", me), ("U1", "E F")], created_by=me)
    foreign = add_match(db, date(2026, 3, 4), crew=[("CC", "C D"), ("U1", "E F")], created_by=other)
    typed_namesake = add_match(db, date(2026, 3, 5), crew=[("CC", "Ja Trener"), ("U1", "E F")], created_by=other)
    assert ids(get(me_client)) == [typed_namesake.id, foreign.id, both.id, created.id, in_crew.id]
    mine = ids(get(me_client, mine="1"))
    assert mine == [both.id, created.id, in_crew.id]       # wpisane nazwisko bez konta nie liczy się jako „ja”
    assert 'name="mine" value="1" checked' in get(me_client, mine="1").text


def test_filters_combine(make_client, db):
    me_client, me = make_client("referee", name="Ja Sędzia")
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    hit = add_match(db, date(2026, 4, 10), level="II liga", crew=[("CC", me), ("U1", ref)])
    add_match(db, date(2026, 4, 11), level="I liga", crew=[("CC", me), ("U1", ref)])        # inna liga
    add_match(db, date(2026, 2, 11), level="II liga", crew=[("CC", me), ("U1", ref)])       # poza zakresem
    add_match(db, date(2026, 4, 12), level="II liga", crew=[("CC", me), ("U1", "Ktoś Inny")])  # inny sędzia
    add_match(db, date(2026, 4, 13), level="II liga", crew=[("CC", "A B"), ("U1", ref)])    # bez mnie
    r = get(me_client, date_from="2026-04-01", date_to="2026-04-30", level="II liga",
            person=f"u{ref.id}", mine="1")
    assert ids(r) == [hit.id]


def test_pagination_25_per_page_keeps_filters(client, db):
    matches = [add_match(db, date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i),
                         level="II liga" if i % 2 == 0 else "I liga") for i in range(60)]
    newest_first = [m.id for m in reversed(matches)]
    r1 = get(client)
    assert ids(r1) == newest_first[:25] and "strona 1 z 3" in r1.text and "Mecze: 60" in r1.text
    assert "Starsze" in r1.text and "Nowsze" not in r1.text
    assert ids(get(client, page="2")) == newest_first[25:50]
    r3 = get(client, page="3")
    assert ids(r3) == newest_first[50:] and "Starsze" not in r3.text and "Nowsze" in r3.text
    assert ids(get(client, page="99")) == newest_first[50:]            # poza zakresem: ostatnia strona
    assert ids(get(client, page="abc")) == newest_first[:25]
    assert ids(get(client, page="-4")) == newest_first[:25]
    # filtr + paginacja: 30 meczów II ligi = 2 strony, a linki niosą filtr
    ii = [m.id for m in reversed(matches) if m.level == "II liga"]
    r = get(client, level="II liga")
    assert ids(r) == ii[:25] and "Mecze: 30" in r.text and "page=2" in r.text and "level=II+liga" in r.text
    assert ids(get(client, level="II liga", page="2")) == ii[25:]


def test_list_state_counts_and_queue_position(client, db):
    none = add_match(db, date(2026, 1, 1))
    ready = add_match(db, date(2026, 1, 2))
    v_ready = make_ready_video(db, ready)
    v_ready.content = "Q1"
    queued = add_match(db, date(2026, 1, 3))
    other_q = add_match(db, date(2026, 1, 4))
    errored = add_match(db, date(2026, 1, 5))
    nomarks = add_match(db, date(2026, 1, 6))
    purged = add_match(db, date(2026, 1, 7))
    for match, status in ((queued, "queued"), (other_q, "queued"), (errored, "error")):
        v = Video(match_id=match.id, status=status, label="x")
        db.add(v)
        db.flush()
        if status == "queued":
            db.add(Job(type="transcode", status="pending", video_id=v.id))
    make_ready_video(db, nomarks)                                  # zawartość „full” bez znaczników
    pv = make_ready_video(db, purged)
    pv.purged_at = datetime(2026, 1, 10)
    db.add_all([Clip(match_id=ready.id, video_id=v_ready.id, time_sec=10, described_at=datetime(2026, 1, 2)),
                Clip(match_id=ready.id, video_id=v_ready.id, time_sec=20),
                Clip(match_id=ready.id, video_id=v_ready.id, time_sec=30)])
    db.commit()
    page = get(client).text
    rows = re.findall(r"<tr>(.*?)</tr>", page, re.S)
    row = {m.id: next(r for r in rows if f'href="/matches/{m.id}"' in r)
           for m in (none, ready, queued, other_q, errored, nomarks, purged)}
    assert "brak nagrania" in row[none.id]
    assert "gotowy" in row[ready.id]
    assert "konwersja" in row[queued.id] and "pozycja w kolejce: 1" in row[queued.id]
    assert "pozycja w kolejce: 2" in row[other_q.id]
    assert "błąd konwersji" in row[errored.id]
    assert "brak znaczników kwart" in row[nomarks.id]
    assert "pełne nagranie usunięte" in row[purged.id]
    # 3 klipy, w tym 2 nieopisane
    assert re.search(r'data-label="Klipy"><a href="/clips\?match_id=%d">3</a>' % ready.id, row[ready.id])
    assert 'data-label="Nieopisane"><span class="chip warn">2</span>' in row[ready.id]
    assert 'data-label="Nieopisane">0<' in row[none.id]


def test_state_ready_after_marks_are_set(client, db):
    match = add_match(db, date(2026, 1, 1))
    v = make_ready_video(db, match)
    assert "brak znaczników kwart" in get(client).text
    db.add_all(PeriodMark(video_id=v.id, period=p, time_sec=i * 600) for i, p in enumerate(["Q1", "Q2", "Q3", "Q4"]))
    db.commit()
    assert "gotowy" in get(client).text


def test_table_is_responsive_and_filters_work_without_js(client, db):
    add_match(db, date(2026, 1, 1))
    page = get(client).text
    assert '<table class="responsive">' in page and 'data-label="Data"' in page and 'data-label="Stan"' in page
    assert '<form method="get" action="/"' in page and '<button class="btn">Filtruj</button>' in page
    css = client.get("/static/app.css").text
    assert "max-width: 720px" in css and "attr(data-label)" in css


def test_htmx_request_gets_page_with_list_fragment(client, db):
    m = add_match(db, date(2026, 1, 1))
    r = client.get("/?level=II+liga", headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="matches-list"' in r.text and f"/matches/{m.id}" in r.text
