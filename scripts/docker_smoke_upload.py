"""Test dymny w kontenerze (uruchamiany przez scripts/docker-smoke.sh): logowanie, mecz,
wgranie pliku protokołem tus i oczekiwanie, aż worker go skonwertuje. Tylko biblioteka standardowa.

Użycie (w kontenerze app): python - EMAIL HASLO PLIK_WIDEO < scripts/docker_smoke_upload.py
"""
import base64
import http.cookiejar
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
email, password, video_path = sys.argv[1], sys.argv[2], Path(sys.argv[3])

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)


def call(method, path, data=None, headers=None, follow=True):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        return (opener if follow else no_redirect).open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303):
            return exc
        raise


def csrf_from(html: str) -> str:
    tag = re.search(r'<input[^>]*name="csrf_token"[^>]*>', html).group(0)
    return re.search(r'value="([^"]+)"', tag).group(1)


def form(path, fields, token):
    body = urllib.parse.urlencode({**fields, "csrf_token": token}).encode()
    return call("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"}, follow=False)


# 1. Logowanie
page = call("GET", "/login").read().decode()
r = form("/login", {"email": email, "password": password}, csrf_from(page))
assert r.status == 303 or r.code == 303, f"logowanie: {r}"
home = call("GET", "/").read().decode()
token = re.search(r'name="csrf-token" content="([^"]+)"', home).group(1)
print("OK logowanie")

# 2. Mecz
r = form("/matches", {"date": "2026-10-28", "level": "Test", "team_a_name": "A", "team_a_color": "białe",
                      "team_b_name": "B", "team_b_color": "ciemne", "cc_name": "Jan Test", "u1_name": "Ewa Test"},
         token)
match_id = int(r.headers["Location"].rsplit("/", 1)[1])
print("OK mecz", match_id)

# 3. tus
data = video_path.read_bytes()
meta = ",".join(f"{k} {base64.b64encode(str(v).encode()).decode()}"
                for k, v in {"filename": "smoke.mp4", "match_id": match_id}.items())
tus = {"Tus-Resumable": "1.0.0", "X-CSRF-Token": token}
r = call("POST", "/uploads/", None, {**tus, "Upload-Length": str(len(data)), "Upload-Metadata": meta,
                                     "Content-Length": "0"})
assert r.status == 201, r.status
location = r.headers["Location"]
r = call("PATCH", location, data, {**tus, "Upload-Offset": "0",
                                   "Content-Type": "application/offset+octet-stream"})
assert r.status == 204 and int(r.headers["Upload-Offset"]) == len(data)
print("OK tus", len(data), "B")

# 4. Czekamy na workera
db = sqlite3.connect("/data/ref-clips.db", timeout=30)
deadline = time.time() + 180
while time.time() < deadline:
    status, original, proxy = db.execute(
        "select status, original_path, proxy_path from videos where match_id=?", (match_id,)).fetchone()
    if status in ("ready", "error"):
        break
    time.sleep(2)
assert status == "ready", f"nagranie: {status}"
assert original is None, "oryginał powinien zostać usunięty"
assert (Path("/data") / proxy).is_file(), "brak wersji roboczej"
assert not list(Path("/data/uploads").glob("*")), "w uploads/ zostały pliki"
print("OK konwersja: ready, oryginał usunięty,", proxy)
