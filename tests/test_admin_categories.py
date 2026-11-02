"""Panel admina: słownik kategorii (walidacja, aktywacja, usuwanie, kolejność) i jego wpływ na parser
notatek oraz formularze opisu."""
from sqlalchemy import select

from app import categories, services
from app.models import Category, Clip
from tests.helpers import category_named, make_match, make_ready_video, mark_periods


def cat(db, name) -> Category:
    db.expire_all()
    return db.scalar(select(Category).where(Category.name == name))


def post(client, path, **data):
    return client.post(path, data=data)


def add(client, name, group="Faule", aliases=""):
    return post(client, "/admin/categories", name=name, group=group, aliases=aliases)


def test_page_lists_groups_with_flags(client, db):
    page = client.get("/admin/categories").text
    for text in ("Faule", "Naruszenia", "Bez gwizdka", "Mechanika", "Inne", "osobisty", "kroki", 'data-category="własna"'):
        assert text in page
    assert "Administracja" in page and 'href="/admin/retention"' in page


def test_add_category_appears_in_group_end_and_in_forms(client, db):
    r = add(client, "  Faul   w ataku ", "Faule", "faul atakujacego, atak faul")
    assert r.status_code == 200 and "Dodano kategorię" in r.text
    new = cat(db, "Faul w ataku")
    assert new.group_name == "Faule" and new.alias_list == ["faul atakujacego", "atak faul"] and new.is_active
    faule = [c.name for c in categories.ordered(db) if c.group_name == "Faule"]
    assert faule[-1] == "Faul w ataku"
    sorts = [c.sort for c in categories.ordered(db)]
    assert sorts == sorted(sorts) and len(set(sorts)) == len(sorts)
    assert "Faul w ataku" in [c.name for c in services.active_categories(db)]


def test_new_category_alias_is_recognised_by_notes_parser(client, db):
    add(client, "Faul w ataku", "Faule", "faul atakujacego")
    match = make_match(db)
    rows = services.parse_for_match(db, match, "1:00 CC Faul Atakującego")
    assert rows[0].category == "Faul w ataku"


def test_name_validation(client, db):
    cases = [("", "Podaj nazwę"), ("KROKI", "koliduje z kategorią „kroki”"), ("Wlasna", "koliduje z kategorią „własna”"),
             ("  osobisty ", "koliduje"), ("x" * 101, "najwyżej 100"), ("cc", "zarezerwowana"), ("???", "Podaj nazwę")]
    for name, fragment in cases:
        r = add(client, name)
        assert r.status_code == 422 and fragment in r.text, name
    assert add(client, "Nowa", "Nieznana grupa").status_code == 422
    assert db.query(Category).filter(Category.name.in_(["Nowa", "cc", "???"])).count() == 0
    r = add(client, "Nowa nazwa", "Faule", "x")
    assert r.status_code == 200
    # wpisane wartości zostają po błędzie
    r = add(client, "kroki", "Naruszenia", "abc, def")
    assert r.status_code == 422 and 'value="abc, def"' in r.text


def test_name_uniqueness_ignores_case_and_polish_letters(client, db):
    assert add(client, "Żółw", "Inne").status_code == 200
    r = add(client, "zolw", "Inne")
    assert r.status_code == 422 and "koliduje" in r.text


def test_alias_conflicts_are_rejected(client, db):
    # alias z aliasem innej kategorii (kroki: „krok”), z nazwą innej, z funkcją sędziego
    r = add(client, "Nowa A", "Naruszenia", "Krok")
    assert r.status_code == 422 and "„Krok” jest już używany przez kategorię „kroki”" in r.text
    r = add(client, "Nowa B", "Naruszenia", "szarza")        # bez polskich znaków
    assert r.status_code == 422 and "blok / szarża" in r.text
    r = add(client, "Nowa C", "Naruszenia", "AUT")            # nazwa innej kategorii
    assert r.status_code == 422 and "„aut”" in r.text
    r = add(client, "Nowa D", "Naruszenia", "u1")
    assert r.status_code == 422 and "zarezerwowany" in r.text
    # sam alias nieaktywnej kategorii też blokuje (po aktywacji byłby konflikt)
    post(client, f"/admin/categories/{cat(db, 'kroki').id}/active", active="0")
    assert add(client, "Nowa E", "Naruszenia", "traveling").status_code == 422
    assert db.query(Category).filter(Category.name.like("Nowa %")).count() == 0


def test_update_name_group_aliases(client, db):
    c = cat(db, "rotacja")
    r = post(client, f"/admin/categories/{c.id}/update", name="rotacja sędziów", group="Naruszenia",
             aliases="rotacje, obrót, obrót")
    assert r.status_code == 200
    c = cat(db, "rotacja sędziów")
    assert c.group_name == "Naruszenia" and c.alias_list == ["rotacje", "obrót"]
    # przeniesiona na koniec nowej grupy, grupy ciągłe
    names = [x.name for x in categories.ordered(db)]
    assert names.index("rotacja sędziów") > names.index("goaltending / interferencja")
    groups = [x.group_name for x in categories.ordered(db)]
    assert groups == sorted(groups, key=lambda g: categories.GROUPS.index(g))
    # zmiana nazwy nie psuje klipów: wskazują kategorię przez id
    match = make_match(db)
    video = make_ready_video(db, match)
    clip = Clip(match_id=match.id, video_id=video.id, time_sec=5, category_id=c.id)
    db.add(clip)
    db.commit()
    assert post(client, f"/admin/categories/{c.id}/update", name="rotacja 2", group="Naruszenia", aliases="").status_code == 200
    db.expire_all()
    assert db.get(Clip, clip.id).category_label == "rotacja 2"


def test_update_validation_keeps_entered_values_and_allows_own_name(client, db):
    c = cat(db, "rotacja")
    r = post(client, f"/admin/categories/{c.id}/update", name="kroki", group="Mechanika", aliases="x")
    assert r.status_code == 422 and "koliduje" in r.text and 'value="kroki"' in r.text
    assert cat(db, "rotacja") is not None
    # własna nazwa i własne aliasy nie są konfliktem; zmiana wielkości liter też
    assert post(client, f"/admin/categories/{c.id}/update", name="Rotacja", group="Mechanika", aliases="rotacje, rotacji").status_code == 200
    assert post(client, "/admin/categories/99999/update", name="X", group="Inne", aliases="").status_code == 404


def test_deactivation_hides_from_forms_and_parser_but_keeps_existing_clips(client, db):
    kroki = cat(db, "kroki")
    match = make_match(db)
    video = mark_periods(db, make_ready_video(db, match))
    clip = Clip(match_id=match.id, video_id=video.id, time_sec=50, category_id=kroki.id, whole_team=True,
                description="stary", described_at=services.utcnow())
    db.add(clip)
    db.commit()
    assert post(client, f"/admin/categories/{kroki.id}/active", active="0").status_code == 200
    assert not cat(db, "kroki").is_active
    assert "kroki" not in [c.name for c in services.active_categories(db)]
    # parser: „krok”/„kroki” przestaje być rozpoznawany
    assert services.parse_for_match(db, match, "1:00 CC kroki")[0].category is None
    # formularz opisu innego klipu nie oferuje kategorii, ale ten klip ją zachowuje
    other = Clip(match_id=match.id, video_id=video.id, time_sec=60)
    db.add(other)
    db.commit()
    assert "(nieaktywna)" not in client.get(f"/clips/{other.id}").text.split('name="category_id"')[1].split("</select>")[0]
    assert ">kroki<" not in client.get(f"/clips/{other.id}").text.split('name="category_id"')[1].split("</select>")[0]
    page = client.get(f"/clips/{clip.id}").text
    assert "kroki (nieaktywna)" in page
    # zapis bez zmian zachowuje nieaktywną kategorię
    r = client.post(f"/clips/{clip.id}/update", data={"official": "team", "category_id": str(kroki.id),
                                                      "description": "nowy opis"}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(clip)
    assert clip.category_id == kroki.id and clip.description == "nowy opis"
    # ale wybrać nieaktywnej kategorii dla innego klipu nie można
    r = client.post(f"/clips/{other.id}/update", data={"official": "team", "category_id": str(kroki.id)},
                    follow_redirects=False)
    assert r.status_code == 422 and "nieaktywna" in r.text
    # filtr klipów nadal zna nieaktywną kategorię
    assert "kroki (nieaktywna)" in client.get("/clips").text
    # ponowna aktywacja
    post(client, f"/admin/categories/{kroki.id}/active", active="1")
    assert services.parse_for_match(db, match, "1:00 CC kroki")[0].category == "kroki"


def test_inactive_category_not_accepted_by_notes_commit(client, db):
    match = make_match(db)
    video = make_ready_video(db, match)
    kroki = cat(db, "kroki")
    post(client, f"/admin/categories/{kroki.id}/active", active="0")
    r = client.post(f"/videos/{video.id}/notes/commit", data={
        "count": "1", "include_0": "1", "time_0": "1:00", "category_0": str(kroki.id), "desc_0": "x"},
        follow_redirects=False)
    assert r.status_code == 303
    assert db.query(Clip).one().category_id is None


def test_custom_category_cannot_be_deactivated_or_deleted(client, db):
    own = cat(db, "własna")
    r = post(client, f"/admin/categories/{own.id}/active", active="0")
    assert r.status_code == 422 and "nie można dezaktywować" in r.text and cat(db, "własna").is_active
    r = post(client, f"/admin/categories/{own.id}/delete")
    assert r.status_code == 422 and "nie można usunąć" in r.text and cat(db, "własna") is not None
    page = client.get("/admin/categories").text
    row = page.split('data-category="własna"')[1].split("</tr>")[0]
    assert "Dezaktywuj" not in row and "Usuń" not in row


def test_used_category_cannot_be_deleted_but_unused_can(client, db):
    kroki = cat(db, "kroki")
    match = make_match(db)
    video = make_ready_video(db, match)
    db.add(Clip(match_id=match.id, video_id=video.id, time_sec=5, category_id=kroki.id))
    db.commit()
    r = post(client, f"/admin/categories/{kroki.id}/delete")
    assert r.status_code == 409 and "użyta w klipach (1)" in r.text and cat(db, "kroki") is not None
    assert add(client, "Tymczasowa", "Inne").status_code == 200
    r = post(client, f"/admin/categories/{cat(db, 'Tymczasowa').id}/delete")
    assert r.status_code == 200 and "Usunięto kategorię" in r.text and cat(db, "Tymczasowa") is None
    assert [c.sort for c in categories.ordered(db)] == sorted(c.sort for c in categories.ordered(db))


def test_move_within_group(client, db):
    def names():
        return [c.name for c in categories.ordered(db) if c.group_name == "Faule"]
    before = names()
    c = cat(db, before[1])
    assert post(client, f"/admin/categories/{c.id}/move", direction="up").status_code == 200
    db.expire_all()
    assert names()[:2] == [before[1], before[0]] and names()[2:] == before[2:]
    assert post(client, f"/admin/categories/{c.id}/move", direction="up").status_code == 200   # już pierwsza
    db.expire_all()
    assert names()[0] == before[1]
    assert post(client, f"/admin/categories/{c.id}/move", direction="down").status_code == 200
    db.expire_all()
    assert names() == before
    last = cat(db, before[-1])
    post(client, f"/admin/categories/{last.id}/move", direction="down")      # ostatnia w grupie: bez zmian
    db.expire_all()
    assert names() == before
    assert post(client, f"/admin/categories/{c.id}/move", direction="sideways").status_code == 422
    # kolejność widać w formularzu opisu
    other = [c.name for c in services.active_categories(db) if c.group_name == "Faule"]
    assert other == before


def test_seeded_dictionary_has_no_alias_conflicts(db):
    """Zasady panelu nie mogą odrzucać zapisu domyślnych kategorii z powodu konfliktów w seedzie."""
    seen: dict[str, str] = {}
    for c in db.scalars(select(Category)):
        for text in (c.name, *c.alias_list):
            from app.textutil import normalize
            key = normalize(text)
            assert seen.setdefault(key, c.name) == c.name, f"{text!r}: {c.name} / {seen[key]}"


def test_category_id_lookup_unchanged_for_helpers(db):
    assert category_named(db, "kroki") == cat(db, "kroki").id


ADMIN_ROUTES = [
    ("get", "/admin"), ("get", "/admin/users"), ("get", "/admin/categories"), ("get", "/admin/retention"),
    ("post", "/admin/categories"), ("post", "/admin/categories/1/update"), ("post", "/admin/categories/1/active"),
    ("post", "/admin/categories/1/move"), ("post", "/admin/categories/1/delete"),
    ("post", "/admin/retention"), ("post", "/admin/videos/1/purge"),
]


def test_anonymous_gets_401_or_login_redirect_on_every_admin_route(anon_client):
    for method, path in ADMIN_ROUTES:
        r = getattr(anon_client, method)(path, follow_redirects=False)
        assert r.status_code in (303, 401), (method, path, r.status_code)
        if r.status_code == 303:
            assert r.headers["location"].startswith("/login")


def test_non_admin_roles_get_403_on_every_admin_route(make_client, db):
    for roles in (("coach",), ("referee",), ("coach", "referee"), ()):
        client, _ = make_client(*roles)
        for method, path in ADMIN_ROUTES:
            r = getattr(client, method)(path, follow_redirects=False)
            assert r.status_code == 403, (roles, method, path, r.status_code)


def test_admin_post_routes_require_csrf_token(admin, db):
    client = admin[0]
    del client.headers["X-CSRF-Token"]
    for path in ("/admin/categories", "/admin/retention", "/admin/categories/1/delete", "/admin/videos/1/purge"):
        assert client.post(path, data={"days": "10"}).status_code == 403, path
    assert db.query(Category).count() > 0 and services.retention_days(db) == 30
