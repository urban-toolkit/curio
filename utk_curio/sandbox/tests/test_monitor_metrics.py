"""Sandbox-side monitor bookkeeping: death classification, counters, errors.

``classify_child_death`` was split out of ``describe_child_death`` so a tally of
how children die and the sentence a user reads come from one branch order. The
first test class pins both halves together: if someone reorders a branch in one,
the other's assertions fail too. That pairing is the whole point of the split.
"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
