import re

from app.web import asset


def test_asset_urls_carry_a_content_hash(client):
    url = asset("app.css")
    assert re.fullmatch(r"/static/app\.css\?v=[0-9a-f]{12}", url)
    page = client.get("/").text
    assert url in page and 'href="/static/app.css"' not in page


def test_hashed_assets_are_cached_for_good_and_plain_ones_revalidate(client):
    hashed = client.get(asset("app.css"))
    assert hashed.status_code == 200 and "immutable" in hashed.headers["cache-control"]
    plain = client.get("/static/app.css")
    assert plain.status_code == 200 and plain.headers["cache-control"] == "no-cache"
