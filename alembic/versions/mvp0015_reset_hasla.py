"""Throttling table of the self-service password reset (and of unusable /set-password links)."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0015'
down_revision = 'mvp0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'password_reset_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('email_key', sa.String(length=64), nullable=False),
        sa.Column('ip', sa.String(length=64), nullable=False),
        sa.Column('mailed', sa.Boolean(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_requests')),
    )
    with op.batch_alter_table('password_reset_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_password_reset_requests_email_key'), ['email_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_password_reset_requests_ip'), ['ip'], unique=False)
        batch_op.create_index(batch_op.f('ix_password_reset_requests_requested_at'), ['requested_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('password_reset_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_password_reset_requests_requested_at'))
        batch_op.drop_index(batch_op.f('ix_password_reset_requests_ip'))
        batch_op.drop_index(batch_op.f('ix_password_reset_requests_email_key'))

    op.drop_table('password_reset_requests')
