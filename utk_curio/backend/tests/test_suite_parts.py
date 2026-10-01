"""The suites split into parts for CI runners without losing a test (tests/parts.py).

The backend unit suite runs as ``CURIO_UNIT_PART`` parts on separate
ubuntu-latest jobs (the e2e suite's split is test_e2e_runner_split.py). The
last test here collects the real suite whole and in parts through pytest and
checks the parts add up to it exactly.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from utk_curio.backend.tests import parts

REPO = Path(__file__).resolve().parents[3]


class PartsTest(unittest.TestCase):
    def test_a_part_is_k_of_n(self):
        self.assertEqual(parts.parse_part("1/2"), (0, 2))
        self.assertEqual(parts.parse_part("2/2"), (1, 2))
        for bad in ("3/2", "0/2", "two", "1"):
            with self.assertRaises(ValueError):
                parts.parse_part(bad)

    def test_groups_go_longest_first_to_the_least_loaded_part(self):
        durations = {"a": 50.0, "b": 30.0, "c": 20.0, "d": 10.0}
        placed = parts.assign(durations, 2, durations)
        loads = [sum(durations[g] for g, p in placed.items() if p == i) for i in range(2)]
        self.assertEqual(sorted(loads), [50.0, 60.0])
        self.assertEqual(placed, parts.assign(list(reversed(list(durations))), 2, durations))

    def test_an_unknown_group_is_priced_not_dropped(self):
        placed = parts.assign(["new", "old"], 2, {"old": 5.0})
        self.assertEqual(set(placed), {"new", "old"})


class NoBackendTestIsLostTest(unittest.TestCase):
    PARTS = 2

    @staticmethod
    def collect(part=""):
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "utk_curio/backend/tests",
             "--ignore=utk_curio/backend/tests/test_frontend",
             "--collect-only", "-q", "-p", "no:cacheprovider"],
            cwd=REPO, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO), "CURIO_UNIT_PART": part},
        )
        ids = [line for line in run.stdout.splitlines() if "::" in line]
        if not ids:
            raise AssertionError(f"collection found nothing:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
        return ids

    def test_the_parts_add_up_to_the_suite(self):
        everything = self.collect()
        pieces = [self.collect(f"{k}/{self.PARTS}") for k in range(1, self.PARTS + 1)]
        placed = [nodeid for piece in pieces for nodeid in piece]
        self.assertEqual(sorted(placed), sorted(everything),
                         "the parts do not add up to the whole backend suite")
        self.assertEqual(len(placed), len(set(placed)), "a test would run twice")
        self.assertTrue(all(pieces), "an empty part")
        # One file never straddles two parts.
        files = [{nodeid.split("::")[0] for nodeid in piece} for piece in pieces]
        self.assertFalse(files[0] & files[1], "a test file split across parts")


if __name__ == "__main__":
    unittest.main()
