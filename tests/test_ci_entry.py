"""deploy/ci-entry.sh: wejście dla klucza CI na serwerze, przetestowane z podstawionymi `docker` i `curl`."""
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "ci-entry.sh"
IMG = "ghcr.io/fkula5/ref-clips"

DOCKER_STUB = r"""#!/usr/bin/env bash
echo "docker $*" >> "$STUB/calls"
case "$1" in
  info) exit 0 ;;
  pull) exit 0 ;;
  image) [ "$2" = ls ] && cat "$STUB/images"; exit 0 ;;
esac
shift 5   # compose -f compose.yaml -f compose.prod.yaml
case "$1" in
  ps) [ "$2" = --status ] && cat "$STUB/running" ;;
  exec) if [ "$3" = app ]; then
          cat > /dev/null; r="$(head -n1 "$STUB/busy")"; sed -i 1d "$STUB/busy"
          case "$r" in
            busy) printf 'ZAJĘTE — trwa:\n  - konwersja nagrania #1 — 40%%\n'; exit 1 ;;
            error) echo 'BŁĄD'; exit 2 ;;
          esac
        else cat "$STUB/caddyfile_running"; fi ;;
  up) echo "up $(grep '^REFCLIPS_IMAGE=' .env)" >> "$STUB/calls"
      [ "$(cat "$STUB/bad")" = up ] && grep -q ':v1.2.3$' .env && exit 1 ;;
esac
exit 0
"""
CURL_STUB = r"""#!/usr/bin/env bash
echo "curl $*" >> "$STUB/calls"
out=""; url="${@: -1}"
while [ $# -gt 1 ]; do [ "$1" = -o ] && out="$2"; shift; done
if [[ "$url" == https://codeload.github.com/* ]]; then
  [[ "$url" == */refs/tags/v1.2.3 ]] || exit 22
  cp "$STUB/src.tar.gz" "$out"; exit 0
fi
if [ "$(cat "$STUB/bad")" = health ] && grep -q ':v1.2.3$' .env; then
  echo '{"status":"error","checks":{"db":"ok","worker":"stale","disk":"ok"}}' > "$out"; printf 503
else echo '{"status":"ok"}' > "$out"; printf 200; fi
"""


@pytest.fixture()
def server(tmp_path):
    """Udawany serwer: /opt/ref-clips w tmp_path, podstawione docker i curl, archiwum wersji v1.2.3."""
    stub, app_dir, bin_dir = tmp_path / "stub", tmp_path / "opt", tmp_path / "bin"
    for d in (stub, app_dir / "deploy", bin_dir):
        d.mkdir(parents=True)
    for name, body in (("docker", DOCKER_STUB), ("curl", CURL_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    (app_dir / "compose.yaml").write_text("STARE compose\n")
    (app_dir / "compose.prod.yaml").write_text("STARE prod\n")
    (app_dir / "deploy" / "Caddyfile").write_text("stary caddyfile\n")
    (app_dir / ".env").write_text(f"REFCLIPS_SITE=x.example\nREFCLIPS_IMAGE={IMG}:v1.1.0\nREFCLIPS_TRUST_PROXY=1\n")
    with tarfile.open(stub / "src.tar.gz", "w:gz") as tar:
        for name, text in {"compose.yaml": "NOWE compose\n", "compose.prod.yaml": "NOWE prod\n",
                           "deploy/Caddyfile": "nowy caddyfile\n", "deploy/backup.sh": "#!/bin/sh\n",
                           "app/busy.py": "print('wolne')\n"}.items():
            info = tarfile.TarInfo(f"ref-clips-1.2.3/{name}")
            data = text.encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    for name, text in {"running": "app\nworker\ncaddy\n", "busy": "", "bad": "-\n", "caddyfile_running": "stary caddyfile\n",
                       "images": "\n".join(f"v{v}" for v in ("1.2.3", "1.2.0", "1.1.5", "1.1.0", "1.0.0")) + "\nlocal\n"}.items():
        (stub / name).write_text(text)

    class Server:
        dir = app_dir

        def run(self, command, busy=(), bad="-", wait_seconds=60):
            (stub / "busy").write_text("".join(f"{b}\n" for b in busy))
            (stub / "bad").write_text(bad + "\n")
            env = {"PATH": os.environ["PATH"], "REFCLIPS_CI_PATH_PREFIX": str(bin_dir), "STUB": str(stub), "SSH_ORIGINAL_COMMAND": command,
                   "REFCLIPS_CI_DIR": str(app_dir), "REFCLIPS_CI_WAIT_SECONDS": str(wait_seconds),
                   "REFCLIPS_CI_WAIT_INTERVAL": "1", "REFCLIPS_CI_HEALTH_TRIES": "2", "REFCLIPS_CI_HEALTH_SLEEP": "0"}
            return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

        def calls(self):
            path = stub / "calls"
            return path.read_text() if path.exists() else ""

        def env_lines(self):
            return (app_dir / ".env").read_text().splitlines()

    return Server()


@pytest.mark.parametrize("command", [
    "", "id", "rm -rf /", "deploy", "deploy v1.2", "deploy 1.2.3", "deploy v1.2.3 extra", "deploy  v1.2.3", "DEPLOY v1.2.3",
    "deploy v1.2.3; id", "deploy v1.2.3 && id", "deploy v1.2.3\nid", "deploy v1.2.3\n", "deploy $(id)", "deploy v1.2.3`id`",
    "deploy ../v1.2.3", "deploy v1.2.3|id", "status; id", "status extra", "STATUS", "deploy v" + "9" * 40,
])
def test_niedozwolone_polecenia_sa_odrzucone_bez_skutkow(server, command):
    r = server.run(command)
    assert r.returncode == 2 and "Niedozwolone polecenie" in r.stderr
    assert server.calls() == ""                         # ani docker, ani curl
    assert not (server.dir / ".deploy.lock").exists()   # nic nie ruszone
    assert "STARE" in (server.dir / "compose.yaml").read_text()


def test_status_nie_zmienia_niczego(server):
    r = server.run("status")
    assert r.returncode == 0
    assert "Wdrożona wersja" in r.stdout
    assert "up" not in server.calls().replace("docker info", "")


def test_zajete_czeka_i_po_limicie_konczy_bez_zmian(server):
    r = server.run("deploy v1.2.3", busy=["busy"] * 10, wait_seconds=2)
    assert r.returncode == 3
    assert r.stdout.count("Czekam") >= 1 and "konwersja nagrania #1" in r.stdout
    assert "NIE zostało wykonane" in r.stderr
    assert "STARE" in (server.dir / "compose.yaml").read_text()          # pliki i .env bez zmian
    assert f"REFCLIPS_IMAGE={IMG}:v1.1.0" in server.env_lines()
    assert "docker pull" not in server.calls() and " up " not in server.calls()


def test_blad_sprawdzenia_zajetosci_blokuje(server):
    r = server.run("deploy v1.2.3", busy=["error"])
    assert r.returncode == 1 and "nie udało się sprawdzić" in r.stderr
    assert "STARE" in (server.dir / "compose.yaml").read_text()


def test_nieznany_tag_konczy_sie_od_razu(server):
    r = server.run("deploy v9.9.9")
    assert r.returncode == 1 and "nie udało się pobrać" in r.stderr
    assert "docker pull" not in server.calls()


def test_sukces_czeka_na_wolne_podmienia_pliki_i_sprzata(server):
    r = server.run("deploy v1.2.3", busy=["busy", "busy"])     # dwa razy zajęte, potem wolne (i wolne przed restartem)
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("Czekam") == 2 and "Gotowe: wdrożono v1.2.3" in r.stdout
    assert (server.dir / "compose.yaml").read_text() == "NOWE compose\n"
    assert (server.dir / "deploy" / "Caddyfile").read_text() == "nowy caddyfile\n"
    assert (server.dir / ".deploy-commit").read_text().startswith("v1.2.3 ")
    # .env: dokładnie jedna linia REFCLIPS_IMAGE z nową wersją, reszta bez zmian
    assert server.env_lines() == ["REFCLIPS_SITE=x.example", "REFCLIPS_TRUST_PROXY=1", f"REFCLIPS_IMAGE={IMG}:v1.2.3"]
    calls = server.calls()
    assert f"docker pull --quiet {IMG}:v1.2.3" in calls
    assert "up -d --no-build --remove-orphans --wait --wait-timeout 300" in calls
    assert "restart caddy" in calls                                      # Caddyfile się zmienił
    assert f"image rm {IMG}:v1.0.0" in calls                             # poza 3 najnowszymi, bieżącym i poprzednim (v1.1.0)
    assert f"image rm {IMG}:v1.1.0" not in calls and "prune" not in calls and "image rm ref-clips" not in calls
    assert not list(server.dir.glob(".ci-incoming.*")) and not (server.dir / ".rollback").exists()


@pytest.mark.parametrize("bad", ["up", "health"])
def test_nieudany_start_przywraca_poprzednia_wersje(server, bad):
    r = server.run("deploy v1.2.3", bad=bad)
    assert r.returncode == 4, r.stderr
    assert "Wracam do poprzedniej wersji" in r.stderr and "serwer działa na poprzedniej wersji" in r.stderr
    assert (server.dir / "compose.yaml").read_text() == "STARE compose\n"
    assert (server.dir / "deploy" / "Caddyfile").read_text() == "stary caddyfile\n"
    assert server.env_lines().count(f"REFCLIPS_IMAGE={IMG}:v1.1.0") == 1 and not any("v1.2.3" in l for l in server.env_lines())
    assert not (server.dir / ".deploy-commit").exists()
    ups = [c for c in server.calls().splitlines() if c.startswith("up ")]
    assert ups == [f"up REFCLIPS_IMAGE={IMG}:v1.2.3", f"up REFCLIPS_IMAGE={IMG}:v1.1.0"]
