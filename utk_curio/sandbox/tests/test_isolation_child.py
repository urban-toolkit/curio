"""The isolated child's execution logic, minus the confinement.

``child.confine()`` needs Linux and cannot run here. Everything *else* the
child does can: rebuilding the input, running the node, serializing the output,
and shaping the manifest are all plain Python. Those are also where the bugs
that would silently corrupt a user's data live, as opposed to the bugs that
merely fail loudly, so they are worth pinning on every platform.

The most valuable test in the file is
``test_every_serialized_output_passes_the_parents_validator``: the child writes
descriptors and the parent validates them, and if the two halves disagree every
node fails. Checking them against each other catches that here rather than in
CI.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from utk_curio.sandbox.isolation import child, protocol


def namespace_factory():
    """A minimal seeded namespace, standing in for the zygote's warm template."""
    import math

    import numpy as np

    return {
        "__builtins__": __builtins__,
        "pd": pd,
        "gpd": gpd,
        "np": np,
        "math": math,
        "os": os,
        "json": json,
    }


def request(code, scratch, **extra):
    """Build an exec request the way the supervisor would."""
    payload = {
        "code": code,
        "node_type": "curio.builtin/computation-analysis",
        "data_type": "",
        "scratch_dir": str(scratch),
        "input": {"kind": "none"},
        "dataset_paths": {},
        "session_imports": [],
        "limits": {},
    }
    payload.update(extra)
    return payload


class ChildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.scratch = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_code(self, code, **extra):
        return child.run_node(request(code, self.scratch, **extra), namespace_factory)


class TestSuccessfulRuns(ChildTestCase):

    def test_scalar_return(self):
        result = self.run_code("    return 1 + 1\n")
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"], {"kind": "int", "value": 2})
        self.assertEqual(result["stderr"], "")

    def test_bool_is_not_flattened_to_int(self):
        result = self.run_code("    return True\n")
        self.assertEqual(result["output"]["kind"], "bool")
        self.assertIs(result["output"]["value"], True)

    def test_stdout_is_captured_line_by_line(self):
        result = self.run_code("    print('one')\n    print('two')\n    return 1\n")
        self.assertEqual(result["stdout"], ["one", "two"])

    def test_blank_stdout_lines_are_dropped(self):
        """Matches execute_code, which filters empty lines out of stdout."""
        result = self.run_code("    print()\n    print('x')\n    return 1\n")
        self.assertEqual(result["stdout"], ["x"])

    def test_dataframe_is_written_to_scratch(self):
        result = self.run_code(
            "    return pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})\n"
        )
        self.assertTrue(result["ok"], result["stderr"])
        descriptor = result["output"]
        self.assertEqual(descriptor["kind"], "dataframe")
        written = self.scratch / descriptor["file"]
        self.assertTrue(written.exists())
        pd.testing.assert_frame_equal(
            pd.read_parquet(written), pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        )

    def test_geodataframe_keeps_geometry_and_crs(self):
        result = self.run_code(
            "    from shapely.geometry import Point\n"
            "    return gpd.GeoDataFrame({'a': [1]}, geometry=[Point(0, 0)], crs='EPSG:4326')\n"
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["kind"], "geodataframe")
        restored = gpd.read_parquet(self.scratch / result["output"]["file"])
        self.assertEqual(restored.crs, "EPSG:4326")

    def test_tuple_becomes_an_outputs_bundle(self):
        result = self.run_code("    return (1, 'two')\n")
        self.assertEqual(result["output"]["kind"], "outputs")
        kinds = [item["kind"] for item in result["output"]["items"]]
        self.assertEqual(kinds, ["int", "str"])

    def test_list_and_dict_go_to_a_json_file(self):
        for code, kind in (("    return [1, 2]\n", "list"),
                           ("    return {'a': 1}\n", "dict")):
            with self.subTest(kind=kind):
                result = self.run_code(code)
                self.assertEqual(result["output"]["kind"], kind)
                path = self.scratch / result["output"]["file"]
                self.assertTrue(path.exists())

    def test_non_finite_floats_are_scrubbed_not_crashed(self):
        """json.dumps(allow_nan=False) on the manifest would otherwise raise."""
        result = self.run_code("    return float('nan')\n")
        self.assertTrue(result["ok"], result["stderr"])
        self.assertIsNone(result["output"]["value"])


class TestFailures(ChildTestCase):

    def test_an_exception_is_reported_not_raised(self):
        result = self.run_code("    raise ValueError('boom')\n")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["output"])
        self.assertIn("ValueError", result["stderr"])
        self.assertIn("boom", result["stderr"])

    def test_stdout_before_a_failure_is_kept(self):
        """Print-debugging is the main tool here, so it must survive the failure."""
        result = self.run_code("    print('got here')\n    raise RuntimeError('x')\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stdout"], ["got here"])

    def test_a_syntax_error_is_reported(self):
        result = self.run_code("    return (\n")
        self.assertFalse(result["ok"])
        self.assertIn("SyntaxError", result["stderr"])

    def test_an_unstorable_return_value_is_reported(self):
        result = self.run_code("    return object()\n")
        self.assertFalse(result["ok"])
        self.assertIn("cannot store", result["stderr"])

    def test_the_arg_tripwire_fires_when_nothing_is_wired(self):
        result = self.run_code("    return arg['x']\n")
        self.assertFalse(result["ok"])
        self.assertIn("no input was delivered", result["stderr"])

    def test_a_system_exit_in_node_code_does_not_escape(self):
        """BaseException, so a bare `except Exception` would miss it."""
        result = self.run_code("    raise SystemExit(1)\n")
        self.assertFalse(result["ok"])


class TestInputRebuilding(ChildTestCase):

    def test_no_input_gives_none(self):
        self.assertIsNone(child.rebuild_input({"kind": "none"}, self.scratch))

    def test_scalars_round_trip(self):
        for spec, expected in (
            ({"kind": "null"}, None),
            ({"kind": "bool", "value": True}, True),
            ({"kind": "int", "value": 5}, 5),
            ({"kind": "float", "value": 1.5}, 1.5),
            ({"kind": "str", "value": "s"}, "s"),
        ):
            with self.subTest(kind=spec["kind"]):
                self.assertEqual(child.rebuild_input(spec, self.scratch), expected)

    def test_json_input(self):
        (self.scratch / "in.json").write_text('{"a": 1}', encoding="utf-8")
        value = child.rebuild_input({"kind": "json", "file": "in.json"}, self.scratch)
        self.assertEqual(value, {"a": 1})

    def test_dataframe_input_reaches_user_code(self):
        frame = pd.DataFrame({"a": [1, 2, 3]})
        frame.to_parquet(self.scratch / "in.parquet")
        result = self.run_code(
            "    return int(arg['a'].sum())\n",
            input={"kind": "dataframe", "file": "in.parquet",
                   "encoded_object_columns": []},
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["value"], 6)

    def test_geodataframe_input_keeps_geometry(self):
        gdf = gpd.GeoDataFrame(
            {"a": [1]}, geometry=[Point(1, 2)], crs="EPSG:4326"
        )
        gdf.to_parquet(self.scratch / "in.parquet")
        rebuilt = child.rebuild_input(
            {"kind": "geodataframe", "file": "in.parquet",
             "encoded_object_columns": []},
            self.scratch,
        )
        self.assertIsInstance(rebuilt, gpd.GeoDataFrame)
        self.assertEqual(rebuilt.crs, "EPSG:4326")

    def test_sequence_container_is_honoured(self):
        tuple_spec = {"kind": "sequence", "container": "tuple",
                      "items": [{"kind": "int", "value": 1}]}
        list_spec = {"kind": "sequence", "container": "list",
                     "items": [{"kind": "int", "value": 1}]}
        self.assertIsInstance(child.rebuild_input(tuple_spec, self.scratch), tuple)
        self.assertIsInstance(child.rebuild_input(list_spec, self.scratch), list)

    def test_mapping_input(self):
        spec = {"kind": "mapping", "items": {"k": {"kind": "int", "value": 2}}}
        self.assertEqual(child.rebuild_input(spec, self.scratch), {"k": 2})

    def test_a_merge_of_two_frames_arrives_as_a_tuple(self):
        for name, values in (("in_0.parquet", [1]), ("in_1.parquet", [2])):
            pd.DataFrame({"a": values}).to_parquet(self.scratch / name)
        result = self.run_code(
            "    return int(arg[0]['a'][0]) + int(arg[1]['a'][0])\n",
            input={
                "kind": "sequence", "container": "tuple",
                "items": [
                    {"kind": "dataframe", "file": "in_0.parquet",
                     "encoded_object_columns": []},
                    {"kind": "dataframe", "file": "in_1.parquet",
                     "encoded_object_columns": []},
                ],
            },
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["value"], 3)


class TestCrossValidation(ChildTestCase):
    """The child writes descriptors; the parent validates them.

    If these two drift, every isolated node fails at the last step. Checking
    the child's real output against the parent's real validator is the cheapest
    way to catch that.
    """

    CASES = [
        "    return None\n",
        "    return True\n",
        "    return 7\n",
        "    return 1.5\n",
        "    return 'text'\n",
        "    return [1, 2]\n",
        "    return {'a': 1}\n",
        "    return pd.DataFrame({'a': [1]})\n",
        "    return (1, pd.DataFrame({'a': [1]}))\n",
    ]

    def test_every_serialized_output_passes_the_parents_validator(self):
        for code in self.CASES:
            with self.subTest(code=code.strip()):
                result = self.run_code(code)
                self.assertTrue(result["ok"], result["stderr"])
                # Must not raise: this is exactly what the supervisor does.
                validated = protocol.validate_payload(result["output"])
                self.assertEqual(validated["kind"], result["output"]["kind"])

    def test_the_whole_manifest_survives_a_json_round_trip(self):
        """The manifest is written with allow_nan=False, so this must hold."""
        for code in self.CASES:
            with self.subTest(code=code.strip()):
                manifest = self.run_code(code)
                raw = json.dumps(manifest, allow_nan=False)
                parsed = protocol.parse_child_result(raw, scratch_dir=self.scratch)
                self.assertTrue(parsed["ok"])

    def test_written_manifest_is_read_back_by_the_supervisor(self):
        from utk_curio.sandbox.isolation import supervisor

        manifest = self.run_code("    return 42\n")
        child.write_result(manifest, self.scratch)
        parsed = supervisor.read_child_manifest(self.scratch)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["output"]["value"], 42)

    def test_a_missing_manifest_is_a_clear_error(self):
        from utk_curio.sandbox.isolation import supervisor

        with self.assertRaises(supervisor.IsolatedExecutionError) as caught:
            supervisor.read_child_manifest(self.scratch)
        self.assertIn("killed", str(caught.exception))


class TestSessionImports(ChildTestCase):
    """Cross-node imports (#158) survive as replayed statements."""

    def test_top_level_imports_are_reported(self):
        result = self.run_code("    import math\n    return math.floor(2.7)\n")
        self.assertTrue(result["ok"], result["stderr"])
        self.assertIn("import math", result["imports"])

    def test_aliased_and_from_imports_are_reported_faithfully(self):
        result = self.run_code(
            "    import numpy as np\n"
            "    from shapely import wkt\n"
            "    return 1\n"
        )
        self.assertIn("import numpy as np", result["imports"])
        self.assertIn("from shapely import wkt", result["imports"])

    def test_a_failing_import_is_not_reported(self):
        """Only imports that actually worked may be replayed downstream."""
        result = self.run_code(
            "    try:\n"
            "        import definitely_not_a_real_module\n"
            "    except ImportError:\n"
            "        pass\n"
            "    return 1\n"
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["imports"], [])

    def test_a_guarded_import_is_not_hoisted(self):
        """Nested imports are conditional by intent; hoisting breaks that."""
        statements = child._hoisted_import_statements(
            "try:\n    import optional_thing\nexcept ImportError:\n    pass\n"
        )
        self.assertEqual(statements, [])

    def test_replayed_imports_are_visible_to_node_code(self):
        result = self.run_code(
            "    return int(np.mean([1, 2, 3]))\n",
            session_imports=["import numpy as np"],
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["value"], 2)

    def test_a_replayed_import_that_no_longer_resolves_is_skipped(self):
        """Recorded because it once worked; failing the node now would surprise."""
        result = self.run_code(
            "    return 1\n",
            session_imports=["import definitely_not_a_real_module"],
        )
        self.assertTrue(result["ok"], result["stderr"])

    def test_reported_imports_satisfy_the_protocol_validator(self):
        """They are replayed as code, so the validator must accept them."""
        result = self.run_code(
            "    import math\n    import numpy as np\n    return 1\n"
        )
        parsed = protocol.parse_child_result(json.dumps(result))
        self.assertEqual(sorted(parsed["imports"]), sorted(result["imports"]))


class TestDatasetPaths(ChildTestCase):

    def test_a_staged_dataset_resolves_to_the_scratch_copy(self):
        (self.scratch / "ds_0.parquet").write_bytes(b"payload")
        result = self.run_code(
            "    p = curio_dataset_path('my.dataset')\n"
            "    return open(p, 'rb').read().decode()\n",
            dataset_paths={"my.dataset": "ds_0.parquet"},
        )
        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["value"], "payload")

    def test_an_unknown_dataset_id_raises_an_actionable_error(self):
        result = self.run_code(
            "    return curio_dataset_path('nope')\n", dataset_paths={}
        )
        self.assertFalse(result["ok"])
        self.assertIn("Data Catalog", result["stderr"])


class TestStoreHelpersAreNotReachable(unittest.TestCase):
    """The in-process path seeds load_from_duckdb into user scope.

    Under isolation that would hand node code the whole artifact store,
    including other sessions', so the zygote binds those names to a stub. The
    name exists on purpose: a sentence beats a NameError.
    """

    def test_the_stub_explains_itself(self):
        from utk_curio.sandbox.isolation import zygote

        stub = zygote._unavailable_under_isolation("load_from_duckdb")
        with self.assertRaises(RuntimeError) as caught:
            stub("some-artifact-id")
        message = str(caught.exception)
        self.assertIn("load_from_duckdb", message)
        self.assertIn("--isolation=off", message)


class TestDeathDescriptions(unittest.TestCase):
    """An abnormal exit must produce something a data scientist can act on."""

    LIMITS = {"memory_mb": 4096, "cpu_seconds": 300}

    def describe(self, **kwargs):
        from utk_curio.sandbox.isolation import supervisor

        return supervisor.describe_child_death(
            wall_timeout=300, limits=self.LIMITS, **kwargs
        )

    def test_timeout_names_the_flag_to_raise(self):
        message = self.describe(exit_code=None, signal_number=9, timed_out=True)
        self.assertIn("--exec-timeout", message)
        self.assertIn("300s", message)

    def test_sigkill_points_at_memory(self):
        # The literal 9, not signal.SIGKILL: Windows has no such constant, and
        # a status reported by the zygote is a Linux signal number regardless
        # of what the parent platform happens to define.
        message = self.describe(exit_code=None, signal_number=9, timed_out=False)
        self.assertIn("memory", message)
        self.assertIn("4096", message)

    def test_sigxcpu_points_at_the_cpu_allowance(self):
        message = self.describe(exit_code=None, signal_number=24, timed_out=False)
        self.assertIn("CPU", message)

    def test_confinement_failure_is_explained(self):
        message = self.describe(exit_code=3, signal_number=None, timed_out=False)
        self.assertIn("confine", message)

    def test_an_unexpected_exit_code_still_says_something(self):
        message = self.describe(exit_code=42, signal_number=None, timed_out=False)
        self.assertIn("42", message)


if __name__ == "__main__":
    unittest.main()
