"""The sandbox server starts serving without DuckDB's import-time pool.

``import duckdb`` opens a default connection with a thread per core, and the
sandbox never queries through it, so it idled for the life of the process: 191
threads per sandbox on CI's 192-core runners, where six stacks share a
4096-thread container. The server closes it at startup
(``sandbox/util/duckdb_threads.py``).

The server runs in a fresh interpreter, up to the point where it would start
serving: ``Flask.run`` is replaced by a stand-in that records whether the
connection the import opened is still open, how many threads the process holds,
and that ``duckdb.sql`` still answers, as node code that calls it needs.
"""

import json
import os
import subprocess
import sys
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: Runs *module* as the server's entry point, with Flask.run standing in for
#: serving, and prints what it saw as one ``RESULT`` line of JSON.
SERVE_SCRIPT = textwrap.dedent("""
    import json
    import runpy
    import sys

    import duckdb
    import flask
    import psutil

    module, preload = sys.argv[1], sys.argv[2]
    __import__(preload)  # what the entry point imports first, DuckDB among it

    me = psutil.Process()
    default = duckdb.default_connection
    imported = default() if callable(default) else default
    loaded = me.num_threads()
    probe = duckdb.connect(":memory:")
    pool = me.num_threads() - loaded  # one DuckDB connection's threads
    probe.close()
    seen = {}

    def serve(self, *args, **kwargs):
        seen["threads"] = me.num_threads()
        try:
            imported.execute("select 1")
            seen["open"] = True
        except Exception as exc:
            seen["open"] = "closed" not in str(exc).lower()
        seen["sql"] = duckdb.sql("select 42").fetchall()[0][0]

    flask.Flask.run = serve
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    print("RESULT " + json.dumps({"loaded": loaded, "pool": pool, **seen}))
""")


def serve_once(module, preload, **env):
    """What the server *module* held when it would have started serving."""
    environ = dict(os.environ)
    environ.update(env)
    environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (REPO_ROOT, environ.get("PYTHONPATH")) if p
    )
    result = subprocess.run(
        [sys.executable, "-c", SERVE_SCRIPT, module, preload],
        cwd=REPO_ROOT, env=environ, capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
    assert result.returncode == 0 and lines, (
        f"the server did not reach serving (exit {result.returncode}):\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
    )
    return json.loads(lines[-1][len("RESULT "):]), result.stderr


class SandboxServerDuckdbPoolTest(unittest.TestCase):
    def test_the_sandbox_serves_without_duckdbs_import_time_pool(self):
        seen, log = serve_once(
            "utk_curio.sandbox.server", "utk_curio.sandbox.app",
            CURIO_ISOLATION="off", CURIO_NO_AUTH="1", FLASK_USE_RELOADER="0",
        )
        self.assertIn("threads", seen, "the server never reached Flask.run")
        self.assertFalse(
            seen["open"],
            f"the sandbox starts serving with DuckDB's import-time connection open: "
            f"its pool of {seen['pool']} threads idles for the life of the process "
            f"({seen['loaded']} threads after the imports, {seen['threads']} when serving)",
        )
        self.assertLessEqual(
            seen["threads"], seen["loaded"] - seen["pool"],
            f"closing the connection joined fewer threads than its pool of {seen['pool']} "
            f"({seen['loaded']} after the imports, {seen['threads']} when serving)\n{log[-2000:]}",
        )
        # Node code keeps the module-level API, with a pool of its own.
        self.assertEqual(seen["sql"], 42)


if __name__ == "__main__":
    unittest.main()
