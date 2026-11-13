"""Daily e-mail digest: per-user preferences, unsubscribe token and the end of the last digest window."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0011'
down_revision = 'mvp0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'email_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('digest_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('new_clips_in_groups', sa.Boolean(), nullable=True),
        sa.Column('new_match_in_groups', sa.Boolean(), nullable=True),
        sa.Column('comments_and_ratings', sa.Boolean(), nullable=True),
        sa.Column('sheet_published', sa.Boolean(), nullable=True),
        sa.Column('group_added', sa.Boolean(), nullable=True),
        sa.Column('unsubscribe_token', sa.String(length=64), nullable=True),
        sa.Column('last_digest_until', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_preferences_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_email_preferences')),
        sa.UniqueConstraint('unsubscribe_token', name=op.f('uq_email_preferences_unsubscribe_token')),
    )


def downgrade() -> None:
    op.drop_table('email_preferences')
