"""Qualifier assessment sheet (descriptive, no points)."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0006'
down_revision = 'mvp0005'
branch_labels = None
depends_on = None

DEFAULT_ELEMENTS = [
    "Obowiązki przedmeczowe", "Przygotowanie fizyczne", "Mechanika", "Sygnalizacja", "Ocena kontaktów",
    "Ocena błędów", "Współpraca", "Kontrola gry", "Przywództwo", "Jakość pracy",
]


def upgrade() -> None:
    elements = op.create_table(
        'sheet_elements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sheet_elements')),
        sa.UniqueConstraint('name', name=op.f('uq_sheet_elements_name')),
    )
    op.bulk_insert(elements, [{'name': name, 'is_active': True, 'sort': index * 10}
                              for index, name in enumerate(DEFAULT_ELEMENTS, start=1)])
    op.create_table(
        'sheets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('coach_id', sa.Integer(), nullable=False),
        sa.Column('result', sa.String(length=50), server_default='', nullable=False),
        sa.Column('difficulty', sa.String(length=10), nullable=True),
        sa.Column('crew_note', sa.Text(), server_default='', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published')", name=op.f('ck_sheets_status_valid')),
        sa.CheckConstraint("difficulty IS NULL OR difficulty IN ('latwy', 'normalny', 'trudny')",
                           name=op.f('ck_sheets_difficulty_valid')),
        sa.CheckConstraint("status = 'draft' OR difficulty IS NOT NULL",
                           name=op.f('ck_sheets_published_has_difficulty')),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_sheets_match_id_matches'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['coach_id'], ['users.id'], name=op.f('fk_sheets_coach_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sheets')),
        sa.UniqueConstraint('match_id', 'coach_id', name=op.f('uq_sheets_match_id')),
    )
    op.create_table(
        'sheet_columns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sheet_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('function', sa.String(length=2), nullable=False),
        sa.Column('official_name', sa.String(length=100), nullable=False),
        sa.Column('overall', sa.Text(), server_default='', nullable=False),
        sa.Column('recommendation', sa.Text(), server_default='', nullable=False),
        sa.ForeignKeyConstraint(['sheet_id'], ['sheets.id'], name=op.f('fk_sheet_columns_sheet_id_sheets'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sheet_columns')),
    )
    op.create_index(op.f('ix_sheet_columns_sheet_id'), 'sheet_columns', ['sheet_id'], unique=False)
    op.create_table(
        'sheet_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sheet_id', sa.Integer(), nullable=False),
        sa.Column('element_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(['sheet_id'], ['sheets.id'], name=op.f('fk_sheet_rows_sheet_id_sheets'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['element_id'], ['sheet_elements.id'],
                                name=op.f('fk_sheet_rows_element_id_sheet_elements'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sheet_rows')),
    )
    op.create_index(op.f('ix_sheet_rows_sheet_id'), 'sheet_rows', ['sheet_id'], unique=False)
    op.create_index(op.f('ix_sheet_rows_element_id'), 'sheet_rows', ['element_id'], unique=False)
    op.create_table(
        'sheet_cells',
        sa.Column('row_id', sa.Integer(), nullable=False),
        sa.Column('column_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), server_default='', nullable=False),
        sa.ForeignKeyConstraint(['row_id'], ['sheet_rows.id'], name=op.f('fk_sheet_cells_row_id_sheet_rows'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['column_id'], ['sheet_columns.id'],
                                name=op.f('fk_sheet_cells_column_id_sheet_columns'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('row_id', 'column_id', name=op.f('pk_sheet_cells')),
    )
    op.create_index(op.f('ix_sheet_cells_column_id'), 'sheet_cells', ['column_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sheet_cells_column_id'), table_name='sheet_cells')
    op.drop_table('sheet_cells')
    op.drop_index(op.f('ix_sheet_rows_element_id'), table_name='sheet_rows')
    op.drop_index(op.f('ix_sheet_rows_sheet_id'), table_name='sheet_rows')
    op.drop_table('sheet_rows')
    op.drop_index(op.f('ix_sheet_columns_sheet_id'), table_name='sheet_columns')
    op.drop_table('sheet_columns')
    op.drop_table('sheets')
    op.drop_table('sheet_elements')
