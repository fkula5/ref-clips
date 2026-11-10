"""Initial MVP schema."""
from alembic import op
import sqlalchemy as sa


revision = 'mvp0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_name', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('aliases', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_custom', sa.Boolean(), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('name', name=op.f('uq_categories_name'))
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('attempted_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_attempts_attempted_at'), ['attempted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_attempts_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_attempts_ip'), ['ip'], unique=False)

    op.create_table('settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_settings'))
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("purpose IN ('activate', 'reset')", name=op.f('ck_invites_purpose_valid')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_invites_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_invites_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invites_token_hash'))
    )
    with op.batch_alter_table('invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invites_user_id'), ['user_id'], unique=False)

    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('level', sa.String(length=100), nullable=False),
    sa.Column('team_a_name', sa.String(length=100), nullable=False),
    sa.Column('team_a_color', sa.String(length=50), nullable=False),
    sa.Column('team_b_name', sa.String(length=100), nullable=False),
    sa.Column('team_b_color', sa.String(length=50), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_matches_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_matches'))
    )
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('user_roles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'coach', 'referee')", name=op.f('ck_user_roles_role_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role', name=op.f('pk_user_roles'))
    )
    op.create_table('match_officials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('function', sa.String(length=2), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=True),
    sa.CheckConstraint("function IN ('CC', 'U1', 'U2')", name=op.f('ck_match_officials_function_valid')),
    sa.CheckConstraint('(user_id IS NOT NULL AND name IS NULL) OR (user_id IS NULL AND name IS NOT NULL)', name=op.f('ck_match_officials_user_or_name')),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_match_officials_match_id_matches'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_match_officials_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_match_officials')),
    sa.UniqueConstraint('match_id', 'function', name=op.f('uq_match_officials_match_id'))
    )
    op.create_table('upload_sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=True),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('offset_bytes', sa.BigInteger(), nullable=False),
    sa.Column('reserved_bytes', sa.BigInteger(), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_upload_sessions_match_id_matches'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_upload_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_sessions'))
    )
    op.create_table('videos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('original_path', sa.String(length=500), nullable=True),
    sa.Column('proxy_path', sa.String(length=500), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('fps', sa.Float(), nullable=True),
    sa.Column('content', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('purged_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_videos_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_videos_match_id_matches'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_videos'))
    )
    op.create_table('clips',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('video_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('official_id', sa.Integer(), nullable=True),
    sa.Column('whole_team', sa.Boolean(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('custom_category', sa.String(length=100), nullable=True),
    sa.Column('time_sec', sa.Float(), nullable=False),
    sa.Column('margin_before', sa.Float(), nullable=False),
    sa.Column('margin_after', sa.Float(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('described_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('clip_path', sa.String(length=500), nullable=True),
    sa.Column('clip_version', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_clips_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_clips_category_id_categories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_clips_match_id_matches'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['official_id'], ['match_officials.id'], name=op.f('fk_clips_official_id_match_officials'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['video_id'], ['videos.id'], name=op.f('fk_clips_video_id_videos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clips'))
    )
    op.create_table('period_marks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('video_id', sa.Integer(), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('time_sec', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['video_id'], ['videos.id'], name=op.f('fk_period_marks_video_id_videos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_period_marks')),
    sa.UniqueConstraint('video_id', 'period', name=op.f('uq_period_marks_video_id'))
    )
    op.create_table('comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=True),
    sa.Column('clip_id', sa.Integer(), nullable=True),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('edited_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('(match_id IS NOT NULL AND clip_id IS NULL) OR (match_id IS NULL AND clip_id IS NOT NULL)', name=op.f('ck_comments_match_or_clip')),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_comments_author_id_users')),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_comments_clip_id_clips'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_comments_match_id_matches'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comments'))
    )
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('video_id', sa.Integer(), nullable=True),
    sa.Column('clip_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_jobs_clip_id_clips'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['video_id'], ['videos.id'], name=op.f('fk_jobs_video_id_videos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_table('ratings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('clip_id', sa.Integer(), nullable=False),
    sa.Column('coach_id', sa.Integer(), nullable=False),
    sa.Column('verdict', sa.String(length=20), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("verdict IN ('correct', 'incorrect', 'debatable')", name=op.f('ck_ratings_verdict_valid')),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_ratings_clip_id_clips'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['coach_id'], ['users.id'], name=op.f('fk_ratings_coach_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ratings')),
    sa.UniqueConstraint('clip_id', 'coach_id', name=op.f('uq_ratings_clip_id'))
    )


def downgrade() -> None:
    op.drop_table('ratings')
    op.drop_table('jobs')
    op.drop_table('comments')
    op.drop_table('period_marks')
    op.drop_table('clips')
    op.drop_table('videos')
    op.drop_table('upload_sessions')
    op.drop_table('match_officials')
    op.drop_table('user_roles')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))

    op.drop_table('sessions')
    op.drop_table('matches')
    with op.batch_alter_table('invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invites_user_id'))

    op.drop_table('invites')
    op.drop_table('users')
    op.drop_table('settings')
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_login_attempts_ip'))
        batch_op.drop_index(batch_op.f('ix_login_attempts_email'))
        batch_op.drop_index(batch_op.f('ix_login_attempts_attempted_at'))

    op.drop_table('login_attempts')
    op.drop_table('categories')
