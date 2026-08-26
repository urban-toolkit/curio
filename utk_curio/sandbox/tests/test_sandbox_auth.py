"""The sandbox refuses code execution to callers without the shared secret.

The sandbox runs arbitrary user code. Before this suite existed, POST /exec and
POST /install were reachable by anyone who could open the port, and the Docker
image published that port. These tests pin the guard so it cannot regress:
which routes require the token, which stay open for health checks, what a
hosted instance does when the token is missing, and that no CORS header invites
a browser to call any of it.
"""

import os
import unittest
from unittest import mock

from utk_curio.sandbox.app import app
from utk_curio.sandbox.app import auth


TOKEN = "test-sandbox-token"

# Guarded routes, with a minimal request each. The bodies are deliberately
# incomplete: authentication must be rejected *before* the handler validates
# anything, so a 401 here proves the decorator ran first.
GUARDED = (
    ("post", "/exec", {"json": {"code": "    return 1\n", "file_path": "",
                                "nodeType": "curio.builtin/computation-analysis",
                                "dataType": ""}}),
    ("post", "/execJs", {"json": {"code": "return 1;", "file_path": "",
                                  "nodeType": "curio.builtin/computation-analysis",
                                  "dataType": ""}}),
    ("post", "/install", {"json": {"packages": ["inflection"]}}),
    ("get", "/get", {"query_string": {"fileName": "does-not-exist"}}),
)

OPEN_ROUTES = (("get", "/live"), ("get", "/version"), ("get", "/health"))


class SandboxAuthTestCase(unittest.TestCase):
    """Shared client plus a clean auth module state per test."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        # _warned is module-level and would leak the "already warned" state
        # between tests, making the warn-once assertion order-dependent.
        auth._warned = False


class TestGuardedRoutes(SandboxAuthTestCase):

    def test_rejects_a_caller_with_no_token(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            for method, path, kwargs in GUARDED:
                with self.subTest(path=path):
                    response = getattr(self.client, method)(path, **kwargs)
                    self.assertEqual(response.status_code, 401, path)
                    self.assertEqual(
                        response.get_json()["error"], "sandbox_unauthorized"
                    )

    def test_rejects_a_wrong_token(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            for method, path, kwargs in GUARDED:
                with self.subTest(path=path):
                    response = getattr(self.client, method)(
                        path, headers={auth.TOKEN_HEADER: "wrong-token"}, **kwargs
                    )
                    self.assertEqual(response.status_code, 401, path)

    def test_rejects_a_wrong_length_token_rather_than_raising(self):
        """A short token must be a clean 401, not a 500 from the comparison.

        This is the cheap, deterministic way to assert the constant-time
        comparison is wired correctly; timing it would be flaky.
        """
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            response = self.client.post(
                "/exec",
                headers={auth.TOKEN_HEADER: "x"},
                json={"code": "    return 1\n", "file_path": "",
                      "nodeType": "curio.builtin/computation-analysis",
                      "dataType": ""},
            )
        self.assertEqual(response.status_code, 401)

    def test_accepts_the_configured_token(self):
        """A correct token gets past the decorator and into the handler.

        Asserted as 'not 401' rather than 200: /get on a missing artifact is a
        legitimate 500, and /install is 403 unless runtime install is enabled.
        Either way the request was authenticated, which is what this pins.
        """
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            for method, path, kwargs in GUARDED:
                with self.subTest(path=path):
                    response = getattr(self.client, method)(
                        path, headers={auth.TOKEN_HEADER: TOKEN}, **kwargs
                    )
                    self.assertNotEqual(response.status_code, 401, path)


class TestUnauthenticatedFallback(SandboxAuthTestCase):

    def test_absent_token_permits(self):
        """Local dev and the unit suites have no launcher to mint a token."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(auth.TOKEN_ENV, None)
            with mock.patch.object(auth, "_warn_once") as warn:
                for _ in range(3):
                    response = self.client.get(
                        "/get", query_string={"fileName": "does-not-exist"}
                    )
                    self.assertNotEqual(response.status_code, 401)
                self.assertEqual(warn.call_count, 3)

    def test_the_unauthenticated_warning_is_printed_only_once(self):
        """Every guarded request calls it; the operator should see one line."""
        auth._warned = False
        with mock.patch("builtins.print") as printed:
            auth._warn_once()
            auth._warn_once()
            auth._warn_once()
        self.assertEqual(printed.call_count, 1)
        self.assertTrue(auth._warned)

    def test_blank_token_counts_as_unset(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: "   "}):
            self.assertIsNone(auth.get_expected_token())


class TestStartupGuard(SandboxAuthTestCase):
    """A hosted instance must not boot with execution routes unguarded."""

    def test_hosted_without_a_token_refuses_to_start(self):
        with mock.patch.dict(os.environ, {"CURIO_NO_AUTH": "0"}):
            os.environ.pop(auth.TOKEN_ENV, None)
            with self.assertRaises(RuntimeError) as caught:
                auth.require_startup_token()
        self.assertIn(auth.TOKEN_ENV, str(caught.exception))

    def test_hosted_with_a_token_starts(self):
        with mock.patch.dict(os.environ, {"CURIO_NO_AUTH": "0",
                                          auth.TOKEN_ENV: TOKEN}):
            auth.require_startup_token()  # must not raise

    def test_local_without_a_token_starts(self):
        with mock.patch.dict(os.environ, {"CURIO_NO_AUTH": "1"}):
            os.environ.pop(auth.TOKEN_ENV, None)
            auth.require_startup_token()  # must not raise

    def test_hosted_mode_reads_curio_no_auth(self):
        for value, expected in (("0", True), ("false", True), ("off", True),
                                ("1", False), ("true", False)):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {"CURIO_NO_AUTH": value}):
                    self.assertEqual(auth.hosted_mode(), expected)


class TestRuntimeInstallGate(SandboxAuthTestCase):
    """POST /install is opt-in even for an authenticated caller."""

    def _post_install(self):
        return self.client.post(
            "/install",
            headers={auth.TOKEN_HEADER: TOKEN},
            json={"packages": ["inflection"]},
        )

    def test_disabled_when_unset(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            os.environ.pop("CURIO_ALLOW_RUNTIME_INSTALL", None)
            response = self._post_install()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "runtime_install_disabled")

    def test_explicitly_disabled(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN,
                                          "CURIO_ALLOW_RUNTIME_INSTALL": "0"}):
            self.assertEqual(self._post_install().status_code, 403)

    def test_enabled_reaches_the_handler(self):
        """With the gate open the request is validated, not refused.

        pip is not actually invoked: an empty package list short-circuits at
        the handler's own 400, which proves we got past the gate without
        installing anything.
        """
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN,
                                          "CURIO_ALLOW_RUNTIME_INSTALL": "1"}):
            response = self.client.post(
                "/install",
                headers={auth.TOKEN_HEADER: TOKEN},
                json={"packages": []},
            )
        self.assertEqual(response.status_code, 400)


class TestNoCorsHeaders(SandboxAuthTestCase):
    """No browser should be able to read a sandbox response.

    The sandbox is server-to-server only. The previous wildcard
    Access-Control-Allow-Origin let any page in the user's browser read
    responses from the service that executes code.
    """

    def test_open_routes_carry_no_cors_header(self):
        for method, path in OPEN_ROUTES:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path)
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
                self.assertNotIn("Access-Control-Allow-Methods", response.headers)

    def test_guarded_routes_carry_no_cors_header(self):
        with mock.patch.dict(os.environ, {auth.TOKEN_ENV: TOKEN}):
            response = self.client.post("/exec", json={})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
