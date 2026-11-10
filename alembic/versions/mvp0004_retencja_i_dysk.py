"""Draft size and rejected uploads."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0004'
down_revision = 'mvp0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('videos') as batch:
        batch.add_column(sa.Column('proxy_bytes', sa.BigInteger(), nullable=True))
    op.create_table(
        'upload_rejections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('free_bytes', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_upload_rejections_user_id_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_rejections')),
    )
    op.create_index(op.f('ix_upload_rejections_created_at'), 'upload_rejections', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_upload_rejections_created_at'), table_name='upload_rejections')
    op.drop_table('upload_rejections')
    with op.batch_alter_table('videos') as batch:
        batch.drop_column('proxy_bytes')
