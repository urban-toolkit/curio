"""Sandbox-side monitor bookkeeping: death classification, counters, errors.

``classify_child_death`` was split out of ``describe_child_death`` so a tally of
how children die and the sentence a user reads come from one branch order. The
first test class pins both halves together: if someone reorders a branch in one,
the other's assertions fail too. That pairing is the whole point of the split.
"""

import threading
import unittest

from utk_curio.sandbox import metrics
from utk_curio.sandbox.isolation import supervisor


LIMITS = {"memory_mb": 4096, "cpu_seconds": 300}
WALL = 300


def describe(exit_code, signal_number, timed_out):
    return supervisor.describe_child_death(
        exit_code, signal_number, timed_out, wall_timeout=WALL, limits=LIMITS,
    )


class ClassifyChildDeathTests(unittest.TestCase):
    """One token per branch, and the branch still says what it used to say."""

    def test_timeout_wins_over_every_other_signal(self):
        # A timed-out child is also SIGKILLed, so order matters: the useful
        # answer is "it ran too long", not "the OS killed it".
        self.assertEqual(
            supervisor.classify_child_death(None, supervisor.SIGKILL, True),
            "timeout",
        )
        self.assertIn(f"stopped after {WALL}s", describe(None, supervisor.SIGKILL, True))

    def test_sigkill_without_a_timeout_is_the_memory_limit(self):
        self.assertEqual(
            supervisor.classify_child_death(None, supervisor.SIGKILL, False), "oom",
        )
        self.assertIn("4096 MB", describe(None, supervisor.SIGKILL, False))

    def test_sigxcpu_is_the_cpu_allowance(self):
        self.assertEqual(
            supervisor.classify_child_death(None, supervisor.SIGXCPU, False), "cpu",
        )
        self.assertIn("CPU allowance of 300s", describe(None, supervisor.SIGXCPU, False))

    def test_any_other_signal_is_reported_by_number(self):
        self.assertEqual(supervisor.classify_child_death(None, 11, False), "signal")
        self.assertIn("signal 11", describe(None, 11, False))

    def test_exit_3_is_a_refused_confinement(self):
        self.assertEqual(supervisor.classify_child_death(3, None, False), "refused")
        self.assertIn("could not confine", describe(3, None, False))

    def test_other_nonzero_exits_report_the_status(self):
        self.assertEqual(supervisor.classify_child_death(7, None, False), "exit")
        self.assertIn("status 7", describe(7, None, False))

    def test_a_clean_exit_with_no_result_is_unknown(self):
        self.assertEqual(supervisor.classify_child_death(0, None, False), "unknown")
        self.assertEqual(supervisor.classify_child_death(None, None, False), "unknown")
        self.assertIn("without reporting a result", describe(0, None, False))

    def test_every_branch_token_is_in_the_closed_vocabulary(self):
        # The monitor puts these tokens in a public payload, so the set a
        # caller can receive must be exactly the set it can allowlist.
        cases = [
            (None, supervisor.SIGKILL, True), (None, supervisor.SIGKILL, False),
            (None, supervisor.SIGXCPU, False), (None, 11, False),
            (3, None, False), (7, None, False), (0, None, False),
        ]
        produced = {supervisor.classify_child_death(*c) for c in cases}
        self.assertEqual(produced, set(supervisor.DEATH_REASONS))


class MetricsCountersTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def test_dispatch_splits_isolated_from_in_process(self):
        metrics.record_dispatch(True)
        metrics.record_dispatch(True)
        metrics.record_dispatch(False)
        snap = metrics.snapshot()
        self.assertEqual(snap["total"], 3)
        self.assertEqual(snap["isolated"], 2)
        self.assertEqual(snap["inProcess"], 1)

    def test_the_slot_gauge_returns_to_zero_after_an_exception(self):
        # The real caller wraps client.run, which raises on a protocol error.
        # A gauge that leaked on that path would climb to the parallelism limit
        # and then report a permanently saturated sandbox.
        with self.assertRaises(ValueError):
            with metrics.slot():
                self.assertEqual(metrics.snapshot()["slotsInUse"], 1)
                raise ValueError("boom")
        self.assertEqual(metrics.snapshot()["slotsInUse"], 0)

    def test_the_slot_gauge_never_goes_negative(self):
        metrics.slot().__exit__(None, None, None)
        self.assertEqual(metrics.snapshot()["slotsInUse"], 0)

    def test_counters_are_coherent_under_threads(self):
        def work():
            for _ in range(500):
                metrics.record_dispatch(True)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(metrics.snapshot()["total"], 4000)

    def test_a_child_death_lands_in_both_the_tally_and_the_log(self):
        metrics.record_child_death("oom", detail="killed at 4096 MB")
        snap = metrics.snapshot()
        self.assertEqual(snap["childDeaths"], {"oom": 1})
        errors = metrics.errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["source"], "sandbox")
        self.assertIn("4096 MB", errors[0]["detail"])


class MetricsErrorWindowTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def test_the_window_is_bounded(self):
        for i in range(metrics.ERROR_WINDOW * 3):
            metrics.record_error(summary=f"failure {i}")
        self.assertEqual(len(metrics.errors()), metrics.ERROR_WINDOW)

    def test_errors_come_back_newest_first(self):
        metrics.record_error(summary="first")
        metrics.record_error(summary="second")
        self.assertEqual([e["summary"] for e in metrics.errors()], ["second", "first"])

    def test_identical_errors_collapse_with_a_count(self):
        # One node failing in a retry loop must not flush the window.
        for _ in range(5):
            metrics.record_error(summary="same", detail="same detail")
        errors = metrics.errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["count"], 5)

    def test_detail_is_capped(self):
        metrics.record_error(summary="huge", detail="x" * 50_000)
        self.assertEqual(len(metrics.errors()[0]["detail"]), 8000)

    def test_recording_never_raises_on_junk(self):
        metrics.record_error(summary=None, detail=None, context=None)
        metrics.record_child_death(None)
        self.assertTrue(metrics.errors())

    def test_the_internal_sort_key_never_escapes(self):
        metrics.record_error(summary="one")
        self.assertNotIn("_at", metrics.errors()[0])


if __name__ == "__main__":
    unittest.main()
