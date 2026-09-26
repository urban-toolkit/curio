"""The backend's dev server runs with Flask debug off unless asked.

Debug mode is not free on this server: Flask's DefaultJSONProvider
pretty-prints every jsonify with indent=2 while ``app.debug`` is true, which
measured 1.00s against 0.25s to encode and 30.8MB against 19.2MB on a
200k-row frame. ``/get`` pays it on every artifact fetch. The interactive
debugger it also enables never fired, because app/__init__.py answers every
in-request fault with a catch-all errorhandler.

These drive ``_run_kwargs`` rather than a live server, which is the reason it
exists: both the socketio and the plain branch pass through it, and neither
can be exercised by starting one.
"""

import importlib
import os
import unittest
from unittest import mock


def run_kwargs(**env):
    """``_run_kwargs()`` as it would resolve under this environment.

    config.py reads its flags at import, so the module is reloaded inside the
    patched environment and restored afterwards.
    """
    from utk_curio.backend import server

    with mock.patch.dict(os.environ, env, clear=False):
        from utk_curio.backend import config

        importlib.reload(config)
        try:
            return server._run_kwargs()
        finally:
            importlib.reload(config)


class BackendDebugFlagTest(unittest.TestCase):
    def test_debug_is_off_by_default(self):
        """The default an operator gets without setting anything."""
        self.assertIs(run_kwargs(CURIO_BACKEND_DEBUG="")["debug"], False)

    def test_an_operator_can_turn_it_back_on(self):
        for value in ("1", "true", "yes", "on", "TRUE"):
            with self.subTest(value=value):
                self.assertIs(run_kwargs(CURIO_BACKEND_DEBUG=value)["debug"], True)

    def test_the_off_vocabulary_is_honoured_too(self):
        for value in ("0", "false", "no", "off"):
            with self.subTest(value=value):
                self.assertIs(run_kwargs(CURIO_BACKEND_DEBUG=value)["debug"], False)

    def test_reloading_is_not_tied_to_debug(self):
        """Turning debug off must not take auto-reload with it.

        They are separate switches, and a developer who loses hot reload to a
        performance fix will simply turn debug back on.
        """
        kwargs = run_kwargs(CURIO_BACKEND_DEBUG="", FLASK_USE_RELOADER="1")
        self.assertIs(kwargs["debug"], False)
        self.assertIs(kwargs["use_reloader"], True)

    def test_host_and_port_still_come_from_the_environment(self):
        """The launcher sets these; _run_kwargs must not have swallowed them."""
        kwargs = run_kwargs(
            FLASK_BACKEND_HOST="0.0.0.0", FLASK_BACKEND_PORT="5102",
        )
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertEqual(kwargs["port"], 5102)


class DebugDrivesJsonFormattingTest(unittest.TestCase):
    """Why the flag is worth having, pinned as a fact about Flask.

    If a Flask upgrade ever decouples pretty-printing from app.debug, this
    fails and the comment in config.py needs rewriting rather than trusting.
    """

    def test_debug_mode_is_what_makes_jsonify_pretty_print(self):
        from flask import Flask, jsonify

        payload = {"rows": [{"a": 1, "b": 2}]}

        app = Flask(__name__)
        with app.test_request_context():
            compact = jsonify(payload).get_data(as_text=True)
        app.debug = True
        with app.test_request_context():
            pretty = jsonify(payload).get_data(as_text=True)

        self.assertNotIn("\n  ", compact)
        self.assertIn("\n  ", pretty)
        self.assertGreater(len(pretty), len(compact))


if __name__ == "__main__":
    unittest.main()
