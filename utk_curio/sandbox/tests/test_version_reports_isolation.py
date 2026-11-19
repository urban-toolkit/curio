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

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest.mock

from utk_curio.sandbox.app import api, app
from utk_curio.sandbox.isolation import mode as isolation_mode

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


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
        with unittest.mock.patch.dict(os.environ, {isolation_mode.MODE_ENV: "auto"}):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

    def test_off_is_reported_as_off(self):
        with unittest.mock.patch.dict(os.environ, {isolation_mode.MODE_ENV: "off"}):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

    def test_fork_is_reported_only_when_it_resolved_to_fork(self):
        """A requested fork that degraded must not be reported as isolated."""
        with unittest.mock.patch.object(
            isolation_mode, "resolve_from_environment",
            return_value=(isolation_mode.OFF, "degraded on this platform"),
        ):
            self.assertEqual(self._version()["isolation"], isolation_mode.OFF)

        api._resolved_isolation_label = None
        with unittest.mock.patch.object(
            isolation_mode, "resolve_from_environment",
            return_value=(isolation_mode.FORK, None),
        ):
            self.assertEqual(self._version()["isolation"], isolation_mode.FORK)

    def test_an_unavailable_configuration_says_so(self):
        """Neither 'isolated' nor a bare 'off' would be honest here."""
        with unittest.mock.patch.object(
            isolation_mode, "resolve_from_environment",
            side_effect=isolation_mode.IsolationUnavailable("no seccomp"),
        ):
            self.assertEqual(self._version()["isolation"], "unavailable")

    def test_the_mode_is_resolved_once(self):
        """Every page load hits this route; resolution probes the platform."""
        with unittest.mock.patch.object(
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
        with unittest.mock.patch.object(api, "_isolation_label", lambda: "fork"):
            body = self._version()
        self.assertEqual(body["isolation"], "fork")
        self.assertEqual(body["isolation_active"], "off")

    def test_the_resolved_field_is_still_reported(self):
        """The badge and the boot-time check both read it; do not break them."""
        api._isolation_state = None
        self.assertIn("isolation", self._version())


class MemoryLimitTestCase(unittest.TestCase):
    """``/version`` and ``/monitor`` name the memory limit isolated nodes run
    under: ``cgroup``, ``address space`` (and, on ``/monitor``, why not a
    cgroup), or ``none`` where nodes run in the sandbox's process.

    A deploy reads ``/version`` before any node has run. The sandbox server
    lays out the container's cgroups as it starts, so its answer is the
    outcome (``MemoryLimitAtTheSandboxsStartTestCase``). In a process that
    laid nothing out, as this suite's app, it is what the container allows.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        api._resolved_isolation_label = None

    tearDown = setUp

    def _get(self, route):
        response = self.client.get(route)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_nodes_that_run_in_the_sandbox_have_none(self):
        with unittest.mock.patch.object(api, "_isolation_label", lambda: "off"):
            self.assertEqual(self._get("/version")["memory_limit"], "none")
            monitor = self._get("/monitor")
        self.assertEqual((monitor["memory_limit"], monitor["memory_limit_reason"]), ("none", None))

    def test_isolated_nodes_have_what_their_zygote_gives_them(self):
        from utk_curio.sandbox.isolation import lifecycle, node_cgroups

        for kind, reason in ((node_cgroups.CGROUP, None), (node_cgroups.ADDRESS_SPACE, "read-only")):
            with unittest.mock.patch.object(api, "_isolation_label", lambda: "fork"), \
                    unittest.mock.patch.object(lifecycle, "memory_limit", return_value=(kind, reason)):
                self.assertEqual(self._get("/version")["memory_limit"], kind)
                monitor = self._get("/monitor")
            self.assertEqual(monitor["memory_limit"], kind)
            self.assertEqual(monitor["memory_limit_reason"], node_cgroups.REASONS.get(reason))

    def test_before_a_zygote_starts_it_is_what_the_container_allows(self):
        from utk_curio.sandbox.isolation import lifecycle, node_cgroups

        self.assertIsNone(lifecycle._memory, "a zygote of another test is still running")
        with unittest.mock.patch.object(api, "_isolation_label", lambda: "fork"):
            with unittest.mock.patch.object(node_cgroups, "predicted", return_value=None):
                self.assertEqual(self._get("/version")["memory_limit"], "cgroup")
            with unittest.mock.patch.object(node_cgroups, "predicted", return_value="read-only"):
                self.assertEqual(self._get("/version")["memory_limit"], "address space")
                self.assertEqual(self._get("/monitor")["memory_limit_reason"],
                                 node_cgroups.REASONS["read-only"])


#: Starts the sandbox server as a deployment does (``python -m
#: utk_curio.sandbox.server``, fork isolation) in a container whose cgroups
#: can hold isolated nodes: ``node_cgroups.unavailable`` says nothing against
#: them, and ``node_cgroups.lay_out`` and ``node_cgroups.try_a_place`` stand in
#: for the kernel's answers to the layout and to a run's cgroup, of which the
#: first argument names the one that fails (``layout``, ``place`` or
#: ``nothing``). Flask.run stands in for serving: it asks /version and
#: /monitor what the first request would get, and prints it as one
#: ``RESULT`` line of JSON.
_START_SCRIPT = textwrap.dedent("""
    import errno
    import json
    import runpy
    import sys

    import flask

    from utk_curio.sandbox.isolation import lifecycle, node_cgroups

    failing = sys.argv[1]
    made = []

    def lay_out(root=node_cgroups.ROOT):
        made.append("layout")
        if failing == "layout":
            raise OSError(errno.EBUSY, "Device or resource busy", root + "/cgroup.subtree_control")

    def try_a_place(memory_mb, root=node_cgroups.ROOT):
        made.append(f"a place at {memory_mb} MB")
        if failing == "place":
            raise OSError(errno.EAGAIN, "Resource temporarily unavailable", root + "/nodes/1")

    node_cgroups.unavailable = lambda **_: None
    node_cgroups.lay_out = lay_out
    node_cgroups.try_a_place = try_a_place
    seen = {}

    def serve(self, *args, **kwargs):
        client = self.test_client()
        seen["version"] = client.get("/version").get_json()
        monitor = client.get("/monitor")
        seen["monitor"] = [monitor.status_code, (monitor.get_json() or {}).get("memory_limit_reason")]
        seen["made"] = made
        seen["zygote"] = lifecycle._process is not None

    flask.Flask.run = serve
    runpy.run_module("utk_curio.sandbox.server", run_name="__main__", alter_sys=True)
    print("RESULT " + json.dumps(seen))
""")


class MemoryLimitAtTheSandboxsStartTestCase(unittest.TestCase):
    """The sandbox lays out the container's cgroups as it starts, and tries
    a run's, before it serves, so /version and /monitor say the outcome
    before any node runs, and a deploy that fails unless /version says
    ``cgroup`` checks what its nodes get.

    Before, the layout waited for the first zygote's start, which the first
    isolated run makes, and a run's cgroup for a run, and until then /version
    said what the container would allow: a layout that failed, or cgroups
    that could not hold a run, read ``cgroup`` until a node ran.
    """

    def _start(self, failing):
        """What the sandbox's first request gets, and the sandbox's log, as it
        starts in a container where the layout or a run's cgroup fails, or
        neither does (*failing*)."""
        with tempfile.TemporaryDirectory() as launch:
            data = os.path.join(launch, "data")
            os.makedirs(data)
            # Nothing of this process's own stack: the start hardens the
            # launch folder and the shared data, and those are the temporary
            # folder's.
            environ = {name: value for name, value in os.environ.items()
                       if not name.startswith(("CURIO_", "FLASK_", "WERKZEUG_"))}
            environ.update({
                "CURIO_ISOLATION": "fork",
                "CURIO_NO_AUTH": "1",
                "FLASK_USE_RELOADER": "0",
                "CURIO_LAUNCH_CWD": launch,
                "CURIO_SHARED_DATA": data,
                "CURIO_EXEC_MEMORY_MB": "4096",
                "PYTHONPATH": os.pathsep.join(p for p in (REPO_ROOT, os.environ.get("PYTHONPATH")) if p),
            })
            result = subprocess.run(
                [sys.executable, "-c", _START_SCRIPT, failing],
                cwd=REPO_ROOT, env=environ, capture_output=True, text=True, timeout=300,
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
        self.assertTrue(
            result.returncode == 0 and lines,
            f"the sandbox did not reach serving (exit {result.returncode}):\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}",
        )
        seen = json.loads(lines[-1][len("RESULT "):])
        # Before any node: an isolated sandbox whose zygote has not started.
        self.assertEqual(seen["version"]["isolation"], "fork", f"{seen}\n{result.stderr[-2000:]}")
        self.assertEqual(seen["version"]["isolation_active"], "pending", seen)
        self.assertFalse(seen["zygote"], f"a zygote started before any node ran: {seen}")
        self.assertEqual(seen["monitor"][0], 200, seen)
        return seen, result.stderr

    def test_a_layout_that_fails_is_reported_by_version_before_any_node_runs(self):
        from utk_curio.sandbox.isolation import node_cgroups

        seen, log = self._start("layout")
        self.assertEqual(
            seen["version"]["memory_limit"], "address space",
            "/version said the nodes run in a cgroup before any node ran, though the "
            f"container's cgroups could not be laid out: {seen}\n{log[-2000:]}",
        )
        self.assertEqual(seen["monitor"][1], node_cgroups.REASONS["layout"], seen)
        self.assertEqual(seen["made"], ["layout"], f"a run's cgroup was tried after a failed layout: {seen}")
        self.assertIn("[isolation] the container's cgroups could not be laid out:", log)
        self.assertIn("[isolation] node memory: the address-space cap", log)

    def test_cgroups_that_cannot_hold_a_run_are_reported_by_version_before_any_node_runs(self):
        from utk_curio.sandbox.isolation import node_cgroups

        seen, log = self._start("place")
        self.assertEqual(
            seen["version"]["memory_limit"], "address space",
            "/version said the nodes run in a cgroup before any node ran, though a run's "
            f"cgroup could not be made: {seen}\n{log[-2000:]}",
        )
        self.assertEqual(seen["monitor"][1], node_cgroups.REASONS["places"], seen)
        self.assertEqual(seen["made"], ["layout", "a place at 4096 MB"], seen)
        self.assertIn("[isolation] a run's cgroup could not be made:", log)
        self.assertIn("[isolation] node memory: the address-space cap", log)

    def test_the_sandbox_lays_out_the_containers_cgroups_and_tries_a_runs_before_it_serves(self):
        seen, log = self._start("nothing")
        self.assertEqual(
            seen["made"], ["layout", "a place at 4096 MB"],
            "the sandbox began serving without laying out the container's cgroups and trying "
            f"a run's, so /version said what they would give: {seen}\n{log[-2000:]}",
        )
        self.assertEqual(seen["version"]["memory_limit"], "cgroup", seen)
        self.assertIsNone(seen["monitor"][1], seen)
        self.assertIn("[isolation] node memory: a cgroup limit of 4096 MB", log)
