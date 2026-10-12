"""Persistence layer — one SQLAlchemy engine PER BOARD, each on its own SQLite file.

Multi-board: instead of a single global engine, engines are created lazily and cached by
board key (see app/projects.py / projects.yaml). Each board's data lives in its own file
under DATA_DIR (e.g. data/nexus.db, data/sethi.db), so boards can never be confused. The
FastAPI dependencies resolve the board from the `/api/{project}/...` path and yield a session
bound to that board's engine.
"""
import os
from collections.abc import Generator

from fastapi import HTTPException, Path
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import ProjectConfig, get_settings


class Base(DeclarativeBase):
    pass


# Board key -> (engine, sessionmaker). Built on first use; cleared on config reload so a
# changed db_file in projects.yaml takes effect without a restart.
_engines: dict[str, tuple[Engine, sessionmaker]] = {}


def _db_url(db_file: str) -> str:
    data_dir = get_settings().data_dir
    os.makedirs(data_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(data_dir, db_file)}"


def get_engine(key: str, db_file: str) -> tuple[Engine, sessionmaker]:
    """Engine + sessionmaker for a board, creating (and migrating) its DB on first use."""
    cached = _engines.get(key)
    if cached is not None:
        return cached
    # check_same_thread=False is required for SQLite under FastAPI's threaded workers.
    engine = create_engine(_db_url(db_file), connect_args={"check_same_thread": False})
    # Import models so they're registered on Base before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_columns(engine)
    maker = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    _engines[key] = (engine, maker)
    return _engines[key]


# The merged-PR store is ONE cross-repo DB on its own declarative Base (see app/pr_models.py
# for why), so it gets its own cache instead of a board entry. Keyed by db_file so a changed
# pr_db_file takes effect exactly like a changed board db_file does.
_pr_engines: dict[str, tuple[Engine, sessionmaker]] = {}


def get_pr_engine() -> tuple[Engine, sessionmaker]:
    """Engine + sessionmaker for the merged-PR store, creating its DB on first use."""
    db_file = get_settings().pr_db_file
    cached = _pr_engines.get(db_file)
    if cached is not None:
        return cached
    engine = create_engine(_db_url(db_file), connect_args={"check_same_thread": False})
    # Imported here so the models are registered on PrBase before create_all.
    from app.pr_models import PrBase

    PrBase.metadata.create_all(bind=engine)
    _pr_engines[db_file] = (engine, sessionmaker(bind=engine, autocommit=False, autoflush=False))
    return _pr_engines[db_file]


def dispose_engines() -> None:
    """Drop all cached engines (used by POST /api/config/reload after the registry changes)."""
    for engine, _ in list(_engines.values()) + list(_pr_engines.values()):
        engine.dispose()
    _engines.clear()
    _pr_engines.clear()


def init_db() -> None:
    """Create + migrate every configured board's DB on startup."""
    from app.projects import get_registry

    for entry in get_registry():
        get_engine(entry.key, entry.db_file)


# create_all() only creates *missing tables* — it never adds new columns to a table
# that already exists. With no migration tool in use, we patch in additive columns
# here so an existing DB self-heals on startup. Each entry is idempotent.
_ADDED_COLUMNS = {
    "sync_logs": {"transitions_count": "INTEGER DEFAULT 0"},
    "issues": {"epic_key": "VARCHAR", "epic_name": "VARCHAR"},
    "daily_snapshots": {
        "epic_key": "VARCHAR", "epic_name": "VARCHAR",
        "sprint_name": "VARCHAR", "sprint_start": "DATE", "sprint_end": "DATE",
        "reconstructed": "BOOLEAN DEFAULT 0",
    },
}


def _migrate_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all already built it with the column
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _resolve_entry(project: str):
    from app.projects import get_project_entry

    entry = get_project_entry(project)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown project '{project}'.")
    return entry


def get_db(project: str = Path(..., description="Board key, e.g. NEX.")) -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session bound to the board's own DB, always closed.

    The board key comes from the `/api/{project}/...` path prefix. Unknown key → 404 before
    any DB file is touched.
    """
    entry = _resolve_entry(project)
    _, maker = get_engine(entry.key, entry.db_file)
    db = maker()
    try:
        yield db
    finally:
        db.close()


def get_cfg(project: str = Path(..., description="Board key, e.g. NEX.")) -> ProjectConfig:
    """FastAPI dependency — the resolved ProjectConfig (shared Settings + this board's block)."""
    from app.projects import resolve_cfg

    cfg = resolve_cfg(project)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown project '{project}'.")
    return cfg
