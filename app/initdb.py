from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.models import User
from app.seed import seed


def init_db() -> None:
    cfg = Config(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    init_db()
    print("Baza gotowa:", config.DATABASE_URL)
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            print("Brak kont — utwórz administratora: python -m app.create_admin")
