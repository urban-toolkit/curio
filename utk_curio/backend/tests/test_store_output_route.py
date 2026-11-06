"""``/storeOutput``: rows a node made in the browser are kept as an output (#1333).

A node that hands on rows as they are reaches a chart but never a Python or
JavaScript node, which read only a stored output. The node asks the backend to
keep its rows; the backend asks the sandbox's ``/artifacts/store`` to keep them
under the caller's session, the one the caller's runs are tagged with, and
hands back the sandbox's answer: the reference, or a refusal with its reason.
The sandbox's own checks are in ``sandbox/tests/test_stored_rows.py``.
"""

import unittest
from unittest import mock

from utk_curio.backend.app import create_app
from utk_curio.backend.app.api import routes
from utk_curio.backend.tests._unit_fixtures import TestConfig

ROWS = {"dataType": "dataframe", "data": {"name": ["Alpha", "Bravo"], "height": [30, 24]}}


class Reply:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class StoreOutputRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.asked = []
        self.reply = Reply(200, {"output": {"path": "1792169042468_bd44c99d", "dataType": "dataframe"}})

        def fake_sandbox_call(method, path, *, label, timeout, **kwargs):
            self.asked.append((method, path, kwargs.get("json")))
            return self.reply

        patched = mock.patch.object(routes, "_sandbox_call", fake_sandbox_call)
        patched.start()
        self.addCleanup(patched.stop)

    def _signed_in(self):
        from utk_curio.backend.app.users import dependencies

        for target, name, value in (
            (dependencies, "get_current_user", lambda *a, **k: mock.Mock(id=1)),
            (routes, "get_current_token", lambda: "the-callers-token"),
        ):
            patched = mock.patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def test_the_rows_are_kept_under_the_callers_session_and_the_reference_comes_back(self):
        self._signed_in()

        response = self.client.post("/storeOutput", json={"value": ROWS, "nodeType": "curio.builtin/spatial-join@1"})

        self.assertEqual(self.asked, [(
            "post", "/artifacts/store",
            {"sessionId": "the-callers-token", "value": ROWS, "nodeType": "curio.builtin/spatial-join@1"},
        )])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.get_json(), {"output": {"path": "1792169042468_bd44c99d", "dataType": "dataframe"}})

    def test_a_refusal_keeps_its_status_and_its_reason(self):
        self._signed_in()
        self.reply = Reply(400, {"error": "The output must be an object whose dataType is dataframe or geodataframe."})

        response = self.client.post("/storeOutput", json={"value": {"dataType": "dict", "data": {}}})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {
            "error": "The output must be an object whose dataType is dataframe or geodataframe.",
        })

    def test_a_reply_that_is_not_json_says_the_sandbox_could_not_keep_it(self):
        self._signed_in()
        self.reply = Reply(500, ValueError("not json"))

        response = self.client.post("/storeOutput", json={"value": ROWS})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "The sandbox could not keep the output (HTTP 500)."})

    def test_without_a_sign_in_nothing_is_kept(self):
        response = self.client.post("/storeOutput", json={"value": ROWS})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.asked, [])
