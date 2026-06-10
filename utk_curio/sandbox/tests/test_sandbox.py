import shutil
import unittest
import tempfile
import os
import sys
import json
from utk_curio.sandbox.app import app
from flask import Flask, jsonify

# Modify sys.path to include the sandbox folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'sandbox')))

_SKIP_NO_NODE = unittest.skipIf(
    shutil.which('node') is None,
    "Node.js is not installed — skipping JS execution tests",
)


class TestSandbox(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_live(self):
        response = self.client.get('/live')
        self.assertEqual(response.data.decode('utf-8'), 'Sandbox is live.')
        self.assertEqual(response.status_code, 200)

    @_SKIP_NO_NODE
    def test_exec_js_returns_scalar(self):
        """POST /execJs with a scalar return value."""
        response = self.client.post('/execJs', json={
            'code': 'return 42;',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('output', data)
        self.assertIn('stdout', data)
        self.assertIn('stderr', data)
        self.assertEqual(data['stderr'], '')
        self.assertNotEqual(data['output']['path'], '')

    @_SKIP_NO_NODE
    def test_exec_js_console_log_captured(self):
        """console.log output appears in stdout."""
        response = self.client.post('/execJs', json={
            'code': 'console.log("hello"); return 1;',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('hello', data['stdout'])

    @_SKIP_NO_NODE
    def test_exec_js_syntax_error_returned_in_stderr(self):
        """A JS syntax/runtime error is returned in stderr, not as a 500."""
        response = self.client.post('/execJs', json={
            'code': 'throw new Error("oops");',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('oops', data['stderr'])
        self.assertEqual(data['output']['path'], '')

    @_SKIP_NO_NODE
    def test_execute_js_code_direct(self):
        """Unit-test execute_js_code() directly."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        _worker_init()
        result = execute_js_code('return arg * 2;', '', 'JS_COMPUTATION', '', session_id=None)
        self.assertIn('output', result)
        self.assertEqual(result['stderr'], '')

    @_SKIP_NO_NODE
    def test_exec_js_result_stored_in_duckdb(self):
        """JS result is retrievable from Python DuckDB via the returned artifact ID."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb
        _worker_init()
        result = execute_js_code('return 42;', '', 'JS_COMPUTATION', '', session_id=None)
        self.assertEqual(result['stderr'], '')
        artifact_id = result['output']['path']
        self.assertNotEqual(artifact_id, '')
        value = load_from_duckdb(artifact_id, session_id=None)
        self.assertEqual(value, 42)

    @_SKIP_NO_NODE
    def test_exec_js_receives_input_from_duckdb(self):
        """JS code receives Python-DuckDB-stored input via the arg parameter."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        artifact_id = save_to_duckdb(10, node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg + 1;', artifact_id, 'JS_COMPUTATION', 'int', session_id=None)
        self.assertEqual(result['stderr'], '')
        value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(value, 11)

    @_SKIP_NO_NODE
    def test_exec_js_float_stored_correclty_in_duckdb(self):
        """Floats can be inserted and accsess from duckDB without any side effects"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        float_artifact_id = save_to_duckdb(3.14159, node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg;', float_artifact_id, 'JS_COMPUTATION', 'float', session_id=None)
        self.assertEqual(result['stderr'], '')
        float_value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertAlmostEqual(float_value, 3.14159)

    @_SKIP_NO_NODE
    def test_exec_js_string_stored_correclty_in_duckdb(self):
        """Strings are stored and accsessed gracefully with DuckDB"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        string_artifact_id = save_to_duckdb("Hello ", node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg + "World";', string_artifact_id, 'JS_COMPUTATION', 'str', session_id=None)
        self.assertEqual(result['stderr'], '')
        string_value =  load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(string_value, "Hello World")
    
    # Tests concerned with interactions between different nodes
    @_SKIP_NO_NODE
    def test_interactions_between_Python_and_JS_node_types(self):
        """Tests whether data will flow nicely from Python to JS nodes"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        artifact_id = save_to_duckdb({"Name": "Ghandi", "Birth_Year": 1947}, node_id="DATA_LOADING", session_id=None)
        result = execute_js_code(
            'let data = arg; data["Birth_Year"] = 1869; return data["Birth_Year"]',
            artifact_id, 'JS_COMPUTATION', 'int', session_id=None
        )
        self.assertEqual(result['stderr'], '')
        value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(value, 1869)

    # Tests concerned with error handling
    @_SKIP_NO_NODE
    def test_empty_returns(self):
        """null and undefined return types are handled gracefully"""
        from utk_curio.sandbox.app.worker import execute_js_code, execute_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        _worker_init()

        # Testing code execution of empty values
        null_result = execute_js_code('return null;', '', 'JS_COMPUTATION', '', session_id=None)
        undefined_result = execute_js_code('return undefined;', '', 'JS_COMPUTATION', '', session_id=None)

        null_artifact_id = null_result['output']['path']
        undefined_artifact_id = undefined_result['output']['path']

        self.assertEqual(null_result['stderr'], '')
        self.assertEqual(undefined_result['stderr'], '')

        null_value = load_from_duckdb(null_artifact_id, session_id=None)
        undefined_value = load_from_duckdb(undefined_artifact_id, session_id=None)

        self.assertEqual(null_value, None)
        self.assertEqual(undefined_value, None)
        
    @_SKIP_NO_NODE
    def test_artifacts_and_session_ids(self):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        """ This tests the isolation of sessions. Can one session grab information from another?"""
        _worker_init()
        init_db()

        artifact_id = save_to_duckdb(67, 'COMPUTATION_ANALYSIS', session_id='8375e155-836c-47zb-ada0-737660baf2ec')     # Fake session id

        # Does the function work properly
        value = load_from_duckdb(artifact_id, session_id="8375e155-836c-47zb-ada0-737660baf2ec")
        self.assertEqual(value, 67)

        # Different session id's cannot accsess information from eachother
        with self.assertRaises(KeyError):
            load_from_duckdb(artifact_id, session_id='1678x145-221f-72fg-rfg2-444333abf2wq')

        # Edge cases may not be nessecary
        # A session without an id cannot accsess information from a session with an id
        # with self.assertRaises(KeyError):
        #     load_from_duckdb(artifact_id, session_id=None)

        # A session with an id cannot accsess information from a session without one
        # artifact_id = save_to_duckdb(10, 'COMPUTATION_ANALYSIS', session_id=None)
        # with self.assertRaises(KeyError):
        #     load_from_duckdb(artifact_id, session_id='1678x145-221f-72fg-rfg2-444333abf2wq')



if __name__ == "__main__":
    unittest.main()