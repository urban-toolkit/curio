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


def _burn_cpu() -> None:
    """Run Python for a few tenths of a second: more than the clock tick CPU
    times are counted in."""
    total = 0
    for value in range(3_000_000):
        total += value * value


class TheCpuReadingsTest(unittest.TestCase):
    def test_a_process_reading_has_its_cpu_seconds_user_plus_system(self):
        """As the probe reads the backend: here, this very process."""
        import psutil

        from utk_curio.backend.tests.stress.backend_probe import process_reading

        before = process_reading(psutil.Process())
        _burn_cpu()
        after = process_reading(psutil.Process())
        self.assertEqual(set(before), {"pid", "threads", "rss_bytes", "cpu_seconds"})
        self.assertGreater(after["cpu_seconds"], before["cpu_seconds"])
        times = psutil.Process().cpu_times()
        self.assertLessEqual(after["cpu_seconds"], round(times.user + times.system, 3))

    def test_each_reading_carries_the_harness_cpu_with_or_without_a_backend(self):
        import time

        from utk_curio.backend.tests.stress.backend_probe import (
            ProbeError, harness_cpu_seconds, reading_now,
        )

        class Up:
            def read(self, project_ids=()):
                return {"threads": 3, "rss_bytes": 1, "cpu_seconds": 2.0}

        class Down:
            def read(self, project_ids=()):
                raise ProbeError("no process here serves -m backend.server")

        began = time.monotonic()
        reading, problem = reading_now(Up())
        ended = time.monotonic()
        self.assertIsNone(problem)
        self.assertTrue(began <= reading["at"] <= reading["harness_at"] <= ended, reading)
        self.assertEqual(reading["cpu_seconds"], 2.0)

        reading, problem = reading_now(Down())
        self.assertIn("no process", problem)
        self.assertEqual(set(reading), {"harness_at", "harness_cpu_seconds"})

        reading, problem = reading_now(None, started=time.monotonic())
        self.assertIsNone(problem)
        self.assertEqual(set(reading), {"harness_at", "harness_cpu_seconds", "t"})

        before = harness_cpu_seconds()
        _burn_cpu()
        self.assertGreater(harness_cpu_seconds(), before)

    def test_the_harness_cpu_counts_its_worker_processes(self):
        """The users run in worker processes: a running one is read as it
        runs, an ended one by what it reported."""
        import os

        from utk_curio.backend.tests.stress.backend_probe import (
            forget_worker, harness_cpu_seconds, process_cpu_seconds, track_worker, worker_finished,
        )

        ended = 2 ** 22 + 7  # a pid no process holds here
        before = harness_cpu_seconds()
        track_worker(ended)
        worker_finished(ended, 5.0)
        try:
            self.assertGreaterEqual(harness_cpu_seconds() - before, 5.0)
            self.assertLess(harness_cpu_seconds() - before, 5.0 + 1.0)
        finally:
            forget_worker(ended)
        # A running worker, read through psutil: this very process, counted twice.
        track_worker(os.getpid())
        try:
            self.assertGreaterEqual(harness_cpu_seconds(), 2 * process_cpu_seconds() - 0.05)
        finally:
            forget_worker(os.getpid())

    def test_without_a_probe_the_sampler_reads_the_harness_alone(self):
        import time

        from utk_curio.backend.tests.stress.backend_probe import Sampler

        sampler = Sampler(None, 0.05).start()
        time.sleep(0.3)
        samples = sampler.stop()
        self.assertGreaterEqual(len(samples), 2)
        for sample in samples:
            self.assertEqual(set(sample), {"harness_at", "harness_cpu_seconds", "t"})
        self.assertIsNone(sampler.problem)


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
