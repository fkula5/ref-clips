"""Training sets: curated clips with the coach's notes, pinned to training groups."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0009'
down_revision = 'mvp0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'training_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('show_names', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_training_sets_created_by_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_training_sets')),
    )
    op.create_table(
        'training_set_clips',
        sa.Column('set_id', sa.Integer(), nullable=False),
        sa.Column('clip_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['set_id'], ['training_sets.id'],
                                name=op.f('fk_training_set_clips_set_id_training_sets'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_training_set_clips_clip_id_clips'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('set_id', 'clip_id', name=op.f('pk_training_set_clips')),
    )
    op.create_index(op.f('ix_training_set_clips_clip_id'), 'training_set_clips', ['clip_id'], unique=False)
    op.create_table(
        'training_set_groups',
        sa.Column('set_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['set_id'], ['training_sets.id'],
                                name=op.f('fk_training_set_groups_set_id_training_sets'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['training_groups.id'],
                                name=op.f('fk_training_set_groups_group_id_training_groups'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('set_id', 'group_id', name=op.f('pk_training_set_groups')),
    )
    op.create_index(op.f('ix_training_set_groups_group_id'), 'training_set_groups', ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_training_set_groups_group_id'), table_name='training_set_groups')
    op.drop_table('training_set_groups')
    op.drop_index(op.f('ix_training_set_clips_clip_id'), table_name='training_set_clips')
    op.drop_table('training_set_clips')
    op.drop_table('training_sets')
