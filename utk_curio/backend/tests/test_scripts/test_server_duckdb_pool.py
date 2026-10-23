"""The backend server starts serving with no pool of DuckDB's default connection.

The backend's twin of ``sandbox/tests/test_server_duckdb_pool.py``, with the
same claims. DuckDB 1.x's import opens a default connection with a thread per
core, which the backend never queries through, so the server closes it at
startup; DuckDB 2.0 opens it on first use only, so the startup must not ask
for it. The server runs in a fresh interpreter up to the point where it would
start serving, with ``Flask.run`` standing in for serving.
"""

import unittest

from utk_curio.sandbox.tests.test_server_duckdb_pool import (
    assert_serves_without_the_pool,
    serve_once,
)


class BackendServerDuckdbPoolTest(unittest.TestCase):
    def test_the_backend_serves_without_duckdbs_import_time_pool(self):
        seen, log = serve_once(
            "utk_curio.backend.server", "utk_curio.backend.app",
            ENABLE_COLLAB="0", CURIO_SEED_EXAMPLES="0", FLASK_USE_RELOADER="0",
        )
        assert_serves_without_the_pool(self, seen, log, "backend")


if __name__ == "__main__":
    unittest.main()
