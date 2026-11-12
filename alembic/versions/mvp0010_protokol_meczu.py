"""Match scoresheet ("Protokół"): files attached to a match."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0010'
down_revision = 'mvp0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'match_scoresheets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_match_scoresheets_match_id_matches'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_match_scoresheets_uploaded_by_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_match_scoresheets')),
    )
    op.create_index(op.f('ix_match_scoresheets_match_id'), 'match_scoresheets', ['match_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_match_scoresheets_match_id'), table_name='match_scoresheets')
    op.drop_table('match_scoresheets')
