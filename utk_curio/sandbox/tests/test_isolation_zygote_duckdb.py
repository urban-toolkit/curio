"""The zygote closing DuckDB's import-time connection, minus the rest of the zygote.

On DuckDB 1.x, ``import duckdb`` opens a default connection with a pool of
threads, and a child forked from a process holding that pool can crash inside
DuckDB (see ``zygote._release_import_time_duckdb``). These tests pin that the
zygote closes it, that doing so never raises, and that DuckDB still works
afterwards. DuckDB 2.0's import opens none, and asking for the default
connection opens one, with its pool. There the servers' release must open
nothing, while the zygote still opens and closes it before its first fork: a
child forked from a zygote that had never opened a DuckDB database died with
signal 11 in DuckDB's ``COPY``. Whether the zygote really ends up
single-threaded needs a live zygote on Linux, so that is in
test_isolation_linux.py.
"""

import io
import os
import subprocess
import sys
import textwrap
import types
import unittest
from contextlib import redirect_stderr
from unittest import mock

from utk_curio.sandbox.isolation import zygote
from utk_curio.sandbox.util import duckdb_threads

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


class _FakeConnection:
    def __init__(self, *, fail_set=False, fail_close=False):
        self.statements = []
        self.closed = False
        self._fail_set = fail_set
        self._fail_close = fail_close

    def execute(self, sql):
        self.statements.append(sql)
        if self._fail_set:
            raise RuntimeError("unrecognized configuration parameter")
        return self

    def close(self):
        if self._fail_close:
            raise RuntimeError("cannot close")
        self.closed = True


def _fake_duckdb(connection, *, as_function=True, version=None):
    """A DuckDB whose default connection, *connection*, is open, as 1.x's import leaves it."""
    module = types.ModuleType("duckdb")
    module.default_connection = (lambda: connection) if as_function else connection
    if version is not None:
        module.__version__ = version
    return module


def _duckdb_that_opens_on_first_use(version):
    """A DuckDB whose import opened no default connection, as 2.0's does.

    Every call that reaches the default connection opens one, with its pool:
    asking for it, and the module-level calls that run on it. Each is recorded
    in ``opened``, and the connection it opened in ``connections``.
    """
    module = types.ModuleType("duckdb")
    module.__version__ = version
    module.opened = []
    module.connections = []

    def opens(name):
        def call(*args, **kwargs):
            module.opened.append(name)
            module.connections.append(_FakeConnection())
            return module.connections[-1]
        return call

    for name in ("default_connection", "close", "connect", "sql", "execute"):
        setattr(module, name, opens(name))
    return module


_REAL_LISTDIR = os.listdir
_REAL_OPEN = open


class _ProcClosingAPool:
    """``/proc/self/task`` of a process whose DuckDB pool of 19 threads closes.

    As on Linux, ``close()`` returns while the pool's last thread is still
    listed, flagged as exiting (PF_EXITING, 0x4 in its stat's flags), and the
    next reading of the directory no longer finds it.
    """

    TASKS = "/proc/self/task"

    def __init__(self, connection):
        self.connection = connection
        self.readings_since_close = 0

    def threads(self):
        """Thread id -> (name, exiting)."""
        threads = {str(n): ("python", False) for n in range(1, 5)}  # main, OpenBLAS
        threads["5"] = ("jemalloc_bg_thd", False)  # pyarrow's
        if not self.connection.closed:
            threads.update({str(n): ("python", False) for n in range(100, 119)})
        elif self.readings_since_close <= 1:
            threads["118"] = ("python", True)
        return threads

    def listdir(self, path):
        if path != self.TASKS:
            return _REAL_LISTDIR(path)
        if self.connection.closed:
            self.readings_since_close += 1
        return list(self.threads())

    def open(self, path, *args, **kwargs):
        if not str(path).startswith(self.TASKS + "/"):
            return _REAL_OPEN(path, *args, **kwargs)
        thread_id, leaf = str(path)[len(self.TASKS) + 1:].split("/")
        threads = self.threads()
        if thread_id not in threads or leaf not in ("comm", "stat"):
            raise FileNotFoundError(path)
        name, exiting = threads[thread_id]
        if leaf == "comm":
            return io.StringIO(name + "\n")
        flags = 0x400040 | (0x4 if exiting else 0)
        return io.StringIO(f"{thread_id} ({name}) {'X' if exiting else 'S'} 1 1 1 0 -1 "
                           f"{flags}" + " 0" * 43 + "\n")


class ReleaseImportTimeDuckdbTest(unittest.TestCase):
    def _release(self, module, names=(None, None)):
        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, {"duckdb": module}), \
                mock.patch.object(zygote, "_thread_names", side_effect=list(names)), \
                redirect_stderr(stderr):
            zygote._release_import_time_duckdb()
        return stderr.getvalue()

    def test_closes_the_default_connection(self):
        connection = _FakeConnection()
        self._release(_fake_duckdb(connection))
        self.assertTrue(connection.closed)

    def test_turns_the_allocator_thread_off_first(self):
        connection = _FakeConnection()
        self._release(_fake_duckdb(connection))
        self.assertEqual(connection.statements,
                         ["SET GLOBAL allocator_background_threads = false"])

    def test_handles_the_older_attribute_form(self):
        connection = _FakeConnection()
        self._release(_fake_duckdb(connection, as_function=False))
        self.assertTrue(connection.closed)

    def test_an_unknown_setting_does_not_stop_the_close(self):
        connection = _FakeConnection(fail_set=True)
        self._release(_fake_duckdb(connection))
        self.assertTrue(connection.closed)

    def test_a_failed_close_warns_and_does_not_raise(self):
        log = self._release(_fake_duckdb(_FakeConnection(fail_close=True)))
        self.assertIn("could not close DuckDB's import-time connection", log)

    def test_does_nothing_when_duckdb_was_never_imported(self):
        with mock.patch.dict(sys.modules), \
                mock.patch.object(zygote, "_thread_names") as thread_names:
            sys.modules.pop("duckdb", None)
            zygote._release_import_time_duckdb()
        thread_names.assert_not_called()

    def test_opens_nothing_where_the_import_opened_nothing(self):
        """DuckDB 2.0 opens its default connection on first use only.

        Asked for it, the servers' release would open one, with its pool, only
        to close it: on CI's runners 19 threads on 4 cores, in both servers at
        every start.
        """
        for version in ("2.0.0", "2.1.0", "3.0.0.dev12"):
            module = _duckdb_that_opens_on_first_use(version)
            stderr = io.StringIO()
            with mock.patch.dict(sys.modules, {"duckdb": module}), redirect_stderr(stderr):
                duckdb_threads.release_default_connection(
                    "[sandbox]", "so its threads stay idle", names=lambda: None)
            self.assertEqual(
                module.opened, [],
                f"on DuckDB {version}, the release called {module.opened}, which "
                f"opens DuckDB's default connection, with its pool, only to close it",
            )
            self.assertEqual(stderr.getvalue(), "", f"on DuckDB {version}")

    def test_the_zygote_opens_and_closes_it_where_the_import_opened_nothing(self):
        """On DuckDB 2.0 its children need a zygote that has opened a database.

        Forked from one that never had, the exec-user suite's weather routing
        child (``test_scouts_weather_routing_runs_as_the_exec_user``) died with
        signal 11 in DuckDB's COPY in ``codec._write_dataframe_parquet``.
        """
        for version in ("2.0.0", "2.1.0", "3.0.0.dev12"):
            module = _duckdb_that_opens_on_first_use(version)
            self._release(module)
            self.assertEqual(module.opened, ["default_connection"], f"on DuckDB {version}")
            self.assertTrue(module.connections[0].closed,
                            f"on DuckDB {version}, the zygote left the connection it opened open")

    def test_closes_it_where_the_import_opened_it(self):
        """DuckDB 1.x opens its default connection at import."""
        for version in ("1.5.3", "1.4.4", "0.10.3"):
            connection = _FakeConnection()
            self._release(_fake_duckdb(connection, version=version))
            self.assertTrue(connection.closed, f"on DuckDB {version}")

    def test_a_version_it_cannot_read_counts_as_one_whose_import_opened_it(self):
        """Asking for a default connection that is open opens nothing, so this side is safe."""
        for version in ("", "unknown", None):
            connection = _FakeConnection()
            module = _fake_duckdb(connection)
            module.__version__ = version
            self._release(module)
            self.assertTrue(connection.closed, f"with __version__ = {version!r}")

    def test_reports_the_threads_it_released(self):
        log = self._release(_fake_duckdb(_FakeConnection()),
                            names=(["python"] * 9, ["python"]))
        self.assertIn("threads 9 (python x9) -> 1 (python x1)", log)
        self.assertNotIn("warning", log)

    def test_a_leftover_allocator_thread_is_reported_not_warned(self):
        """pyarrow's jemalloc thread survives the release, and is harmless."""
        log = self._release(
            _fake_duckdb(_FakeConnection()),
            names=(["python"] * 9 + ["jemalloc_bg_thd"], ["python", "jemalloc_bg_thd"]),
        )
        self.assertIn("-> 2 (python x1, jemalloc_bg_thd x1)", log)
        self.assertNotIn("warning", log)

    def test_is_silent_without_proc(self):
        self.assertEqual(self._release(_fake_duckdb(_FakeConnection())), "")

    def test_counts_once_the_pools_threads_have_exited(self):
        """``close()`` joins the pool, and Linux lists a joined thread until its exit ends.

        Counted right after the close, the pool's last thread, already
        exiting, looked like a thread the close had left running.
        """
        connection = _FakeConnection()
        proc = _ProcClosingAPool(connection)
        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, {"duckdb": _fake_duckdb(connection)}), \
                mock.patch("os.listdir", proc.listdir), \
                mock.patch("builtins.open", proc.open), \
                redirect_stderr(stderr):
            zygote._release_import_time_duckdb()
        self.assertIn(
            "threads 24 (python x23, jemalloc_bg_thd x1) -> 5 (python x4, jemalloc_bg_thd x1)",
            stderr.getvalue(),
        )


class RealDuckdbTest(unittest.TestCase):
    """Against the installed DuckDB, in a fresh interpreter.

    A subprocess, so closing the default connection cannot disturb anything
    else this test process has done with DuckDB. What the release must do
    depends on what the bare ``import duckdb`` did there, seen as the threads
    it started: DuckDB 1.x opens the default connection and its pool, 2.0
    nothing.
    """

    def test_duckdb_still_works_after_the_release(self):
        script = textwrap.dedent("""
            import psutil
            from utk_curio.sandbox.isolation import zygote

            me = psutil.Process()
            before_import = me.num_threads()
            import duckdb
            at_import = me.num_threads()

            # Counts the release's requests for the default connection: on a
            # DuckDB whose import opened none, each one opens it.
            real = duckdb.default_connection
            asked = []

            def default_connection():
                asked.append(1)
                return real()

            duckdb.default_connection = default_connection
            zygote._release_import_time_duckdb()
            after = me.num_threads()
            duckdb.default_connection = real

            # Asked for now, the default connection opens with a pool of its
            # own, unless the release left one open.
            reopened = real()
            probe = me.num_threads() - after
            # The module-level API reopens a default connection on demand,
            # and explicit connections were never affected.
            print(duckdb.sql("select 42").fetchall()[0][0])
            con = duckdb.connect(":memory:")
            print(con.execute("select 7").fetchall()[0][0])
            con.close()
            print(before_import, at_import, after, len(asked), probe)
        """)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (REPO_ROOT, env.get("PYTHONPATH")) if p
        )
        result = subprocess.run([sys.executable, "-c", script], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        answer, explicit, counts = result.stdout.strip().splitlines()[-3:]
        self.assertEqual((answer, explicit), ("42", "7"))
        before_import, at_import, after, asked, probe = (int(n) for n in counts.split())
        seen = (f"threads {before_import} before the import, {at_import} after it, "
                f"{after} after the release; asked {asked} time(s)\n{result.stderr[-2000:]}")
        if at_import > before_import:
            # DuckDB 1.x: the import opened the default connection, and its pool.
            self.assertLess(after, at_import, f"closing the connection joined no threads: {seen}")
        else:
            # DuckDB 2.0: the import opened nothing. The zygote still opens the
            # default connection and closes it before forking: its children
            # need a process that has opened a DuckDB database.
            self.assertEqual(
                asked, 1,
                f"the zygote did not open and close DuckDB's default connection "
                f"before forking: {seen}",
            )
            self.assertLessEqual(after, at_import, f"the release left threads running: {seen}")
        self.assertGreater(
            probe, 0,
            f"the release left DuckDB's default connection open: asked for "
            f"afterwards, it started no threads of its own: {seen}",
        )


class WarmUpTest(unittest.TestCase):
    def test_the_release_comes_after_the_imports(self):
        """The imports are what open the connection; releasing first is useless."""
        calls = []

        def imports():
            calls.append("imports")
            return {}

        with mock.patch.object(zygote, "build_namespace_template",
                               side_effect=imports), \
                mock.patch.object(zygote, "_release_import_time_duckdb",
                                  side_effect=lambda: calls.append("release")):
            zygote.Zygote("unused.sock").warm_up()
        self.assertEqual(calls, ["imports", "release"])


class ThreadReportTest(unittest.TestCase):
    def test_describe_threads_counts_and_orders_by_frequency(self):
        self.assertEqual(
            zygote._describe_threads(["python3", "duckdb", "python3"]),
            "3 (python3 x2, duckdb x1)",
        )

    def test_thread_names_is_none_without_proc(self):
        with mock.patch.object(zygote.os, "listdir", side_effect=FileNotFoundError):
            self.assertIsNone(zygote._thread_names())

    @unittest.skipUnless(os.path.isdir("/proc/self/task"), "needs /proc")
    def test_thread_names_sees_at_least_this_thread(self):
        names = zygote._thread_names()
        self.assertGreaterEqual(len(names), 1)
        self.assertTrue(all(isinstance(name, str) and name for name in names))


if __name__ == "__main__":
    unittest.main()
