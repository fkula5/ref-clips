"""Upload notes: upload_sessions.notes column."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0002'
down_revision = 'mvp0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('upload_sessions') as batch:
        batch.add_column(sa.Column('notes', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('upload_sessions') as batch:
        batch.drop_column('notes')
