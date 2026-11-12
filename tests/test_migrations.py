import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import config
from app.db import Base

EXPECTED_TABLES = {
    "users", "user_roles", "sessions", "invites", "login_attempts", "matches", "match_officials",
    "videos", "upload_sessions", "period_marks", "categories", "clips", "ratings", "comments",
    "jobs", "settings", "upload_rejections", "share_links", "share_link_clips",
    "sheet_elements", "sheets", "sheet_columns", "sheet_rows", "sheet_cells", "notifications",
    "training_groups", "group_members", "training_sets", "training_set_clips", "training_set_groups",
    "match_scoresheets",
}


def _config(url):
    cfg = Config(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_config(url), "head")
    engine = create_engine(url)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migration_downgrade_and_seed(tmp_path):
    from sqlalchemy.orm import Session

    from app.models import Category, Setting
    from app.seed import seed

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with Session(engine) as db:
        seed(db)
        seed(db)
        assert db.get(Setting, "retention_days").value == "30"
        names = [c.name for c in db.query(Category).order_by(Category.sort)]
        assert len(names) == len(set(names))
    command.downgrade(cfg, "base")
    assert not (EXPECTED_TABLES & set(inspect(create_engine(url)).get_table_names()))


def test_notes_column_migration_keeps_existing_uploads(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0001")
    engine = create_engine(url)
    assert "notes" not in {c["name"] for c in inspect(engine).get_columns("upload_sessions")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text(
            "INSERT INTO upload_sessions (id, user_id, filename, size_bytes, offset_bytes, reserved_bytes, "
            "metadata_json) VALUES ('abc', 1, 'mecz.mp4', 10, 5, 0, '{}')"))
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, offset_bytes, notes FROM upload_sessions")).one()
        assert tuple(row) == ("abc", 5, "")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(cfg, "mvp0001")
    assert "notes" not in {c["name"] for c in inspect(create_engine(url)).get_columns("upload_sessions")}


def test_comment_indexes_migration_is_additive(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0002")
    engine = create_engine(url)
    assert not {"ix_comments_clip_id", "ix_comments_match_id"} & {i["name"] for i in inspect(engine).get_indexes("comments")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
            "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO comments (match_id, author_id, body) VALUES (1, 1, 'Zostaje')"))
    command.upgrade(cfg, "head")
    assert {"ix_comments_clip_id", "ix_comments_match_id"} <= {i["name"] for i in inspect(engine).get_indexes("comments")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT body FROM comments")).scalar() == "Zostaje"
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(cfg, "mvp0002")
    assert "ix_comments_clip_id" not in {i["name"] for i in inspect(create_engine(url)).get_indexes("comments")}


def test_retention_migration_is_additive(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0003")
    engine = create_engine(url)
    assert "proxy_bytes" not in {c["name"] for c in inspect(engine).get_columns("videos")}
    assert "upload_rejections" not in inspect(engine).get_table_names()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
            "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO videos (id, match_id, size_bytes, content, status, label, original_filename) "
                          "VALUES (1, 1, 123, 'full', 'ready', 'Całość', 'm.mp4')"))
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        assert tuple(conn.execute(text("SELECT size_bytes, proxy_bytes, label FROM videos")).one()) == (123, None, "Całość")
        conn.execute(text("INSERT INTO upload_rejections (created_at, user_id, filename, size_bytes, free_bytes) "
                          "VALUES ('2026-11-02 10:00:00', 1, 'a.mp4', 10, 5)"))
        assert conn.execute(text("SELECT filename FROM upload_rejections")).scalar() == "a.mp4"
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(cfg, "mvp0003")
    assert "upload_rejections" not in inspect(create_engine(url)).get_table_names()
    assert "proxy_bytes" not in {c["name"] for c in inspect(create_engine(url)).get_columns("videos")}


def test_share_links_migration_is_additive(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0004")
    engine = create_engine(url)
    assert "share_links" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO videos (id, match_id, size_bytes, content, status, label, original_filename) "
                          "VALUES (1, 1, 1, 'full', 'ready', '', '')"))
        for i in (1, 2):
            conn.execute(text("INSERT INTO clips (id, match_id, video_id, whole_team, time_sec, margin_before, margin_after, "
                              "description, status, clip_version) VALUES (:i, 1, 1, 0, 10, 15, 15, '', 'cut', 1)"), {"i": i})
        conn.execute(text("INSERT INTO share_links (id, token_hash, created_by, expires_at) VALUES (1, 'h', 1, '2026-12-01')"))
        conn.execute(text("INSERT INTO share_link_clips VALUES (1, 1, 1), (1, 2, 2)"))
        assert conn.execute(text("SELECT view_count FROM share_links")).scalar() == 0
        conn.execute(text("DELETE FROM clips WHERE id = 2"))
        assert conn.execute(text("SELECT clip_id FROM share_link_clips")).scalars().all() == [1]
        conn.execute(text("DELETE FROM users WHERE id = 1"))
        assert conn.execute(text("SELECT created_by FROM share_links")).one()[0] is None
        conn.execute(text("DELETE FROM share_links"))
        assert conn.execute(text("SELECT count(*) FROM share_link_clips")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM clips")).scalar() == 1
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(cfg, "mvp0004")
    assert not {"share_links", "share_link_clips"} & set(inspect(create_engine(url)).get_table_names())


def test_sheet_migration_seeds_elements_and_cascades(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0005")
    assert "sheets" not in inspect(create_engine(url)).get_table_names()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        names = conn.execute(text("SELECT name FROM sheet_elements WHERE is_active ORDER BY sort")).scalars().all()
        assert names[:3] == ["Obowiązki przedmeczowe", "Przygotowanie fizyczne", "Mechanika"]
        assert names[-1] == "Jakość pracy" and len(names) == 10
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO sheets (id, match_id, coach_id) VALUES (1, 1, 1)"))
        conn.execute(text("INSERT INTO sheet_columns (id, sheet_id, position, function, official_name) VALUES (1, 1, 0, 'CC', 'X')"))
        conn.execute(text("INSERT INTO sheet_rows (id, sheet_id, position, name) VALUES (1, 1, 0, 'Mechanika')"))
        conn.execute(text("INSERT INTO sheet_cells (row_id, column_id, text) VALUES (1, 1, 'ok')"))
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    for sql in ("INSERT INTO sheets (match_id, coach_id) VALUES (1, 1)",  # second sheet
                "UPDATE sheets SET status = 'published'",  # no difficulty
                "UPDATE sheets SET difficulty = 'bardzo'",
                "DELETE FROM users WHERE id = 1"):  # author FK: no cascade
        with engine.begin() as conn, pytest.raises(Exception):
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text(sql))
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM matches WHERE id = 1"))
        for table in ("sheets", "sheet_columns", "sheet_rows", "sheet_cells"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
        assert conn.execute(text("SELECT count(*) FROM sheet_elements")).scalar() == 10
    command.downgrade(cfg, "mvp0005")
    assert not {"sheets", "sheet_elements", "sheet_cells"} & set(inspect(create_engine(url)).get_table_names())


def test_notifications_migration_is_additive_and_cascades(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0006")
    assert "notifications" not in inspect(create_engine(url)).get_table_names()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    assert {"ix_notifications_unread", "ix_notifications_clip_id"} <= {i["name"] for i in inspect(engine).get_indexes("notifications")}
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        for i in (1, 2):
            conn.execute(text(f"INSERT INTO users (id, email, name, is_active) VALUES ({i}, 'u{i}@b.pl', 'U', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO videos (id, match_id, size_bytes, content, status, label, original_filename) "
                          "VALUES (1, 1, 1, 'full', 'ready', '', '')"))
        conn.execute(text("INSERT INTO clips (id, match_id, video_id, whole_team, time_sec, margin_before, margin_after, "
                          "description, status, clip_version) VALUES (1, 1, 1, 0, 10, 15, 15, '', 'cut', 1)"))
        conn.execute(text("INSERT INTO notifications (recipient_id, kind, actor_id, match_id, clip_id, verdict) "
                          "VALUES (1, 'rating', 2, 1, 1, 'correct'), (1, 'match_comment', 2, 1, NULL, NULL)"))
        assert conn.execute(text("SELECT count(*) FROM notifications WHERE read_at IS NULL")).scalar() == 2
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    for sql in ("INSERT INTO notifications (recipient_id, kind, match_id) VALUES (1, 'bogus', 1)",
                "INSERT INTO notifications (recipient_id, kind, match_id, verdict) VALUES (1, 'rating', 1, 'bogus')"):
        with engine.begin() as conn, pytest.raises(Exception):
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text(sql))
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM users WHERE id = 2"))
        assert conn.execute(text("SELECT count(*) FROM notifications WHERE actor_id IS NULL")).scalar() == 2
        conn.execute(text("DELETE FROM clips"))
        assert conn.execute(text("SELECT kind FROM notifications")).scalars().all() == ["match_comment"]
        conn.execute(text("DELETE FROM users WHERE id = 1"))
        assert conn.execute(text("SELECT count(*) FROM notifications")).scalar() == 0
    command.downgrade(cfg, "mvp0006")
    assert "notifications" not in inspect(create_engine(url)).get_table_names()


def test_groups_migration_keeps_notifications_and_cascades_memberships(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0007")
    engine = create_engine(url)
    with engine.begin() as conn:
        for i in (1, 2):
            conn.execute(text(f"INSERT INTO users (id, email, name, is_active) VALUES ({i}, 'u{i}@b.pl', 'U', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO notifications (recipient_id, kind, actor_id, match_id) VALUES (1, 'match_comment', 2, 1)"))
        conn.execute(text("INSERT INTO videos (id, match_id, label, original_filename, size_bytes, content, status) VALUES (1, 1, '', 'a.mp4', 0, 'full', 'ready')"))
        conn.execute(text("INSERT INTO clips (id, match_id, video_id, author_id, whole_team, time_sec, margin_before, "
                          "margin_after, description, described_at, status, clip_version) "
                          "VALUES (1, 1, 1, 1, 0, 5, 15, 15, '', '2026-10-29 12:00:00', 'new', 0)"))
    command.upgrade(cfg, "head")
    assert {"training_groups", "group_members"} <= set(inspect(engine).get_table_names())
    assert "ix_group_members_user_id" in {i["name"] for i in inspect(engine).get_indexes("group_members")}
    assert "ix_clips_described_by_id" in {i["name"] for i in inspect(engine).get_indexes("clips")}
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        assert conn.execute(text("SELECT described_by_id FROM clips")).scalar() is None
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (3, 'u3@b.pl', 'U', 1)"))
        conn.execute(text("UPDATE clips SET described_by_id = 3"))
        assert conn.execute(text("SELECT kind, match_id, group_id FROM notifications")).one() == ("match_comment", 1, None)
        conn.execute(text("INSERT INTO training_groups (id, name) VALUES (1, 'A')"))
        conn.execute(text("INSERT INTO group_members (group_id, user_id, role) VALUES (1, 1, 'coach'), (1, 2, 'referee')"))
        conn.execute(text("INSERT INTO notifications (recipient_id, kind, actor_id, group_id) VALUES (2, 'group_added', 1, 1)"))
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    for sql in ("INSERT INTO group_members (group_id, user_id, role) VALUES (1, 1, 'referee')",  # once per account
                "INSERT INTO group_members (group_id, user_id, role) VALUES (1, 2, 'boss')",
                "INSERT INTO notifications (recipient_id, kind) VALUES (1, 'bogus')"):
        with engine.begin() as conn, pytest.raises(Exception):
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text(sql))
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM training_groups"))
        assert conn.execute(text("SELECT count(*) FROM group_members")).scalar() == 0
        assert conn.execute(text("SELECT kind FROM notifications")).scalars().all() == ["match_comment"]
        conn.execute(text("DELETE FROM users WHERE id = 3"))
        assert conn.execute(text("SELECT described_by_id FROM clips")).scalar() is None
        conn.execute(text("INSERT INTO training_groups (id, name) VALUES (2, 'B')"))
        conn.execute(text("INSERT INTO notifications (recipient_id, kind, group_id) VALUES (2, 'group_added', 2)"))
    command.downgrade(cfg, "mvp0007")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert not {"training_groups", "group_members"} & tables
    with create_engine(url).connect() as conn:
        assert conn.execute(text("SELECT kind FROM notifications")).scalars().all() == ["match_comment"]
        assert "group_id" not in {c["name"] for c in inspect(conn).get_columns("notifications")}
        assert "described_by_id" not in {c["name"] for c in inspect(conn).get_columns("clips")}


def test_training_sets_migration_is_additive_and_cascades(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0008")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
        conn.execute(text("INSERT INTO videos (id, match_id, size_bytes, content, status, label, original_filename) "
                          "VALUES (1, 1, 1, 'full', 'ready', '', '')"))
        for i in (1, 2):
            conn.execute(text("INSERT INTO clips (id, match_id, video_id, whole_team, time_sec, margin_before, margin_after, "
                              "description, status, clip_version) VALUES (:i, 1, 1, 0, 10, 15, 15, 'Opis', 'cut', 1)"), {"i": i})
        conn.execute(text("INSERT INTO training_groups (id, name) VALUES (1, 'G')"))
    assert not {"training_sets", "training_set_clips", "training_set_groups"} & set(inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert "ix_training_set_clips_clip_id" in {i["name"] for i in inspect(create_engine(url)).get_indexes("training_set_clips")}
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        assert conn.execute(text("SELECT description FROM clips WHERE id = 1")).scalar() == "Opis"  # old tables untouched
        conn.execute(text("INSERT INTO training_sets (id, name, created_by) VALUES (1, 'Zestaw', 1)"))
        assert tuple(conn.execute(text("SELECT description, show_names FROM training_sets")).one()) == ("", 0)
        conn.execute(text("INSERT INTO training_set_clips (set_id, clip_id, position) VALUES (1, 1, 1), (1, 2, 2)"))
        conn.execute(text("INSERT INTO training_set_groups (set_id, group_id) VALUES (1, 1)"))
        assert conn.execute(text("SELECT note FROM training_set_clips WHERE clip_id = 1")).scalar() == ""
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with engine.begin() as conn, pytest.raises(Exception):  # a clip is in a set at most once
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("INSERT INTO training_set_clips (set_id, clip_id, position) VALUES (1, 1, 3)"))
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM clips WHERE id = 2"))
        assert conn.execute(text("SELECT clip_id FROM training_set_clips")).scalars().all() == [1]
        conn.execute(text("DELETE FROM matches"))  # takes its clips along
        assert conn.execute(text("SELECT count(*) FROM training_set_clips")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM training_sets")).scalar() == 1
        conn.execute(text("DELETE FROM training_groups"))
        assert conn.execute(text("SELECT count(*) FROM training_set_groups")).scalar() == 0
        conn.execute(text("DELETE FROM users"))
        assert conn.execute(text("SELECT created_by FROM training_sets")).scalar() is None
    command.downgrade(cfg, "mvp0008")
    assert not {"training_sets", "training_set_clips", "training_set_groups"} & set(inspect(create_engine(url)).get_table_names())
    assert {"training_groups", "clips"} <= set(inspect(create_engine(url)).get_table_names())


def test_scoresheets_migration_is_additive_and_cascades(tmp_path):
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "mvp0009")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, name, is_active) VALUES (1, 'a@b.pl', 'A', 1)"))
        conn.execute(text("INSERT INTO matches (id, date, level, team_a_name, team_a_color, team_b_name, team_b_color) "
                          "VALUES (1, '2026-10-28', '', '', '', '', '')"))
    assert "match_scoresheets" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    assert "ix_match_scoresheets_match_id" in {i["name"] for i in inspect(create_engine(url)).get_indexes("match_scoresheets")}
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        assert conn.execute(text("SELECT count(*) FROM matches")).scalar() == 1  # old tables untouched
        conn.execute(text("INSERT INTO match_scoresheets (match_id, path, original_filename, content_type, size_bytes, uploaded_by) "
                          "VALUES (1, 'scoresheets/x.pdf', 'p.pdf', 'application/pdf', 10, 1)"))
        assert conn.execute(text("SELECT created_at FROM match_scoresheets")).scalar() is not None
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM users"))
        assert conn.execute(text("SELECT uploaded_by FROM match_scoresheets")).scalar() is None
        conn.execute(text("DELETE FROM matches"))
        assert conn.execute(text("SELECT count(*) FROM match_scoresheets")).scalar() == 0
    command.downgrade(cfg, "mvp0009")
    assert "match_scoresheets" not in set(inspect(create_engine(url)).get_table_names())
    assert {"training_sets", "matches"} <= set(inspect(create_engine(url)).get_table_names())
