"""The sandbox server starts serving without DuckDB's default connection pool.

DuckDB's default connection, the one ``duckdb.sql`` and the other module-level
calls use, holds a pool of threads, and the sandbox never queries through it.
Open when the server starts, the pool would idle for the life of the process:
191 threads per sandbox on CI's 192-core runners, where six stacks share a
4096-thread container. The server closes it at startup
(``sandbox/util/duckdb_threads.py``).

The server runs in a fresh interpreter, up to the point where it would start
serving: ``Flask.run`` is replaced by a stand-in that records whether the
connection is still open, which of the pool's threads are still there, and
that ``duckdb.sql`` still answers, as node code that calls it needs. The
script opens the default connection before the server starts, so there is a
pool to close whichever DuckDB is installed: DuckDB 2.0 opens it on first use,
earlier versions at import.

The pool's threads are followed by id, not counted. ``close()`` joins them,
but Linux lists a joined thread in ``/proc/self/task`` until its exit
completes, so a count taken right after the close can include threads that
are already exiting. The stand-in gives them a few seconds to go. A pool that
something keeps alive never goes, and the second test checks that the first
test's check fails on one.
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
    import flask
    __import__(preload)  # what the entry point imports first, DuckDB among it

    started = thread_ids()
    default = duckdb.default_connection
    imported = default() if callable(default) else default
    pool |= thread_ids() - started  # or of one opened on first use, here
    if hold == "hold":
        # An Arrow reader left unread keeps its connection's database, and with
        # it the pool, alive after the connection is closed. Read from a cursor,
        # a second connection to the same database, it leaves the default
        # connection free for the release's own statement.
        held = imported.cursor().sql("select * from range(1000000)").to_arrow_reader(1000)
    loaded = me.num_threads()

    def pool_left():
        if BY_ID:
            return {tid: state(tid) for tid in sorted(pool & thread_ids(), key=int)}
        return {str(n): "?" for n in range(me.num_threads() - (loaded - len(pool)))}

    seen = {"pool": len(pool), "loaded": loaded}

    def serve(self, *args, **kwargs):
        seen["threads"] = me.num_threads()
        left = seen["at_serve"] = pool_left()
        deadline = time.monotonic() + wait
        while left and time.monotonic() < deadline:
            time.sleep(0.01)
            left = pool_left()
        seen["left"] = left
        try:
            imported.execute("select 1")
            seen["open"] = True
        except Exception as exc:
            seen["open"] = "closed" not in str(exc).lower()
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


class SandboxServerDuckdbPoolTest(unittest.TestCase):
    def assert_the_pool_is_gone(self, seen, log):
        self.assertGreater(
            seen["pool"], 0,
            "opening DuckDB's default connection started no threads to follow; "
            "was it open before the script opened it?",
        )
        self.assertFalse(
            seen["left"],
            f"{len(seen['left'])} of the {seen['pool']} threads of DuckDB's default "
            f"connection were still running {WAIT:g} s after the sandbox began serving: "
            f"{seen['left']} (when it began: {seen['at_serve']})\n{log[-2000:]}",
        )

    def test_the_sandbox_serves_without_duckdbs_import_time_pool(self):
        seen, log = serve_the_sandbox()
        self.assertIn("left", seen, "the server never reached Flask.run")
        self.assertFalse(
            seen["open"],
            f"the sandbox starts serving with DuckDB's default connection open: its "
            f"pool of {seen['pool']} threads idles for the life of the process",
        )
        self.assert_the_pool_is_gone(seen, log)
        # Node code keeps the module-level API, with a pool of its own.
        self.assertEqual(seen["sql"], 42)

    def test_a_pool_that_outlives_the_close_fails_the_check(self):
        """What the check is for: the connection is closed, yet its pool stays."""
        seen, log = serve_the_sandbox(hold=True)
        self.assertIn("left", seen, "the server never reached Flask.run")
        self.assertFalse(seen["open"], "the sandbox did not close the connection")
        with self.assertRaises(AssertionError) as caught:
            self.assert_the_pool_is_gone(seen, log)
        self.assertIn("were still running", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
