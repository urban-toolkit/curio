"""Each input circle is its own variable, input_0, input_1, ... (util/input_names.py).

The in-process worker, the isolated child and the JavaScript wrapper bind the
names through one module, so a node reads the same name for the same circle
whichever runs it.
"""
from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from utk_curio.sandbox.util import input_names


class TestSplitInputs(unittest.TestCase):
    def test_each_wired_circle_is_its_own_name(self):
        self.assertEqual(input_names.split_inputs([1, 2], [0, 2]), {"input_0": 1, "input_2": 2})

    def test_a_tuple_on_one_circle_is_that_circles_input(self):
        self.assertEqual(input_names.split_inputs((1, 2), [1]), {"input_1": (1, 2)})

    def test_a_bundle_on_one_circle_stays_whole(self):
        self.assertEqual(input_names.split_inputs([1, 2, 3], [0], "outputs"), {"input_0": [1, 2, 3]})

    def test_without_slots_the_circles_are_counted_from_zero(self):
        self.assertEqual(input_names.split_inputs([1, 2], None, "outputs"), {"input_0": 1, "input_1": 2})
        self.assertEqual(input_names.split_inputs([1, 2], None, "dataframe"), {"input_0": [1, 2]})

    def test_several_edges_on_one_circle_are_its_list(self):
        self.assertEqual(input_names.split_inputs([1, 2, 3], [0, 0, 1]), {"input_0": [1, 2], "input_1": 3})

    def test_no_input_binds_nothing(self):
        self.assertEqual(input_names.split_inputs("", None), {})
        self.assertEqual(input_names.split_inputs(None, [0]), {})


class TestTheHeader(unittest.TestCase):
    def test_each_name_the_code_reads_is_a_parameter(self):
        header = input_names.user_code_header("    return input_0 + input_3\n")
        self.assertEqual(header, "def userCode(input_0=None, input_3=None, **_curio_unread_inputs):")

    def test_a_name_in_a_string_or_comment_is_not_read(self):
        self.assertEqual(input_names.input_names_read("    # input_1\n    return 'input_2'\n"), [])


class TestInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init

        _worker_init()

    def _run(self, code, values, slots):
        from utk_curio.sandbox.app.worker import execute_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

        refs = [save_to_duckdb(v, node_id=f"up-{i}") for i, v in enumerate(values)]
        if len(refs) == 1:
            file_path, data_type = refs[0], "str"
        else:
            file_path, data_type = repr(refs), "outputs"
        result = execute_code(
            textwrap.indent(code, "    "), file_path, "curio.builtin/computation-analysis", data_type,
            save_dataset=False, input_slots=slots,
        )
        if result["stderr"]:
            return result["stderr"]
        return load_from_duckdb(result["output"]["path"])

    def test_circles_keep_their_numbers_when_one_between_has_no_edge(self):
        out = self._run("return f'{input_0}|{input_1}|{input_2}'", ["a", "c"], [0, 2])
        self.assertEqual(out, "a|None|c")

    def test_one_input_on_a_later_circle_is_that_circles_name(self):
        self.assertEqual(self._run("return input_1 + '!'", ["b"], [1]), "b!")

    def test_reading_the_old_name_is_told_the_new_one(self):
        stderr = self._run("return input", ["a"], [0])
        self.assertIn("reads `input`, which Curio no longer defines", stderr)


class TestJavaScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("Node.js is not installed")
        from utk_curio.sandbox.app.worker import _worker_init

        _worker_init()

    def _run(self, code, values, slots):
        from utk_curio.sandbox.app.worker import execute_js_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

        refs = [save_to_duckdb(v, node_id=f"up-{i}") for i, v in enumerate(values)]
        file_path, data_type = (refs[0], "int") if len(refs) == 1 else (repr(refs), "outputs")
        result = execute_js_code(code, file_path, "curio.builtin/js-computation", data_type,
                                 save_dataset=False, input_slots=slots)
        if result["stderr"]:
            return result["stderr"]
        return load_from_duckdb(result["output"]["path"])

    def test_each_circle_is_its_own_name(self):
        self.assertEqual(self._run("return input_0 * 10 + input_2;", [4, 5], [0, 2]), 45)

    def test_an_unwired_circle_is_undefined(self):
        self.assertEqual(self._run("return input_1 === undefined ? input_0 : -1;", [7], [0]), 7)

    def test_reading_the_old_name_is_told_the_new_one(self):
        stderr = self._run("return input + 1;", [1], [0])
        self.assertIn("reads `input`, which Curio no longer defines", stderr)


class TestIsolatedMatchesInProcess(unittest.TestCase):
    """The isolated child binds the same names from the same input."""

    def test_the_same_code_reads_the_same_values(self):
        from utk_curio.sandbox.isolation import child, zygote

        scratch = Path(tempfile.mkdtemp())
        try:
            manifest = child.run_node({
                "code": "    return f'{input_0}|{input_1}|{input_2}'\n",
                "node_type": "curio.builtin/computation-analysis",
                "data_type": "outputs",
                "scratch_dir": str(scratch),
                "input": {"kind": "sequence", "container": "tuple",
                          "items": [{"kind": "str", "value": "a"}, {"kind": "str", "value": "c"}]},
                "input_slots": [0, 2],
                "session_imports": [],
                "limits": {},
            }, zygote.build_namespace_template)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self.assertTrue(manifest["ok"], manifest["stderr"])
        self.assertEqual(manifest["output"]["value"], "a|None|c")


if __name__ == "__main__":
    unittest.main()
