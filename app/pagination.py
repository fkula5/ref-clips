from __future__ import annotations

from dataclasses import dataclass


def parse_page(raw: str | None) -> int:
    """Anything that is not a positive number means the first page."""
    try:
        return max(1, int(raw or 1))
    except ValueError:
        return 1


@dataclass(frozen=True)
class Page:
    total: int
    page: int
    pages: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def paginate(total: int, requested: int, size: int) -> Page:
    """A page past the end becomes the last one (a list that shrank after the link was made)."""
    pages = max(1, -(-total // size))
    return Page(total, min(max(1, requested), pages), pages, size)


def page_query(number: int) -> str:
    return f"page={number}" if number > 1 else ""
