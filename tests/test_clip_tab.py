"""Zakładka „Klipy” meczu i globalna lista: filtry w adresie, kolumny, widok mobilny, poprzedni/następny
klip na stronie klipu, nazwa pliku do pobrania i stany błędów klipu."""
import re
from datetime import datetime

import pytest

from app import clip_list
from app.models import Clip
from tests.helpers import category_named, make_match, make_ready_video, make_user, mark_periods


@pytest.fixture()
def tab(db, client):
    """Mecz: CC=konto, U1=wpisany; kwarty co 100 s; pięć klipów o różnych opisach i stanach."""
    ref = make_user(db, ["referee"], email="r@example.com", name="Rafał Sędzia")
    match = make_match(db, officials=(("CC", ref), ("U1", "Ewa Druga")))
    video = mark_periods(db, make_ready_video(db, match, duration=900), times=(0.0, 100.0, 200.0, 300.0))
    cc, u1 = match.official("CC"), match.official("U1")
    done = datetime(2026, 10, 29, 12, 0)

    def clip(t, **kw):
        c = Clip(match_id=match.id, video_id=video.id, time_sec=t, **kw)
        db.add(c)
        db.commit()
        return c

    clips = dict(
        q1_cc=clip(30, official_id=cc.id, category_id=category_named(db, "kroki"), described_at=done,
                   description="Przekroczył linię " + "bardzo " * 20 + "długo", status="cut"),
        q1_none=clip(60),
        q2_u1=clip(150, official_id=u1.id, category_id=category_named(db, "aut"), described_at=done),
        q2_team=clip(180, whole_team=True, category_id=category_named(db, "własna"), custom_category="Kontakt z ławką",
                     described_at=done),
        q4_cc=clip(350, official_id=cc.id, category_id=category_named(db, "aut")),
    )
    return dict(match=match, video=video, clips=clips, cc=cc, u1=u1, ref=ref)


def listed(html, clips):
    """Klucze klipów (z fixture) widoczne w tabeli, w kolejności wystąpienia."""
    by_id = {c.id: k for k, c in clips.items()}
    found = [int(i) for i in re.findall(r'href="/clips/(\d+)(?:\?[^"]*)?"[^>]*>(?!Otwórz)', html)]
    seen = []
    for i in found:
        if i in by_id and by_id[i] not in seen:
            seen.append(by_id[i])
    return seen


def tab_page(client, match, **params):
    return client.get(f"/matches/{match.id}", params=params).text


def test_tab_shows_all_columns_per_row(client, tab):
    page = tab_page(client, tab["match"])
    for header in ("Sędzia", "Kategoria", "Kwarta · od początku kwarty", "Czas w nagraniu", "Opis", "Oceny"):
        assert header in page
    assert "CC · Rafał Sędzia" in page and "U1 · Ewa Druga" in page and "cały zespół" in page
    assert "Q2 · 0:50" in page and "Q1 · 0:30" in page                      # kwarta · czas od początku kwarty
    assert "Kontakt z ławką" in page and "kroki" in page
    assert "Przekroczył linię bardzo" in page and "bardzo długo" not in page and "…" in page   # opis skrócony
    assert "to nie jest zegar meczowy" in page
    assert 'data-label="Oceny"' in page                                                    # kolumna ocen
    assert "Klipy (5, nieopisane: 2)" in page and 'id="btn-describe"' in page and "Opisz znaczniki (2)" in page


def test_tab_rows_are_cards_on_mobile(client, tab):
    page = tab_page(client, tab["match"])
    assert '<table class="responsive clips-table">' in page
    row = page.split("<tbody>")[1].split("</tr>")[0]
    for label in ("Sędzia", "Kategoria", "Kwarta · od początku", "Czas w nagraniu", "Opis", "Stan", "Oceny"):
        assert f'data-label="{label}"' in row
    css = open("app/static/app.css", encoding="utf-8").read()
    assert "table.responsive tr { display: block" in css and "max-width: 720px" in css


def test_each_filter_alone(client, tab):
    m, c = tab["match"], tab["clips"]
    every = ["q1_cc", "q1_none", "q2_u1", "q2_team", "q4_cc"]
    assert listed(tab_page(client, m), c) == every
    assert listed(tab_page(client, m, person=clip_list_key(tab, "cc")), c) == ["q1_cc", "q4_cc"]
    assert listed(tab_page(client, m, person=clip_list_key(tab, "u1")), c) == ["q2_u1"]
    assert listed(tab_page(client, m, person="team"), c) == ["q2_team"]
    assert listed(tab_page(client, m, category_id=category_named_id(client, "aut")), c) == ["q2_u1", "q4_cc"]
    assert listed(tab_page(client, m, period="Q2"), c) == ["q2_u1", "q2_team"]
    assert listed(tab_page(client, m, period="Q4"), c) == ["q4_cc"]
    assert listed(tab_page(client, m, described="1"), c) == ["q1_cc", "q2_u1", "q2_team"]
    assert listed(tab_page(client, m, described="0"), c) == ["q1_none", "q4_cc"]


def test_filter_combinations_and_empty_result(client, tab):
    m, c = tab["match"], tab["clips"]
    cc = clip_list_key(tab, "cc")
    assert listed(tab_page(client, m, person=cc, described="0"), c) == ["q4_cc"]
    assert listed(tab_page(client, m, person=cc, period="Q1", described="1"), c) == ["q1_cc"]
    assert listed(tab_page(client, m, category_id=category_named_id(client, "aut"), period="Q2"), c) == ["q2_u1"]
    page = tab_page(client, m, person="team", period="Q1")
    assert listed(page, c) == [] and "Brak klipów dla wybranych filtrów." in page
    assert "Klipy (5, nieopisane: 2)" in page                                            # nagłówek liczy cały mecz


def test_period_none_filter_finds_unresolved_quarter(client, tab, db):
    db.delete(tab["video"].marks[0])                                                     # Q1 znika: klipy z Q1 bez kwarty
    db.commit()
    page = tab_page(client, tab["match"], period="none")
    assert set(listed(page, tab["clips"])) == {"q1_cc", "q1_none"}


def test_invalid_filter_values_are_ignored(client, tab):
    page = tab_page(client, tab["match"], period="Q9", described="x", category_id="abc", person="")
    assert len(listed(page, tab["clips"])) == 5


def test_filter_form_works_without_js_and_with_htmx(client, tab):
    page = tab_page(client, tab["match"], period="Q2", described="1", category_id=category_named_id(client, "aut"))
    form = re.search(r'<form method="get" action="[^"]*"[^>]*id="clip-filters".*?</form>', page, re.S).group(0)
    assert f'action="/matches/{tab["match"].id}#klipy"' in form                      # zwykły GET działa bez JS
    assert 'hx-push-url="true"' in form and 'hx-target="#clips-list"' in form
    for name in ("person", "category_id", "period", "described"):
        assert f'name="{name}"' in form
    assert re.search(r'<option value="Q2" selected>', form) and re.search(r'<option value="1" selected>', form)
    assert f'<optgroup label="Naruszenia">' in form
    assert "Wszyscy" in form and "cały zespół" in form and "CC · Rafał Sędzia" in form


def test_links_carry_filters_to_the_clip_page(client, tab):
    page = tab_page(client, tab["match"], period="Q2", described="1")
    cid = tab["clips"]["q2_u1"].id
    assert f'href="/clips/{cid}?period=Q2&amp;described=1"' in page
    plain = tab_page(client, tab["match"])
    assert f'href="/clips/{cid}"' in plain


def test_global_list_uses_the_same_filters(client, tab, db):
    other = make_match(db)
    ov = make_ready_video(db, other)
    mark_periods(db, ov)
    stray = Clip(match_id=other.id, video_id=ov.id, time_sec=20, whole_team=True, described_at=datetime(2026, 10, 30))
    db.add(stray)
    db.commit()
    c = tab["clips"]
    page = client.get("/clips").text
    assert len(listed(page, c)) == 5 and f'href="/clips/{stray.id}"' in page
    assert listed(client.get("/clips", params={"match_id": tab["match"].id, "described": "0"}).text, c) == ["q1_none", "q4_cc"]
    only_team = client.get("/clips", params={"person": "team"}).text
    assert listed(only_team, c) == ["q2_team"] and f'href="/clips/{stray.id}' in only_team
    assert listed(client.get("/clips", params={"period": "Q4"}).text, c) == ["q4_cc"]
    for name in ("match_id", "person", "category_id", "period", "described"):
        assert f'name="{name}"' in page
    assert 'table class="responsive clips-table"' in page and 'data-label="Mecz"' in page


def test_pending_clips_poll_only_the_list_with_current_filters(client, tab, db):
    for clip in tab["clips"].values():
        clip.status = "cut"
    tab["clips"]["q4_cc"].status = "queued"
    db.commit()
    page = tab_page(client, tab["match"], described="0")
    assert re.search(rf'<div id="clips-list" hx-get="/matches/{tab["match"].id}\?described=0" hx-trigger="every 3s"', page)
    assert 'hx-select-oob="#clips-head"' in page
    quiet = tab_page(client, tab["match"], described="1")                      # pokazane klipy nie czekają na cięcie
    assert 'id="clips-list" hx-get' not in quiet


def test_busy_video_panel_refreshes_tab_with_current_url_filters(client, tab, db):
    tab["video"].status = "processing"
    db.commit()
    page = tab_page(client, tab["match"])
    assert "location.search" in page and '#match-state,#clips-head,#clips-list' in page


# --- nawigacja poprzedni/następny ------------------------------------------------------
def clip_page(client, clip, **params):
    return client.get(f"/clips/{clip.id}", params=params).text


def test_previous_and_next_follow_recording_time(client, tab):
    c = tab["clips"]
    mid = clip_page(client, c["q2_u1"])
    assert f'id="prev-clip" rel="prev" href="/clips/{c["q1_none"].id}"' in mid and "Poprzedni klip (1:00)" in mid
    assert f'id="next-clip" rel="next" href="/clips/{c["q2_team"].id}"' in mid and "Następny klip (3:00)" in mid
    first = clip_page(client, c["q1_cc"])
    assert 'id="prev-clip"' not in first and 'aria-disabled="true">‹ Poprzedni klip' in first
    last = clip_page(client, c["q4_cc"])
    assert 'id="next-clip"' not in last and 'aria-disabled="true">Następny klip ›' in last


def test_previous_and_next_respect_the_filters_we_came_from(client, tab):
    c = tab["clips"]
    page = clip_page(client, c["q1_cc"], described="1")
    assert f'id="next-clip" rel="next" href="/clips/{c["q2_u1"].id}?described=1"' in page            # pomija nieopisany
    page = clip_page(client, c["q2_team"], described="1", period="Q2")
    assert f'id="prev-clip" rel="prev" href="/clips/{c["q2_u1"].id}?period=Q2&amp;described=1"' in page
    assert 'id="next-clip"' not in page
    # bieżący klip nie pasuje do filtra (np. właśnie go opisano): sąsiedzi nadal wg filtra
    page = clip_page(client, c["q1_none"], described="1")
    assert f'id="prev-clip" rel="prev" href="/clips/{c["q1_cc"].id}' in page
    assert f'id="next-clip" rel="next" href="/clips/{c["q2_u1"].id}' in page
    # nawigacja zostaje w obrębie meczu, nawet gdy w adresie jest inny mecz
    page = clip_page(client, c["q4_cc"], match_id="9999")
    assert 'id="next-clip"' not in page


def test_clip_page_links_back_to_the_filtered_tab(client, tab):
    page = clip_page(client, tab["clips"]["q2_u1"], period="Q2")
    assert f'href="/matches/{tab["match"].id}?period=Q2#klipy"' in page


# --- strona klipu ------------------------------------------------------------------------
def test_clip_page_shows_description_fields_and_ratings_card(client, tab, admin):
    page = clip_page(client, tab["clips"]["q2_team"])
    info = page.split('id="clip-info"')[1].split('id="oceny"')[0]
    for text in ("cały zespół", "Kontakt z ławką", "Q2 · 1:20 od początku kwarty (czas nagrania)",
                 "czas nagrania – nie zegar meczowy", "Znacznik dodał(a)", "Opisano", "29.10.2026 12:00"):
        assert text in info, text
    assert "Klip nie ma jeszcze ocen." in page


def test_full_recording_link_only_while_the_full_video_exists(client, tab, db):
    assert f'href="/videos/{tab["video"].id}?t=30.0"' in clip_page(client, tab["clips"]["q1_cc"])
    tab["video"].purged_at = datetime(2026, 11, 1)
    db.commit()
    assert "pokaż w pełnym nagraniu" not in clip_page(client, tab["clips"]["q1_cc"])


def test_error_state_outside_the_recording_offers_only_delete(client, tab, db):
    clip = tab["clips"]["q4_cc"]
    clip.status, clip.error = "error", "Moment poza nagraniem: 99:00 (nagranie trwa 15:00)"
    db.commit()
    page = clip_page(client, clip)
    assert "Moment poza nagraniem" in page and "więc klipu nie da się wyciąć" in page
    assert "Wytnij ponownie" not in page and "Usuń klip" in page and page.count("Usuń klip") == 1


def test_error_state_with_cut_failure_offers_recut_and_delete(client, tab, db):
    clip = tab["clips"]["q4_cc"]
    clip.status, clip.error = "error", "ffmpeg zakończył się błędem"
    db.commit()
    page = clip_page(client, clip)
    assert "Nie udało się wyciąć klipu: ffmpeg zakończył się błędem" in page
    assert "Wytnij ponownie" in page and "Usuń klip" in page and page.count("Usuń klip") == 1
    r = client.post(f"/clips/{clip.id}/recut?period=Q4", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/clips/{clip.id}?period=Q4"
    db.refresh(clip)
    assert clip.status == "queued" and clip.error is None


def test_recut_after_purge_is_refused_and_not_offered(client, tab, db):
    clip = tab["clips"]["q4_cc"]
    clip.status, clip.error = "error", "ffmpeg zakończył się błędem"
    tab["video"].purged_at = datetime(2026, 11, 1)
    db.commit()
    page = clip_page(client, clip)
    assert "nie ma już na serwerze" in page and "Wytnij ponownie" not in page
    assert client.post(f"/clips/{clip.id}/recut").status_code == 409


def test_error_state_buttons_hidden_from_viewers_without_rights(make_client, tab, db):
    clip = tab["clips"]["q4_cc"]
    clip.status, clip.error = "error", "ffmpeg zakończył się błędem"
    db.commit()
    outsider, _ = make_client("referee")
    page = outsider.get(f"/clips/{clip.id}").text
    assert "Nie udało się wyciąć klipu" in page and "Wytnij ponownie" not in page and "Usuń klip" not in page
    assert "Edytuj opis" not in page and "Opisz klip" not in page


# --- nazwa pliku -----------------------------------------------------------------------------
def test_download_name_pattern_is_date_quarter_time_referee_category(tab, db):
    from app import services
    c = tab["clips"]
    assert services.clip_filename(c["q1_cc"]) == "2026-10-28_Q1_00m30s_CC_kroki.mp4"
    assert services.clip_filename(c["q2_u1"]) == "2026-10-28_Q2_02m30s_U1_aut.mp4"
    assert services.clip_filename(c["q2_team"]) == "2026-10-28_Q2_03m00s_zespol_Kontakt-z-lawka.mp4"
    assert services.clip_filename(c["q1_none"]) == "2026-10-28_Q1_01m00s.mp4"                    # bez opisu
    c["q4_cc"].category_id = None
    c["q4_cc"].custom_category = "Zażółć gęślą jaźń / <script>" + "x" * 90
    name = services.clip_filename(c["q4_cc"])
    assert re.fullmatch(r"2026-10-28_Q4_05m50s_CC_[A-Za-z0-9-]{1,40}\.mp4", name), name
    c["q4_cc"].time_sec = 7503.7                                                                   # powyżej 99 minut
    assert "_125m03s_" in services.clip_filename(c["q4_cc"])


def test_download_name_follows_description_changes(client, tab, db):
    from app.storage import storage
    clip = tab["clips"]["q2_u1"]
    clip.clip_path, clip.status = "clips/x.mp4", "cut"
    with storage.open_write(clip.clip_path) as fh:
        fh.write(b"mp4")
    db.commit()
    cd = client.get(f"/clips/{clip.id}/download").headers["content-disposition"]
    assert 'filename="2026-10-28_Q2_02m30s_U1_aut.mp4"' in cd
    client.post(f"/clips/{clip.id}/update", data={"official": str(tab["cc"].id),
                                                  "category_id": str(category_named(db, "techniczny"))})
    cd = client.get(f"/clips/{clip.id}/download").headers["content-disposition"]
    assert 'filename="2026-10-28_Q2_02m30s_CC_techniczny.mp4"' in cd
    assert page_has_name(client, clip, "2026-10-28_Q2_02m30s_CC_techniczny.mp4")


def page_has_name(client, clip, name):
    return name in client.get(f"/clips/{clip.id}").text


# --- pomocnicze ---------------------------------------------------------------------------------
def clip_list_key(tab, which):
    from app import services
    from app.db import SessionLocal
    official = tab["cc"] if which == "cc" else tab["u1"]
    with SessionLocal() as db:
        return services.person_key(official.user_id, official.name, services.account_names(db))


def category_named_id(client, name):
    from app.db import SessionLocal
    with SessionLocal() as db:
        return category_named(db, name)
