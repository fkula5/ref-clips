"""Notatki przy wgrywaniu: kolumna upload_sessions.notes (segment 4).

Revision ID: mvp0002
Revises: mvp0001
Create Date: 2026-11-01 23:10:00.000000
"""
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
