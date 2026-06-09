from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from docpilot.db.schema import Base, EMBEDDING_DIM
from docpilot.exceptions import SearchError

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_backend: str = "sqlite"

def _default_sqlite_url() -> str:
    from pathlib import Path
    return "sqlite:///" + str(Path.home() / "docpilot.db")


def init(database_url: str | None = None) -> None:
    """
    Initialize the database engine.

    Defaults to ~/docpilot.db (absolute path) when no URL is provided.
    Pass a PostgreSQL URL or set DOCPILOT_DATABASE_URL to use PostgreSQL + pgvector.
    """
    global _engine, _SessionLocal, _backend

    url = database_url or os.environ.get("DOCPILOT_DATABASE_URL") or _default_sqlite_url()
    _backend = "sqlite" if url.startswith("sqlite") else "postgresql"

    _engine = create_engine(url, pool_pre_ping=(_backend != "sqlite"))

    if _backend == "sqlite":
        @event.listens_for(_engine, "connect")
        def _load_sqlite_vec(dbapi_connection, _):
            # SQLite는 기본적으로 외래키 제약을 비활성화함.
            # ON DELETE CASCADE가 실제로 동작하려면 연결마다 활성화 필요.
            dbapi_connection.execute("PRAGMA foreign_keys = ON")
            try:
                import sqlite_vec
                dbapi_connection.enable_load_extension(True)
                sqlite_vec.load(dbapi_connection)
                dbapi_connection.enable_load_extension(False)
            except ImportError:
                pass  # sqlite-vec not installed; vector search unavailable

    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def create_tables() -> None:
    """Create all tables. Sets up sqlite-vec virtual table or pgvector DDL."""
    engine = _get_engine()
    Base.metadata.create_all(engine)

    if _backend == "sqlite":
        with engine.begin() as conn:
            conn.execute(text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
                f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{EMBEDDING_DIM}])"
            ))
            # vec_chunks는 가상 테이블이라 FK CASCADE가 적용되지 않음.
            # chunks 행 삭제 시 대응하는 vec_chunks 행을 트리거로 제거.
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_delete_vec_on_chunk_delete
                AFTER DELETE ON chunks
                BEGIN
                    DELETE FROM vec_chunks WHERE chunk_id = OLD.id;
                END
            """))
    else:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE chunks "
                f"ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})"
            ))


def is_sqlite() -> bool:
    return _backend == "sqlite"


@contextmanager
def session() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    factory = _get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_engine() -> Engine:
    if _engine is None:
        raise SearchError("DB not initialized — call client.init() first")
    return _engine


def _get_session_factory() -> sessionmaker:
    if _SessionLocal is None:
        raise SearchError("DB not initialized — call client.init() first")
    return _SessionLocal
