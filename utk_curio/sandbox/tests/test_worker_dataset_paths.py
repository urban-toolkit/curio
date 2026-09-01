"""The ``curio_dataset_path`` resolver injected into Python node executions.

Generated Data Loading nodes call ``curio_dataset_path("<id>")`` instead of
embedding an absolute path; the backend resolves the ids and passes the mapping
into ``execute_code``, which exposes it to user code as a per-call function.
"""
import os
import tempfile
import unittest

from utk_curio.sandbox.app.worker import _make_curio_dataset_path, _worker_init, execute_code


class TestDatasetPathResolver(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _worker_init()
        from utk_curio.sandbox.util.db import init_db
        init_db()

    def test_mapped_id_resolves_and_code_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "table.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("a,b\n1,2\n")
            code = (
                '    df = pd.read_csv(curio_dataset_path("imported.xabc"))\n'
                '    return int(df["a"].iloc[0])\n'
            )
            result = execute_code(
                code, "", "PYTHON_COMPUTATION", "",
                save_dataset=False,
                dataset_paths={"imported.xabc": csv_path},
            )
            self.assertEqual(result["stderr"], "")
            self.assertEqual(result["output"]["dataType"], "int")

    def test_missing_id_raises_actionable_error(self):
        code = '    return curio_dataset_path("imported.xgone")\n'
        result = execute_code(
            code, "", "PYTHON_COMPUTATION", "",
            save_dataset=False,
            dataset_paths={"imported.xother": "/somewhere/else.csv"},
        )
        self.assertIn("imported.xgone", result["stderr"])
        self.assertIn("is not available in this environment", result["stderr"])

    def test_no_mapping_gives_same_error_not_a_crash(self):
        code = '    return curio_dataset_path("imported.xgone")\n'
        result = execute_code(
            code, "", "PYTHON_COMPUTATION", "",
            save_dataset=False,
            dataset_paths=None,
        )
        self.assertIn("is not available in this environment", result["stderr"])

    def test_resolver_unit_contract(self):
        resolver = _make_curio_dataset_path({"d1": "/data/d1.csv"})
        self.assertEqual(resolver("d1"), "/data/d1.csv")
        with self.assertRaises(RuntimeError):
            resolver("d2")

    def test_exec_route_threads_dataset_paths_through(self):
        """POST /exec: the dataset_paths field reaches the injected resolver."""
        from utk_curio.sandbox.app import app

        client = app.test_client()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "table.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("a,b\n7,8\n")
            response = client.post("/exec", json={
                "code": (
                    '    df = pd.read_csv(curio_dataset_path("imported.xhttp"))\n'
                    '    return int(df["b"].iloc[0])\n'
                ),
                "file_path": "",
                "nodeType": "PYTHON_COMPUTATION",
                "dataType": "",
                "session_id": None,
                "save_dataset": False,
                "dataset_paths": {"imported.xhttp": csv_path},
            })
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["stderr"], "")
            self.assertEqual(data["output"]["dataType"], "int")

    # -- Defensive re-shaping of the /exec payload -------------------------
    # dataset_paths crosses a process boundary, so the sandbox re-validates it
    # instead of trusting the backend's shape. None of these may 500.

    def _exec_with(self, dataset_paths, code="    return 1\n"):
        from utk_curio.sandbox.app import app

        return app.test_client().post("/exec", json={
            "code": code,
            "file_path": "",
            "nodeType": "PYTHON_COMPUTATION",
            "dataType": "",
            "session_id": None,
            "save_dataset": False,
            "dataset_paths": dataset_paths,
        })

    def test_non_dict_dataset_paths_is_ignored(self):
        for bogus in (["a", "b"], "imported.x", 7, True):
            with self.subTest(bogus=bogus):
                response = self._exec_with(bogus)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["stderr"], "")

    def test_missing_dataset_paths_is_ignored(self):
        from utk_curio.sandbox.app import app

        response = app.test_client().post("/exec", json={
            "code": "    return 1\n",
            "file_path": "",
            "nodeType": "PYTHON_COMPUTATION",
            "dataType": "",
            "session_id": None,
            "save_dataset": False,
        })
        self.assertEqual(response.status_code, 200)

    def test_falsy_values_are_dropped(self):
        # An empty path would resolve to the process CWD; the id must instead
        # report as unmapped.
        response = self._exec_with(
            {"imported.xempty": ""},
            code='    return curio_dataset_path("imported.xempty")\n',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("imported.xempty", response.get_json()["stderr"])

    def test_keys_and_values_are_coerced_to_str(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "t.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("a\n5\n")
            # A non-str key must not crash the dict comprehension.
            response = self._exec_with({7: csv_path})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["stderr"], "")

    def test_entries_past_the_cap_are_dropped_not_fatal(self):
        # The cap mirrors the backend's MAX_EXEC_DATASET_IDS; surplus ids are
        # dropped, so the request still succeeds and the dropped id reports as
        # unmapped rather than 500ing.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "t.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("a\n5\n")
            paths = {f"imported.x{i:03d}": csv_path for i in range(40)}
            surplus = "imported.x039"
            response = self._exec_with(
                paths,
                code=f'    return curio_dataset_path("{surplus}")\n',
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(surplus, response.get_json()["stderr"])


if __name__ == "__main__":
    unittest.main()
