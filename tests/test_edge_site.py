import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
TEMPLATE = DEPLOY / "ref-clips.caddy"
RENDER = DEPLOY / "render-site.sh"
INSTALL = DEPLOY / "install-site.sh"


def render(tmp_path, env_text):
    env = tmp_path / ".env"
    env.write_text(env_text)
    return subprocess.run(["bash", str(RENDER), str(TEMPLATE), str(env)], capture_output=True, text=True)


def header_line(output):
    return next(line for line in output.splitlines() if line.endswith(" {") and not line.startswith(("\t", "#")))


def test_substitutes_site_and_redirect_hosts(tmp_path):
    r = render(tmp_path, 'REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS="www.refclips.pl 57-131-162-204.sslip.io"\nOTHER=1\n')
    assert r.returncode == 0, r.stderr
    assert header_line(r.stdout) == "refclips.pl www.refclips.pl 57-131-162-204.sslip.io {"
    assert "@other_host not host refclips.pl\n" in r.stdout
    assert "redir @other_host https://refclips.pl{uri} 308" in r.stdout
    assert "{$" not in r.stdout
    assert "reverse_proxy ref-clips-app:8000 {" in r.stdout


@pytest.mark.parametrize("env_text", [
    "REFCLIPS_SITE=refclips.pl\n",
    "REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS=\n",
    'REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS=""\n',
    "REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS=   \n",
])
def test_empty_redirect_hosts_leave_a_single_host_block(tmp_path, env_text):
    r = render(tmp_path, env_text)
    assert r.returncode == 0, r.stderr
    assert header_line(r.stdout) == "refclips.pl {"


def test_quotes_crlf_and_last_assignment_are_handled(tmp_path):
    r = render(tmp_path, "REFCLIPS_SITE=old.example\r\nREFCLIPS_SITE='refclips.pl'\r\nREFCLIPS_REDIRECT_HOSTS=\"www.refclips.pl\"\r\n")
    assert r.returncode == 0, r.stderr
    assert header_line(r.stdout) == "refclips.pl www.refclips.pl {"


def test_everything_but_the_placeholders_is_kept(tmp_path):
    r = render(tmp_path, "REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS=\"www.refclips.pl\"\n")
    template = TEMPLATE.read_text()
    expected = (
        template.replace("{$REFCLIPS_SITE} {$REFCLIPS_REDIRECT_HOSTS}", "refclips.pl www.refclips.pl").replace("{$REFCLIPS_SITE}", "refclips.pl")
    )
    assert r.stdout.split("\n", 1)[1] == expected
    for fragment in ("request_body @tus {\n\t\tmax_size 64MB", "max_size 220MB", "max_size 10MB", "flush_interval -1", "dial_timeout 5s", "format filter"):
        assert fragment in r.stdout


@pytest.mark.parametrize("site", ["a{b", "a b", "a.b;", "-a.b", "a-.b", "a..b", ".a.b", "a.b.", "a.b/c", "a.b:443", "https://a.b", "", "ü.pl", "a" * 64 + ".pl", "$(id).pl", "a.b}"])
def test_bad_site_is_rejected(tmp_path, site):
    r = render(tmp_path, f"REFCLIPS_SITE={site}\n")
    assert r.returncode == 1 and r.stdout == ""
    assert "REFCLIPS_SITE" in r.stderr


@pytest.mark.parametrize("hosts", ["a{b", "ok.pl evil.pl}", "ok.pl a..b", "*", "ok.pl;rm", "ok.pl\tevil.pl", "http://x.pl", "ok.pl {", "-bad.pl"])
def test_bad_redirect_host_is_rejected(tmp_path, hosts):
    r = render(tmp_path, f'REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS="{hosts}"\n')
    assert r.returncode == 1 and r.stdout == ""
    assert "REFCLIPS_REDIRECT_HOSTS" in r.stderr


def call_function(site, hosts):
    script = f'source "{RENDER}"; render_site "{TEMPLATE}" "$1" "$2"'
    return subprocess.run(["bash", "-c", script, "_", site, hosts], capture_output=True, text=True)


@pytest.mark.parametrize("site,hosts", [
    ("a.b\nevil.com {", ""), ("refclips.pl\n", ""), ("refclips.pl", "ok.pl\nevil.com {\n}"), ("refclips.pl", "ok.pl\n"),
    ("a.b} evil {", ""), ("refclips.pl", "x.pl} evil.com {"),
])
def test_bad_values_are_rejected_by_the_function(site, hosts):
    r = call_function(site, hosts)
    assert r.returncode == 1 and r.stdout == ""


def test_hostnames_with_digits_hyphens_and_single_labels_are_accepted():
    assert call_function("localhost", "").returncode == 0
    assert call_function("203-0-113-7.sslip.io", "WWW.Example.COM a1-b2.example.pl").returncode == 0


def test_missing_site_or_env_file_fails(tmp_path):
    assert render(tmp_path, "REFCLIPS_REDIRECT_HOSTS=www.refclips.pl\n").returncode == 1
    r = subprocess.run(["bash", str(RENDER), str(TEMPLATE), str(tmp_path / "nie-ma")], capture_output=True, text=True)
    assert r.returncode == 1
    assert subprocess.run(["bash", str(RENDER)], capture_output=True, text=True).returncode == 2


def test_unresolved_placeholder_is_an_error(tmp_path):
    template = tmp_path / "t.caddy"
    template.write_text("{$REFCLIPS_SITE} {\n\trespond {$REFCLIPS_OTHER}\n}\n")
    env = tmp_path / ".env"
    env.write_text("REFCLIPS_SITE=refclips.pl\n")
    r = subprocess.run(["bash", str(RENDER), str(template), str(env)], capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == ""


def test_the_template_is_a_site_block_only():
    text = TEMPLATE.read_text()
    code = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert code[0] == "{$REFCLIPS_SITE} {$REFCLIPS_REDIRECT_HOSTS} {"
    assert not any(line.startswith("import") for line in code)
    assert "servers {" not in text
    assert "reverse_proxy ref-clips-app:8000" in text and "app:8000" not in text.replace("ref-clips-app:8000", "")
    assert re.findall(r"\{\$(\w+)\}", text) and set(re.findall(r"\{\$(\w+)\}", text)) == {"REFCLIPS_SITE", "REFCLIPS_REDIRECT_HOSTS"}


# --- compose layout -----------------------------------------------------------------------------------

def test_prod_overlay_has_no_caddy_and_joins_the_edge_network():
    text = (ROOT / "compose.prod.yaml").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"^  caddy:", code, re.M) and "image: caddy" not in code
    assert not re.search(r"^volumes:", code, re.M)
    assert re.search(r"^networks:\n  edge:\n    name: edge\n    external: true\s*$", code, re.M)
    assert "ports: !reset []" in code
    app = re.search(r"^  app:\n(.*?)(?=^  \w|^\w)", code, re.M | re.S).group(1)
    assert re.search(r"networks:\n      default:.*\n      edge:\n        aliases:\n          - ref-clips-app\b", app)
    for gone in ("REFCLIPS_CADDY_SITES_DIR", "REFCLIPS_HTTP_PORT", "REFCLIPS_HTTPS_PORT", "caddy-sites"):
        assert gone not in code
    assert "networks:" not in re.search(r"^  worker:\n(.*?)(?=^\w)", code, re.M | re.S).group(1)


def test_local_compose_does_not_need_the_edge_network():
    text = (ROOT / "compose.yaml").read_text()
    assert "external: true" not in text and "edge" not in text and "ref-clips-app" not in text


# --- install-site.sh ----------------------------------------------------------------------------------

DOCKER_STUB = r"""#!/usr/bin/env bash
echo "docker $*" >> "$STUB/calls"
case "$1" in
  info) exit 0 ;;
  inspect) [ -f "$STUB/no-container" ] && exit 1; echo true ;;
esac
"""
RELOAD_STUB = r"""#!/usr/bin/env bash
echo "reload: $(cat "$EDGE/conf/sites/ref-clips.caddy" 2>/dev/null | head -n3 | tail -n1)" >> "$STUB/calls"
[ -f "$STUB/reload-fails" ] && { echo "Error: adapting config" >&2; exit 1; }
exit 0
"""


@pytest.fixture()
def edge(tmp_path):
    stub, edge_dir, bin_dir = tmp_path / "stub", tmp_path / "edge", tmp_path / "bin"
    for d in (stub, edge_dir / "conf" / "sites", bin_dir):
        d.mkdir(parents=True)
    (bin_dir / "docker").write_text(DOCKER_STUB)
    (edge_dir / "reload.sh").write_text(RELOAD_STUB)
    for f in (bin_dir / "docker", edge_dir / "reload.sh"):
        f.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text("REFCLIPS_SITE=refclips.pl\n")
    sites = edge_dir / "conf" / "sites"

    class Edge:
        dir = edge_dir
        site_file = sites / "ref-clips.caddy"
        env = env_file

        def run(self, *args, env_text=None):
            if env_text is not None:
                env_file.write_text(env_text)
            env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB": str(stub), "EDGE": str(edge_dir), "REFCLIPS_EDGE_DIR": str(edge_dir)}
            return subprocess.run(["bash", str(INSTALL), *args, str(TEMPLATE), str(env_file)], env=env, capture_output=True, text=True)

        def flag(self, name):
            (stub / name).write_text("")

        def calls(self):
            path = stub / "calls"
            return path.read_text() if path.exists() else ""

        def leftovers(self):
            return sorted(p.name for p in sites.iterdir() if p.name != "ref-clips.caddy")

    return Edge()


def test_install_places_the_rendered_file_and_reloads(edge):
    r = edge.run()
    assert r.returncode == 0, r.stderr
    text = edge.site_file.read_text()
    assert "refclips.pl {" in text and "{$" not in text
    assert edge.calls().count("reload:") == 1
    assert edge.leftovers() == []


def test_install_skips_the_reload_when_nothing_changed(edge):
    assert edge.run().returncode == 0
    r = edge.run()
    assert r.returncode == 0 and "bez zmian" in r.stdout
    assert edge.calls().count("reload:") == 1


def test_check_changes_nothing(edge):
    r = edge.run("--check")
    assert r.returncode == 0, r.stderr
    assert not edge.site_file.exists() and edge.leftovers() == [] and "reload:" not in edge.calls()


def test_failed_reload_restores_the_previous_file_and_reloads_again(edge):
    edge.site_file.write_text("# stary\nold.example {\n}\n")
    edge.flag("reload-fails")
    r = edge.run()
    assert r.returncode == 1 and "przywracam" in r.stderr
    assert edge.site_file.read_text() == "# stary\nold.example {\n}\n"
    assert edge.calls().count("reload:") == 2
    assert edge.leftovers() == []


def test_failed_first_reload_removes_the_new_file(edge):
    edge.flag("reload-fails")
    r = edge.run()
    assert r.returncode == 1
    assert not edge.site_file.exists() and edge.leftovers() == []


@pytest.mark.parametrize("mode", [(), ("--check",)])
def test_missing_edge_dir_fails_with_a_pointer_to_the_docs(edge, mode):
    for p in sorted((edge.dir / "conf").rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    (edge.dir / "conf").rmdir()
    r = edge.run(*mode)
    assert r.returncode == 1 and "stos edge nie jest zainstalowany" in r.stderr and "docs/wdrozenie.md" in r.stderr


@pytest.mark.parametrize("mode", [(), ("--check",)])
def test_missing_edge_container_fails_and_changes_nothing(edge, mode):
    edge.flag("no-container")
    edge.site_file.write_text("# stary\n")
    r = edge.run(*mode)
    assert r.returncode == 1 and "edge-caddy" in r.stderr and "docs/wdrozenie.md" in r.stderr
    assert edge.site_file.read_text() == "# stary\n" and "reload:" not in edge.calls()


def test_bad_env_value_changes_nothing(edge):
    edge.site_file.write_text("# stary\n")
    r = edge.run(env_text='REFCLIPS_SITE=refclips.pl\nREFCLIPS_REDIRECT_HOSTS="www.x.pl evil{"\n')
    assert r.returncode == 1
    assert edge.site_file.read_text() == "# stary\n" and edge.leftovers() == [] and "reload:" not in edge.calls()
