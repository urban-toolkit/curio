import contextlib
import duckdb
import os
import threading
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
    """True when *exc* is cross-process contention rather than a real fault.

    The wording is platform-specific, and matching only the POSIX phrasing is
    not enough. POSIX/DuckDB says "Could not set lock" / "Conflicting lock is
    held". **Windows** raises a sharing violation whose message never contains
    the word "lock" at all::

        IO Error: Cannot open file "...curio_data.duckdb": The process cannot
        access the file because it is being used by another process.
        File is already open in <python.exe> (PID 1234)

    Missing that phrasing made ``_connect_with_retry`` re-raise on the first
    attempt, so the retry below never engaged on Windows and a transient
    collision with a backend read-only open failed the whole node. Both Windows
    signatures are contention-specific, so matching them cannot swallow a
    genuine corruption or permission fault.
    """
    msg = str(exc).lower()
    return (
        "lock" in msg
        or "conflicting" in msg
        or "resource temporarily unavailable" in msg
        or "being used by another process" in msg
        or "already open in" in msg
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

# The sandbox serves requests on threads, and every execution path releases the
# shared connection when it finishes (see release_connection). Without the two
# below, whichever request finished first closed the connection out from under
# the ones still running: concurrent Autark data loads failed with "Connection
# already closed!" mid-INSERT, and two threads racing init_db's migration
# produced "Column with name session_id". Both were reproduced by the stress
# tiers at ten users.
#
# ``_in_use`` counts the requests currently holding the connection open via
# ``connection_in_use``; ``_close_pending`` remembers that somebody asked for
# the close that had to be deferred.
_state_lock = threading.RLock()
_in_use: int = 0
_close_pending: bool = False

# True once this process has opened the read-write connection, i.e. it is the
# sandbox rather than the backend. DuckDB refuses to open the same file
# read-only in a process that already holds it read-write ("Can't open a
# connection to same database file with a different configuration"), so the
# read path has to know which side it is on. Inferring it from "is the shared
# connection open right now" is not enough: between a release and the next
# open there is a window where the sandbox looks like the backend, and a read
# arriving in that window took out a read-only handle that then blocked the
# next write.
_writer_process: bool = False

# DuckDB's Python client is explicit that concurrent work needs a cursor per
# thread: several threads sharing one connection object share its transaction
# state, and a statement can then run inside a transaction another thread
# opened. That is not a crash, which is what made it hard to see -- it is a
# stale read. Under the stress tiers a node would be handed "No artifact with
# id X" for a row that was already committed and is still in the database
# afterwards.
#
# ``con.cursor()`` is a duplicate over the same database instance, so the
# cursors share the data and the file handle while each keeps its own
# transaction. ``_cursor_generation`` invalidates the per-thread cache when
# the master is closed, so a thread that outlives a release does not hold a
# cursor on a dead connection.
_thread_state = threading.local()
_cursor_generation: int = 0


@contextlib.contextmanager
def connection_in_use():
    """Hold the shared connection open for the duration of one request.

    Wrap any handler that touches DuckDB. A ``release_connection()`` from
    another thread while this is held is remembered and carried out when the
    last holder leaves -- so the cross-process contract still holds (the
    sandbox does not keep the write handle open between requests) without a
    request losing its connection mid-query.
    """
    global _in_use
    with _state_lock:
        _in_use += 1
    try:
        yield
    finally:
        with _state_lock:
            _in_use -= 1
            if _in_use == 0 and _close_pending:
                _close_now()


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


def _thread_cursor(master: '_NonClosingConn') -> '_NonClosingConn':
    """This thread's cursor over *master*, created on first use.

    Callers get something that behaves like the connection and whose close()
    is a no-op, exactly as before; what changed is that two threads no longer
    share one transaction context.
    """
    cursor = getattr(_thread_state, "cursor", None)
    generation = getattr(_thread_state, "generation", None)
    if cursor is None or generation != _cursor_generation:
        raw = object.__getattribute__(master, "_con")
        cursor = _NonClosingConn(raw.cursor())
        _thread_state.cursor = cursor
        _thread_state.generation = _cursor_generation
    return cursor


def get_connection() -> '_NonClosingConn':
    """
    Return the shared persistent DuckDB connection for this process.
    Opens it on first call; subsequent calls return the same object.
    close() on the returned wrapper is a no-op.

    Reopens when ``CURIO_LAUNCH_CWD`` / ``CURIO_SHARED_DATA`` change — e.g.
    pytest switches per-test workspaces while reusing the same process.
    """
    global _connection, _connection_path, _writer_process
    path = get_db_path()
    with _state_lock:
        if _connection is not None and _connection_path != path:
            release_connection()
        if _connection is None:
            _connection = _NonClosingConn(_connect_with_retry(path))
            _connection_path = path
            _writer_process = True
        return _thread_cursor(_connection)


def get_read_connection():
    """
    Return a connection suitable for reading artifacts.

    Sandbox process: reuses the persistent R/W connection (_connection is set).
      close() on the returned _NonClosingConn is a no-op — the connection stays open.
    Backend process: opens a fresh read-only connection (_connection is None).
      close() on the returned raw connection actually closes it.
    """
    with _state_lock:
        if _connection is not None:
            return _thread_cursor(_connection)
        if _writer_process:
            # The sandbox between two runs: reopen the read-write connection
            # rather than a read-only one it would then have to fight.
            return get_connection()
    return _connect_with_retry(get_db_path(), read_only=True)


def _close_now() -> None:
    """Close the connection and reset state. Callers hold ``_state_lock``."""
    global _connection, _connection_path, _initialized, _close_pending
    global _cursor_generation
    if _connection is not None:
        object.__getattribute__(_connection, '_con').close()
        _connection = None
    _connection_path = None
    _initialized = False
    _close_pending = False
    # Every per-thread cursor is dead with the master; make them be recreated.
    _cursor_generation += 1


def release_connection(force: bool = False) -> None:
    """
    Close the persistent connection and reset state.
    Call this when the current request is done with DuckDB and another
    process (e.g., the sandbox subprocess) needs write access to the file.

    Deferred while another thread is inside ``connection_in_use``: that thread
    closes it on the way out instead. ``force=True`` closes regardless, for
    teardown paths that know nothing else is running.
    """
    global _close_pending
    with _state_lock:
        if _in_use > 0 and not force:
            _close_pending = True
            return
        _close_now()


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
    # Serialized: two threads running the DESCRIBE/ALTER migration below at
    # once is what produced "Column with name session_id" under load.
    with _state_lock:
        if _initialized:
            return
        _init_db_locked()


def _init_db_locked() -> None:
    global _initialized
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
