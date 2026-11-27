import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.frontend_shell import VueShell


@pytest.fixture
def shell_client(tmp_path):
    (tmp_path / "index.html").write_text("<div id='app'></div>", encoding="utf-8")

    async def downstream(scope, receive, send):
        response = JSONResponse({"path": scope["path"], "method": scope["method"]})
        await response(scope, receive, send)

    return TestClient(VueShell(downstream, directory=tmp_path))


@pytest.mark.parametrize("path", [
    "/matches", "/matches/new", "/matches/12/edit", "/matches/12/describe",
    "/clips", "/clips/12", "/recordings/12/edit", "/groups/12/review",
    "/training-sets/3/clips/12", "/notifications/settings", "/admin/sheet-elements",
    "/sheets/12/edit", "/self-assessments/12/edit", "/referees/12",
    "/klipy/12", "/nagrania/12", "/s/example-code",
])
def test_shell_serves_canonical_and_former_browser_paths(shell_client, path):
    response = shell_client.get(path, headers={"Accept": "text/html"})
    assert response.text == "<div id='app'></div>"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    head = shell_client.head(path, headers={"Accept": "text/html"})
    assert head.headers["Content-Type"].startswith("text/html")
    assert not head.content


@pytest.mark.parametrize(("method", "path", "headers"), [
    ("GET", "/groups/12/review", {"Accept": "application/json"}),
    ("GET", "/matches/new", {"Accept": "application/json"}),
    ("GET", "/notifications/bell", {"Accept": "text/html"}),
    ("GET", "/clips/12/file", {"Accept": "text/html"}),
    ("GET", "/matches/12/scoresheets/4/download", {"Accept": "text/html"}),
    ("GET", "/clips?view=classic", {"Accept": "text/html"}),
    ("GET", "/clips/12", {"Accept": "text/html", "HX-Request": "true"}),
    ("POST", "/matches/12/edit", {"Accept": "text/html"}),
])
def test_shell_leaves_api_files_and_classic_pages_to_fastapi(shell_client, method, path, headers):
    response = shell_client.request(method, path, headers=headers)
    assert response.json() == {"path": path.split("?")[0], "method": method}
