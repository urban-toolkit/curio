"""The zygote closing DuckDB's import-time connection, minus the rest of the zygote.

``import duckdb`` opens a default connection with a pool of threads, and a
child forked from a process holding that pool can crash inside DuckDB (see
``zygote._release_import_time_duckdb``). These tests pin that the zygote closes
it, that doing so never raises, and that DuckDB still works afterwards. Whether
the zygote really ends up single-threaded needs a live zygote on Linux, so that
is in test_isolation_linux.py.
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


def _fake_duckdb(connection, *, as_function=True):
    module = types.ModuleType("duckdb")
    module.default_connection = (lambda: connection) if as_function else connection
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
    else this test process has done with DuckDB.
    """

    def test_duckdb_still_works_after_the_release(self):
        script = textwrap.dedent("""
            import os
            import duckdb
            from utk_curio.sandbox.isolation import zygote

            def threads():
                try:
                    return len(os.listdir("/proc/self/task"))
                except OSError:
                    return -1

            before = threads()
            zygote._release_import_time_duckdb()
            after = threads()
            # The module-level API reopens a default connection on demand,
            # and explicit connections were never affected.
            print(duckdb.sql("select 42").fetchall()[0][0])
            con = duckdb.connect(":memory:")
            print(con.execute("select 7").fetchall()[0][0])
            con.close()
            print(before, after)
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
        before, after = (int(n) for n in counts.split())
        if before > 1:  # only measurable where /proc exists
            self.assertLess(after, before, "closing the connection joined no threads")


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
