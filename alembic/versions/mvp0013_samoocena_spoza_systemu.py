"""Standalone self-assessments (a match that is not in the system) and manual clip rows."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0013'
down_revision = 'mvp0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('self_assessments') as batch:
        batch.alter_column('match_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('league', sa.String(length=200), server_default='', nullable=False))
        batch.add_column(sa.Column('match_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('home_team', sa.String(length=200), server_default='', nullable=False))
        batch.add_column(sa.Column('away_team', sa.String(length=200), server_default='', nullable=False))
        batch.add_column(sa.Column('main_referee', sa.String(length=200), server_default='', nullable=False))
        batch.add_column(sa.Column('assistant_referees', sa.String(length=200), server_default='', nullable=False))
    with op.batch_alter_table('self_assessment_clips') as batch:
        batch.add_column(sa.Column('is_manual', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('self_assessment_clips') as batch:
        batch.drop_column('is_manual')
    # A standalone sheet has no match to go back to, so it is deleted (its rows and notifications cascade).
    op.execute("DELETE FROM notifications WHERE self_assessment_id IN "
               "(SELECT id FROM self_assessments WHERE match_id IS NULL)")
    op.execute("DELETE FROM self_assessment_clips WHERE self_assessment_id IN "
               "(SELECT id FROM self_assessments WHERE match_id IS NULL)")
    op.execute("DELETE FROM self_assessments WHERE match_id IS NULL")
    with op.batch_alter_table('self_assessments') as batch:
        batch.drop_column('assistant_referees')
        batch.drop_column('main_referee')
        batch.drop_column('away_team')
        batch.drop_column('home_team')
        batch.drop_column('match_date')
        batch.drop_column('league')
        batch.alter_column('match_id', existing_type=sa.Integer(), nullable=False)
