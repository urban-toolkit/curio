"""dev/116 — connection keys under isolation: they cross the parent->child
request, are popped out of it before the node runs, become the same callable
the in-process path injects, and never reach the manifest un-redacted."""
import json
import os
import tempfile
import unittest

from utk_curio.sandbox.isolation import child, protocol
from utk_curio.sandbox.tests.test_isolation_child import namespace_factory, request

VALUE = "k3y-v4lue-9876-abcdef"


class TestProtocol(unittest.TestCase):

    def test_build_exec_request_carries_secrets_and_defaults_to_empty(self):
        common = dict(code="x", node_type="t", data_type="", scratch_dir="/s",
                      input_spec={"kind": "none"})
        self.assertEqual(protocol.build_exec_request(**common)["secrets"], {})
        req = protocol.build_exec_request(**common, secrets={"census": VALUE})
        self.assertEqual(req["secrets"], {"census": VALUE})
        # Round-trips the private pipe encoding unchanged.
        self.assertEqual(protocol.decode_request(protocol.encode_request(req))["secrets"],
                         {"census": VALUE})


class TestChild(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.scratch = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_value_is_injected_popped_and_absent_from_env_and_namespace(self):
        req = request(
            '    assert "secrets" not in globals()\n'
            f'    assert "{VALUE}" not in str(os.environ)\n'
            '    return len(curio_secret("census"))\n',
            self.scratch, secrets={"census": VALUE},
        )
        result = child.run_node(req, namespace_factory)
        self.assertTrue(result["ok"], result["stderr"])
        self.assertNotIn("secrets", req)  # popped before the node ran
        self.assertNotIn(VALUE, json.dumps(result))

    def test_missing_name_and_no_secrets_field(self):
        result = child.run_node(request('    return curio_secret("noaa")\n', self.scratch),
                                namespace_factory)
        self.assertFalse(result["ok"])
        self.assertIn("'noaa'", result["stderr"])
        self.assertIn("Connection keys", result["stderr"])

    def test_printed_and_raised_values_are_redacted_before_the_manifest(self):
        req = request(
            '    print("k=" + curio_secret("census"))\n'
            '    raise ValueError(curio_secret("census"))\n',
            self.scratch, secrets={"census": VALUE},
        )
        result = child.run_node(req, namespace_factory)
        self.assertFalse(result["ok"])
        self.assertNotIn(VALUE, json.dumps(result))
        self.assertIn("«redacted:census»", result["stdout"][0])
        self.assertIn("«redacted:census»", result["stderr"])
        # Nothing in scratch holds the value either.
        for name in os.listdir(self.scratch):
            with open(os.path.join(self.scratch, name), "rb") as handle:
                self.assertNotIn(VALUE.encode(), handle.read())


if __name__ == "__main__":
    unittest.main()
