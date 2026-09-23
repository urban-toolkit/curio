"""The execution lock counts its own contention, per call site.

A slot queue and a lock queue are indistinguishable from outside the process:
both make a request that takes a second when idle take minutes under load.
Raising ``CURIO_EXEC_PARALLELISM`` from 8 to 32 on the 100-user stress tier
changed total blocked time by 0.2%, which said the constraint was not the slot
count without saying what it was. These counters answered that: 18722s of the
tier's 24051s of waiting was this lock, 403.4s of its 407.6s of hold time was
artifact serving, and that is what the change alongside them removes.

(Percentiles are not the evidence here. /get's p50 ranged from 3.66s to 33.25s
across five runs including two that changed nothing, while these counters
reproduced within 3%.)

Runs everywhere: threads and a mutex, no fork and no sandbox.
"""

import threading
import time
import unittest

from utk_curio.sandbox.app.worker import _ExecLock


class ExecLockAccountingTest(unittest.TestCase):
    def setUp(self):
        self.lock = _ExecLock()

    def test_an_uncontended_hold_records_no_meaningful_wait(self):
        with self.lock.hold("isolated_persist"):
            pass
        entry = self.lock.snapshot()["labels"]["isolated_persist"]
        self.assertEqual(entry["acquisitions"], 1)
        self.assertLess(entry["wait_seconds"], 0.05)

    def test_a_blocked_acquisition_records_what_it_waited(self):
        """The number that matters: time spent queueing, not time holding."""
        holder_has_it = threading.Event()
        release = threading.Event()

        def holder():
            with self.lock.hold("isolated_persist"):
                holder_has_it.set()
                release.wait(5)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(holder_has_it.wait(5))

        def waiter():
            with self.lock.hold("exec_in_process"):
                pass

        blocked = threading.Thread(target=waiter)
        blocked.start()
        time.sleep(0.3)  # the waiter is now queued behind the holder
        release.set()
        thread.join(5)
        blocked.join(5)

        labels = self.lock.snapshot()["labels"]
        self.assertGreater(labels["exec_in_process"]["wait_seconds"], 0.2)
        self.assertGreater(labels["isolated_persist"]["held_seconds"], 0.2)
        # And the holder itself waited for nothing, so the two are not conflated.
        self.assertLess(labels["isolated_persist"]["wait_seconds"], 0.05)

    def test_call_sites_are_counted_apart(self):
        """Which call site is queueing is the whole point of labelling."""
        for label in ("isolated_persist", "isolated_persist", "exec_in_process"):
            with self.lock.hold(label):
                pass
        labels = self.lock.snapshot()["labels"]
        self.assertEqual(labels["isolated_persist"]["acquisitions"], 2)
        self.assertEqual(labels["exec_in_process"]["acquisitions"], 1)

    def test_the_plain_context_manager_still_works(self):
        """``with _exec_lock:`` is what three call sites and the tests use."""
        with self.lock:
            pass
        self.assertEqual(self.lock.snapshot()["labels"]["other"]["acquisitions"], 1)

    def test_the_lock_is_released_when_the_body_raises(self):
        """An exception inside a node run must not wedge the sandbox."""
        with self.assertRaises(ValueError):
            with self.lock.hold("exec_in_process"):
                raise ValueError("boom")
        acquired = self.lock._lock.acquire(blocking=False)
        self.assertTrue(acquired, "the lock stayed held after an exception")
        self.lock._lock.release()

    def test_waiting_is_a_gauge_of_who_is_queued_now(self):
        holder_has_it = threading.Event()
        release = threading.Event()

        def holder():
            with self.lock.hold("isolated_persist"):
                holder_has_it.set()
                release.wait(5)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(holder_has_it.wait(5))
        self.assertEqual(self.lock.snapshot()["waiting"], 0)

        let_waiters_go = threading.Event()

        def waiter():
            with self.lock.hold("isolated_persist"):
                let_waiters_go.wait(5)

        blocked = [threading.Thread(target=waiter) for _ in range(2)]
        for t in blocked:
            t.start()
        time.sleep(0.3)  # both are now queued behind the holder
        self.assertEqual(self.lock.snapshot()["waiting"], 2)

        release.set()
        thread.join(5)
        let_waiters_go.set()
        for t in blocked:
            t.join(5)
        self.assertEqual(self.lock.snapshot()["waiting"], 0)


class ExecLockDeltaTest(unittest.TestCase):
    """One tier's contention is the difference between two cumulative reads."""

    def _snapshot(self, **labels):
        return {"labels": {
            name: {"acquisitions": a, "wait_seconds": w, "held_seconds": h,
                   "max_wait_seconds": m}
            for name, (a, w, h, m) in labels.items()
        }}

    def test_the_delta_is_what_happened_between_the_reads(self):
        from utk_curio.backend.tests.stress.report import exec_lock_delta

        before = self._snapshot(isolated_persist=(10, 5.0, 2.0, 1.0))
        after = self._snapshot(isolated_persist=(30, 65.0, 12.0, 9.0))
        delta = exec_lock_delta(before, after)["labels"]["isolated_persist"]
        self.assertEqual(delta["acquisitions"], 20)
        self.assertEqual(delta["wait_seconds"], 60.0)
        self.assertEqual(delta["held_seconds"], 10.0)
        self.assertEqual(delta["mean_wait_seconds"], 3.0)
        # The peak is a high-water mark, not a sum, so it is carried as-is.
        self.assertEqual(delta["max_wait_seconds"], 9.0)

    def test_a_label_that_did_not_move_is_left_out(self):
        from utk_curio.backend.tests.stress.report import exec_lock_delta

        before = self._snapshot(isolated_persist=(10, 5.0, 2.0, 1.0), other=(3, 0.1, 0.1, 0.1))
        after = self._snapshot(isolated_persist=(11, 6.0, 3.0, 1.0), other=(3, 0.1, 0.1, 0.1))
        self.assertEqual(list(exec_lock_delta(before, after)["labels"]), ["isolated_persist"])

    def test_a_missing_reading_reports_nothing_rather_than_zero(self):
        """A failed monitor call must not read as an uncontended run."""
        from utk_curio.backend.tests.stress.report import exec_lock_delta

        self.assertIsNone(exec_lock_delta(None, self._snapshot()))
        self.assertIsNone(exec_lock_delta(self._snapshot(), None))


if __name__ == "__main__":
    unittest.main()


class ExecLockReachesTheMonitorTest(unittest.TestCase):
    """The counters are only useful if they leave the process.

    The sandbox's /monitor is where the backend, the monitor page and the
    stress harness all read execution state from, so the section has to be
    in that payload and has to survive the route's own error handling.
    """

    def test_the_sandbox_monitor_payload_carries_the_counters(self):
        import os

        from utk_curio.sandbox.app.api import app
        from utk_curio.sandbox.app.worker import _exec_lock

        with _exec_lock.hold("isolated_persist"):
            pass

        token = os.environ.get("CURIO_SANDBOX_TOKEN")
        headers = {"X-Curio-Sandbox-Token": token} if token else {}
        body = app.test_client().get("/monitor", headers=headers).get_json()

        self.assertIn("exec_lock", body)
        self.assertIn("isolated_persist", body["exec_lock"]["labels"])
        self.assertGreaterEqual(
            body["exec_lock"]["labels"]["isolated_persist"]["acquisitions"], 1
        )
