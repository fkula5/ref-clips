"""Comment indexes by clip and match."""
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
