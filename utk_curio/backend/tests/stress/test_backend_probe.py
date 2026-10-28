"""What the probe reads of the backend, where it runs (``backend_probe.py``).

It finds the backend's process by the module the launcher starts it as, the
reloader's child when there is one; the backend's state root as
``user_storage.curio_root`` does, from the backend's own environment; and each
shared dataflow's doc logs, a checkpoint and the updates of each day, with
their sizes. The harness runs the file's own source with ``python -c`` where
the backend runs, so it must run as a script with nothing of Curio's.
Names are imported in each test, so a checkout without them fails test by test.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FindingTheBackendTest(unittest.TestCase):
    def test_the_backend_is_the_process_serving_backend_server(self):
        from utk_curio.backend.tests.stress.backend_probe import pick_backend

        processes = [
            (10, 1, ["python", "curio.py", "start", "all", "--deploy"]),
            (11, 10, ["/usr/local/bin/python", "-u", "-m", "backend.server"]),
            (12, 10, ["/usr/local/bin/python", "-u", "-m", "sandbox.server"]),
        ]
        self.assertEqual(pick_backend(processes, own_pid=99), 11)

    def test_with_the_reloader_its_child_serves(self):
        from utk_curio.backend.tests.stress.backend_probe import pick_backend

        processes = [
            (20, 1, ["python", "-u", "-m", "backend.server"]),
            (21, 20, ["python", "-u", "-m", "backend.server"]),
        ]
        self.assertEqual(pick_backend(processes, own_pid=99), 21)

    def test_the_probe_itself_and_other_processes_are_not_the_backend(self):
        from utk_curio.backend.tests.stress.backend_probe import is_backend, pick_backend

        own = (30, 1, ["python", "-c", "... -m backend.server ...", "p1"])
        self.assertIsNone(pick_backend([own], own_pid=30))
        self.assertFalse(is_backend(["python", "-m", "pytest", "backend.server"]))
        self.assertTrue(is_backend(["python", "utk_curio/backend/server.py"]))
        self.assertTrue(is_backend(["python", "-m", "utk_curio.backend.server"]))
        self.assertIsNone(pick_backend([], own_pid=1))


class TheDocFilesTest(unittest.TestCase):
    PROJECT = "0f8fad5b-d9cb-469f-a165-70867728950e"
    DOC = "a" * 32

    def _tree(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def test_the_state_root_follows_the_backends_environment(self):
        from utk_curio.backend.tests.stress.backend_probe import state_roots

        self.assertEqual(state_roots({"CURIO_LAUNCH_CWD": "/app"}, "/app/utk_curio"),
                         [Path("/app/.curio"), Path("/app/.curio/test")])
        self.assertEqual(state_roots({}, "/srv"), [Path("/srv/.curio"), Path("/srv/.curio/test")])
        self.assertEqual(state_roots({"CURIO_STATE_DIR": "/state"}, "/app/utk_curio"),
                         [Path("/state"), Path("/state/test")])
        self.assertEqual(state_roots({"CURIO_STATE_DIR": "rel"}, "/app"),
                         [Path("/app/rel"), Path("/app/rel/test")])

    def test_each_days_checkpoint_and_updates_are_listed_with_their_sizes(self):
        from utk_curio.backend.tests.stress.backend_probe import doc_files

        root = self._tree() / ".curio"
        log = root / "test" / "users" / "7" / "projects" / self.PROJECT / "ydoc" / self.DOC
        log.mkdir(parents=True)
        (log / "2026-10-28.bin").write_bytes(b"x" * 100)
        (log / "2026-10-28.updates").write_bytes(b"x" * 2500)
        (log / "2026-10-29.bin").write_bytes(b"x" * 300)
        (log.parent.parent / "ydoc.json").write_text("{}", encoding="utf-8")
        other = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"
        found = doc_files([root, root / "test"], [self.PROJECT, other, "../../etc"])
        self.assertEqual(found, {
            self.PROJECT: [
                {"doc": self.DOC, "day": "2026-10-28", "bin_bytes": 100, "updates_bytes": 2500},
                {"doc": self.DOC, "day": "2026-10-29", "bin_bytes": 300, "updates_bytes": None},
            ],
            other: [],
        })


class TheProbeRunsAsAScriptTest(unittest.TestCase):
    def test_its_source_runs_alone_with_python_c_and_prints_one_reading(self):
        """As ``docker exec <container> python -c`` runs it: nothing of
        Curio's to import there, one JSON object out, an error or a reading."""
        from utk_curio.backend.tests.stress import backend_probe

        source = Path(backend_probe.__file__).read_text(encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True,
                              text=True, timeout=60, cwd=tempfile.gettempdir())
        self.assertEqual(done.returncode, 0, done.stderr)
        reading = json.loads(done.stdout)
        self.assertTrue("error" in reading or {"pid", "threads", "rss_bytes"} <= set(reading), reading)

    def test_a_reading_that_failed_says_why(self):
        from utk_curio.backend.tests.stress.backend_probe import BackendProbe, ProbeError

        # Python runs the first -c it is given: the probe's own source, after
        # it, is then only an argument, and this one script answers instead.
        stand_in = [sys.executable, "-I", "-c", "print('{\"error\": \"no backend\"}')"]
        with self.assertRaises(ProbeError) as raised:
            BackendProbe(stand_in).read()
        self.assertIn("no backend", str(raised.exception))
        with self.assertRaises(ProbeError):
            BackendProbe(["/nonexistent/python"]).read()


if __name__ == "__main__":
    unittest.main()
