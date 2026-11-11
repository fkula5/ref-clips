"""Training groups; notifications can point at a group instead of a match; clips record who described them."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0008'
down_revision = 'mvp0007'
branch_labels = None
depends_on = None

OLD_KINDS = "kind IN ('rating', 'rating_changed', 'clip_comment', 'match_comment', 'sheet_published')"
NEW_KINDS = ("kind IN ('rating', 'rating_changed', 'clip_comment', 'match_comment', 'sheet_published', "
             "'group_added')")


def upgrade() -> None:
    op.create_table(
        'training_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_training_groups_created_by_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_training_groups')),
    )
    op.create_table(
        'group_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.CheckConstraint("role IN ('coach', 'referee')", name=op.f('ck_group_members_role_valid')),
        sa.ForeignKeyConstraint(['group_id'], ['training_groups.id'],
                                name=op.f('fk_group_members_group_id_training_groups'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_group_members_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_group_members')),
        sa.UniqueConstraint('group_id', 'user_id', name=op.f('uq_group_members_group_id')),
    )
    op.create_index(op.f('ix_group_members_user_id'), 'group_members', ['user_id'], unique=False)

    with op.batch_alter_table('notifications') as batch:
        batch.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch.alter_column('match_id', existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint(op.f('ck_notifications_kind_valid'), type_='check')
        batch.create_check_constraint(op.f('ck_notifications_kind_valid'), NEW_KINDS)
        batch.create_foreign_key(op.f('fk_notifications_group_id_training_groups'), 'training_groups',
                                 ['group_id'], ['id'], ondelete='CASCADE')
        batch.create_index(op.f('ix_notifications_group_id'), ['group_id'], unique=False)

    with op.batch_alter_table('clips') as batch:
        batch.add_column(sa.Column('described_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(op.f('fk_clips_described_by_id_users'), 'users', ['described_by_id'], ['id'],
                                 ondelete='SET NULL')
        batch.create_index(op.f('ix_clips_described_by_id'), ['described_by_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('clips') as batch:
        batch.drop_index(op.f('ix_clips_described_by_id'))
        batch.drop_constraint(op.f('fk_clips_described_by_id_users'), type_='foreignkey')
        batch.drop_column('described_by_id')
    op.execute("DELETE FROM notifications WHERE kind = 'group_added'")
    with op.batch_alter_table('notifications') as batch:
        batch.drop_index(op.f('ix_notifications_group_id'))
        batch.drop_constraint(op.f('fk_notifications_group_id_training_groups'), type_='foreignkey')
        batch.drop_constraint(op.f('ck_notifications_kind_valid'), type_='check')
        batch.create_check_constraint(op.f('ck_notifications_kind_valid'), OLD_KINDS)
        batch.alter_column('match_id', existing_type=sa.Integer(), nullable=False)
        batch.drop_column('group_id')
    op.drop_index(op.f('ix_group_members_user_id'), table_name='group_members')
    op.drop_table('group_members')
    op.drop_table('training_groups')
