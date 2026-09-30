"""The e2e suite splits between the utk GPU runner and ubuntu-latest (runner_split).

Two things must hold for the split to be safe. The WebGPU tests land on utk,
the only runner with hardware WebGPU. And no test is lost: every collected test
runs on exactly one runner, and within ubuntu-latest on exactly one shard. The
last class checks that on the real suite, through pytest's own collection.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from utk_curio.backend.tests.test_frontend import runner_split

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "docs" / "examples"
DATAFLOWS = EXAMPLES / "dataflows"


class ClassificationTest(unittest.TestCase):
    def test_an_autark_dataflow_needs_webgpu(self):
        self.assertTrue(runner_split.dataflow_needs_webgpu(str(DATAFLOWS / "AutkMap.json")))
        self.assertTrue(runner_split.dataflow_needs_webgpu(
            str(EXAMPLES / "07-autark-gpu-shader.json")))

    def test_a_vega_dataflow_does_not(self):
        self.assertFalse(runner_split.dataflow_needs_webgpu(str(DATAFLOWS / "Vega.json")))
        self.assertFalse(runner_split.dataflow_needs_webgpu(
            str(EXAMPLES / "01-vega-lite-chained-transforms.json")))

    def test_an_unreadable_dataflow_stays_on_utk(self):
        self.assertTrue(runner_split.dataflow_needs_webgpu(str(DATAFLOWS / "missing.json")))

    def test_a_walk_needs_webgpu_through_its_example_or_its_script(self):
        def plain(ctx):
            ctx.capture("canvas")

        def drives_the_gpu(ctx):
            ctx.page.evaluate("() => navigator.gpu")

        self.assertTrue(runner_split.walk_needs_webgpu(
            SimpleNamespace(example="07-autark-gpu-shader.json", run=plain)))
        self.assertTrue(runner_split.walk_needs_webgpu(
            SimpleNamespace(example=None, run=drives_the_gpu)))
        self.assertFalse(runner_split.walk_needs_webgpu(
            SimpleNamespace(example="01-vega-lite-chained-transforms.json", run=plain)))

    def test_a_test_that_needs_the_parallel_stack_is_on_utk(self):
        marked = SimpleNamespace(
            get_closest_marker=lambda name: object() if name == "needs_parallel" else None)
        self.assertTrue(runner_split.item_needs_webgpu(marked))

    def test_the_shipped_autark_walks_are_on_utk(self):
        from utk_curio.backend.tests.test_frontend.walkthroughs import WALKTHROUGHS

        by_slug = {w.slug: w for w in WALKTHROUGHS}
        self.assertTrue(runner_split.walk_needs_webgpu(by_slug["autark-without-webgpu-says-so"]))


class SelectionTest(unittest.TestCase):
    @staticmethod
    def items(*groups_and_gpu):
        made = []
        for group, gpu in groups_and_gpu:
            item = SimpleNamespace(nodeid=group, group=group, gpu=gpu)
            made.append(item)
        return made

    def setUp(self):
        patches = [
            mock.patch.object(runner_split, "item_needs_webgpu", lambda i: i.gpu),
            mock.patch.object(runner_split, "group_of", lambda i: i.group),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_runners_partition_the_suite(self):
        items = self.items(("a", True), ("b", False), ("c", False), ("d", True))
        utk, _ = runner_split.select(items, "utk", None)
        desktop, _ = runner_split.select(items, "desktop", None)
        self.assertEqual({i.group for i in utk}, {"a", "d"})
        self.assertEqual({i.group for i in desktop}, {"b", "c"})

    def test_shards_partition_a_runner_and_balance_it(self):
        items = self.items(*[(f"g{n}", False) for n in range(10)])
        durations = {f"g{n}": float(10 - n) for n in range(10)}
        seen, loads = [], []
        for k in range(1, 4):
            kept, _ = runner_split.select(items, "desktop", f"{k}/3", durations)
            seen += [i.group for i in kept]
            loads.append(sum(durations[i.group] for i in kept))
        self.assertEqual(sorted(seen), sorted(i.group for i in items))
        self.assertLessEqual(max(loads) - min(loads), max(durations.values()))

    def test_a_bad_setting_is_refused(self):
        with self.assertRaises(ValueError):
            runner_split.select([], "gpu", None)
        with self.assertRaises(ValueError):
            runner_split.parse_shard("4/3")
        with self.assertRaises(ValueError):
            runner_split.parse_shard("two")


class NoTestIsLostTest(unittest.TestCase):
    """The real e2e suite: every test on exactly one runner and one shard."""

    SHARDS = 10

    @staticmethod
    def collect(**env):
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_frontend", "--collect-only", "-q",
             "-p", "no:cacheprovider"],
            cwd=REPO / "utk_curio" / "backend", capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO),
                 "CURIO_E2E_RUNNER": "", "CURIO_E2E_PART": "", **env},
        )
        ids = [line for line in run.stdout.splitlines() if "::" in line]
        if not ids:
            raise AssertionError(f"collection found nothing:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
        return ids

    def test_every_test_runs_on_exactly_one_runner_and_shard(self):
        everything = self.collect()
        utk = self.collect(CURIO_E2E_RUNNER="utk")
        shards = [self.collect(CURIO_E2E_RUNNER="desktop", CURIO_E2E_PART=f"{k}/{self.SHARDS}")
                  for k in range(1, self.SHARDS + 1)]
        placed = utk + [nodeid for shard in shards for nodeid in shard]
        self.assertEqual(sorted(placed), sorted(everything),
                         "the runners and shards do not add up to the whole suite")
        self.assertEqual(len(placed), len(set(placed)), "a test would run twice")
        self.assertTrue(utk, "nothing selected for the GPU runner")
        self.assertTrue(all(shards), "an empty desktop shard")


if __name__ == "__main__":
    unittest.main()
