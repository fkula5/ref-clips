"""Referee self-assessment sheets, their notification kind and the digest switch."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0012'
down_revision = 'mvp0011'
branch_labels = None
depends_on = None

OLD_KINDS = ("kind IN ('rating', 'rating_changed', 'clip_comment', 'match_comment', 'sheet_published', "
             "'group_added')")
NEW_KINDS = ("kind IN ('rating', 'rating_changed', 'clip_comment', 'match_comment', 'sheet_published', "
             "'group_added', 'self_assessment')")


def upgrade() -> None:
    op.create_table(
        'self_assessments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('opinion', sa.Text(), server_default='', nullable=False),
        sa.Column('good', sa.Text(), server_default='', nullable=False),
        sa.Column('bad', sa.Text(), server_default='', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name=op.f('ck_self_assessments_status_valid')),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_self_assessments_match_id_matches'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_self_assessments_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_self_assessments')),
        sa.UniqueConstraint('match_id', 'user_id', name=op.f('uq_self_assessments_match_id')),
    )
    op.create_index(op.f('ix_self_assessments_user_id'), 'self_assessments', ['user_id'], unique=False)
    op.create_table(
        'self_assessment_clips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('self_assessment_id', sa.Integer(), nullable=False),
        sa.Column('clip_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('time_label', sa.String(length=200), server_default='', nullable=False),
        sa.Column('name_label', sa.String(length=200), server_default='', nullable=False),
        sa.ForeignKeyConstraint(['self_assessment_id'], ['self_assessments.id'],
                                name=op.f('fk_self_assessment_clips_self_assessment_id_self_assessments'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_self_assessment_clips_clip_id_clips'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_self_assessment_clips')),
        sa.UniqueConstraint('self_assessment_id', 'clip_id', name=op.f('uq_self_assessment_clips_self_assessment_id')),
    )
    op.create_index(op.f('ix_self_assessment_clips_self_assessment_id'), 'self_assessment_clips',
                    ['self_assessment_id'], unique=False)
    op.create_index(op.f('ix_self_assessment_clips_clip_id'), 'self_assessment_clips', ['clip_id'], unique=False)

    with op.batch_alter_table('notifications') as batch:
        batch.add_column(sa.Column('self_assessment_id', sa.Integer(), nullable=True))
        batch.drop_constraint(op.f('ck_notifications_kind_valid'), type_='check')
        batch.create_check_constraint(op.f('ck_notifications_kind_valid'), NEW_KINDS)
        batch.create_foreign_key(op.f('fk_notifications_self_assessment_id_self_assessments'), 'self_assessments',
                                 ['self_assessment_id'], ['id'], ondelete='CASCADE')
        batch.create_index(op.f('ix_notifications_self_assessment_id'), ['self_assessment_id'], unique=False)

    with op.batch_alter_table('email_preferences') as batch:
        batch.add_column(sa.Column('self_assessment_submitted', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('email_preferences') as batch:
        batch.drop_column('self_assessment_submitted')
    op.execute("DELETE FROM notifications WHERE kind = 'self_assessment'")
    with op.batch_alter_table('notifications') as batch:
        batch.drop_index(op.f('ix_notifications_self_assessment_id'))
        batch.drop_constraint(op.f('fk_notifications_self_assessment_id_self_assessments'), type_='foreignkey')
        batch.drop_constraint(op.f('ck_notifications_kind_valid'), type_='check')
        batch.create_check_constraint(op.f('ck_notifications_kind_valid'), OLD_KINDS)
        batch.drop_column('self_assessment_id')
    op.drop_index(op.f('ix_self_assessment_clips_clip_id'), table_name='self_assessment_clips')
    op.drop_index(op.f('ix_self_assessment_clips_self_assessment_id'), table_name='self_assessment_clips')
    op.drop_table('self_assessment_clips')
    op.drop_index(op.f('ix_self_assessments_user_id'), table_name='self_assessments')
    op.drop_table('self_assessments')
