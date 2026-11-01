"""Testy interfejsu w przeglądarce (Playwright, Chromium): prawdziwy serwer i worker.

Uruchomienie: `pytest -m e2e` albo `scripts/e2e.sh`. Domyślne `pytest` te testy pomija.
Każdy test kończy się porażką, gdy w przeglądarce wystąpi błąd JavaScript (`pageerror`,
`console.error`), chyba że test jawnie go dopuścił (`ui.allow("wzorzec")`). Przy porażce zapisujemy
zrzut ekranu, log konsoli i logi serwera w katalogu tymczasowym (ścieżka w komunikacie błędu).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="brak playwright — pip install -r requirements-dev.txt")

from playwright.sync_api import Browser, BrowserContext, Page, expect  # noqa: E402

from tests.e2e.support import PASSWORD, USERS, Server, make_sample_video  # noqa: E402

ARTIFACTS_ROOT = Path(tempfile.gettempdir()) / "refclips-e2e-artifacts"
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 844}


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


# --- serwer ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """Wideo próbne (50 s, 640x360, z dźwiękiem) — jedno na cały przebieg."""
    return make_sample_video(tmp_path_factory.mktemp("e2e-video") / "mecz-probka.mp4")


@pytest.fixture(scope="session")
def server(sample_video):
    workdir = Path(tempfile.mkdtemp(prefix="refclips-e2e-"))
    srv = Server(workdir, sample_video)
    try:
        srv.start()
        yield srv
    finally:
        srv.stop()
        if not _keep_workdir():
            shutil.rmtree(workdir, ignore_errors=True)


def _keep_workdir() -> bool:
    import os
    return os.environ.get("E2E_KEEP") == "1"


@pytest.fixture(scope="session", autouse=True)
def _expect_timeout():
    expect.set_options(timeout=10_000)


# --- przeglądarka ---------------------------------------------------------------------
@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Odtwarzanie z wywołania skryptu bez gestu użytkownika (np. video.play() w teście).
    return {**browser_type_launch_args, "args": ["--autoplay-policy=no-user-gesture-required"]}


class Diagnostics:
    """Zbiera logi konsoli i błędy JavaScript ze wszystkich stron kontekstów testu."""

    def __init__(self):
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.allowed: list[re.Pattern] = []

    def allow(self, pattern: str) -> None:
        self.allowed.append(re.compile(pattern))

    def attach(self, page: Page) -> None:
        def on_console(msg):
            line = f"[{msg.type}] {msg.text} ({msg.location.get('url', '')}:{msg.location.get('lineNumber', '')})"
            self.lines.append(line)
            if msg.type == "error":
                self.errors.append(line)

        def on_pageerror(err):
            line = f"[pageerror] {err}"
            self.lines.append(line)
            self.errors.append(line)

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

    def unexpected(self) -> list[str]:
        return [e for e in self.errors if not any(p.search(e) for p in self.allowed)]


class UI:
    """Fabryka stron przeglądarki dla testu: konteksty z zalogowaną rolą, diagnostyka, sprzątanie."""

    def __init__(self, browser: Browser, server: Server, states: dict[str, Path]):
        self.browser, self.server, self.states = browser, server, states
        self.contexts: list[BrowserContext] = []
        self.pages: list[Page] = []
        self.diag = Diagnostics()

    def allow(self, pattern: str) -> None:
        """Dopuszcza błąd konsoli pasujący do wyrażenia regularnego (test sprawdza go sam)."""
        self.diag.allow(pattern)

    def context(self, role: str | None = None, *, mobile: bool = False, **kwargs) -> BrowserContext:
        options = dict(base_url=self.server.base_url, locale="pl-PL", viewport=MOBILE if mobile else DESKTOP, **kwargs)
        if mobile:
            options.update(is_mobile=True, has_touch=True, device_scale_factor=2)
        if role:
            options["storage_state"] = str(self.states[role])
        context = self.browser.new_context(**options)
        context.set_default_timeout(15_000)
        context.on("page", self.diag.attach)
        self.contexts.append(context)
        return context

    def page(self, role: str | None = None, *, mobile: bool = False, **kwargs) -> Page:
        context = self.context(role, mobile=mobile, **kwargs)
        page = context.new_page()
        self.pages.append(page)
        return page

    def close(self) -> None:
        for context in self.contexts:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - kontekst mógł zostać już zamknięty przez test
                pass


def login(page: Page, email: str, password: str = PASSWORD, next_path: str = "") -> None:
    page.goto("/login" + (f"?next={next_path}" if next_path else ""))
    page.get_by_label("E-mail").fill(email)
    page.get_by_label("Hasło").fill(password)
    page.get_by_role("button", name="Zaloguj").click()


@pytest.fixture(scope="session")
def role_states(browser: Browser, server: Server, tmp_path_factory) -> dict[str, Path]:
    """Stan zalogowania (cookies) per rola, zapisany po prawdziwym logowaniu przez formularz."""
    states = {}
    folder = tmp_path_factory.mktemp("e2e-states")
    for role, (email, _name, _roles) in USERS.items():
        context = browser.new_context(base_url=server.base_url, locale="pl-PL")
        page = context.new_page()
        login(page, email)
        page.wait_for_url("**/")
        expect(page.locator(".who")).to_contain_text(USERS[role][1])
        states[role] = folder / f"{role}.json"
        context.storage_state(path=str(states[role]))
        context.close()
    return states


@pytest.fixture()
def ui(browser, server, role_states):
    helper = UI(browser, server, role_states)
    yield helper
    helper.close()


# --- diagnostyka porażek ----------------------------------------------------------------
def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)


def save_artifacts(item, helper: UI) -> Path:
    folder = ARTIFACTS_ROOT / RUN_ID / _safe(item.name)
    folder.mkdir(parents=True, exist_ok=True)
    for i, page in enumerate(helper.pages):
        try:
            page.screenshot(path=str(folder / f"strona-{i}.png"), full_page=False, timeout=5000)
            (folder / f"strona-{i}.url").write_text(page.url)
        except Exception as exc:  # noqa: BLE001
            (folder / f"strona-{i}.blad").write_text(str(exc))
    (folder / "konsola-przegladarki.log").write_text("\n".join(helper.diag.lines) + "\n")
    helper.server.copy_logs(folder)
    return folder


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    helper: UI | None = item.funcargs.get("ui")
    try:
        result = yield
    except BaseException as exc:
        if helper is not None and helper.pages:
            folder = save_artifacts(item, helper)
            exc.add_note(f"Artefakty E2E (zrzut ekranu, log konsoli, logi serwera): {folder}")
        raise
    if helper is not None:
        problems = helper.diag.unexpected()
        if problems:
            folder = save_artifacts(item, helper)
            raise AssertionError("Błędy JavaScript w przeglądarce:\n  " + "\n  ".join(problems)
                                 + f"\nArtefakty E2E: {folder}")
    return result
