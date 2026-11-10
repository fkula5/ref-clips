from sqlalchemy import select

from app import sheet_elements
from app.models import SheetElement


def names(db):
    db.expire_all()
    return [e.name for e in sheet_elements.ordered(db)]


def test_admin_edits_the_element_dictionary(client, db):
    assert "Obowiązki przedmeczowe" in client.get("/admin/sheet-elements").text
    assert "Dodano element arkusza" in client.post("/admin/sheet-elements", data={"name": "  Nowy   element "}).text
    assert names(db)[-1] == "Nowy element"
    for name, fragment in (("", "Podaj nazwę"), ("MECHANIKA", "już istnieje"), ("x" * 101, "najwyżej 100")):
        r = client.post("/admin/sheet-elements", data={"name": name})
        assert r.status_code == 422 and fragment in r.text, name
    element = db.scalar(select(SheetElement).where(SheetElement.name == "Mechanika"))
    r = client.post(f"/admin/sheet-elements/{element.id}/update", data={"name": "Sędziowska mechanika"})
    assert "Sędziowska mechanika" in names(db) and "istniejące arkusze zostają" in r.text
    r = client.post(f"/admin/sheet-elements/{element.id}/update", data={"name": "ocena błędów"})
    assert r.status_code == 422 and "ocena błędów" in r.text
    client.post(f"/admin/sheet-elements/{element.id}/move", data={"direction": "up"})
    assert names(db)[1] == "Sędziowska mechanika"
    client.post(f"/admin/sheet-elements/{element.id}/active", data={"active": "0"})
    assert element.id not in [e.id for e in sheet_elements.ordered(db, active_only=True)]
    assert client.post(f"/admin/sheet-elements/{element.id}/delete").status_code == 200
    assert "Sędziowska mechanika" not in names(db)
    assert client.post("/admin/sheet-elements/99999/delete").status_code == 404
