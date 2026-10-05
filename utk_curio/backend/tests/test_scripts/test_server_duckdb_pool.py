"""The backend server starts serving without DuckDB's import-time pool.

The backend's twin of ``sandbox/tests/test_server_duckdb_pool.py``: ``import
duckdb`` opens a default connection with a thread per core, which the backend
never queries through, so the server closes it at startup. The server runs in
a fresh interpreter up to the point where it would start serving, with
``Flask.run`` standing in for serving.
"""

import unittest

from utk_curio.sandbox.tests.test_server_duckdb_pool import serve_once


class BackendServerDuckdbPoolTest(unittest.TestCase):
    def test_the_backend_serves_without_duckdbs_import_time_pool(self):
        seen, log = serve_once(
            "utk_curio.backend.server", "utk_curio.backend.app",
            ENABLE_COLLAB="0", CURIO_SEED_EXAMPLES="0", FLASK_USE_RELOADER="0",
        )
        self.assertIn("threads", seen, f"the server never reached Flask.run\n{log[-2000:]}")
        self.assertFalse(
            seen["open"],
            f"the backend starts serving with DuckDB's import-time connection open: "
            f"its pool of {seen['pool']} threads idles for the life of the process "
            f"({seen['loaded']} threads after the imports, {seen['threads']} when serving)",
        )
        # Anything that runs a query through the module-level API still can.
        self.assertEqual(seen["sql"], 42)


if __name__ == "__main__":
    unittest.main()
