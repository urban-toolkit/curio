"""``/version`` reports the isolation mode actually in force.

The UI's version badge shows this, so it has to be the *resolved* mode rather
than the requested one. `CURIO_ISOLATION=auto` resolves to `off`; a `fork` on a
platform that cannot support it degrades to `off` on a local launch. A badge
that echoed the request would tell an operator their instance was isolated when
it was not, which is worse than showing nothing.

`isolation_active` is the companion field, and it answers a different
question: not "what did this instance resolve to" but "what did execution
actually do". The two can disagree, because the zygote is started lazily on
the first `/exec` and a spawn that fails degrades to in-process for the life
of the process without moving the resolved label.

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


class ExecutionActuallyDidTestCase(unittest.TestCase):
    """``/version`` has to distinguish the intent from the outcome.

    The ``isolation`` field is the *resolved mode*, computed from the
    environment and the platform's capabilities. It is settled before any node
    runs, so a CI job that boots an isolated stack and checks it has verified a
    configuration, not a workload.

    That gap is reachable. The zygote is started lazily on the first ``/exec``,
    and a spawn that fails degrades to in-process for the life of the process
    rather than failing the request - deliberately, because the node still has
    to run. The resolved label does not move when that happens. Before
    ``isolation_active``, a stack in that state reported ``fork`` and ran every
    node in-process, and nothing an operator or a CI job could ask would say
    so.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        # Both caches, for the same reason the case above clears one: they
        # outlive a test and the next one would assert against leftovers.
        self._previous = api._isolation_state
        api._resolved_isolation_label = None

    def tearDown(self):
        api._isolation_state = self._previous
        api._resolved_isolation_label = None

    def _version(self):
        response = self.client.get("/version")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_before_anything_runs_it_reports_pending_not_off(self):
        """``off`` here would be a lie, and the damaging direction of one.

        A CI job asserting "not off" immediately after boot would pass for the
        wrong reason forever, because nothing has executed yet.
        """
        api._isolation_state = None
        self.assertEqual(self._version()["isolation_active"], "pending")

    def test_a_dispatched_execution_reports_fork(self):
        api._isolation_state = ("runner-sentinel", "config-sentinel")
        self.assertEqual(self._version()["isolation_active"], "fork")

    def test_an_in_process_execution_reports_off(self):
        api._isolation_state = False
        self.assertEqual(self._version()["isolation_active"], "off")

    def test_a_failed_zygote_is_visible_even_though_the_mode_says_fork(self):
        """The whole point: the two fields disagree, and both are truthful.

        This is the shape of a silently degraded isolated stack - resolved
        ``fork``, executing in-process - which is exactly what an isolated CI
        job must not mistake for success.
        """
        api._isolation_state = False
        with mock.patch.object(api, "_isolation_label", lambda: "fork"):
            body = self._version()
        self.assertEqual(body["isolation"], "fork")
        self.assertEqual(body["isolation_active"], "off")

    def test_the_resolved_field_is_still_reported(self):
        """The badge and the boot-time check both read it; do not break them."""
        api._isolation_state = None
        self.assertIn("isolation", self._version())
