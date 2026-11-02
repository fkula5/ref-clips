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
    "jobs", "settings",
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
        seed(db)  # powtórne uruchomienie niczego nie dubluje
        assert db.get(Setting, "retention_days").value == "30"
        names = [c.name for c in db.query(Category).order_by(Category.sort)]
        assert len(names) == len(set(names))
    command.downgrade(cfg, "base")
    assert not (EXPECTED_TABLES & set(inspect(create_engine(url)).get_table_names()))


def test_notes_column_migration_keeps_existing_uploads(tmp_path):
    """Migracja mvp0002 dodaje upload_sessions.notes do istniejącej bazy bez utraty danych."""
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
    """Migracja mvp0003 dodaje tylko indeksy komentarzy; dane zostają, a schemat zgadza się z modelami."""
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
