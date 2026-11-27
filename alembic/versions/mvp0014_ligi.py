"""Managed list of leagues, seeded from the levels typed into existing matches."""
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


def _seed_names(levels: list[str]) -> list[str]:
    """Spellings that are equal after normalizing collapse into one league named like the most used one
    (ties: the alphabetically first), listed by name.
    """
    counts = Counter(level.strip() for level in levels if level and level.strip())
    best: dict[str, str] = {}
    for spelling, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        best.setdefault(_normalize(spelling), spelling)
    return sorted(best.values(), key=lambda name: (_normalize(name), name))


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
    levels = [row[0] for row in op.get_bind().execute(sa.text("SELECT level FROM matches"))]
    names = _seed_names(levels)
    if names:
        op.bulk_insert(leagues, [{'name': name, 'position': index * 10, 'is_active': True}
                                 for index, name in enumerate(names, start=1)])


def downgrade() -> None:
    op.drop_table('leagues')
