import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

if getattr(sys, "frozen", False):
    _BASE = Path(os.environ.get("APPDATA", Path.home())) / "AutoApply"
else:
    _BASE = Path(__file__).parent.parent

DB_PATH = _BASE / "data" / "autoapply.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)
    # Migrate: add columns added after initial release
    _migrate()


def _migrate():
    with engine.connect() as conn:
        for table, col, typedef in [
            ("jobs",         "extra_data", "TEXT"),
            ("applications", "notes",      "TEXT"),
            ("applications", "viewed",     "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_session():
    with Session(engine) as session:
        yield session
