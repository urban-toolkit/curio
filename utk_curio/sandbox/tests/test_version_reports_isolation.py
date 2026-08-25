"""``/version`` reports the isolation mode actually in force.

The UI's version badge shows this, so it has to be the *resolved* mode rather
than the requested one. `CURIO_ISOLATION=auto` resolves to `off`; a `fork` on a
platform that cannot support it degrades to `off` on a local launch. A badge
that echoed the request would tell an operator their instance was isolated when
it was not, which is worse than showing nothing.

The route stays un-gated, alongside `/live` and `/health`
(`test_sandbox_auth.py::OPEN_ROUTES` pins that), because the backend reads it
to answer the browser and it discloses nothing a caller could not infer by
watching whether node code can open a socket.

Run:  pytest utk_curio/sandbox/tests/test_version_reports_isolation.py -v
"""

import os
import unittest
from unittest import mock

from utk_curio.sandbox.app import api, app
from utk_curio.sandbox.isolation import mode as isolation_mode


class VersionIsolationTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        # The label is cached for the life of the process, so a test that did
        # not clear it would assert against whatever ran first.
        api._resolved_isolation_label = None

    tearDown = setUp

    def _version(self):
        response = self.client.get("/version")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_it_still_reports_the_version(self):
        from utk_curio import __version__

        self.assertEqual(self._version()["version"], __version__)

    def test_auto_is_reported_as_off_not_as_auto(self):
        """The badge must not show a mode nobody is running in."""
        with mock.patch.dict(os.environ, {isolation_mode.MODE_ENV: "auto"}):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

    def test_off_is_reported_as_off(self):
        with mock.patch.dict(os.environ, {isolation_mode.MODE_ENV: "off"}):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

    def test_fork_is_reported_only_when_it_resolved_to_fork(self):
        """A requested fork that degraded must not be reported as isolated."""
        with mock.patch.object(
            isolation_mode, "resolve_from_environment",
            return_value=(isolation_mode.OFF, "degraded on this platform"),
        ):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

        api._resolved_isolation_label = None
        with mock.patch.object(
            isolation_mode, "resolve_from_environment",
            return_value=(isolation_mode.FORK, None),
        ):
            self.assertEqual(self._version()["isolation"], isolation_mode.FORK)

    def test_an_unavailable_configuration_says_so(self):
        """Neither 'isolated' nor a bare 'off' would be honest here."""
        with mock.patch.object(
            isolation_mode, "resolve_from_environment",
            side_effect=isolation_mode.IsolationUnavailable("no seccomp"),
        ):
            self.assertEqual(self._version()["isolation"], "unavailable")

    def test_the_mode_is_resolved_once(self):
        """Every page load hits this route; resolution probes the platform."""
        with mock.patch.object(
            isolation_mode, "resolve_from_environment",
            return_value=(isolation_mode.OFF, None),
        ) as resolve:
            self._version()
            self._version()
            self._version()
            self.assertEqual(resolve.call_count, 1)


if __name__ == "__main__":
    unittest.main()
