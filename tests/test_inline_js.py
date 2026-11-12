"""User-controlled names reach inline JS (`confirm(...)`) only through `|tojson`: the browser decodes
HTML entities in an attribute before running it, so `|e` alone lets a quote break out of the JS string.
"""
import html
import json
import re

from app import groups
from app.models import Category, GroupMember, SheetElement
from tests.helpers import make_user

EVIL = """O'Brien "x" </script><img src=x onerror=alert(1)>"""


def confirm_arguments(page: str) -> list[str]:
    """What the browser would execute: attribute values entity-decoded, then the confirm argument parsed
    as JSON (a valid JSON string literal is a single JS string, nothing can escape it).
    """
    found = []
    for attr in re.findall(r"""on(?:submit|click)=(?:'([^']*)'|"([^"]*)")""", page):
        code = html.unescape(attr[0] or attr[1])
        match = re.fullmatch(r"return confirm\((.*)\)", code)
        if match and match[1].startswith('"'):
            found.append(json.loads(match[1]))
    return found


def test_referee_removal_confirm_is_a_json_string_even_for_nasty_names(client, db):
    admin_group = groups.create_group(db, make_user(db, ("coach",), email="c@example.com", name="Trener"), "G", "")
    referee = make_user(db, ("referee",), email="r@example.com", name=EVIL)
    admin_group.members.append(GroupMember(user_id=referee.id, role="referee"))
    db.commit()
    page = client.get(f"/groups/{admin_group.id}").text
    assert f"Usunąć {EVIL} z grupy? Jej mecze i klipy zostają bez zmian." in confirm_arguments(page)
    assert "<img src=x" not in page


def test_coach_removal_confirm_is_a_json_string_even_for_nasty_names(client, db):
    coach = make_user(db, ("coach",), email="c@example.com", name=EVIL)
    group = groups.create_group(db, coach, "G", "")
    page = client.get(f"/groups/{group.id}").text
    assert f"Usunąć {EVIL} z grupy?" in confirm_arguments(page)


def test_category_and_sheet_element_delete_confirms_are_json_strings(client, db):
    db.add_all([Category(name=EVIL, group_name="Inne", is_custom=False), SheetElement(name=EVIL)])
    db.commit()
    assert f"Usunąć kategorię „{EVIL}”?" in confirm_arguments(client.get("/admin/categories").text)
    assert f"Usunąć element „{EVIL}”?" in confirm_arguments(client.get("/admin/sheet-elements").text)
