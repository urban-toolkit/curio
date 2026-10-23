"""The sandbox server starts serving with no pool of DuckDB's default connection.

DuckDB's default connection, the one ``duckdb.sql`` and the other module-level
calls use, holds a pool of threads, and the sandbox never queries through it.
Open when the server starts, the pool would idle for the life of the process:
191 threads per sandbox on CI's 192-core runners, where six stacks share a
4096-thread container. DuckDB 1.x opens it at import, and the server closes it
at startup (``sandbox/util/duckdb_threads.py``). DuckDB 2.0 opens it on first
use only, and asking for it opens it, so there the startup must not ask.

The server runs in a fresh interpreter, up to the point where it would start
serving: ``Flask.run`` is replaced by a stand-in that records which threads of
the pool are still there, whether a default connection is still open, and
that ``duckdb.sql`` still answers, as node code that calls it needs. Which
claims apply depends on what the bare ``import duckdb`` did, seen as the
threads it started: those are the pool of a default connection DuckDB 1.x
opened. The script itself opens none on a DuckDB whose import opened none,
except in the case built to fail the check.

The pool's threads are followed by id, not counted. ``close()`` joins them,
but Linux lists a joined thread in ``/proc/self/task`` until its exit
completes, so a count taken right after the close can include threads that
are already exiting. The stand-in gives them a few seconds to go. A pool that
something keeps alive never goes, and the second test checks that the first
test's check fails on one.

Whether a default connection is still open when serving starts is seen by
asking for it then: if none is, that opens one, and its pool's threads appear.
"""

import json
import os
import subprocess
import sys
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: Seconds the pool's threads get to finish exiting once serving starts.
WAIT = 5.0

#: Runs *module* as the server's entry point, with Flask.run standing in for
#: serving, and prints what it saw as one ``RESULT`` line of JSON.
SERVE_SCRIPT = textwrap.dedent("""
    import json
    import os
    import runpy
    import sys
    import time

    import psutil

    module, preload, wait, hold = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    me = psutil.Process()
    TASKS = "/proc/self/task"
    # Linux lists each thread by id. Elsewhere psutil numbers threads by
    # position, so they are only counted.
    BY_ID = os.path.isdir(TASKS)

    def thread_ids():
        return set(os.listdir(TASKS)) if BY_ID else set(range(me.num_threads()))

    def state(thread_id):
        # Its state letter, and "exiting" once it has begun to exit (PF_EXITING).
        try:
            with open(f"{TASKS}/{thread_id}/stat") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
            return fields[0] + (" exiting" if int(fields[6]) & 0x4 else "")
        except (OSError, IndexError, ValueError):
            return "gone"

    started = thread_ids()
    import duckdb
    pool = thread_ids() - started  # the threads of a default connection opened at import
    at_import = len(pool)
    import flask
    __import__(preload)  # what the entry point imports first, DuckDB among it

    real_default = duckdb.default_connection
    imported = None
    opened_here = 0
    if at_import or hold == "hold":
        # DuckDB 1.x: the connection its import opened, which asking for opens
        # nothing new. With hold on 2.0: one opened here, as startup code that
        # used DuckDB's module-level API would open it.
        started = thread_ids()
        imported = real_default()
        opened_here = len(thread_ids() - started)
        pool |= thread_ids() - started
    if hold == "hold":
        # An Arrow reader left unread keeps its connection's database, and with
        # it the pool, alive after the connection is closed. Read from a cursor,
        # a second connection to the same database, it leaves the default
        # connection free for the release's own statement.
        held = imported.cursor().sql("select * from range(1000000)").to_arrow_reader(1000)
    loaded = me.num_threads()

    # Counts the startup's requests for the default connection: on a DuckDB
    # whose import opened none, each one opens it.
    asked = []

    def default_connection():
        asked.append(1)
        return real_default()

    duckdb.default_connection = default_connection

    def pool_left():
        if BY_ID:
            return {tid: state(tid) for tid in sorted(pool & thread_ids(), key=int)}
        return {str(n): "?" for n in range(me.num_threads() - (loaded - len(pool)))}

    seen = {"at_import": at_import, "opened_here": opened_here, "pool": len(pool),
            "loaded": loaded}

    def serve(self, *args, **kwargs):
        duckdb.default_connection = real_default
        seen["asked"] = len(asked)
        seen["threads"] = me.num_threads()
        left = seen["at_serve"] = pool_left()
        deadline = time.monotonic() + wait
        while left and time.monotonic() < deadline:
            time.sleep(0.01)
            left = pool_left()
        seen["left"] = left
        if imported is not None:
            try:
                # Read to the end: on DuckDB 2.0 a result left unread keeps the
                # connection busy, and the duckdb.sql below runs on it while it
                # is still the default.
                imported.execute("select 1").fetchall()
                seen["open"] = True
            except Exception as exc:
                seen["open"] = "closed" not in str(exc).lower()
        # Asked for now, the default connection opens with a pool of its own,
        # unless one is still open. Asked before duckdb.sql, which opens one too.
        started = thread_ids()
        real_default()
        seen["probe"] = len(thread_ids() - started)
        seen["sql"] = duckdb.sql("select 42").fetchall()[0][0]

    flask.Flask.run = serve
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    print("RESULT " + json.dumps(seen))
""")


def serve_once(module, preload, *, hold=False, **env):
    """What the server *module* held when it would have started serving.

    With *hold*, something keeps the default connection's pool alive.
    """
    environ = dict(os.environ)
    environ.update(env)
    environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (REPO_ROOT, environ.get("PYTHONPATH")) if p
    )
    result = subprocess.run(
        [sys.executable, "-c", SERVE_SCRIPT, module, preload, str(WAIT),
         "hold" if hold else "close"],
        cwd=REPO_ROOT, env=environ, capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
    assert result.returncode == 0 and lines, (
        f"the server did not reach serving (exit {result.returncode}):\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
    )
    return json.loads(lines[-1][len("RESULT "):]), result.stderr


def serve_the_sandbox(**kwargs):
    return serve_once(
        "utk_curio.sandbox.server", "utk_curio.sandbox.app",
        CURIO_ISOLATION="off", CURIO_NO_AUTH="1", FLASK_USE_RELOADER="0", **kwargs,
    )


def assert_the_pool_is_gone(test, seen, log, who):
    """No thread of the pool the script followed is left once serving starts."""
    test.assertFalse(
        seen["left"],
        f"{len(seen['left'])} of the {seen['pool']} threads of DuckDB's default "
        f"connection were still running {WAIT:g} s after the {who} began serving: "
        f"{seen['left']} (when it began: {seen['at_serve']})\n{log[-2000:]}",
    )


def assert_serves_without_the_pool(test, seen, log, who):
    """The claims for a server *who* that began serving, on the DuckDB it ran with."""
    test.assertIn("left", seen, f"the {who} never reached Flask.run\n{log[-2000:]}")
    if seen["at_import"]:
        # DuckDB 1.x: its import opened the default connection; the server closes it.
        test.assertEqual(
            seen["opened_here"], 0,
            f"asking for the connection the import opened started "
            f"{seen['opened_here']} threads: the script opened the pool it then "
            f"asks the {who} to close",
        )
        test.assertFalse(
            seen["open"],
            f"the {who} starts serving with DuckDB's default connection open: its "
            f"pool of {seen['pool']} threads idles for the life of the process "
            f"({seen['loaded']} threads after the imports, {seen['threads']} when serving)",
        )
    else:
        # DuckDB 2.0: its import opened none, and asking for one opens it.
        test.assertEqual(
            seen["asked"], 0,
            f"the {who}'s startup asked for DuckDB's default connection "
            f"{seen['asked']} time(s): on a DuckDB whose import opened none, that "
            f"opens it, with its pool, only to close it\n{log[-2000:]}",
        )
    assert_the_pool_is_gone(test, seen, log, who)
    test.assertGreater(
        seen["probe"], 0,
        f"DuckDB's default connection was open when the {who} began serving: "
        f"asked for then, it started no threads of its own\n{log[-2000:]}",
    )
    # Node code keeps the module-level API, with a pool of its own.
    test.assertEqual(seen["sql"], 42)


class SandboxServerDuckdbPoolTest(unittest.TestCase):
    def test_the_sandbox_serves_without_duckdbs_import_time_pool(self):
        seen, log = serve_the_sandbox()
        assert_serves_without_the_pool(self, seen, log, "sandbox")

    def test_a_pool_that_outlives_the_close_fails_the_check(self):
        """What the check is for: a pool still running when serving starts.

        On DuckDB 1.x the server closes the connection the import opened, and
        an unread Arrow reader keeps its pool alive past the close. On 2.0 the
        script opens the default connection itself, as startup code that used
        the module-level API would, and the server cannot see it without
        opening one.
        """
        seen, log = serve_the_sandbox(hold=True)
        self.assertIn("left", seen, "the server never reached Flask.run")
        self.assertGreater(seen["pool"], 0,
                           "holding DuckDB's default connection left no threads to follow")
        if seen["at_import"]:
            self.assertFalse(seen["open"], "the sandbox did not close the connection")
        with self.assertRaises(AssertionError) as caught:
            assert_the_pool_is_gone(self, seen, log, "sandbox")
        self.assertIn("were still running", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
