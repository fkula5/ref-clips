import pytest

from app.notes_parser import CategoryDef, RefereeDef, parse_notes, parse_time
from app.seed import DEFAULT_CATEGORIES

REFEREES = [RefereeDef(1, "Filip Kowalski", "CC"), RefereeDef(2, "Kasia Żółć", "U1"),
            RefereeDef(3, "Łukasz Nowak", "U2")]
CATEGORIES = [
    CategoryDef(name, tuple(a.strip() for a in aliases.split(",") if a.strip()))
    for _group, items in DEFAULT_CATEGORIES for name, aliases, _custom in items
]


def parse(text, referees=REFEREES):
    return parse_notes(text, referees, CATEGORIES)


@pytest.mark.parametrize("text,expected", [
    ("2:54", 174), ("02:54", 174), ("0:05", 5), ("12:30", 750), ("1:02:15", 3735),
    ("2.54", 174), ("2,54", 174), ("1.02.15", 3735), ("75:30", 4530), (" 2:54 ", 174),
])
def test_parse_time_formats(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "2:5", "2:60", "1:75:00", "1:02:61", "254"])
def test_parse_time_invalid(text):
    assert parse_time(text) is None


def test_basic_lines():
    rows = parse("2:54 Filip kroki\n3:17 Filip Dlaczego nie blok?\n1:02:15 Kasia 24 s błąd")
    assert [r.time_sec for r in rows] == [174, 197, 3735]
    assert [r.referee_id for r in rows] == [1, 1, 2]
    assert [r.category for r in rows] == ["kroki", "blok / szarża", "24 s"]
    assert rows[0].description == ""
    assert rows[1].description == "Dlaczego nie blok?"
    assert rows[2].description == "błąd"
    assert all(not r.warnings for r in rows)


@pytest.mark.parametrize("line", ["2.54 filip kroki", "2,54 FILIP KROKI", "2:54 - Filip kroki", "2:54) Filip, kroki"])
def test_time_separators_and_case(line):
    r = parse(line)[0]
    assert r.time_sec == 174 and r.referee_id == 1 and r.category == "kroki"


@pytest.mark.parametrize("token,expected_id", [
    ("CC", 1), ("cc", 1), ("U1", 2), ("u1", 2), ("U2", 3), ("U2,", 3),
])
def test_referee_by_function(token, expected_id):
    r = parse(f"2:54 {token} kroki")[0]
    assert r.referee_id == expected_id and r.category == "kroki" and not r.warnings


def test_function_not_in_crew_is_unknown_referee():
    crew = REFEREES[:2]
    r = parse("2:54 U2 kroki", crew)[0]
    assert r.referee_id is None and any("Nieznany sędzia" in w for w in r.warnings)


def test_referee_polish_characters_ignored():
    r = parse("1:10 lukasz aut")[0]
    assert r.referee_id == 3 and r.category == "aut"
    r = parse("1:10 ŁUKASZ aut")[0]
    assert r.referee_id == 3
    r = parse("1:10 kasia kroki")[0]
    assert r.referee_id == 2
    r = parse("1:10 Zolc kroki")[0]
    assert r.referee_id == 2


def test_referee_inflection_and_full_name():
    assert parse("0:30 Filipa kroki")[0].referee_id == 1
    assert parse("0:30 Kasi kroki")[0].referee_id == 2
    r = parse("0:30 Filip Kowalski kroki")[0]
    assert r.referee_id == 1 and r.category == "kroki"


def test_unknown_referee_warns():
    r = parse("2:54 Marek kroki")[0]
    assert r.ok and r.referee_id is None
    assert any("Nieznany sędzia" in w for w in r.warnings)
    assert r.category == "kroki"


def test_missing_referee_when_first_word_is_category():
    r = parse("2:54 kroki")[0]
    assert r.referee_id is None and r.category == "kroki"
    assert any("Brak sędziego" in w for w in r.warnings)


def test_ambiguous_referee():
    refs = [RefereeDef(1, "Jan Kowal", "CC"), RefereeDef(2, "Jan Nowak", "U1")]
    r = parse("1:00 Jan kroki", refs)[0]
    assert r.referee_id is None and any("Niejednoznaczny" in w for w in r.warnings)
    assert parse("1:00 Nowak kroki", refs)[0].referee_id == 2


def test_unparseable_lines_warn_but_are_kept():
    rows = parse("bez czasu Filip kroki\n99:99:99 Filip kroki\n1:02:75 Filip kroki\n\n# komentarz\n2:54 Filip kroki")
    assert [r.ok for r in rows] == [False, False, False, True]
    assert rows[0].line_no == 1 and rows[3].line_no == 6
    assert all(r.warnings for r in rows[:3])


@pytest.mark.parametrize("text,expected", [
    ("5:00 Filip faul osobisty", "osobisty"),
    ("5:00 Filip faul w akcji rzutowej", "w akcji rzutowej"),
    ("5:00 Filip szarza w ataku", "blok / szarża"),
    ("5:00 Filip podwójne prowadzenie", "podwójny kozioł"),
    ("5:00 Filip 3 s w trumnie", "3 s"),
    ("5:00 Filip 24s", "24 s"),
    ("5:00 Filip 8 sek", "8 s"),
    ("5:00 Filip piłka na aut", "aut"),
    ("5:00 Filip goaltending", "goaltending / interferencja"),
    ("5:00 Filip brak gwizdka", "brak gwizdka (powinien być)"),
    ("5:00 Filip niepotrzebny gwizdek", "gwizdek niepotrzebny"),
    ("5:00 Filip rotacja spóźniona", "rotacja"),
    ("5:00 Filip pozycja", "pozycja / poruszanie się"),
    ("5:00 Filip współpraca", "współpraca w zespole"),
    ("5:00 Filip sygnalizacja", "sygnalizacja"),
])
def test_category_aliases(text, expected):
    assert parse(text)[0].category == expected


def test_pts_is_not_guessed():
    r = parse("2:54 Filip PTS")[0]
    assert r.category is None and r.referee_id == 1


def test_short_aliases_only_uppercase():
    assert parse("1:00 Filip T")[0].category == "techniczny"
    assert parse("1:00 Filip U")[0].category == "niesportowy"
    assert parse("1:00 Filip D")[0].category == "dyskwalifikujący"
    assert parse("1:00 Filip u mnie nie ma t ani d")[0].category is None


def test_category_word_boundaries():
    assert parse("1:00 Filip autor zagrania")[0].category is None
    assert parse("1:00 Filip aut!")[0].category == "aut"
    assert parse("1:00 Filip 3 sekundy")[0].category == "3 s"
    assert parse("1:00 Filip 13 s")[0].category is None


def test_longest_alias_wins_and_multiple_categories_warn():
    r = parse("1:00 Filip faul techniczny")[0]
    assert r.category == "techniczny" and not r.warnings
    r = parse("1:00 Filip kroki i aut")[0]
    assert r.category == "kroki" and any("Kilka kategorii" in w for w in r.warnings)


def test_unknown_category_ignored_description_kept():
    r = parse("1:00 Filip dziwna sytuacja")[0]
    assert r.category is None and r.description == "dziwna sytuacja"


def test_inactive_category_not_offered():
    r = parse_notes("1:00 Filip kroki", REFEREES, [CategoryDef("aut")])[0]
    assert r.category is None


def test_time_only_line():
    r = parse("2:54")[0]
    assert r.ok and r.referee_id is None and any("Brak opisu" in w for w in r.warnings)


UPLOAD_NOTES = "2:54 Filip PTS\n3:17 U1 dlaczego nie blok?\n\n# rozgrzewka\n  1:02:15   CC  faul techniczny na ławce  \n"


def test_upload_notes_examples_from_the_spec():
    rows = parse(UPLOAD_NOTES)
    assert [r.line_no for r in rows] == [1, 2, 5]
    assert [r.time_sec for r in rows] == [174, 197, 3735]
    assert [r.referee_id for r in rows] == [1, 2, 1]
    assert rows[0].category is None and rows[0].warnings == [] and rows[0].description == "PTS"
    assert rows[1].category == "blok / szarża"
    assert rows[2].category == "techniczny"


def test_windows_line_endings_and_trailing_blank_lines():
    rows = parse("2:54 Filip kroki\r\n3:17 U1 aut\r\n\r\n")
    assert [r.time_sec for r in rows] == [174, 197] and all(not r.warnings for r in rows)


def test_each_line_is_independent_when_some_are_broken():
    rows = parse("2:54 Filip kroki\nnic tu nie ma\n99:99 Filip kroki\n4:00\n5:00 Zenek aut")
    assert [r.ok for r in rows] == [True, False, False, True, True]
    assert rows[1].warnings == ["Nie rozpoznano czasu na początku linii"]
    assert "Niepoprawny czas" in rows[2].warnings[0]
    assert rows[3].warnings == ["Brak opisu po czasie"]
    assert any("Nieznany sędzia" in w for w in rows[4].warnings) and rows[4].category == "aut"


def test_referee_and_category_recognised_without_function_prefix_variants():
    rows = parse("0:30 Łukasz 3 s\n0:45 u2 24 sek\n1:10 Kasi bez gwizdka")
    assert [r.referee_id for r in rows] == [3, 3, 2]
    assert [r.category for r in rows] == ["3 s", "24 s", "brak gwizdka (powinien być)"]


@pytest.mark.parametrize("line,description,category,referee_id", [
    ("2:54 CC kroki za późno", "za późno", "kroki", 1),
    ("2:54 CC kroki", "", "kroki", 1),
    ("2:54 Filip PTS", "PTS", None, 1),
    ("1:02:15 CC faul techniczny na ławce", "na ławce", "techniczny", 1),
    ("2:54 U1 24 sek spóźnione", "spóźnione", "24 s", 2),
    ("2:54 Kasi Brak gwizdka, widoczny kontakt", "widoczny kontakt", "brak gwizdka (powinien być)", 2),
    ("2:54 Filip KROKI!", "", "kroki", 1),
    ("2:54 - CC: kroki - za późno", "za późno", "kroki", 1),
    ("2:54 Filip T", "", "techniczny", 1),
    ("2:54 Filip T za mocno", "za mocno", "techniczny", 1),
])
def test_description_keeps_only_unrecognised_remainder(line, description, category, referee_id):
    r = parse(line)[0]
    assert (r.description, r.category, r.referee_id) == (description, category, referee_id)


def test_category_alias_inside_a_sentence_keeps_the_whole_sentence():
    for line, text, cat in [
        ("3:17 Filip Dlaczego nie blok?", "Dlaczego nie blok?", "blok / szarża"),
        ("3:17 U1 dlaczego nie blok? bo sam faul osobisty", "dlaczego nie blok? bo sam faul osobisty", "osobisty"),
        ("3:17 Filip piłka była na aut moim zdaniem", "piłka była na aut moim zdaniem", "aut"),
        ("3:17 Filip za późno kroki", "za późno kroki", "kroki"),
    ]:
        r = parse(line)[0]
        assert (r.description, r.category) == (text, cat), line
        assert r.referee_id is not None


def test_unrecognised_first_word_stays_in_description():
    r = parse("2:54 Marek kroki za późno")[0]
    assert r.referee_id is None and r.category == "kroki" and r.description == "Marek za późno"
    assert any("Nieznany sędzia" in w for w in r.warnings)
    r = parse("2:54 kroki za późno")[0]
    assert r.referee_id is None and r.description == "za późno"
    refs = [RefereeDef(1, "Jan Kowal", "CC"), RefereeDef(2, "Jan Nowak", "U1")]
    r = parse("1:00 Jan kroki spóźnione", refs)[0]
    assert r.referee_id is None and r.description == "Jan spóźnione"


def test_only_the_chosen_category_is_removed_when_several_match():
    r = parse("1:00 Filip kroki i aut")[0]
    assert r.category == "kroki" and r.description == "i aut" and r.warnings
    r = parse("1:00 Filip aut kroki")[0]
    assert r.category == "kroki" and r.description == "aut kroki"


def test_time_only_and_broken_lines_descriptions():
    assert parse("2:54")[0].description == ""
    assert parse("bez czasu Filip kroki")[0].description == "bez czasu Filip kroki"


def test_description_does_not_change_recognition():
    rows = parse("2:54 Filip kroki\n3:17 Filip Dlaczego nie blok?\n1:02:15 Kasia 24 s błąd")
    assert [r.referee_id for r in rows] == [1, 1, 2]
    assert [r.category for r in rows] == ["kroki", "blok / szarża", "24 s"]
