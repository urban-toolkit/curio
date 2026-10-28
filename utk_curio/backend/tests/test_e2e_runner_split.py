"""The e2e suite splits between the utk GPU runner and the CPU runners (runner_split).

Two things must hold for the split to be safe. The WebGPU tests land on utk,
the only runner with hardware WebGPU. And no test is lost: every collected test
runs on exactly one runner, and within the CPU runners on exactly one shard. The
last class checks that on the real suite, through pytest's own collection, with
the options CI runs it with: the parts add up to the suite, what shares a
session stays on one part, and a part holds only tests that will run.
"""

import re
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from utk_curio.backend.tests import parts
from utk_curio.backend.tests._support import collection
from utk_curio.backend.tests.test_frontend import fixtures, runner_split

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "utk_curio" / "backend"
EXAMPLES = REPO / "docs" / "examples"
DATAFLOWS = EXAMPLES / "dataflows"
E2E = Path(__file__).resolve().parent / "test_frontend"


class ClassificationTest(unittest.TestCase):
    def test_an_autark_dataflow_needs_webgpu(self):
        self.assertTrue(runner_split.dataflow_needs_webgpu(str(DATAFLOWS / "autk-map.json")))
        self.assertTrue(runner_split.dataflow_needs_webgpu(
            str(EXAMPLES / "07-autark-gpu-shader.json")))

    def test_a_vega_dataflow_does_not(self):
        self.assertFalse(runner_split.dataflow_needs_webgpu(str(DATAFLOWS / "vega.json")))
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

    def test_a_shipped_scenario_drop_runs_where_its_dataflow_needs(self):
        def drop(dataflow):
            return SimpleNamespace(
                get_closest_marker=lambda name: None,
                module=SimpleNamespace(
                    __name__="utk_curio.backend.tests.test_frontend.test_shipped_scenario_drops_e2e"),
                callspec=SimpleNamespace(params={"dataflow": dataflow, "scenario": "s"}),
            )

        self.assertTrue(runner_split.item_needs_webgpu(
            drop("docs/examples/06-back-bay-road-sunlight.json")))
        # Each quad-cities-flood-vulnerability scenario maps its depth on an Autark map.
        self.assertTrue(runner_split.item_needs_webgpu(
            drop("docs/examples/dataflows/quad-cities-flood-vulnerability.json")))
        self.assertFalse(runner_split.item_needs_webgpu(
            drop("docs/examples/dataflows/scenarios.json")))

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
            mock.patch.object(runner_split, "part_key", lambda i: i.group),
            mock.patch.object(runner_split, "item_key", lambda i: i.nodeid),
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

    def test_a_group_of_tests_costs_their_sum_on_one_part(self):
        """Three short tests that share a group outweigh one longer test."""
        items = [SimpleNamespace(nodeid=f"t{n}", group="shared", gpu=False) for n in range(3)]
        items += [SimpleNamespace(nodeid="long", group="long", gpu=False),
                  SimpleNamespace(nodeid="short", group="short", gpu=False)]
        durations = {"t0": 5.0, "t1": 5.0, "t2": 5.0, "long": 12.0, "short": 2.0}
        first, _ = runner_split.select(items, "desktop", "1/2", durations)
        second, _ = runner_split.select(items, "desktop", "2/2", durations)
        self.assertEqual([i.nodeid for i in first], ["t0", "t1", "t2"])
        self.assertEqual([i.nodeid for i in second], ["long", "short"])

    def test_a_test_that_needs_collaboration_runs_on_the_collab_runner_alone(self):
        """The one stack with --collab (the e2e-collab job) runs the tests
        marked needs_collab, and nothing else; the other runners leave them
        out, whatever their WebGPU."""
        def collab(group, gpu):
            return SimpleNamespace(nodeid=group, group=group, gpu=gpu,
                                   get_closest_marker=lambda name: object() if name == "needs_collab" else None)

        items = self.items(("a", True), ("b", False)) + [collab("c", False), collab("d", True)]
        picked = {runner: {i.group for i in runner_split.select(items, runner, None)[0]}
                  for runner in ("utk", "desktop", "collab")}
        self.assertEqual(picked, {"utk": {"a"}, "desktop": {"b"}, "collab": {"c", "d"}})
        self.assertEqual({i.group for i in runner_split.select(items, None, None)[0]}, {"a", "b", "c", "d"})

    def test_a_bad_setting_is_refused(self):
        with self.assertRaises(ValueError):
            runner_split.select([], "gpu", None)
        with self.assertRaises(ValueError):
            runner_split.parse_shard("4/3")
        with self.assertRaises(ValueError):
            runner_split.parse_shard("two")


def _item(module_file, name, cls=None, fixturenames=(), group=None):
    """A collected e2e item as part_key reads it."""
    module = Path(module_file).stem
    marker = SimpleNamespace(kwargs={}, args=(group or module,))
    nodeid = f"tests/test_frontend/{module}.py::" + (f"{cls.__name__}::" if cls else "") + name
    return SimpleNamespace(
        nodeid=nodeid, cls=cls, fixturenames=list(fixturenames),
        module=SimpleNamespace(__name__=f"utk_curio.backend.tests.test_frontend.{module}",
                               __file__=str(module_file)),
        get_closest_marker=lambda marker_name: marker if marker_name == "xdist_group" else None)


class PartKeyTest(unittest.TestCase):
    """What a CPU part keeps together: one test, unless it shares a session or a server."""

    PLAIN = E2E / "test_monitor_page_e2e.py"

    def test_a_test_that_gets_the_reset_is_a_group_of_its_own(self):
        item = _item(self.PLAIN, "test_polls[chromium]")
        self.assertEqual(runner_split.part_key(item),
                         "tests.test_frontend.test_monitor_page_e2e::test_polls[chromium]")
        self.assertEqual(runner_split.part_key(item), parts.item_key(item))

    def test_a_shared_session_class_keeps_its_xdist_group(self):
        for name in fixtures._SHARED_SESSION_CLASSES:
            shared = type(name, (), {})
            item = _item(self.PLAIN, "test_one[chromium]", cls=shared, group="its-group")
            self.assertEqual(runner_split.part_key(item), "its-group", name)

    def test_a_workflow_class_keeps_its_workflow_group(self):
        plain = type("TestOther", (), {})
        for fixture in ("loaded_workflow", "workflow_page"):
            item = _item(self.PLAIN, "test_one[vega.json-chromium]", cls=plain,
                         fixturenames=["page", fixture], group="wf-vega.json")
            self.assertEqual(runner_split.part_key(item), "wf-vega.json", fixture)

    def test_a_module_with_a_fixture_of_its_own_stays_whole(self):
        for module in ("test_dashboard_standalone_e2e", "test_spa_deep_link_e2e"):
            item = _item(E2E / f"{module}.py", "test_one[chromium]", group="anything")
            self.assertEqual(runner_split.part_key(item), module)

    def test_a_fixture_that_outlives_one_test_is_read_from_the_source(self):
        self.assertTrue(runner_split.module_keeps_a_fixture(str(E2E / "test_dashboard_standalone_e2e.py")))
        self.assertTrue(runner_split.module_keeps_a_fixture(str(E2E / "test_spa_deep_link_e2e.py")))
        self.assertFalse(runner_split.module_keeps_a_fixture(str(self.PLAIN)))
        with tempfile.TemporaryDirectory() as folder:
            cases = {
                "in_a_class": ("class TestX:\n    @pytest.fixture(scope='class')\n"
                               "    def session(self):\n        return 1\n", True),
                "session": "@fixture(scope='session')\ndef server():\n    return 1\n",
                "function": ("@pytest.fixture(scope='function')\ndef page():\n    return 1\n"
                             "@pytest.fixture\ndef other():\n    return 2\n", False),
            }
            for name, case in cases.items():
                source, expected = case if isinstance(case, tuple) else (case, True)
                path = Path(folder) / f"test_{name}.py"
                path.write_text("import pytest\nfrom pytest import fixture\n" + source, encoding="utf-8")
                self.assertIs(runner_split.module_keeps_a_fixture(str(path)), expected, name)


#: A workflow test's parameter: the dataflow's file name, then the browser.
WORKFLOW_ID = re.compile(r"\[(?P<workflow>[^\[\]]+\.json)-chromium\]$")


class NoTestIsLostTest(unittest.TestCase):
    """The real e2e suite: every test on exactly one runner and one shard.

    Collected as CI runs it (scripts/test.sh passes --with-examples), in as
    many desktop parts as CI's matrix has.
    """

    SHARDS = parts.E2E_DESKTOP_PARTS

    @staticmethod
    def command(*args, **env):
        """The collection of the CI job whose environment adds *env*, as (argv, env)."""
        return ([sys.executable, "-m", "pytest", "tests/test_frontend", "--collect-only", "-q",
                 "-p", "no:cacheprovider", "--with-examples", *args],
                {"PYTHONPATH": str(REPO),
                 "CURIO_E2E_RUNNER": "", "CURIO_E2E_PART": "", "CURIO_UNIT_PART": "", **env})

    @classmethod
    def collect(cls, *args, **env):
        argv, environ = cls.command(*args, **env)
        return collection.collect(argv, BACKEND, environ)

    @classmethod
    def setUpClass(cls):
        # The whole suite, utk's share, the collab job's and every desktop
        # part, several at once (_support/collection.py).
        everything, utk, collab, *shards = collection.collect_each(
            [cls.command(), cls.command(CURIO_E2E_RUNNER="utk"), cls.command(CURIO_E2E_RUNNER="collab")]
            + [cls.command(CURIO_E2E_RUNNER="desktop", CURIO_E2E_PART=f"{k}/{cls.SHARDS}")
               for k in range(1, cls.SHARDS + 1)],
            BACKEND)
        cls.everything, cls.utk, cls.collab, cls.shards = everything, utk, collab, shards

    def test_every_test_runs_on_exactly_one_runner_and_shard(self):
        everything, utk, collab, shards = self.everything, self.utk, self.collab, self.shards
        placed = utk + collab + [nodeid for shard in shards for nodeid in shard]
        self.assertEqual(sorted(placed), sorted(everything),
                         "the runners and shards do not add up to the whole suite")
        self.assertEqual(len(placed), len(set(placed)), "a test would run twice")
        self.assertTrue(utk, "nothing selected for the GPU runner")
        self.assertTrue(all(shards), "an empty desktop shard")
        self.assertTrue(any("test_collaboration_editors_e2e.py::" in nodeid for nodeid in collab),
                        f"the collab runner does not run the collaboration e2e: {collab}")
        # The modules --with-examples adds are in the check.
        self.assertTrue(any("test_shipped_scenario_drops_e2e.py::" in nodeid for nodeid in placed))

    def test_what_shares_a_session_stays_on_one_part(self):
        """A shared-session class, a workflow's class-scoped page (wf-*) and a
        module with a fixture of its own each run whole on one desktop part."""
        where = defaultdict(set)
        for k, shard in enumerate(self.shards, 1):
            for nodeid in shard:
                path, *names = nodeid.split("::")
                module = Path(path).stem
                workflow = WORKFLOW_ID.search(nodeid)
                if len(names) > 1 and names[0] in fixtures._SHARED_SESSION_CLASSES:
                    if workflow:
                        where[("workflow", workflow["workflow"])].add(k)
                    else:
                        where[("class", module, names[0])].add(k)
                if runner_split.module_keeps_a_fixture(str(E2E / f"{module}.py")):
                    where[("module", module)].add(k)
        spread = {unit: sorted(ks) for unit, ks in where.items() if len(ks) > 1}
        self.assertEqual(spread, {}, "split across desktop parts")
        kinds = {unit[0] for unit in where}
        self.assertEqual(kinds, {"workflow", "class", "module"}, "a kind of group the check never saw")
        self.assertIn(("module", "test_dashboard_standalone_e2e"), where)
        self.assertIn(("module", "test_spa_deep_link_e2e"), where)

    def test_a_part_holds_only_tests_that_will_run(self):
        """The split comes after pytest's -k and -m deselection.

        A test the whole-suite split puts in the last part, selected alone by
        -k, is then the whole run, so the first part holds it. Split before
        deselection, it would stay in the last part and the first would be empty.
        """
        last = self.shards[-1]
        candidates = []
        for nodeid in last:
            name = nodeid.split("::")[-1].split("[")[0]
            if re.fullmatch(r"test_\w+", name) and sum(name in other for other in self.everything) == 1:
                candidates.append((nodeid, name))
        self.assertTrue(candidates, "no test in the last part has a name of its own")
        nodeid, name = candidates[0]
        first = self.collect("-k", name, CURIO_E2E_RUNNER="desktop", CURIO_E2E_PART=f"1/{self.SHARDS}")
        self.assertEqual(first, [nodeid])


if __name__ == "__main__":
    unittest.main()
