"""The suites split into parts for CI runners without losing a test (tests/parts.py).

The backend unit suite runs as ``CURIO_UNIT_PART`` parts on separate CPU
runner jobs (the e2e suite's split is test_e2e_runner_split.py). The
last tests here collect the real suite whole and in parts through pytest,
several processes at once (_support/collection.py), and check the parts add
up to it exactly, and that a part holds only tests that will run.
"""

import itertools
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest.mock
from pathlib import Path

from utk_curio.backend.tests import parts
from utk_curio.backend.tests._support import collection

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

    def test_a_group_costs_the_sum_of_its_tests(self):
        """Three 5 s tests in one group (15 s) go after a 20 s group, not before it."""
        group = {"a1": "a", "a2": "a", "a3": "a", "b": "b", "c": "c"}
        durations = {"a1": 5.0, "a2": 5.0, "a3": 5.0, "b": 20.0, "c": 12.0}
        kept = [parts.keep_part(list(group), f"{k}/2", group.get, str, durations)[0] for k in (1, 2)]
        self.assertEqual(kept, [["b"], ["a1", "a2", "a3", "c"]])

    def test_an_unrecorded_test_costs_the_median_recorded_one(self):
        durations = {"x": 1.0, "y": 2.0, "z": 30.0}
        self.assertEqual(parts.group_seconds({"old": {"x", "z"}, "new": {"n1", "n2"}}, durations),
                         {"old": 31.0, "new": 4.0})
        # With nothing recorded at all, every test costs the same.
        self.assertEqual(parts.group_seconds({"g": {"a", "b"}}, {}),
                         {"g": 2 * parts.DEFAULT_GROUP_SECONDS})

    def test_a_test_has_one_key_in_a_run_with_and_without_workers(self):
        """xdist's ``@<group>`` goes, an ``@`` in the parameters stays."""
        self.assertEqual(parts.case_key("tests.test_a.TestB", "test_c[x@1]@grp"),
                         "tests.test_a.TestB::test_c[x@1]")
        self.assertEqual(parts.case_key("utk_curio.backend.tests.test_a", "test_c@test_a"),
                         "tests.test_a::test_c")
        self.assertEqual(parts.file_key("tests.test_agents.test_routes.TestX"), "test_agents.test_routes")
        self.assertEqual(parts.file_key("utk_curio.backend.tests.test_suite_parts.PartsTest"),
                         "test_suite_parts")

    def test_the_split_comes_after_every_deselection(self):
        """A plugin from parts.after_deselection splits only what -m kept.

        Three slow tests, deselected by -m, would take the first part if they
        counted, and leave the kept test to the second.
        """
        with tempfile.TemporaryDirectory() as folder:
            suite = Path(folder)
            (suite / "pytest.ini").write_text(
                "[pytest]\nmarkers =\n    slow: deselected below\n", encoding="utf-8")
            (suite / "conftest.py").write_text(textwrap.dedent('''
                from utk_curio.backend.tests import parts

                SECONDS = {"test_mod::test_kept": 1.0, "test_mod::test_slow_1": 100.0,
                           "test_mod::test_slow_2": 100.0, "test_mod::test_slow_3": 100.0}

                def first_part(items):
                    return parts.keep_part(items, "1/2", parts.item_key, parts.item_key, SECONDS)

                def pytest_configure(config):
                    config.pluginmanager.register(parts.after_deselection(first_part), "split")
            '''), encoding="utf-8")
            (suite / "test_mod.py").write_text(textwrap.dedent('''
                import pytest

                def test_kept():
                    pass

                @pytest.mark.slow
                def test_slow_1():
                    pass

                @pytest.mark.slow
                def test_slow_2():
                    pass

                @pytest.mark.slow
                def test_slow_3():
                    pass
            '''), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-m", "pytest", ".", "--collect-only", "-q", "-p", "no:cacheprovider",
                 "-m", "not slow"],
                cwd=suite, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(REPO), "PYTEST_ADDOPTS": ""},
            )
        ids = [line for line in run.stdout.splitlines() if "::" in line]
        self.assertEqual(ids, ["test_mod.py::test_kept"], run.stdout[-2000:] + run.stderr[-2000:])

    def test_the_parts_of_a_split_are_what_each_part_keeps(self):
        """parts.split, which a listing writes, puts each item where keep_part keeps it."""
        group = {"a1": "a", "a2": "a", "b": "b", "c": "c", "d": "d", "e": "e"}
        durations = {"a1": 5.0, "a2": 5.0, "b": 20.0, "c": 12.0, "d": 0.0, "e": 3.0}
        items = list(group)
        for count in (1, 2, 3, 4, 8):
            kept = [parts.keep_part(items, f"{k}/{count}", group.get, str, durations)[0]
                    for k in range(1, count + 1)]
            self.assertEqual(parts.split(items, count, group.get, str, durations), kept, count)

    LISTING_CONFTEST = textwrap.dedent('''
        from utk_curio.backend.tests import parts

        def first_part(items):
            return parts.keep_part(items, "1/2", parts.item_key, parts.item_key, {})

        def listing(items):
            pieces = parts.split(items, 2, parts.item_key, parts.item_key, {})
            return {"job-1": pieces[0], "job-2": pieces[1]}, items

        def pytest_configure(config):
            config.pluginmanager.register(parts.after_deselection(first_part, listing), "split")
    ''')

    def _listing_run(self, tests: str, *args):
        """A suite of *tests* run with CURIO_LIST_PARTS: (the process, the listing or None)."""
        with tempfile.TemporaryDirectory() as folder:
            suite = Path(folder)
            (suite / "pytest.ini").write_text(
                "[pytest]\nmarkers =\n    slow: deselected below\n", encoding="utf-8")
            (suite / "conftest.py").write_text(self.LISTING_CONFTEST, encoding="utf-8")
            (suite / "test_mod.py").write_text(textwrap.dedent(tests), encoding="utf-8")
            listing = suite / "listed" / "parts.json"
            run = subprocess.run(
                [sys.executable, "-m", "pytest", ".", "-q", "-p", "no:cacheprovider", *args],
                cwd=suite, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(REPO), "PYTEST_ADDOPTS": "",
                     "CURIO_LIST_PARTS": str(listing)},
            )
            written = json.loads(listing.read_text(encoding="utf-8")) if listing.exists() else None
        return run, written

    def test_a_listing_names_each_jobs_tests_and_runs_none(self):
        """CURIO_LIST_PARTS writes every part's tests, after -m, and runs nothing.

        Every test fails if it runs, so the exit code says none did (pytest's
        5, nothing collected), and the -m deselected one is in no part.
        """
        run, written = self._listing_run('''
            import pytest

            def test_one():
                assert False

            def test_two():
                assert False

            @pytest.mark.slow
            def test_slow():
                assert False
        ''', "-m", "not slow")
        output = run.stdout[-2000:] + run.stderr[-2000:]
        self.assertEqual(run.returncode, 5, output)
        self.assertIsNotNone(written, output)
        self.assertEqual(set(written), {"job-1", "job-2"})
        listed = sorted(key for keys in written.values() for key in keys)
        self.assertEqual(listed, ["test_mod::test_one", "test_mod::test_two"])
        self.assertTrue(all(len(keys) == 1 for keys in written.values()), written)

    def test_a_collection_error_writes_no_listing(self):
        run, written = self._listing_run('''
            import a_module_that_is_not_there

            def test_one():
                pass
        ''')
        self.assertNotIn(run.returncode, (0, 5), run.stdout[-2000:])
        self.assertIsNone(written)

    def test_a_listing_keeps_the_jobs_another_split_listed(self):
        """One session can list both suites into one file: each adds its own jobs."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "parts.json"
            parts.write_listing(path, {"unit-backend-1": ["tests.test_a::test_b"], "unit-backend-2": []})
            parts.write_listing(path, {"test-gpu": [], "unit-backend-2": ["tests.test_c::test_d"]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "test-gpu": [], "unit-backend-1": ["tests.test_a::test_b"],
                "unit-backend-2": ["tests.test_c::test_d"]})


class CollectionsAtOnceTest(unittest.TestCase):
    def test_each_collection_has_a_state_folder_of_its_own(self):
        """Collections that run at once never share the test database.

        tests/conftest.py deletes the test database it owns at import and builds
        it again, so each collection (_support/collection.py) gets its own
        CURIO_STATE_DIR and none of the database paths this process holds.
        """
        keys = ("CURIO_UNIT_PART", "CURIO_STATE_DIR", *collection.STATE_PATHS, "LOG_TO_STDOUT")
        with tempfile.TemporaryDirectory() as folder:
            suite = Path(folder)
            (suite / "conftest.py").write_text(textwrap.dedent(f'''
                import os

                print("env::" + "::".join(os.environ.get(key, "unset") for key in {keys!r}))
            '''), encoding="utf-8")
            (suite / "test_mod.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
            argv = [sys.executable, "-m", "pytest", ".", "--collect-only", "-q", "-s",
                    "-p", "no:cacheprovider"]
            held = {key: os.environ.get(key) or f"held-here-{key}" for key in collection.STATE_PATHS}
            with unittest.mock.patch.dict(os.environ, held):
                found = collection.collect_each(
                    [(argv, {"CURIO_UNIT_PART": f"{k}/2", "PYTEST_ADDOPTS": ""}) for k in (1, 2)], suite)
        self.assertTrue(all("test_mod.py::test_one" in ids for ids in found), found)
        printed = [next((line for line in ids if line.startswith("env::")), "") for ids in found]
        self.assertTrue(all(printed), f"a collection did not print its environment: {found}")
        seen = [dict(zip(keys, line.split("::")[1:])) for line in printed]
        self.assertEqual([env["CURIO_UNIT_PART"] for env in seen], ["1/2", "2/2"], "not in the order asked")
        states = [env["CURIO_STATE_DIR"] for env in seen]
        self.assertNotIn("unset", states)
        self.assertNotEqual(states[0], states[1], "two collections shared a state folder")
        for env in seen:
            self.assertEqual({key: env[key] for key in collection.STATE_PATHS},
                             dict.fromkeys(collection.STATE_PATHS, "unset"))
            self.assertEqual(env["LOG_TO_STDOUT"], "1")


class NoBackendTestIsLostTest(unittest.TestCase):
    PARTS = parts.BACKEND_UNIT_PARTS

    @staticmethod
    def command(part="", *args):
        """The collection of CI's backend part *part*, the whole suite when empty, as (argv, env)."""
        return ([sys.executable, "-m", "pytest", "utk_curio/backend/tests",
                 "--ignore=utk_curio/backend/tests/test_frontend",
                 "--collect-only", "-q", "-p", "no:cacheprovider", *args],
                {"PYTHONPATH": str(REPO), "CURIO_UNIT_PART": part})

    @classmethod
    def collect(cls, part="", *args):
        argv, env = cls.command(part, *args)
        return collection.collect(argv, REPO, env)

    @classmethod
    def setUpClass(cls):
        # The whole suite, every part, and the listing of every part a filtered
        # CI run makes (CURIO_LIST_PARTS), several at once (_support/collection.py).
        everything, *pieces, listed = collection.collect_each(
            [cls.command()] + [cls.command(f"{k}/{cls.PARTS}") for k in range(1, cls.PARTS + 1)], REPO,
            listings=[cls.command(f"1/{cls.PARTS}")])
        cls.everything, cls.pieces, cls.listed = everything, pieces, listed

    def test_the_listing_names_what_each_part_runs(self):
        """What build-image lists for a filtered run is what each unit part then runs.

        pytest loads the conftest of every test* folder under its argument,
        --ignore or not, so the e2e split lists its jobs too, each holding
        nothing: this session collected no e2e test.
        """
        unit = sorted(job for job in self.listed if job.startswith("unit-"))
        self.assertEqual(unit, [f"unit-backend-{k}" for k in range(1, self.PARTS + 1)])
        others = {job: keys for job, keys in self.listed.items() if not job.startswith("unit-")}
        self.assertEqual(others, {job: [] for job in others})
        for k, piece in enumerate(self.pieces, 1):
            self.assertEqual(sorted(self.listed[f"unit-backend-{k}"]),
                             sorted(parts.case_key(*parts.nodeid_address(nodeid)) for nodeid in piece), k)

    def test_the_parts_add_up_to_the_suite(self):
        everything, pieces = self.everything, self.pieces
        placed = [nodeid for piece in pieces for nodeid in piece]
        self.assertEqual(sorted(placed), sorted(everything),
                         "the parts do not add up to the whole backend suite")
        self.assertEqual(len(placed), len(set(placed)), "a test would run twice")
        self.assertTrue(all(pieces), "an empty part")
        # One file never straddles two parts, whichever two.
        files = [{nodeid.split("::")[0] for nodeid in piece} for piece in pieces]
        for a, b in itertools.combinations(range(self.PARTS), 2):
            self.assertFalse(files[a] & files[b], f"a test file split across parts {a + 1} and {b + 1}")

    def test_a_part_holds_only_tests_that_will_run(self):
        """The split comes after pytest's -k and -m deselection.

        A test the whole-suite split puts in the last part, selected alone by
        -k, is then the whole run, so the first part holds it. Split before
        deselection, it would stay in the last part and the first would be empty.
        """
        candidates = []
        for nodeid in self.pieces[-1]:
            name = nodeid.split("::")[-1].split("[")[0]
            if name.startswith("test_") and name.isidentifier() and "[" not in nodeid \
                    and sum(name in other for other in self.everything) == 1:
                candidates.append((nodeid, name))
        self.assertTrue(candidates, "no test in the last part has a name of its own")
        nodeid, name = candidates[0]
        self.assertEqual(self.collect(f"1/{self.PARTS}", "-k", name), [nodeid])


if __name__ == "__main__":
    unittest.main()
