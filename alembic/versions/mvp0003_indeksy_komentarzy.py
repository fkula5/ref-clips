"""Indeksy komentarzy po klipie i meczu (segment 6): lista komentarzy strony i kaskada przy usuwaniu.

Revision ID: mvp0003
Revises: mvp0002
Create Date: 2026-11-02 10:00:00.000000
"""
from alembic import op


revision = 'mvp0003'
down_revision = 'mvp0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f('ix_comments_clip_id'), 'comments', ['clip_id'], unique=False)
    op.create_index(op.f('ix_comments_match_id'), 'comments', ['match_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_comments_match_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_clip_id'), table_name='comments')
