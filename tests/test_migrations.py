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
