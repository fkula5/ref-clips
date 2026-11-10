"""In-app notifications."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0007'
down_revision = 'mvp0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('clip_id', sa.Integer(), nullable=True),
        sa.Column('sheet_id', sa.Integer(), nullable=True),
        sa.Column('verdict', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('rating', 'rating_changed', 'clip_comment', 'match_comment', 'sheet_published')",
            name=op.f('ck_notifications_kind_valid')),
        sa.CheckConstraint("verdict IS NULL OR verdict IN ('correct', 'incorrect', 'debatable')",
                           name=op.f('ck_notifications_verdict_valid')),
        sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], name=op.f('fk_notifications_recipient_id_users'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_notifications_actor_id_users'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_notifications_match_id_matches'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_notifications_clip_id_clips'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sheet_id'], ['sheets.id'], name=op.f('fk_notifications_sheet_id_sheets'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    )
    op.create_index('ix_notifications_unread', 'notifications', ['recipient_id', 'read_at'], unique=False)
    op.create_index(op.f('ix_notifications_match_id'), 'notifications', ['match_id'], unique=False)
    op.create_index(op.f('ix_notifications_clip_id'), 'notifications', ['clip_id'], unique=False)
    op.create_index(op.f('ix_notifications_sheet_id'), 'notifications', ['sheet_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_sheet_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_clip_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_match_id'), table_name='notifications')
    op.drop_index('ix_notifications_unread', table_name='notifications')
    op.drop_table('notifications')
