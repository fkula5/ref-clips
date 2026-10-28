import pytest

from app.notes_parser import RefereeDef, TagDef, TeamDef, parse_notes, parse_time
from app.seed import DEFAULT_TAGS

REFEREES = [RefereeDef(1, "Filip Kowalski"), RefereeDef(2, "Kasia Żółć"), RefereeDef(3, "Łukasz Nowak")]
TAGS = [TagDef(n, tuple(a.strip() for a in al.split(",") if a.strip())) for n, al in DEFAULT_TAGS]
TEAMS = [TeamDef("a", ("Legia", "białe")), TeamDef("b", ("Wisła", "ciemne"))]


def parse(text):
    return parse_notes(text, REFEREES, TAGS, TEAMS)


@pytest.mark.parametrize("text,expected", [
    ("2:54", 174), ("02:54", 174), ("0:05", 5), ("12:30", 750), ("1:02:15", 3735),
    ("2.54", 174), ("2,54", 174), ("1.02.15", 3735), ("75:30", 4530), (" 2:54 ", 174),
])
def test_parse_time_formats(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "2:5", "2:60", "1:75:00", "1:02:61", "254"])
def test_parse_time_invalid(text):
    assert parse_time(text) is None


def test_basic_lines_from_plan():
    rows = parse("2:54 Filip PTS\n3:17 Filip Dlaczego nie blok?\n1:02:15 Kasia kroki białe błąd")
    assert [r.time_sec for r in rows] == [174, 197, 3735]
    assert [r.referee_id for r in rows] == [1, 1, 2]
    assert rows[0].tags == ["PTS"]
    assert rows[1].tags == ["blok"]
    assert rows[2].tags == ["kroki"] and rows[2].team == "a"
    assert rows[0].description == "2:54 Filip PTS"
    assert all(not r.warnings for r in rows)


@pytest.mark.parametrize("line", ["2.54 filip pts", "2,54 FILIP PTS", "2:54 - Filip PTS", "2:54) Filip, PTS"])
def test_time_separators_and_case(line):
    r = parse(line)[0]
    assert r.time_sec == 174 and r.referee_id == 1 and r.tags == ["PTS"]


def test_referee_polish_characters_ignored():
    r = parse("1:10 lukasz aut")[0]
    assert r.referee_id == 3 and r.tags == ["aut"]
    r = parse("1:10 ŁUKASZ aut")[0]
    assert r.referee_id == 3
    r = parse("1:10 kasia kroki")[0]
    assert r.referee_id == 2
    r = parse("1:10 Zolc kroki")[0]  # po nazwisku, bez polskich znaków
    assert r.referee_id == 2


def test_referee_inflection_and_full_name():
    assert parse("0:30 Filipa PTS")[0].referee_id == 1
    assert parse("0:30 Kasi PTS")[0].referee_id == 2
    r = parse("0:30 Filip Kowalski PTS")[0]
    assert r.referee_id == 1 and r.tags == ["PTS"]


def test_unknown_referee_warns():
    r = parse("2:54 Marek PTS")[0]
    assert r.ok and r.referee_id is None
    assert any("Nieznany sędzia" in w for w in r.warnings)
    assert r.tags == ["PTS"]


def test_missing_referee_when_first_word_is_tag():
    r = parse("2:54 PTS")[0]
    assert r.referee_id is None and r.tags == ["PTS"]
    assert any("Brak sędziego" in w for w in r.warnings)


def test_ambiguous_referee():
    refs = [RefereeDef(1, "Jan Kowal"), RefereeDef(2, "Jan Nowak")]
    r = parse_notes("1:00 Jan PTS", refs, TAGS)[0]
    assert r.referee_id is None and any("Niejednoznaczny" in w for w in r.warnings)
    assert parse_notes("1:00 Nowak PTS", refs, TAGS)[0].referee_id == 2


def test_unparseable_lines_warn_but_are_kept():
    rows = parse("bez czasu Filip PTS\n99:99:99 Filip PTS\n1:02:75 Filip PTS\n\n# komentarz\n2:54 Filip PTS")
    assert [r.ok for r in rows] == [False, False, False, True]
    assert rows[0].line_no == 1 and rows[3].line_no == 6
    assert all(r.warnings for r in rows[:3])


def test_multiword_and_numeric_tags():
    r = parse("5:00 Filip brak gwizdka 3 s")[0]
    assert r.tags == ["3s", "brak gwizdka"]
    r = parse("5:00 Filip 24s i 8 sek")[0]
    assert r.tags == ["8s", "24s"]
    r = parse("5:00 Filip szarza w ataku")[0]
    assert r.tags == ["szarża"]


def test_short_tags_only_uppercase():
    assert parse("1:00 Filip U")[0].tags == ["U"]
    assert parse("1:00 Filip T i D")[0].tags == ["T", "D"]
    assert parse("1:00 Filip u mnie nie ma t ani d")[0].tags == []


def test_tag_word_boundaries():
    assert parse("1:00 Filip autor zagrania")[0].tags == []
    assert parse("1:00 Filip aut!")[0].tags == ["aut"]


def test_unknown_tags_ignored_description_kept():
    r = parse("1:00 Filip dziwna sytuacja")[0]
    assert r.tags == [] and r.description == "1:00 Filip dziwna sytuacja"


def test_team_detection():
    assert parse("1:00 Filip blok białych")[0].team == "a"
    assert parse("1:00 Filip blok Wisła")[0].team == "b"
    assert parse("1:00 Filip blok ciemne")[0].team == "b"
    both = parse("1:00 Filip blok białe ciemne")[0]
    assert both.team is None and any("drużyna" in w for w in both.warnings)
    assert parse("1:00 Filip blok")[0].team is None


def test_time_only_line():
    r = parse("2:54")[0]
    assert r.ok and r.referee_id is None and any("Brak opisu" in w for w in r.warnings)
