"""The backend serves through Socket.IO, whatever ``--collab`` says, and its dev
server keeps the reloader's exclusions.

Flask-SocketIO's threading mode starts Werkzeug through ``Flask.run``, which
stands in for serving here, and hands Werkzeug's reloader only what it gets as
``reloader_options``. Without the exclusions there, a package install, which
writes under ``.curio/`` and ``site-packages/``, restarts a dev backend in the
middle of a request.
"""

import unittest
from unittest import mock


class BackendSocketServerTest(unittest.TestCase):
    def test_the_backend_serves_through_socketio_with_the_reloaders_exclusions(self):
        from utk_curio.backend import server
        from utk_curio.backend.reloader import DEFAULT_RELOADER_TYPE, RELOADER_EXCLUDE_PATTERNS

        seen = {}

        def run(app, *args, **kwargs):
            seen.update(kwargs, app=app)

        debug = server.app.debug
        try:
            with mock.patch("flask.Flask.run", run), mock.patch(
                "utk_curio.sandbox.util.duckdb_threads.release_default_connection",
                lambda *args, **kwargs: None,
            ):
                server.serve()
        finally:
            server.app.debug = debug

        self.assertIs(seen.get("app"), server.app, "the backend did not reach Flask.run")
        self.assertEqual(seen["exclude_patterns"], RELOADER_EXCLUDE_PATTERNS)
        self.assertEqual(seen["reloader_type"], DEFAULT_RELOADER_TYPE)
        self.assertIs(seen["threaded"], True)

    def test_every_backend_mounts_socketio_without_collab(self):
        from utk_curio.backend import config
        from utk_curio.backend.app import create_app

        with mock.patch.object(config, "ENABLE_COLLAB", False):
            app = create_app()
        sio = app.extensions.get("socketio")
        self.assertIsNotNone(sio, "a backend started without --collab serves no Socket.IO")
        handlers = sio.server.handlers.get(config.COLLAB_NAMESPACE, {})
        for event in ("connect", "join_session", "disconnect", "yjs"):
            self.assertIn(event, handlers)


if __name__ == "__main__":
    unittest.main()
