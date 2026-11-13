from sqlalchemy import select

from app import sheet_elements
from app.models import Category, SheetElement, UploadRejection
from app.timeutil import utcnow


def category(db, name):
    db.expire_all()
    return db.scalar(select(Category).where(Category.name == name))


def test_coach_manages_categories(make_client, db):
    client, _ = make_client("coach")
    assert "Faule" in client.get("/admin/categories").text
    r = client.post("/admin/categories", data={"name": "Faul trenera", "group": "Faule", "aliases": "ft"})
    assert r.status_code == 200 and "Dodano kategorię" in r.text
    created = category(db, "Faul trenera")
    assert created.alias_list == ["ft"] and created.is_active
    r = client.post(f"/admin/categories/{created.id}/update",
                    data={"name": "Faul trenera 2", "group": "Inne", "aliases": "ft2"})
    assert "Zapisano kategorię" in r.text
    assert category(db, "Faul trenera 2").group_name == "Inne"
    client.post(f"/admin/categories/{created.id}/active", data={"active": "0"})
    assert not category(db, "Faul trenera 2").is_active
    assert client.post(f"/admin/categories/{created.id}/delete").status_code == 200
    assert category(db, "Faul trenera 2") is None


def test_coach_manages_sheet_elements(make_client, db):
    client, _ = make_client("coach")
    assert "Obowiązki przedmeczowe" in client.get("/admin/sheet-elements").text
    assert "Dodano element arkusza" in client.post("/admin/sheet-elements", data={"name": "Element trenera"}).text
    db.expire_all()
    element_id = db.scalar(select(SheetElement.id).where(SheetElement.name == "Element trenera"))
    client.post(f"/admin/sheet-elements/{element_id}/update", data={"name": "Element trenera 2"})
    client.post(f"/admin/sheet-elements/{element_id}/active", data={"active": "0"})
    db.expire_all()
    assert db.get(SheetElement, element_id).name == "Element trenera 2"
    assert element_id not in [e.id for e in sheet_elements.ordered(db, active_only=True)]
    assert client.post(f"/admin/sheet-elements/{element_id}/delete").status_code == 200
    db.expire_all()
    assert db.get(SheetElement, element_id) is None


def test_referee_cannot_change_dictionaries(make_client, db):
    client, _ = make_client("referee")
    before = db.query(Category).count(), db.query(SheetElement).count()
    assert client.post("/admin/categories", data={"name": "Nie", "group": "Inne"}).status_code == 403
    assert client.post("/admin/sheet-elements", data={"name": "Nie"}).status_code == 403
    assert (db.query(Category).count(), db.query(SheetElement).count()) == before


def test_header_link_and_tabs_follow_the_roles(admin, make_client):
    page = admin[0].get("/admin/categories").text
    assert '<a href="/admin/users">Administracja</a>' in page
    for tab in ("/admin/users", "/admin/categories", "/admin/sheet-elements", "/admin/retention"):
        assert f'<a href="{tab}"' in page

    coach, _ = make_client("coach")
    page = coach.get("/admin/categories").text
    assert '<a href="/admin/categories">Administracja</a>' in page
    assert '<a href="/admin/sheet-elements"' in page
    assert 'href="/admin/users"' not in page and 'href="/admin/retention"' not in page
    assert '<a href="/admin/categories">Administracja</a>' in coach.get("/").text

    referee, _ = make_client("referee")
    assert "Administracja" not in referee.get("/").text


def test_coach_does_not_see_the_disk_space_banner(admin, make_client, db):
    db.add(UploadRejection(created_at=utcnow(), size_bytes=1, free_bytes=0))
    db.commit()
    assert "rejected-banner" in admin[0].get("/admin/categories").text
    coach, _ = make_client("coach")
    assert "rejected-banner" not in coach.get("/admin/categories").text
