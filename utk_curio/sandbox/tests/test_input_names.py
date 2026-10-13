"""Each input circle is its own variable, input_0, input_1, ... (util/input_names.py).

The in-process worker, the isolated child and the JavaScript wrapper bind the
names through one module, so a node reads the same name for the same circle
whichever runs it. Code that still reads ``arg`` or ``input``, the names a
node's whole input once had, or that holds a chip spelled the old way,
``[!! input 0 !!]``, is refused with a message that names ``input_0``.

``input_names`` is imported inside each test, so a checkout without it fails
each test on its own instead of failing the whole collection.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

_OLD_NAME = "which Curio no longer defines"
_OLD_CHIP = "names an input the old way"


def _input_names():
    from utk_curio.sandbox.util import input_names

    return input_names


def _refs(values):
    """The artifacts of *values*, as the runner hands them to ``execute_code``."""
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    refs = [save_to_duckdb(v, node_id=f"up-{i}") for i, v in enumerate(values)]
    if len(refs) == 1:
        return refs[0], "str"
    return repr(refs), "outputs"


class TestSplitInputs(unittest.TestCase):
    def test_each_wired_circle_is_its_own_name(self):
        self.assertEqual(_input_names().split_inputs([1, 2], [0, 3]), {"input_0": 1, "input_3": 2})

    def test_a_tuple_on_one_circle_is_that_circles_input(self):
        self.assertEqual(_input_names().split_inputs((1, 2), [1]), {"input_1": (1, 2)})

    def test_a_list_gathered_on_one_circle_stays_whole(self):
        self.assertEqual(_input_names().split_inputs([1, 2, 3], [0], "outputs"), {"input_0": [1, 2, 3]})

    def test_without_slots_the_circles_are_counted_from_zero(self):
        names = _input_names()
        self.assertEqual(names.split_inputs([1, 2], None, "outputs"), {"input_0": 1, "input_1": 2})
        self.assertEqual(names.split_inputs([1, 2], None, "dataframe"), {"input_0": [1, 2]})

    def test_several_edges_on_one_circle_are_its_list(self):
        self.assertEqual(_input_names().split_inputs([1, 2, 3], [0, 0, 1]), {"input_0": [1, 2], "input_1": 3})

    def test_no_input_binds_nothing(self):
        names = _input_names()
        self.assertEqual(names.split_inputs("", None), {})
        self.assertEqual(names.split_inputs(None, [0]), {})


class TestTheHeader(unittest.TestCase):
    def test_each_name_the_code_reads_is_a_parameter(self):
        header = _input_names().user_code_header("    return input_0 + input_3\n")
        self.assertEqual(header, "def userCode(input_0=None, input_3=None, **_curio_unread_inputs):")

    def test_a_name_in_a_string_or_a_comment_is_not_read(self):
        self.assertEqual(_input_names().input_names_read("    # input_1\n    return 'input_2'\n"), [])

    def test_the_header_is_one_line_so_tracebacks_keep_their_line_numbers(self):
        from utk_curio.sandbox.util.user_code import compile_user_code

        source = compile_user_code("    return input_0\n", os.getcwd())
        self.assertEqual(source.splitlines()[0], _input_names().user_code_header("    return input_0\n"))
        self.assertEqual(source.splitlines()[1], "    return input_0")


class TestWhatIsRefused(unittest.TestCase):
    def test_reading_arg_or_input_unbound(self):
        names = _input_names()
        self.assertEqual(names.legacy_name_read("    return arg\n"), "arg")
        self.assertEqual(names.legacy_name_read("    return input.head()\n"), "input")

    def test_a_name_the_code_binds_itself_is_its_own(self):
        names = _input_names()
        self.assertIsNone(names.legacy_name_read("    arg = 1\n    return arg\n"))
        self.assertIsNone(names.legacy_name_read("    return [arg for arg in range(3)]\n"))
        self.assertIsNone(names.legacy_name_read("    f = lambda input: input + 1\n    return f(1)\n"))

    def test_the_letters_in_a_word_a_string_or_a_comment_are_not_a_read(self):
        code = (
            "    # pull the target layer, large extent, no upstream input needed\n"
            "    import geopandas as gpd\n"
            "    return gpd.read_file('https://example.org/x?margin=2&args=1&arg=input')\n"
        )
        self.assertIsNone(_input_names().legacy_name_read(code))

    def test_javascript_reads_and_bindings(self):
        names = _input_names()
        self.assertEqual(names.legacy_name_read_js("return arg + 1;"), "arg")
        self.assertEqual(names.legacy_name_read_js("return input.length;"), "input")
        self.assertIsNone(names.legacy_name_read_js("const input = 3;\nreturn input;"))
        self.assertIsNone(names.legacy_name_read_js("return [1].map((arg) => arg * 2);"))
        self.assertIsNone(names.legacy_name_read_js("return {input: input_0, arg: 2};"))
        self.assertIsNone(names.legacy_name_read_js("// arg\nreturn 'input';"))

    def test_an_old_chip_names_its_new_spelling(self):
        names = _input_names()
        message = names.legacy_chip_message("    return [!! input 0 !!]\n")
        self.assertIn(_OLD_CHIP, message)
        self.assertIn("[!! input_0 !!]", message)
        column = names.legacy_chip_message("    return x[[!! input 2.height !!]]\n")
        self.assertIn("[!! input_2.height !!]", column)
        self.assertIsNone(names.legacy_chip_message("    return input_0  # [!! input_0 !!]\n"))

    def test_the_messages_name_input_0(self):
        names = _input_names()
        self.assertIn("input_0", names.legacy_input_message("arg"))
        self.assertIn("input_0", names.legacy_input_message("input"))


class TestInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init

        _worker_init()

    def _run(self, code, values, slots):
        from utk_curio.sandbox.app.worker import execute_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        file_path, data_type = _refs(values) if values else ("", "")
        result = execute_code(
            textwrap.indent(code, "    "), file_path, "curio.builtin/computation-analysis", data_type,
            save_dataset=False, input_slots=slots,
        )
        if result["stderr"]:
            return result["stderr"]
        return load_from_duckdb(result["output"]["path"])

    def test_circles_0_and_3_are_input_0_and_input_3(self):
        self.assertEqual(self._run("return f'{input_0}|{input_1}|{input_3}'", ["a", "d"], [0, 3]), "a|None|d")

    def test_one_input_on_a_later_circle_is_that_circles_name(self):
        self.assertEqual(self._run("return input_3 + '!'", ["d"], [3]), "d!")

    def test_reading_an_input_none_arrived_on_names_its_circle(self):
        stderr = self._run("return input_2.head()", [], None)
        self.assertIn("reads `input_2`, but nothing arrived on input circle 2", stderr)

    def test_reading_arg_or_input_is_told_input_0(self):
        for name in ("arg", "input"):
            stderr = self._run(f"return {name}", ["a"], [0])
            self.assertIn(f"reads `{name}`, {_OLD_NAME}", stderr)
            self.assertIn("input_0", stderr)

    def test_an_old_chip_is_told_its_new_spelling(self):
        stderr = self._run("return [!! input 0 !!]", ["a"], [0])
        self.assertIn(_OLD_CHIP, stderr)
        self.assertIn("[!! input_0 !!]", stderr)


class TestThroughTheExecRoute(unittest.TestCase):
    """``/exec`` takes the wired circles as ``input_slots``: a lone edge on
    circle 3 is the code's ``input_3``, not ``input_0``."""

    def setUp(self):
        from utk_curio.sandbox.app import app
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db, release_connection

        self.client = app.test_client()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {"CURIO_LAUNCH_CWD": self._tmp.name, "CURIO_ISOLATION": "off"})
        env.start()
        self.addCleanup(env.stop)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        _worker_init()

    def _exec(self, route, code, values, slots):
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        file_path, data_type = _refs(values)
        response = self.client.post(route, json={
            "code": code, "file_path": file_path, "nodeType": "curio.builtin/computation-analysis",
            "dataType": data_type, "save_dataset": False, "input_slots": slots,
        })
        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        if body["stderr"]:
            return body["stderr"]
        return load_from_duckdb(body["output"]["path"])

    def test_python_reads_a_lone_edge_on_circle_3_as_input_3(self):
        self.assertEqual(self._exec("/exec", "    return input_3 + '!'\n", ["d"], [3]), "d!")

    def test_python_reads_circles_0_and_3(self):
        self.assertEqual(self._exec("/exec", "    return input_0 + input_3\n", ["a", "d"], [0, 3]), "ad")

    def test_javascript_reads_a_lone_edge_on_circle_3_as_input_3(self):
        self.assertEqual(self._exec("/execJs", "return input_3 + '!';", ["d"], [3]), "d!")


class TestJavaScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init

        _worker_init()

    def _run(self, code, values, slots):
        from utk_curio.sandbox.app.worker import execute_js_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        file_path, data_type = _refs(values)
        if data_type == "str":
            data_type = "int"
        result = execute_js_code(code, file_path, "curio.builtin/js-computation", data_type,
                                 save_dataset=False, input_slots=slots)
        if result["stderr"]:
            return result["stderr"]
        return load_from_duckdb(result["output"]["path"])

    def test_circles_0_and_3_are_input_0_and_input_3(self):
        self.assertEqual(self._run("return input_0 * 10 + input_3;", [4, 5], [0, 3]), 45)

    def test_an_unwired_circle_is_undefined(self):
        self.assertEqual(self._run("return input_1 === undefined ? input_0 : -1;", [7], [0]), 7)

    def test_reading_arg_or_input_is_told_input_0(self):
        for name in ("arg", "input"):
            stderr = self._run(f"return {name} + 1;", [1], [0])
            self.assertIn(f"reads `{name}`, {_OLD_NAME}", stderr)
            self.assertIn("input_0", stderr)

    def test_an_old_chip_is_told_its_new_spelling(self):
        stderr = self._run("return [!! input 0 !!] + 1;", [1], [0])
        self.assertIn(_OLD_CHIP, stderr)
        self.assertIn("[!! input_0 !!]", stderr)


class TestIsolatedChild(unittest.TestCase):
    """The isolated child binds the same names from the same input, and
    refuses the same old forms with the same messages."""

    def _run(self, code, **extra):
        from utk_curio.sandbox.isolation import child

        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch, True)
        request = {
            "code": textwrap.indent(code, "    "),
            "node_type": "curio.builtin/computation-analysis",
            "data_type": "",
            "scratch_dir": str(scratch),
            "input": {"kind": "none"},
            "dataset_paths": {},
            "session_imports": [],
            "limits": {},
        }
        request.update(extra)
        return child.run_node(request, lambda: {"__builtins__": __builtins__})

    def _two_values(self):
        return {"kind": "sequence", "container": "tuple",
                "items": [{"kind": "str", "value": "a"}, {"kind": "str", "value": "d"}]}

    def test_circles_0_and_3_are_input_0_and_input_3(self):
        manifest = self._run("return f'{input_0}|{input_1}|{input_3}'",
                             data_type="outputs", input=self._two_values(), input_slots=[0, 3])
        self.assertTrue(manifest["ok"], manifest["stderr"])
        self.assertEqual(manifest["output"]["value"], "a|None|d")

    def test_reading_arg_or_input_is_told_input_0(self):
        for name in ("arg", "input"):
            manifest = self._run(f"return {name}", input={"kind": "str", "value": "a"}, input_slots=[0])
            self.assertFalse(manifest["ok"])
            self.assertIn(f"reads `{name}`, {_OLD_NAME}", manifest["stderr"])
            self.assertIn("input_0", manifest["stderr"])

    def test_an_old_chip_is_told_its_new_spelling(self):
        manifest = self._run("return [!! input 0 !!]", input={"kind": "str", "value": "a"}, input_slots=[0])
        self.assertFalse(manifest["ok"])
        self.assertIn(_OLD_CHIP, manifest["stderr"])
        self.assertIn("[!! input_0 !!]", manifest["stderr"])

    def test_its_messages_are_the_in_process_ones(self):
        from utk_curio.sandbox.app import worker

        worker._worker_init()
        for code, said in (
            ("return arg", _OLD_NAME),
            ("return [!! input 0 !!]", _OLD_CHIP),
            ("return input_0['x']", "nothing arrived on input circle 0"),
        ):
            isolated = self._run(code)
            in_process = worker.execute_code(textwrap.indent(code, "    "), "", "DATA_TRANSFORMATION", "",
                                             session_id=None)
            isolated_line = isolated["stderr"].strip().splitlines()[-1]
            self.assertIn(said, isolated_line)
            self.assertEqual(isolated_line, in_process["stderr"].strip().splitlines()[-1], code)


if __name__ == "__main__":
    unittest.main()
