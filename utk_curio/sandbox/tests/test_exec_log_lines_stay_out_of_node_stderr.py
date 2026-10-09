"""A node's stderr holds only what its own run wrote (#770).

Without isolation, ``execute_code`` (``app/worker.py``) runs one node at a
time under ``_exec_lock`` and captures its output with
``contextlib.redirect_stdout`` and ``redirect_stderr``. Those swap
``sys.stdout`` and ``sys.stderr`` for the whole process, not for one thread.
The sandbox's own log lines were printed to ``sys.stderr`` from other request
threads, so a request that arrived while a node ran wrote its line into that
node's stderr: Run All showed ``[sandbox /exec] received  node=...`` above a
node's output.

Each test runs node A, which holds the lock until the test lets it go, sends a
second request meanwhile, and reads A's stderr.
"""

import io
import os
import sys
import textwrap
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from utk_curio.sandbox.app import api, app, worker
from utk_curio.sandbox.util.db import init_db, release_connection

# The longest any one step may take before the test gives up on it.
WAIT = 30

NODE_A = (
    "import sys\n"
    "print('a line of node A', file=sys.stderr)\n"
    "node_a_entered.set()\n"
    "node_a_release.wait(60)\n"
    "return 1\n"
)


def _exec_body(code, node_type, session_id):
    return {
        "code": textwrap.indent(code, "    "),
        "file_path": "",
        "nodeType": node_type,
        "dataType": "",
        "session_id": session_id,
        "save_dataset": False,
    }


class LogLinesStayOutOfNodeStderrTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
            "CURIO_ISOLATION": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        # In process, whatever this host would resolve: the choice is cached
        # for the process, so the variable alone can come too late.
        previous = api._isolation_state
        api._isolation_state = False
        self.addCleanup(setattr, api, "_isolation_state", previous)
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        # What node A's code waits on, in the namespace every node run starts from.
        self.entered = threading.Event()
        self.release = threading.Event()
        gates = mock.patch.dict(worker._globals_cache, {
            "node_a_entered": self.entered,
            "node_a_release": self.release,
        })
        gates.start()
        self.addCleanup(gates.stop)
        # The process's own stderr, where the sandbox's log lines belong.
        self.server_log = io.StringIO()
        own_stderr = mock.patch.object(sys, "__stderr__", self.server_log)
        own_stderr.start()
        self.addCleanup(own_stderr.stop)

    def post(self, route, body, into):
        """POST *body* from a thread of its own, as Run All's requests come."""
        def send():
            try:
                response = app.test_client().post(route, json=body)
                into["status"] = response.status_code
                into["body"] = response.get_json()
            except Exception as exc:  # noqa: BLE001 - reported by the assertions
                into["error"] = repr(exc)

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        return thread

    def run_while_node_a_holds_the_lock(self, meanwhile):
        """Start node A, call *meanwhile* once A's code runs, then let A go.

        Returns A's response body.
        """
        a = {}
        a_thread = self.post("/exec", _exec_body(NODE_A, "NODE_A", "session-a"), a)
        try:
            if self.entered.wait(WAIT):
                meanwhile()
        finally:
            self.release.set()
            a_thread.join(WAIT)
        self.assertTrue(self.entered.is_set(), f"node A never ran its code: {a}")
        self.assertFalse(a_thread.is_alive(), "node A did not finish")
        self.assertEqual(a.get("status"), 200, a)
        return a["body"]

    def test_a_request_queued_behind_a_running_node_logs_outside_its_stderr(self):
        b = {}
        b_thread = None

        def send_b_and_wait_until_it_queues():
            nonlocal b_thread
            b_thread = self.post("/exec", _exec_body("return 2\n", "NODE_B", "session-b"), b)
            # B prints its "received" line before it asks for the lock.
            deadline = time.monotonic() + WAIT
            while worker._exec_lock.snapshot()["waiting"] < 1:
                self.assertTrue(b_thread.is_alive(), f"node B ended without queueing: {b}")
                self.assertLess(time.monotonic(), deadline, f"node B never queued: {b}")
                time.sleep(0.01)

        a = self.run_while_node_a_holds_the_lock(send_b_and_wait_until_it_queues)
        b_thread.join(WAIT)
        self.assertFalse(b_thread.is_alive(), "node B did not finish")
        self.assertEqual(b.get("status"), 200, b)

        self.assertIn("a line of node A", a["stderr"])
        self.assertNotIn("[sandbox /exec]", a["stderr"])
        self.assertNotIn("[sandbox /exec]", b["body"]["stderr"])
        # The line is still written, to the process's own stderr.
        self.assertIn("[sandbox /exec] received  node=NODE_B", self.server_log.getvalue())

    def test_a_javascript_node_run_meanwhile_logs_outside_its_stderr(self):
        js = {}

        def run_a_javascript_node():
            thread = self.post("/execJs", {
                "code": "return 40 + 2;",
                "file_path": "",
                "nodeType": "NODE_JS",
                "dataType": "",
                "session_id": "session-js",
                "save_dataset": False,
            }, js)
            # JavaScript nodes take no lock, so this one runs to its end while
            # node A still holds the lock.
            thread.join(WAIT)
            self.assertFalse(thread.is_alive(), "the JavaScript node did not finish")

        a = self.run_while_node_a_holds_the_lock(run_a_javascript_node)
        self.assertEqual(js.get("status"), 200, js)
        self.assertTrue(js["body"]["output"]["path"], js)

        self.assertIn("a line of node A", a["stderr"])
        self.assertNotIn("[sandbox /execJs]", a["stderr"])
        self.assertNotIn("[execJs]", a["stderr"])
        log = self.server_log.getvalue()
        self.assertIn("[sandbox /execJs] received  node=NODE_JS", log)
        self.assertIn("[execJs] starting Node.js  node=NODE_JS", log)
