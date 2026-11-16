"""SQLAlchemy engine setup.

SQLite keeps the whole database in one file. Moving to Postgres later only means
passing a different URL to `make_engine`; nothing outside `storage/` would change.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

from immo.paths import db_path
from immo.storage.tables import Base

IN_MEMORY_URL = "sqlite:///:memory:"


def make_engine(url: str | None = None) -> Engine:
    """Create an engine and make sure all tables exist.

    `url=None` uses the SQLite file from `immo.paths.db_path()`.
    """
    if url is None:
        path: Path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"

    kwargs: dict = {}
    if url.startswith("sqlite"):
        # Streamlit runs the script in worker threads; SQLite's default forbids sharing
        # a connection across threads.
        kwargs["connect_args"] = {"check_same_thread": False}
    if url == IN_MEMORY_URL:
        # An in-memory database lives inside ONE connection. StaticPool makes every
        # session reuse that connection; otherwise each session would see an empty DB.
        kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine
