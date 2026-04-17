import threading
from contextlib import contextmanager
import duckdb
import os
from pathlib import Path
from typing import Optional

_conn: Optional[duckdb.DuckDBPyConnection] = None
_lock = threading.Lock()


def _init_connection() -> duckdb.DuckDBPyConnection:
    """Initialize the root DuckDB connection (called once)."""
    global _conn
    if _conn is None:
        db_path = os.getenv("DB_PATH", "./data/stocks.duckdb")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Remove stale lock file left by a crashed process
        pid_lock = Path(db_path + ".lock")
        if pid_lock.exists():
            try:
                pid_lock.unlink()
            except OSError:
                pass

        _conn = duckdb.connect(db_path)
    return _conn


def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Return a thread-safe cursor from the shared DuckDB connection.
    Each call returns a new cursor so concurrent requests don't collide.
    """
    with _lock:
        root = _init_connection()
    return root.cursor()


@contextmanager
def get_cursor():
    """Context manager that yields a DuckDB cursor and closes it on exit."""
    cursor = get_connection()
    try:
        yield cursor
    finally:
        cursor.close()


def close_connection():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
