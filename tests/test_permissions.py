import inspect
import sys

import pytest
from sqlalchemy import select

from app import permissions as p
from app.models import (Clip, Comment, GroupMember, Match, MatchOfficial, Notification, Rating, ShareLink, Sheet,
                        TrainingGroup, User, Video)
from tests.helpers import (TUS, category_named, make_match, make_ready_video, make_user, mark_periods, tus_create,
                           tus_metadata)

ME = 10
OTHER = 99

ROLE_SETS = {
    "brak ról": (),
    "admin": ("admin",),
    "coach": ("coach",),
    "referee": ("referee",),
    "admin+coach": ("admin", "coach"),
    "admin+referee": ("admin", "referee"),
    "coach+referee": ("coach", "referee"),
}


def user(roles, *, active=True) -> User:
    u = User(id=ME, email="u@example.com", name="U", is_active=active)
    u.set_roles(roles)
    return u


def match(*, in_crew=False, owner=OTHER, extra_crew=True) -> Match:
    m = Match(created_by=owner)
    m.officials = [MatchOfficial(function="CC", user_id=ME if in_crew else OTHER)]
    if extra_crew:
        m.officials.append(MatchOfficial(function="U1", name="Wpisany Sędzia"))
    return m


def clip(*, in_crew=False, author=OTHER) -> Clip:
    return Clip(match=match(in_crew=in_crew), author_id=author)


def sheet(*, author=OTHER, published=False, in_crew=False) -> Sheet:
    return Sheet(match=match(in_crew=in_crew), coach_id=author, status="published" if published else "draft")


def group(role=None) -> TrainingGroup:
    """`role`: my role in the group, or None when I am not in it."""
    g = TrainingGroup(name="G")
    g.members = [GroupMember(user_id=OTHER, role="coach")]
    if role:
        g.members.append(GroupMember(user_id=ME, role=role))
    return g


# (rule name, function(user, context), {role set: expected result})
# The context is a list of scenarios; the expectation is a tuple of results for them.
def _row(name, check, scenarios, **expected):
    return pytest.param(name, check, scenarios, expected, id=name)


ROWS = [
    _row("zarządzanie kontami", lambda u, _: p.can_manage_users(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (False,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (False,)}),
    _row("słownik kategorii", lambda u, _: p.can_manage_categories(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (False,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (False,)}),
    _row("retencja i dysk", lambda u, _: p.can_manage_retention(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (False,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (False,)}),
    _row("elementy arkusza", lambda u, _: p.can_manage_sheet_elements(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (False,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (False,)}),
    _row("przeglądanie", lambda u, _: p.can_view(u), [None],
         **{k: (True,) for k in ROLE_SETS}),
    _row("nowy mecz (formularz)", lambda u, _: p.can_create_match(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (True,), "referee": (True,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (True,)}),
    # 4b. a referee may save only with themself in the crew; scenarios: me in the crew / without me
    _row("zapis meczu z obsadą", lambda u, ids: p.can_save_match(u, ids), [[ME, None], [OTHER, None], []],
         **{"brak ról": (False, False, False), "admin": (True, True, True), "coach": (True, True, True),
            "referee": (True, False, False), "admin+coach": (True, True, True),
            "admin+referee": (True, True, True), "coach+referee": (True, True, True)}),
    # 4c. scenarios: I am in the crew / I am not
    _row("wgrywanie do meczu", lambda u, m: p.can_upload_to_match(u, m),
         [match(in_crew=True), match(in_crew=False)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, True),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, True)}),
    _row("tworzenie klipów", lambda u, m: p.can_manage_clips(u, m),
         [match(in_crew=True), match(in_crew=False)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, True),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, True)}),
    _row("opisywanie klipów", lambda u, c: p.can_describe_clip(u, c),
         [clip(in_crew=True), clip(in_crew=False)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, True),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, True)}),
    _row("ocena klipu", lambda u, _: p.can_rate(u), [None],
         **{"brak ról": (False,), "admin": (False,), "coach": (True,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (False,), "coach+referee": (True,)}),
    _row("komentowanie", lambda u, _: p.can_comment(u), [None],
         **{k: (True,) for k in ROLE_SETS}),
    # 8a. scenarios: own / foreign
    _row("edycja meczu", lambda u, m: p.can_edit_match(u, m),
         [match(owner=ME), match(owner=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    _row("usuwanie meczu", lambda u, m: p.can_delete_match(u, m),
         [match(owner=ME), match(owner=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    _row("usuwanie nagrania", lambda u, v: p.can_delete_video(u, v),
         [Video(created_by=ME, match=match(owner=OTHER)), Video(created_by=OTHER, match=match(owner=ME)),
          Video(created_by=OTHER, match=match(owner=OTHER))],
         **{"brak ról": (False, False, False), "admin": (True, True, True), "coach": (True, True, False),
            "referee": (True, True, False), "admin+coach": (True, True, True),
            "admin+referee": (True, True, True), "coach+referee": (True, True, False)}),
    _row("usuwanie klipu", lambda u, c: p.can_delete_clip(u, c),
         [clip(author=ME), clip(author=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    _row("udostępnianie klipu", lambda u, c: p.can_share_clip(u, c),
         [clip(author=ME), clip(author=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, True),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, True)}),
    _row("unieważnienie linku", lambda u, link: p.can_revoke_share(u, link),
         [ShareLink(created_by=ME), ShareLink(created_by=OTHER)],
         **{"brak ról": (True, False), "admin": (True, True), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    # 8d. scenarios: own / foreign
    _row("edycja oceny", lambda u, r: p.can_edit_rating(u, r),
         [Rating(coach_id=ME), Rating(coach_id=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, False),
            "referee": (False, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    _row("usuwanie oceny", lambda u, r: p.can_delete_rating(u, r),
         [Rating(coach_id=ME), Rating(coach_id=OTHER)],
         **{"brak ról": (False, False), "admin": (True, True), "coach": (True, False),
            "referee": (False, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    _row("edycja komentarza", lambda u, c: p.can_edit_comment(u, c),
         [Comment(author_id=ME), Comment(author_id=OTHER)],
         **{"brak ról": (True, False), "admin": (True, False), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, False), "admin+referee": (True, False),
            "coach+referee": (True, False)}),
    _row("usuwanie komentarza", lambda u, c: p.can_delete_comment(u, c),
         [Comment(author_id=ME), Comment(author_id=OTHER)],
         **{"brak ról": (True, False), "admin": (True, True), "coach": (True, False),
            "referee": (True, False), "admin+coach": (True, True), "admin+referee": (True, True),
            "coach+referee": (True, False)}),
    # 9. Qualifier assessment sheet: coach role only (the admin role alone is not enough, as with clip
    # ratings)
    _row("zakładanie arkusza", lambda u, _: p.can_create_sheet(u), [None],
         **{"brak ról": (False,), "admin": (False,), "coach": (True,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (False,), "coach+referee": (True,)}),
    _row("edycja arkusza", lambda u, s: p.can_edit_sheet(u, s), [sheet(author=ME), sheet(author=OTHER)],
         **{k: (True, False) for k in ROLE_SETS}),
    _row("publikacja arkusza", lambda u, s: p.can_publish_sheet(u, s),
         [sheet(author=ME, published=True), sheet(author=OTHER)], **{k: (True, False) for k in ROLE_SETS}),
    # delete: the author while it is a draft, an admin always (own draft / own published / foreign draft
    # / foreign published)
    _row("usuwanie arkusza", lambda u, s: p.can_delete_sheet(u, s),
         [sheet(author=ME), sheet(author=ME, published=True), sheet(author=OTHER), sheet(author=OTHER, published=True)],
         **{"brak ról": (True, False, False, False), "admin": (True, True, True, True),
            "coach": (True, False, False, False), "referee": (True, False, False, False),
            "admin+coach": (True, True, True, True), "admin+referee": (True, True, True, True),
            "coach+referee": (True, False, False, False)}),
    # view: own draft / own published / foreign draft (I am in the crew) / foreign published (in the
    # crew)
    # / foreign published (not in the crew)
    _row("podgląd arkusza", lambda u, s: p.can_view_sheet(u, s),
         [sheet(author=ME), sheet(author=ME, published=True), sheet(in_crew=True),
          sheet(published=True, in_crew=True), sheet(published=True)],
         **{"brak ról": (True, True, False, True, False), "admin": (True, True, False, True, True),
            "coach": (True, True, False, True, True), "referee": (True, True, False, True, False),
            "admin+coach": (True, True, False, True, True), "admin+referee": (True, True, False, True, True),
            "coach+referee": (True, True, False, True, True)}),
    # groups; view and manage: I am its coach / I am only a referee in it / I am not in it
    _row("tworzenie grupy", lambda u, _: p.can_create_group(u), [None],
         **{"brak ról": (False,), "admin": (True,), "coach": (True,), "referee": (False,),
            "admin+coach": (True,), "admin+referee": (True,), "coach+referee": (True,)}),
    _row("moje grupy", lambda u, _: p.can_see_my_groups(u), [None], **{k: (True,) for k in ROLE_SETS}),
    _row("podgląd grupy", lambda u, g: p.can_view_group(u, g), [group("coach"), group("referee"), group()],
         **{"brak ról": (True, False, False), "admin": (True, True, True), "coach": (True, False, False),
            "referee": (True, False, False), "admin+coach": (True, True, True), "admin+referee": (True, True, True),
            "coach+referee": (True, False, False)}),
    _row("zarządzanie grupą", lambda u, g: p.can_manage_group(u, g), [group("coach"), group("referee"), group()],
         **{"brak ról": (True, False, False), "admin": (True, True, True), "coach": (True, False, False),
            "referee": (True, False, False), "admin+coach": (True, True, True), "admin+referee": (True, True, True),
            "coach+referee": (True, False, False)}),
    # notifications: only the recipient (own / foreign)
    _row("podgląd powiadomienia", lambda u, n: p.can_view_notification(u, n),
         [Notification(recipient_id=ME), Notification(recipient_id=OTHER)], **{k: (True, False) for k in ROLE_SETS}),
]


@pytest.mark.parametrize("roles_name", list(ROLE_SETS))
@pytest.mark.parametrize("name,check,scenarios,expected", ROWS)
def test_permission_table(name, check, scenarios, expected, roles_name):
    u = user(ROLE_SETS[roles_name])
    got = tuple(check(u, scenario) for scenario in scenarios)
    assert got == expected[roles_name], f"{name} / {roles_name}"


def test_table_covers_every_permission_function():
    source = inspect.getsource(sys.modules[__name__])
    missing = {n for n in dir(p) if n.startswith("can_") and f"p.{n}(" not in source}
    assert not missing, f"brak wierszy tabeli dla: {missing}"


def test_crew_membership_counts_only_accounts_not_typed_names():
    m = Match(created_by=OTHER)
    m.officials = [MatchOfficial(function="CC", name="U"), MatchOfficial(function="U1", user_id=OTHER)]
    referee = user(["referee"])
    assert not p.is_official(referee, m) and not p.can_manage_clips(referee, m)


def test_inactive_user_and_anonymous_have_no_access():
    inactive = user(["admin"], active=False)
    assert not p.can_view(inactive) and not p.can_comment(inactive)
    assert not p.can_view_notification(inactive, Notification(recipient_id=ME))
    assert not p.can_view_notification(None, Notification(recipient_id=ME))
    assert not p.can_view(None) and not p.can_manage_users(None) and not p.can_create_match(None)
    assert not p.can_upload_to_match(None, match(in_crew=True))
    assert not p.can_share_clip(inactive, clip(author=ME)) and not p.can_share_clip(None, clip())
    assert not p.can_revoke_share(inactive, ShareLink(created_by=ME)) and not p.can_revoke_share(None, ShareLink())
    own = sheet(author=ME, published=True, in_crew=True)
    assert not any(f(inactive, own) for f in (p.can_view_sheet, p.can_edit_sheet, p.can_delete_sheet))
    assert not p.can_view_sheet(None, own) and not p.can_create_sheet(None) and not p.can_manage_sheet_elements(None)
    assert not any(f(inactive, group("coach")) for f in (p.can_view_group, p.can_manage_group))
    assert not p.can_create_group(inactive) and not p.can_see_my_groups(None) and not p.can_view_group(None, group())


@pytest.fixture()
def world(db, make_client):
    member_client, member = make_client("referee", name="Sędzia Z Obsady")
    outsider_client, outsider = make_client("referee", name="Sędzia Spoza Obsady")
    coach_client, coach = make_client("coach", name="Trener")
    other_coach_client, other_coach = make_client("coach", name="Inny Trener")
    admin_client, admin = make_client("admin", name="Szef")
    m = make_match(db, officials=(("CC", member), ("U1", "Wpisany Sędzia")), created_by=coach)
    video = mark_periods(db, make_ready_video(db, m))
    clip = Clip(match_id=m.id, video_id=video.id, author_id=coach.id, time_sec=100)
    db.add(clip)
    db.commit()
    return dict(member=member_client, member_user=member, outsider=outsider_client,
                coach=coach_client, coach_user=coach, other_coach=other_coach_client,
                admin=admin_client, admin_user=admin, match=m, video=video, clip=clip)


def forbidden_requests(w):
    m, v, c = w["match"], w["video"], w["clip"]
    form = {"date": "2026-10-28", "cc_name": "A B", "u1_name": "C D"}
    return [
        ("spoza obsady: upload (tus)", "outsider", "post", "/uploads/", {"headers": {
            **TUS, "Upload-Length": "10", "Upload-Metadata": tus_metadata(filename="a.mp4", match_id=m.id)}}),
        ("spoza obsady: znacznik kwarty", "outsider", "post", f"/api/videos/{v.id}/marks", {"json": {"time_sec": 1}}),
        ("spoza obsady: nowy klip", "outsider", "post", f"/api/videos/{v.id}/quick-clip", {"json": {"time_sec": 5}}),
        ("spoza obsady: notatki", "outsider", "post", f"/videos/{v.id}/notes/commit", {"data": {"count": "0"}}),
        ("spoza obsady: podgląd notatek", "outsider", "post", f"/videos/{v.id}/notes/preview", {"data": {"text": "1:00 CC aut"}}),
        ("spoza obsady: opis klipu", "outsider", "post", f"/clips/{c.id}/update", {"data": {"official": "team"}}),
        ("spoza obsady: ponowne cięcie", "outsider", "post", f"/clips/{c.id}/recut", {}),
        ("spoza obsady: nowy mecz bez siebie w obsadzie", "outsider", "post", "/matches", {"data": form}),
        ("z obsady: nowy mecz bez siebie w obsadzie", "member", "post", "/matches", {"data": form}),
        ("obcy szkoleniowiec: edycja meczu", "other_coach", "post", f"/matches/{m.id}", {"data": form}),
        ("obcy szkoleniowiec: formularz edycji", "other_coach", "get", f"/matches/{m.id}/edit", {}),
        ("obcy szkoleniowiec: usunięcie meczu", "other_coach", "post", f"/matches/{m.id}/delete", {}),
        ("obcy szkoleniowiec: potwierdzenie usunięcia meczu", "other_coach", "get", f"/matches/{m.id}/delete", {}),
        ("sędzia z obsady: potwierdzenie usunięcia cudzego meczu", "member", "get", f"/matches/{m.id}/delete", {}),
        ("sędzia spoza obsady: potwierdzenie usunięcia meczu", "outsider", "get", f"/matches/{m.id}/delete", {}),
        ("obcy szkoleniowiec: usunięcie klipu", "other_coach", "post", f"/clips/{c.id}/delete", {}),
        ("obcy szkoleniowiec: usunięcie nagrania", "other_coach", "post", f"/videos/{v.id}/delete", {}),
        ("sędzia z obsady: usunięcie cudzego klipu", "member", "post", f"/clips/{c.id}/delete", {}),
        ("sędzia z obsady: usunięcie cudzego meczu", "member", "post", f"/matches/{m.id}/delete", {}),
        ("sędzia z obsady: edycja cudzego meczu", "member", "post", f"/matches/{m.id}", {"data": form}),
        ("szkoleniowiec: lista kont", "coach", "get", "/admin/users", {}),
        ("szkoleniowiec: nowe konto", "coach", "post", "/admin/users",
         {"data": {"email": "x@example.com", "name": "X", "roles": ["admin"]}}),
        ("sędzia: zmiana ról", "member", "post", f"/admin/users/{w['member_user'].id}/roles", {"data": {"roles": ["admin"]}}),
        ("sędzia: link resetu", "member", "post", f"/admin/users/{w['coach_user'].id}/invite", {}),
        ("sędzia: dezaktywacja", "outsider", "post", f"/admin/users/{w['coach_user'].id}/active", {"data": {"active": "0"}}),
        ("szkoleniowiec: lista kategorii", "coach", "get", "/admin/categories", {}),
        ("sędzia: nowa kategoria", "member", "post", "/admin/categories", {"data": {"name": "X", "group": "Inne"}}),
        ("szkoleniowiec: zmiana kategorii", "coach", "post", "/admin/categories/1/update", {"data": {"name": "X", "group": "Inne"}}),
        ("szkoleniowiec: dezaktywacja kategorii", "coach", "post", "/admin/categories/1/active", {"data": {"active": "0"}}),
        ("sędzia: przesunięcie kategorii", "outsider", "post", "/admin/categories/1/move", {"data": {"direction": "up"}}),
        ("szkoleniowiec: usunięcie kategorii", "coach", "post", "/admin/categories/1/delete", {}),
        ("szkoleniowiec: retencja i dysk", "coach", "get", "/admin/retention", {}),
        ("sędzia: zmiana retencji", "member", "post", "/admin/retention", {"data": {"days": "1", "recalculate": "1"}}),
        ("szkoleniowiec: ręczne usunięcie pełnego nagrania", "coach", "post", f"/admin/videos/{v.id}/purge", {}),
        ("sędzia z obsady: ręczne usunięcie pełnego nagrania", "member", "post", f"/admin/videos/{v.id}/purge", {}),
        ("sędzia z obsady: nowy arkusz", "member", "post", f"/matches/{m.id}/sheets", {}),
        ("sędzia spoza obsady: nowy arkusz", "outsider", "post", f"/matches/{m.id}/sheets", {}),
        ("sam admin: nowy arkusz", "admin", "post", f"/matches/{m.id}/sheets", {}),
        ("szkoleniowiec: lista elementów arkusza", "coach", "get", "/admin/sheet-elements", {}),
        ("sędzia: nowy element arkusza", "member", "post", "/admin/sheet-elements", {"data": {"name": "X"}}),
        ("szkoleniowiec: zmiana elementu arkusza", "coach", "post", "/admin/sheet-elements/1/update", {"data": {"name": "X"}}),
        ("szkoleniowiec: usunięcie elementu arkusza", "coach", "post", "/admin/sheet-elements/1/delete", {}),
    ]


def test_forbidden_requests_are_rejected_by_server(world, db):
    for label, who, method, url, kwargs in forbidden_requests(world):
        r = getattr(world[who], method)(url, **kwargs, follow_redirects=False)
        assert r.status_code == 403, f"{label}: {r.status_code} {r.text[:120]}"
    db.expire_all()
    assert db.get(Match, world["match"].id) is not None
    assert db.get(Clip, world["clip"].id).described_at is None
    assert db.get(Video, world["video"].id).purged_at is None
    assert db.query(Video).count() == 1 and db.query(User).filter_by(email="x@example.com").count() == 0
    assert "admin" not in db.get(User, world["member_user"].id).roles


def test_match_delete_confirmation_allowed_for_owner_and_admin_only(world):
    url = f"/matches/{world['match'].id}/delete"
    assert world["coach"].get(url).status_code == 200
    assert world["admin"].get(url).status_code == 200


def test_user_without_roles_can_only_view_and_comment(make_client, db, world):
    client, _ = make_client()
    assert client.get("/").status_code == 200
    assert client.get("/?mine=1&level=II+liga").status_code == 200
    assert client.get(f"/matches/{world['match'].id}").status_code == 200
    assert client.get(f"/matches/{world['match'].id}/delete").status_code == 403
    assert client.get("/matches/new").status_code == 403
    assert client.post("/matches", data={"date": "2026-10-28"}).status_code == 403
    assert client.post(f"/api/videos/{world['video'].id}/quick-clip", json={"time_sec": 5}).status_code == 403
    r = client.post(f"/clips/{world['clip'].id}/comments", data={"body": "Widzę i komentuję"})
    assert r.status_code == 200 and "Widzę i komentuję" in r.text


def test_allowed_requests_for_crew_member(world, db):
    member = world["member"]
    m, v, c = world["match"], world["video"], world["clip"]
    r = member.post(f"/api/videos/{v.id}/quick-clip", json={"time_sec": 50, "text": "CC aut"})
    assert r.status_code == 200
    assert member.post(f"/api/videos/{v.id}/marks", json={"time_sec": 0, "period": "Q1"}).status_code == 200
    r = member.post(f"/clips/{c.id}/update", data={"official": "team", "category_id": str(category_named(db, "kroki"))},
                    follow_redirects=False)
    db.expire_all()
    assert r.status_code == 303 and db.get(Clip, c.id).whole_team
    assert member.get(f"/videos/{v.id}/notes").status_code == 200
    own = db.scalar(select(Clip).where(Clip.author_id == world["member_user"].id))
    assert member.post(f"/clips/{own.id}/delete", follow_redirects=False).status_code == 303
    assert member.post(f"/clips/{c.id}/delete").status_code == 403


def test_referee_creates_match_only_with_self_in_crew(make_client, db):
    client, ref = make_client("referee", name="Rafał Sędzia")
    base = {"date": "2026-10-28", "level": "II liga", "cc_name": "A B", "u1_name": "C D"}
    assert client.post("/matches", data=base).status_code == 403
    assert db.scalar(select(Match)) is None
    r = client.post("/matches", data={**base, "u1_user": str(ref.id), "u1_name": ""}, follow_redirects=False)
    assert r.status_code == 303
    created = db.scalar(select(Match))
    assert created.created_by == ref.id and created.official("U1").user_id == ref.id
    r = client.post(f"/matches/{created.id}", data=base)
    assert r.status_code == 403
    db.refresh(created)
    assert created.official("U1").user_id == ref.id


def test_coach_and_admin_can_work_on_any_match(world, db):
    for who in ("other_coach", "admin"):
        client = world[who]
        r = client.post(f"/api/videos/{world['video'].id}/quick-clip", json={"time_sec": 10})
        assert r.status_code == 200, who
        assert client.post(f"/clips/{world['clip'].id}/update",
                           data={"official": "team", "category_id": str(category_named(db, "aut"))},
                           follow_redirects=False).status_code == 303
        assert tus_create(client, world["match"].id, 4).status_code == 201, who


def test_comment_deletion_rules(world, db):
    c = world["clip"]
    author_client = world["member"]
    r = author_client.post(f"/clips/{c.id}/comments", data={"body": "Mój komentarz"})
    assert r.status_code == 200
    comment = db.scalar(select(Comment))
    url = f"/clips/{c.id}/comments/{comment.id}/delete"
    assert world["other_coach"].post(url).status_code == 403
    assert world["coach"].post(url).status_code == 403
    assert db.get(Comment, comment.id) is not None
    assert world["admin"].post(url).status_code == 200
    assert db.scalar(select(Comment)) is None
    world["coach"].post(f"/clips/{c.id}/comments", data={"body": "Komentarz trenera"})
    own = db.scalar(select(Comment))
    assert world["coach"].post(f"/clips/{c.id}/comments/{own.id}/delete").status_code == 200
