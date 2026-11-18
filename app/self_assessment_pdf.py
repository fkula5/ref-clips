"""PDF of the report, rendered by WeasyPrint from the same HTML and stylesheet as the on-screen report."""
from __future__ import annotations

from functools import cache

from app import config
from app.models import SelfAssessment
from app.self_assessments import QUESTIONS, header
from app.web import env


@cache
def _css() -> str:
    return (config.BASE_DIR / "app" / "static" / "self_assessment_report.css").read_text(encoding="utf-8")


def _deny(url: str, *args, **kwargs):
    """The page needs no external resource; refusing them keeps a stray URL from being fetched."""
    raise ValueError(f"external resource refused: {url}")


def render_html(sa: SelfAssessment) -> str:
    return env.get_template("self_assessment_pdf.html").render(
        sa=sa, h=header(sa.match), questions=QUESTIONS, css=_css())


def render_pdf(sa: SelfAssessment) -> bytes:
    from weasyprint import HTML  # imported here so the app starts even where its system libraries are missing

    return HTML(string=render_html(sa), url_fetcher=_deny).write_pdf()
