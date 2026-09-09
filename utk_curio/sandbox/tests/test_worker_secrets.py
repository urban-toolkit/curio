"""dev/116 — ``curio_secret("<name>")`` in the in-process worker.

The value reaches node code only through the injected callable: not through
``os.environ``, not through a namespace dict, and never back out in stdout or
stderr un-redacted.
"""
import os
import unittest

from utk_curio.sandbox.app.worker import _worker_init, execute_code
from utk_curio.sandbox.util.secrets import MAX_SECRETS, make_curio_secret, shape_secrets

VALUE = "k3y-v4lue-9876-abcdef"


class TestSecretResolver(unittest.TestCase):

    def test_shape_drops_anything_but_valid_name_to_string(self):
        raw = {"census": VALUE, "Bad Name": "x" * 10, "empty": "", "num": 12, 7: "seven",
               "long": "x" * 5000}
        self.assertEqual(shape_secrets(raw), {"census": VALUE})
        self.assertEqual(shape_secrets(None), {})
        self.assertEqual(shape_secrets(["census"]), {})
        many = {f"k{i}": VALUE for i in range(MAX_SECRETS + 5)}
        self.assertEqual(len(shape_secrets(many)), MAX_SECRETS)

    def test_callable_contract_and_no_value_in_repr(self):
        resolver = make_curio_secret({"census": VALUE})
        self.assertEqual(resolver("census"), VALUE)
        with self.assertRaises(RuntimeError) as ctx:
            resolver("noaa")
        self.assertIn("'noaa'", str(ctx.exception))
        self.assertIn("Settings > Connection keys", str(ctx.exception))
        self.assertNotIn(VALUE, repr(resolver))
        self.assertFalse(hasattr(resolver, "__dict__"))


class TestWorkerInjection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _worker_init()
        from utk_curio.sandbox.util.db import init_db
        init_db()

    def _run(self, code, secrets):
        return execute_code(code, "", "PYTHON_COMPUTATION", "", save_dataset=False, secrets=secrets)

    def test_value_reaches_the_code_through_the_callable_only(self):
        code = (
            '    assert "census" not in str(os.environ)\n'
            f'    assert "{VALUE}" not in str(os.environ)\n'
            '    assert "secrets" not in globals()\n'
            '    return len(curio_secret("census"))\n'
        )
        result = self._run(code, {"census": VALUE})
        self.assertEqual(result["stderr"], "")
        self.assertEqual(result["output"]["dataType"], "int")

    def test_missing_name_is_the_nodes_error_with_the_key_named(self):
        result = self._run('    return curio_secret("noaa")\n', {"census": VALUE})
        self.assertIn("'noaa'", result["stderr"])
        self.assertIn("Connection keys", result["stderr"])
        result = self._run('    return curio_secret("noaa")\n', None)
        self.assertIn("'noaa'", result["stderr"])

    def test_a_printed_or_raised_value_is_redacted_on_the_way_out(self):
        code = (
            '    print("key is", curio_secret("census"))\n'
            '    raise RuntimeError("bad key " + curio_secret("census"))\n'
        )
        result = self._run(code, {"census": VALUE})
        self.assertNotIn(VALUE, "\n".join(result["stdout"]))
        self.assertNotIn(VALUE, result["stderr"])
        self.assertIn("«redacted:census»", result["stdout"][0])
        self.assertIn("«redacted:census»", result["stderr"])

    def test_exec_route_threads_secrets_and_ignores_bad_shapes(self):
        from utk_curio.sandbox.app import app

        client = app.test_client()
        response = client.post("/exec", json={
            "code": '    return len(curio_secret("census"))\n',
            "file_path": "", "nodeType": "PYTHON_COMPUTATION", "dataType": "",
            "session_id": None, "save_dataset": False,
            "secrets": {"census": VALUE, "Bad Name": "zzz"},
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["stderr"], "")
        self.assertEqual(data["output"]["dataType"], "int")
        for bad in (["census"], "census", 5):
            response = client.post("/exec", json={
                "code": '    return 1\n', "file_path": "", "nodeType": "PYTHON_COMPUTATION",
                "dataType": "", "session_id": None, "save_dataset": False, "secrets": bad,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["stderr"], "")


if __name__ == "__main__":
    unittest.main()
