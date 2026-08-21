import duckdb
import os
import time
from pathlib import Path


# DuckDB allows a single read-write connection across processes. The sandbox
# holds a read-write connection during node execution while the backend opens
# short-lived read-only connections (catalog, auto-install, output resolution).
# Those opens can briefly collide and raise a "Conflicting lock"/"Could not set
# lock" error. Rather than surface that as a flaky node failure, retry the open
# with a short backoff — the conflicting connection is always released quickly.
_LOCK_RETRY_ATTEMPTS = 12
_LOCK_RETRY_BASE_DELAY = 0.05  # seconds; total worst-case wait ~3.9s


def _is_lock_conflict(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "lock" in msg
        or "conflicting" in msg
        or "resource temporarily unavailable" in msg
    )


def _connect_with_retry(path: str, *, read_only: bool = False):
    """Open a DuckDB connection, retrying transient cross-process lock conflicts."""
    last_exc: Exception | None = None
    for attempt in range(_LOCK_RETRY_ATTEMPTS):
        try:
            return duckdb.connect(path, read_only=read_only)
        except Exception as exc:  # noqa: BLE001 - re-raised below if not a lock conflict
            if not _is_lock_conflict(exc):
                raise
            last_exc = exc
            time.sleep(_LOCK_RETRY_BASE_DELAY * (attempt + 1))
    assert last_exc is not None
    raise last_exc


class _NonClosingConn:
    """
    Wraps a DuckDB connection so that close() is a no-op.

    parsers.py calls con.close() after every save/load. With a shared persistent
    connection those calls must not actually close it, or the next call would
    fail. All other attribute access is forwarded transparently to the real
    connection via __getattr__.
    """
    __slots__ = ('_con',)

    def __init__(self, con):
        object.__setattr__(self, '_con', con)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_con'), name)

    def close(self):
        pass  # intentional no-op — the real connection stays open


_connection: '_NonClosingConn | None' = None
_connection_path: str | None = None
_initialized: bool = False


def _ensure_data_dir() -> Path:
    """
    Resolve the data directory and ensure it exists on disk.

    If the directory was missing — e.g., wiped by a parallel pytest teardown
    or ``scripts/clean.sh`` — any cached connection is now pointing at a
    vanished path, so close it before recreating the directory. The next
    ``get_connection()`` will reopen against a fresh file.
    """
    global _connection
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_data = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    db_dir = (launch_dir / shared_data).resolve()
    if not db_dir.exists():
        if _connection is not None:
            release_connection()
        os.makedirs(db_dir, exist_ok=True)
    return db_dir


def get_db_path() -> str:
    return str(_ensure_data_dir() / "curio_data.duckdb")


def get_connection() -> '_NonClosingConn':
    """
    Return the shared persistent DuckDB connection for this process.
    Opens it on first call; subsequent calls return the same object.
    close() on the returned wrapper is a no-op.

    Reopens when ``CURIO_LAUNCH_CWD`` / ``CURIO_SHARED_DATA`` change — e.g.
    pytest switches per-test workspaces while reusing the same process.
    """
    global _connection, _connection_path
    path = get_db_path()
    if _connection is not None and _connection_path != path:
        release_connection()
    if _connection is None:
        _connection = _NonClosingConn(_connect_with_retry(path))
        _connection_path = path
    return _connection


def get_read_connection():
    """
    Return a connection suitable for reading artifacts.

    Sandbox process: reuses the persistent R/W connection (_connection is set).
      close() on the returned _NonClosingConn is a no-op — the connection stays open.
    Backend process: opens a fresh read-only connection (_connection is None).
      close() on the returned raw connection actually closes it.
    """
    if _connection is not None:
        return _connection
    return _connect_with_retry(get_db_path(), read_only=True)


def release_connection() -> None:
    """
    Actually close the persistent connection and reset state.
    Call this when the current process is done with DuckDB and another
    process (e.g., the sandbox subprocess) needs write access to the file.
    """
    global _connection, _connection_path, _initialized
    if _connection is not None:
        object.__getattribute__(_connection, '_con').close()
        _connection = None
    _connection_path = None
    _initialized = False


def init_db() -> None:
    """
    Create the artifacts table if it does not exist.
    Runs the DDL only once per process; subsequent calls are instant no-ops.
    """
    global _initialized
    # Re-assert the data dir on every call. _ensure_data_dir resets the
    # cache via release_connection() if the dir was wiped, so a stale
    # _initialized=True after a teardown will fall through to re-DDL.
    _ensure_data_dir()
    if _initialized:
        return
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id          VARCHAR PRIMARY KEY,
            node_id     VARCHAR,
            kind        VARCHAR NOT NULL,
            session_id  VARCHAR,
            value_int   BIGINT,
            value_float DOUBLE,
            value_str   VARCHAR,
            value_json  JSON,
            blob        BLOB
        )
    """)
    # Migrate existing tables that pre-date the session_id column.
    existing = {row[0] for row in con.execute("DESCRIBE artifacts").fetchall()}
    if "session_id" not in existing:
        con.execute("ALTER TABLE artifacts ADD COLUMN session_id VARCHAR")
    _initialized = True
