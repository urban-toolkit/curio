"""Isolation degrades on a developer laptop and fails closed in production.

**This suite must run on Windows, not be skipped there.** CI is Linux-only
(.github/workflows/docker-compose.yml runs on a self-hosted linux runner), so
nothing else in the project ever exercises the Windows fallback path. If these
were gated behind a POSIX skip, a change that broke `curio start` on Windows
would ship unnoticed.

``resolve_mode`` takes its capabilities as an argument precisely so the whole
decision table can be driven from any host.
"""

import sys
import unittest
from unittest import mock

from utk_curio.sandbox.isolation import mode
from utk_curio.sandbox.isolation.mode import IsolationUnavailable


def caps(*, fork=True, rlimit=True, seccomp=True, linux=True, platform="linux"):
    return {
        "platform": platform,
        "fork": fork,
        "rlimit": rlimit,
        "seccomp": seccomp,
        "linux": linux,
    }


WINDOWS = caps(fork=False, rlimit=False, seccomp=False, linux=False, platform="win32")
MACOS = caps(fork=True, rlimit=True, seccomp=False, linux=False, platform="darwin")
LINUX_NO_SECCOMP = caps(seccomp=False)
LINUX_FULL = caps()


class TestLocalLaunchDegrades(unittest.TestCase):
    """A missing capability must never stop a developer working."""

    def test_windows_auto_is_off_and_silent(self):
        resolved, reason = mode.resolve_mode("auto", hosted=False, caps=WINDOWS)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNone(reason, "the default local path should not nag")

    def test_windows_explicit_fork_falls_back_with_a_reason(self):
        resolved, reason = mode.resolve_mode("fork", hosted=False, caps=WINDOWS)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNotNone(reason)
        self.assertIn("os.fork", reason)
        self.assertIn("in-process", reason)

    def test_macos_explicit_fork_falls_back_locally(self):
        """fork and rlimits exist; seccomp does not, but that only gates hosting."""
        resolved, _reason = mode.resolve_mode("fork", hosted=False, caps=MACOS)
        self.assertEqual(resolved, mode.FORK)

    def test_linux_local_auto_stays_off(self):
        """Local single-user work does not pay the isolation cost by default."""
        resolved, reason = mode.resolve_mode("auto", hosted=False, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNone(reason)

    def test_linux_local_explicit_fork_is_honoured(self):
        resolved, reason = mode.resolve_mode("fork", hosted=False, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.FORK)
        self.assertIsNone(reason)


class TestAutoIsOptInOnly(unittest.TestCase):
    """`auto` resolves to OFF everywhere, on purpose.

    Isolation is opt-in. Making `auto` isolate would silently move every hosted
    Linux instance onto the fork path the moment this shipped, and CI (Linux,
    --auth) would be the first to run it. When child.confine() has actually
    been exercised, these expectations change deliberately, together with the
    AUTO branch in mode.resolve_mode.
    """

    def test_hosted_auto_does_not_isolate_even_where_it_could(self):
        resolved, reason = mode.resolve_mode("auto", hosted=True, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNotNone(reason, "a hosted instance must be told it is exposed")
        self.assertIn("--isolation=fork", reason)

    def test_hosted_auto_does_not_raise_where_it_could_not_isolate(self):
        """CI runs Linux with --auth and no pyseccomp; it must still boot."""
        for capabilities in (WINDOWS, MACOS, LINUX_NO_SECCOMP):
            with self.subTest(platform=capabilities["platform"]):
                resolved, _reason = mode.resolve_mode(
                    "auto", hosted=True, caps=capabilities
                )
                self.assertEqual(resolved, mode.OFF)

    def test_the_hosted_warning_states_the_actual_risk(self):
        _resolved, reason = mode.resolve_mode("auto", hosted=True, caps=LINUX_FULL)
        self.assertIn("shell access", reason)


class TestExplicitForkFailsClosedWhenHosted(unittest.TestCase):
    """Asking for isolation and not getting it must not pass silently."""

    def test_windows_hosted_explicit_fork_refuses_to_start(self):
        with self.assertRaises(IsolationUnavailable) as caught:
            mode.resolve_mode("fork", hosted=True, caps=WINDOWS)
        self.assertIn("os.fork", str(caught.exception))

    def test_macos_hosted_refuses_because_seccomp_is_absent(self):
        """POSIX is not enough: without a syscall filter the child keeps network."""
        with self.assertRaises(IsolationUnavailable) as caught:
            mode.resolve_mode("fork", hosted=True, caps=MACOS)
        self.assertIn("Linux", str(caught.exception))

    def test_linux_hosted_without_pyseccomp_refuses(self):
        with self.assertRaises(IsolationUnavailable) as caught:
            mode.resolve_mode("fork", hosted=True, caps=LINUX_NO_SECCOMP)
        self.assertIn("pyseccomp", str(caught.exception))

    def test_linux_hosted_with_everything_isolates(self):
        resolved, reason = mode.resolve_mode("fork", hosted=True, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.FORK)
        self.assertIsNone(reason)

    def test_the_refusal_names_a_way_out(self):
        """An operator hitting this at 3am needs the next step in the message."""
        with self.assertRaises(IsolationUnavailable) as caught:
            mode.resolve_mode("fork", hosted=True, caps=WINDOWS)
        message = str(caught.exception)
        self.assertIn("--isolation=off", message)
        self.assertIn("Docker", message)


class TestExplicitOff(unittest.TestCase):

    def test_off_is_honoured_locally_and_silently(self):
        resolved, reason = mode.resolve_mode("off", hosted=False, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNone(reason)

    def test_off_on_a_hosted_instance_is_allowed_but_loud(self):
        """The operator asked for it; they should still see what they bought."""
        resolved, reason = mode.resolve_mode("off", hosted=True, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.OFF)
        self.assertIsNotNone(reason)
        self.assertIn("shell access", reason)


class TestInvalidInput(unittest.TestCase):

    def test_an_unknown_mode_is_rejected(self):
        for requested in ("sandbox", "true", "1", "fork-please"):
            with self.subTest(requested=requested):
                with self.assertRaises(IsolationUnavailable):
                    mode.resolve_mode(requested, hosted=False, caps=LINUX_FULL)

    def test_mode_is_case_and_space_insensitive(self):
        resolved, _ = mode.resolve_mode("  FORK ", hosted=False, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.FORK)

    def test_none_means_auto(self):
        resolved, _ = mode.resolve_mode(None, hosted=False, caps=LINUX_FULL)
        self.assertEqual(resolved, mode.OFF)


class TestEnvironmentReading(unittest.TestCase):

    def test_hosted_is_read_from_curio_no_auth(self):
        for value, expected in (("0", True), ("false", True), ("off", True),
                                ("1", False), ("true", False)):
            with self.subTest(value=value):
                _requested, hosted = mode.mode_from_environment(
                    {"CURIO_NO_AUTH": value}
                )
                self.assertEqual(hosted, expected)

    def test_mode_defaults_to_auto_when_unset(self):
        requested, hosted = mode.mode_from_environment({})
        self.assertEqual(requested, mode.AUTO)
        self.assertFalse(hosted)

    def test_resolve_from_environment_threads_both_values(self):
        with self.assertRaises(IsolationUnavailable):
            mode.resolve_from_environment(
                {"CURIO_ISOLATION": "fork", "CURIO_NO_AUTH": "0"}, caps=WINDOWS
            )


class TestWarnOnce(unittest.TestCase):

    def setUp(self):
        mode.reset_warning_state()

    def tearDown(self):
        mode.reset_warning_state()

    def test_the_reason_is_printed_once_across_many_executions(self):
        with mock.patch("builtins.print") as printed:
            for _ in range(5):
                mode.warn_once("falling back")
        self.assertEqual(printed.call_count, 1)

    def test_an_empty_reason_prints_nothing(self):
        with mock.patch("builtins.print") as printed:
            mode.warn_once(None)
            mode.warn_once("")
        self.assertEqual(printed.call_count, 0)


class TestExecStillWorksWhenIsolationIsUnavailable(unittest.TestCase):
    """The end-to-end shape of the fallback, through the real /exec route.

    This is the test that would have caught a broken Windows launch. Asking for
    isolation on a platform that cannot provide it must still execute the node,
    via the in-process path, and return the normal response.
    """

    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app import app

        cls.client = app.test_client()

    def setUp(self):
        from utk_curio.sandbox.app import api

        self._api = api
        self._previous = api._isolation_state
        api._isolation_state = None
        mode.reset_warning_state()

    def tearDown(self):
        self._api._isolation_state = self._previous
        mode.reset_warning_state()

    def _post(self):
        return self.client.post(
            "/exec",
            json={
                "code": "    return 6 * 7\n",
                "file_path": "",
                "nodeType": "curio.builtin/computation-analysis",
                "dataType": "",
                "save_dataset": False,
            },
        )

    def test_requesting_fork_on_an_unsupported_platform_still_runs_the_node(self):
        if sys.platform.startswith("linux"):
            self.skipTest("this asserts the *unsupported* platform path")
        with mock.patch.dict("os.environ", {"CURIO_ISOLATION": "fork",
                                            "CURIO_NO_AUTH": "1"}):
            response = self._post()
        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        self.assertEqual(body["stderr"], "")
        self.assertEqual(body["output"]["dataType"], "int")

    def test_the_default_path_is_unaffected(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("CURIO_ISOLATION", None)
            response = self._post()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.get_json()["stderr"], "")

    def test_an_invalid_mode_does_not_break_execution(self):
        """A typo in the flag must not take the sandbox down."""
        with mock.patch.dict("os.environ", {"CURIO_ISOLATION": "nonsense"}):
            response = self._post()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.get_json()["output"]["dataType"], "int")


class TestRealCapabilitiesOnThisHost(unittest.TestCase):
    """Sanity-check the probe against the platform actually running the suite."""

    def test_capabilities_match_the_platform(self):
        caps_here = mode.capabilities()
        self.assertEqual(caps_here["fork"], hasattr(sys.modules["os"], "fork"))
        self.assertEqual(caps_here["linux"], sys.platform.startswith("linux"))
        if sys.platform == "win32":
            self.assertFalse(caps_here["fork"], "Windows has no os.fork")
            self.assertFalse(caps_here["seccomp"])

    def test_this_host_resolves_without_raising_for_a_local_launch(self):
        """Whatever machine this runs on, a local launch must always work."""
        resolved, _reason = mode.resolve_mode("auto", hosted=False)
        self.assertIn(resolved, (mode.OFF, mode.FORK))


if __name__ == "__main__":
    unittest.main()
