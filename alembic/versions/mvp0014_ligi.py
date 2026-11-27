"""Managed list of leagues, seeded from the levels typed into existing matches. Matches typed with another
spelling of a seeded league ("II Liga", " ii liga ") are rewritten to the league's name, so every match counts
toward its league; the downgrade keeps the unified spelling."""
from collections import Counter
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision = 'mvp0014'
down_revision = 'mvp0013'
branch_labels = None
depends_on = None


def _normalize(text: str) -> str:
    """A frozen copy of `app.textutil.normalize`, so the migration does not change with the app."""
    text = text.translate(str.maketrans({"ł": "l", "Ł": "L"}))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _winners(levels: list[str]) -> dict[str, str]:
    """Normalized spelling -> the league name: the most used spelling (ties: the alphabetically first)."""
    counts = Counter(level.strip() for level in levels if level and level.strip())
    best: dict[str, str] = {}
    for spelling, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        best.setdefault(_normalize(spelling), spelling)
    return best


def _seed_names(levels: list[str]) -> list[str]:
    return sorted(_winners(levels).values(), key=lambda name: (_normalize(name), name))


def upgrade() -> None:
    leagues = op.create_table(
        'leagues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_leagues')),
        sa.UniqueConstraint('name', name=op.f('uq_leagues_name')),
    )
    bind = op.get_bind()
    levels = [row[0] for row in bind.execute(sa.text("SELECT level FROM matches"))]
    winners = _winners(levels)
    for raw in {level for level in levels if level and level.strip()}:
        name = winners[_normalize(raw.strip())]
        if raw != name:
            bind.execute(sa.text("UPDATE matches SET level = :name WHERE level = :raw"), {"name": name, "raw": raw})
    names = _seed_names(levels)
    if names:
        op.bulk_insert(leagues, [{'name': name, 'position': index * 10, 'is_active': True}
                                 for index, name in enumerate(names, start=1)])


def downgrade() -> None:
    op.drop_table('leagues')
