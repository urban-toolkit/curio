"""dev/120: the sandbox refuses no node by its type NAME.

``checkIOType`` used to refuse a Data Loading node whose output was not a
(geo)dataframe/raster and any Data Export node that produced output — but only
when addressed by the legacy uppercase name, which no caller has sent since
namespaced ids landed. The validators are gone; these tests pin that the same
code executes whichever spelling the request carries, so the check can never
silently return through a canonicalisation.
"""

import unittest

from utk_curio.sandbox.app.worker import _worker_init, execute_code
from utk_curio.sandbox.util import parsers


def _run(code: str, node_type: str) -> dict:
    return execute_code(code, "", node_type, "", save_dataset=False)


class TestIOCheckRetired(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _worker_init()
        from utk_curio.sandbox.util.db import init_db
        init_db()

    def test_a_data_loading_node_may_return_a_dict(self):
        code = '    return {"rows": 3, "source": "inline"}\n'
        for node_type in ("curio.builtin/data-loading@1", "curio.builtin/data-loading", "DATA_LOADING"):
            result = _run(code, node_type)
            self.assertEqual(result["stderr"], "", node_type)
            self.assertEqual(result["output"]["dataType"], "dict", node_type)

    def test_a_data_export_node_may_return_a_value(self):
        code = '    return 42\n'
        for node_type in ("curio.builtin/data-export@1", "DATA_EXPORT"):
            result = _run(code, node_type)
            self.assertEqual(result["stderr"], "", node_type)
            self.assertEqual(result["output"]["dataType"], "int", node_type)

    def test_the_name_is_a_no_op_for_every_argument(self):
        self.assertIsNone(parsers.checkIOType({"dataType": "outputs", "data": [{}] * 9}, "DATA_TRANSFORMATION"))
        self.assertIsNone(parsers.checkIOType({"dataType": "str", "data": None}, "DATA_LOADING", False))
        for gone in ("validate_input", "validate_output", "check_valid_output",
                     "check_dataframe_input", "check_transformation_input"):
            self.assertFalse(hasattr(parsers, gone), gone)


if __name__ == "__main__":
    unittest.main()
