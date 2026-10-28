"""The backend serves through Socket.IO, whatever ``--collab`` says, and its dev
server keeps the reloader's exclusions.

Flask-SocketIO's threading mode starts Werkzeug through ``Flask.run``, which
stands in for serving here, and hands Werkzeug's reloader only what it gets as
``reloader_options``. Without the exclusions there, a package install, which
writes under ``.curio/`` and ``site-packages/``, restarts a dev backend in the
middle of a request.
"""

import runpy
import unittest
from unittest import mock


class BackendSocketServerTest(unittest.TestCase):
    def test_the_backend_serves_through_socketio_with_the_reloaders_exclusions(self):
        """The server module run as the launcher runs it, ``python -m
        backend.server``, up to the point where it would serve."""
        from flask_socketio import SocketIO

        from utk_curio.backend.reloader import DEFAULT_RELOADER_TYPE, RELOADER_EXCLUDE_PATTERNS

        seen = {}
        socketio_run = SocketIO.run

        def through_socketio(sio, app, *args, **kwargs):
            seen["socketio"] = kwargs
            return socketio_run(sio, app, *args, **kwargs)

        def serving(app, *args, **kwargs):
            seen["flask"] = kwargs

        with mock.patch.object(SocketIO, "run", through_socketio), \
                mock.patch("flask.Flask.run", serving), \
                mock.patch("utk_curio.sandbox.util.duckdb_threads.release_default_connection",
                           lambda *args, **kwargs: None):
            runpy.run_module("utk_curio.backend.server", run_name="__main__")

        self.assertIn("socketio", seen, "the backend serves without Socket.IO")
        self.assertIn("flask", seen, "the backend never reached Flask.run")
        self.assertEqual(seen["flask"].get("exclude_patterns"), RELOADER_EXCLUDE_PATTERNS,
                         "Socket.IO's server dropped the reloader's exclusions")
        self.assertEqual(seen["flask"].get("reloader_type"), DEFAULT_RELOADER_TYPE)
        self.assertIs(seen["flask"].get("threaded"), True)

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
