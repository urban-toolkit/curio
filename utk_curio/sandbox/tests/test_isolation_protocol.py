"""The parent must not trust anything an isolated child sends back.

A child manifest is written by a process that just ran hostile-by-assumption
user code. These tests are the adversarial half of the boundary: each one is
something a malicious child would actually try.

Runs on every platform. The manifest format has no POSIX dependency, and this
is the security-critical logic, so it must not be gated behind a Linux-only
skip that never runs on the developer's machine.
"""

import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path

from utk_curio.sandbox.isolation import protocol
from utk_curio.sandbox.isolation.protocol import ProtocolError


def manifest(**overrides):
    """A minimal well-formed successful manifest."""
    base = {
        "ok": True,
        "stdout": [],
        "stderr": "",
        "output": {"kind": "int", "value": 7},
        "imports": [],
    }
    base.update(overrides)
    return json.dumps(base)


class TestFilenameEscapes(unittest.TestCase):
    """A child naming a file outside its scratch dir would turn the parent's
    own store-write into an arbitrary file read."""

    ESCAPES = [
        "../../instance/urban_workflow.db",
        "../secret.parquet",
        "..",
        ".",
        "/etc/passwd",
        "C:\\Windows\\System32\\config\\SAM",
        "sub/dir.parquet",
        "sub\\dir.parquet",
        "with\x00nul.parquet",
        ".hidden",
        "",
        "x" * 200,
    ]

    def test_unsafe_filenames_are_rejected(self):
        for name in self.ESCAPES:
            with self.subTest(name=name):
                with self.assertRaises(ProtocolError):
                    protocol.validate_scratch_filename(name)

    def test_non_string_filenames_are_rejected(self):
        for name in (None, 1, ["a"], {"a": 1}):
            with self.subTest(name=name):
                with self.assertRaises(ProtocolError):
                    protocol.validate_scratch_filename(name)

    def test_ordinary_filenames_are_accepted(self):
        for name in ("out.parquet", "out_0.json", "a-b.tif", "A1.parquet"):
            with self.subTest(name=name):
                self.assertEqual(protocol.validate_scratch_filename(name), name)

    def test_escape_via_file_field_is_rejected(self):
        payload = {"kind": "dataframe", "file": "../../etc/passwd"}
        with self.assertRaises(ProtocolError):
            protocol.validate_payload(payload)


class TestSymlinkContainment(unittest.TestCase):
    """The filename check alone cannot see a symlink the child planted."""

    def test_a_symlink_out_of_scratch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "scratch"
            scratch.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")

            link = scratch / "out.parquet"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not permitted on this machine")

            with self.assertRaises(ProtocolError):
                protocol.resolve_in_scratch(scratch, "out.parquet")

    def test_a_real_file_inside_scratch_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "out.parquet").write_bytes(b"x")
            resolved = protocol.resolve_in_scratch(tmp, "out.parquet")
            self.assertTrue(os.path.exists(resolved))
            self.assertTrue(
                os.path.realpath(resolved).startswith(os.path.realpath(tmp))
            )


class TestPickleIsNeverAccepted(unittest.TestCase):
    """Regression guard.

    Returning a DataFrame by pickle is the obvious implementation and a direct
    path back to arbitrary code execution in the parent. If someone swaps the
    transport for pickle later, these fail.
    """

    def test_a_pickle_payload_is_rejected(self):
        blob = pickle.dumps({"ok": True, "output": {"kind": "int", "value": 1}})
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(blob)

    def test_a_pickle_of_a_dangerous_reduce_is_rejected(self):
        class Exploit:
            def __reduce__(self):
                return (os.system, ("echo pwned",))

        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(pickle.dumps(Exploit()))

    def test_the_parser_never_calls_a_code_executing_deserializer(self):
        """Checks for real usage, not mentions.

        The module deliberately talks about pickle in its comments; what must
        never appear is an import of, or call into, a deserializer that can
        execute code.
        """
        import ast

        tree = ast.parse(Path(protocol.__file__).read_text(encoding="utf-8"))

        imported = set()
        bare_calls = set()      # eval(...)      -> the builtin
        attr_calls = set()      # re.compile(...) -> a method, qualified below
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    bare_calls.add(func.id)
                elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    attr_calls.add(f"{func.value.id}.{func.attr}")

        for module in ("pickle", "marshal", "shelve", "dill"):
            self.assertNotIn(module, imported, f"{module} must not be imported")
        # Bare names only: re.compile is a regex, not the compile() builtin.
        for builtin in ("eval", "exec", "compile", "__import__"):
            self.assertNotIn(builtin, bare_calls, f"{builtin}() must not be called")
        for qualified in ("pickle.loads", "marshal.loads", "os.system"):
            self.assertNotIn(qualified, attr_calls, f"{qualified} must not be called")


class TestMalformedManifests(unittest.TestCase):

    def test_not_json(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result("not json at all")

    def test_json_but_not_an_object(self):
        for raw in ("[]", '"a string"', "42", "null"):
            with self.subTest(raw=raw):
                with self.assertRaises(ProtocolError):
                    protocol.parse_child_result(raw)

    def test_oversized_manifest(self):
        raw = "x" * (protocol.MAX_MANIFEST_BYTES + 1)
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(raw)

    def test_success_without_an_output(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(json.dumps({"ok": True, "stderr": ""}))

    def test_unknown_kind(self):
        for kind in ("unknown", "pickle", "bytes", None, 5, "DataFrame"):
            with self.subTest(kind=kind):
                with self.assertRaises(ProtocolError):
                    protocol.validate_payload({"kind": kind})

    def test_non_object_descriptor(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload(["kind", "int"])

    def test_stdout_must_be_strings(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(manifest(stdout=[1, 2]))

    def test_stderr_must_be_a_string(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(manifest(stderr={"a": 1}))


class TestKindTypeConfusion(unittest.TestCase):
    """A mislabelled scalar would be stored in the wrong DuckDB column."""

    def test_bool_may_not_masquerade_as_int(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload({"kind": "int", "value": True})

    def test_int_kind_rejects_a_string(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload({"kind": "int", "value": "7"})

    def test_null_kind_rejects_a_value(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload({"kind": "null", "value": 1})

    def test_str_kind_rejects_an_object(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload({"kind": "str", "value": {"a": 1}})

    def test_file_backed_kinds_require_a_file(self):
        for kind in ("dataframe", "geodataframe", "raster"):
            with self.subTest(kind=kind):
                with self.assertRaises(ProtocolError):
                    protocol.validate_payload({"kind": kind})

    def test_scalar_kinds_round_trip(self):
        cases = [
            ({"kind": "null", "value": None}, None),
            ({"kind": "bool", "value": True}, True),
            ({"kind": "int", "value": 7}, 7),
            ({"kind": "float", "value": 1.5}, 1.5),
            ({"kind": "str", "value": "hi"}, "hi"),
        ]
        for payload, expected in cases:
            with self.subTest(kind=payload["kind"]):
                self.assertEqual(protocol.validate_payload(payload)["value"], expected)


class TestOutputsBundles(unittest.TestCase):

    def test_a_valid_bundle_round_trips(self):
        payload = {
            "kind": "outputs",
            "items": [
                {"kind": "int", "value": 1},
                {"kind": "dataframe", "file": "out_1.parquet"},
            ],
        }
        validated = protocol.validate_payload(payload)
        self.assertEqual(len(validated["items"]), 2)
        self.assertEqual(validated["items"][1]["file"], "out_1.parquet")

    def test_items_must_be_a_list(self):
        with self.assertRaises(ProtocolError):
            protocol.validate_payload({"kind": "outputs", "items": {"a": 1}})

    def test_an_escape_nested_in_a_bundle_is_caught(self):
        payload = {
            "kind": "outputs",
            "items": [{"kind": "dataframe", "file": "../../etc/passwd"}],
        }
        with self.assertRaises(ProtocolError):
            protocol.validate_payload(payload)

    def test_too_many_items(self):
        payload = {
            "kind": "outputs",
            "items": [{"kind": "int", "value": 1}] * (protocol.MAX_OUTPUTS_ITEMS + 1),
        }
        with self.assertRaises(ProtocolError):
            protocol.validate_payload(payload)

    def test_nesting_is_bounded(self):
        payload = {"kind": "outputs", "items": [{"kind": "int", "value": 1}]}
        for _ in range(5):
            payload = {"kind": "outputs", "items": [payload]}
        with self.assertRaises(ProtocolError):
            protocol.validate_payload(payload)


class TestImportReplay(unittest.TestCase):
    """Reported imports are replayed as code in a later child's prologue."""

    def test_valid_imports_pass(self):
        result = protocol.parse_child_result(
            manifest(imports=["import numpy as np", "from shapely import wkt"])
        )
        self.assertEqual(
            result["imports"], ["import numpy as np", "from shapely import wkt"]
        )

    def test_a_smuggled_second_statement_is_rejected(self):
        for statement in (
            "import os; os.system('rm -rf /')",
            "import os\nos.system('id')",
            "import os\rprint(1)",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(ProtocolError):
                    protocol.parse_child_result(manifest(imports=[statement]))

    def test_non_import_statements_are_rejected(self):
        for statement in ("print('hi')", "os.system('id')", "__import__('os')", ""):
            with self.subTest(statement=statement):
                with self.assertRaises(ProtocolError):
                    protocol.parse_child_result(manifest(imports=[statement]))

    def test_oversized_statement_is_rejected(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_child_result(
                manifest(imports=["import " + "a" * 600])
            )


class TestFailureManifests(unittest.TestCase):
    """A failed run carries stderr and no output, and must parse cleanly."""

    def test_failure_needs_no_output(self):
        result = protocol.parse_child_result(
            json.dumps({"ok": False, "stderr": "Traceback...", "stdout": ["before"]})
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["output"])
        self.assertEqual(result["stdout"], ["before"])
        self.assertIn("Traceback", result["stderr"])

    def test_oversized_stderr_is_truncated_not_rejected(self):
        result = protocol.parse_child_result(
            json.dumps({"ok": False, "stderr": "x" * (protocol.MAX_STDERR_CHARS + 500)})
        )
        self.assertEqual(len(result["stderr"]), protocol.MAX_STDERR_CHARS)

    def test_too_many_stdout_lines_are_truncated_not_rejected(self):
        lines = ["line"] * (protocol.MAX_STDOUT_LINES + 10)
        result = protocol.parse_child_result(json.dumps({"ok": False, "stdout": lines}))
        self.assertEqual(len(result["stdout"]), protocol.MAX_STDOUT_LINES)


class TestRequestEncoding(unittest.TestCase):

    def test_request_round_trips(self):
        request = protocol.build_exec_request(
            code="    return 1\n",
            node_type="curio.builtin/computation-analysis",
            data_type="",
            scratch_dir="/tmp/scratch",
            input_spec={"kind": "none"},
            dataset_paths={"ds": "staged.parquet"},
            session_imports=["import numpy as np"],
            limits={"memory_mb": 512},
        )
        decoded = protocol.decode_request(protocol.encode_request(request))
        self.assertEqual(decoded["code"], "    return 1\n")
        self.assertEqual(decoded["dataset_paths"], {"ds": "staged.parquet"})
        self.assertEqual(decoded["limits"], {"memory_mb": 512})

    def test_encoding_is_single_line_utf8(self):
        raw = protocol.encode_request(
            protocol.build_exec_request(
                code="    return 'ünï'\n", node_type="n", data_type="",
                scratch_dir="/s", input_spec={"kind": "none"},
            )
        )
        self.assertIsInstance(raw, bytes)
        self.assertNotIn(b"\n", raw)
        raw.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
