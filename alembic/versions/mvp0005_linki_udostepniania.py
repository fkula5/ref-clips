"""Linki udostępniające klipy osobom bez konta (`/s/<kod>`).

Wyłącznie addytywna: tabele `share_links` (skrót kodu, ważność, unieważnienie, licznik wejść) i
`share_link_clips` (klipy w linku z trwałą pozycją; ON DELETE CASCADE po stronie linku i klipu).

Revision ID: mvp0005
Revises: mvp0004
Create Date: 2026-11-09 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0005'
down_revision = 'mvp0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'share_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('view_count', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_share_links_created_by_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_share_links')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_share_links_token_hash')),
    )
    op.create_table(
        'share_link_clips',
        sa.Column('link_id', sa.Integer(), nullable=False),
        sa.Column('clip_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['link_id'], ['share_links.id'], name=op.f('fk_share_link_clips_link_id_share_links'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_share_link_clips_clip_id_clips'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('link_id', 'clip_id', name=op.f('pk_share_link_clips')),
        sa.UniqueConstraint('link_id', 'position', name=op.f('uq_share_link_clips_link_id')),
    )
    op.create_index(op.f('ix_share_link_clips_clip_id'), 'share_link_clips', ['clip_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_share_link_clips_clip_id'), table_name='share_link_clips')
    op.drop_table('share_link_clips')
    op.drop_table('share_links')
