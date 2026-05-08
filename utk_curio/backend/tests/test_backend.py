import shutil
import unittest
import tempfile
import os
import sys
import json
from unittest.mock import patch, MagicMock
import requests
from flask import Flask, jsonify
from utk_curio.backend.app.api.routes import bp

# These tests use a bare Flask app with only the blueprint registered; they have
# no SQLAlchemy user DB, so auth-protected endpoints cannot work here.
# Full coverage for those routes lives in test_projects/ and test_users/.
_SKIP_AUTH = unittest.skip("Requires full app+db setup — covered by test_projects/test_users/")

# Initialize the Flask app for testing
app = Flask(__name__)
app.register_blueprint(bp)

# Modify sys.path to include the backend folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

test_data = {
    "workflow": "test_workflow",
    "data": {
        "workflow_name": "test_workflow",
        "activity_name": "COMPUTATION_ANALYSIS",
        "activityexec_start_time": "2025-05-09T02:00:00",
        "activityexec_end_time": "2025-05-09T03:00:00",
        "types_input": {"input_relation_1": 1},
        "types_output": {"output_relation_1": 1},
        "activity_source_code": "return sum(args[0]) / len(args[0])",
        "input": {
            "dataType": "dataframe",
            "path": "./examples/data/test.data"
        }
    }
}

class TestRoutes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_live(self):
        response = self.client.get('/live')
        self.assertEqual(response.data.decode('utf-8'), 'Backend is live.')
        self.assertEqual(response.status_code, 200)

    @_SKIP_AUTH
    def test_upload_file(self):
        # Create a temporary file for the test
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(b"Test content")  # Write some test data to the file
            tmp_file.seek(0)  # Move the file pointer back to the beginning for reading
            temp_file_path = tmp_file.name  # Save the file path to use in the test

        try:
            # Simulate a file upload using the temporary file
            with open(temp_file_path, 'rb') as file:
                data = {
                    'file': (file, 'test_file.txt')  # Simulate the file upload
                }
                response = self.client.post('/upload', data=data)

                # Test if the file upload was successful
                self.assertIn('File uploaded successfully', response.data.decode('utf-8'))
                self.assertEqual(response.status_code, 200)

        finally:
            # Clean up: Delete the temporary file after the test
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    @_SKIP_AUTH
    def test_process_python_code(self):
        test_code = {
            "code": test_data["data"]["activity_source_code"],
            "nodeType": test_data["data"]["activity_name"],
            "input": {
                "dataType": test_data["data"]["input"]["dataType"],
                "path": test_data["data"]["input"].get("path", ""),
                "data": test_data["data"]["input"].get("data", "")
            }
        }

        response = self.client.post('/processPythonCode', json=test_code)
        self.assertEqual(response.status_code, 200)

    @_SKIP_AUTH
    @unittest.skipIf(shutil.which('node') is None, "Node.js is not installed")
    def test_process_javascript_code_no_input(self):
        """Basic JS execution with no upstream input via /processJavaScriptCode."""
        response = self.client.post('/processJavaScriptCode', json={
            "code": "return 42;",
            "nodeType": "JS_COMPUTATION",
            "input": {},
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('output', data)
        self.assertIn('stdout', data)
        self.assertIn('stderr', data)

    @_SKIP_AUTH
    def test_db(self):
        # checkDB now requires SQLAlchemy (full app) — covered by integration tests
        response = self.client.get('/checkDB')
        self.assertEqual(response.status_code, 200)


class TestSandboxTransportErrors(unittest.TestCase):
    """Verify _sandbox_call converts requests.Timeout / ConnectionError into
    structured JSON error responses (504 / 502) instead of letting them
    propagate as unhandled exceptions that surface to the browser as opaque
    'NetworkError when attempting to fetch resource'.

    The previous behaviour: an unhandled `requests.Timeout` from the bridge
    call would crash the request thread, Werkzeug would close the connection
    mid-flight, and the browser's `fetch` would reject with no useful info.

    These tests mock out (a) the auth dependency and (b) the sandbox HTTP
    session, so they run without a live sandbox or user database.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        # `require_auth` inside routes.py imports `get_current_user` from
        # `utk_curio.backend.app.users.dependencies`. Patching that name so
        # the auth check passes without touching SQLAlchemy.
        cls._user_patch = patch(
            "utk_curio.backend.app.users.dependencies.get_current_user",
            return_value=MagicMock(is_guest=False),
        )
        cls._user_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._user_patch.stop()

    def _auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    # ---- /processPythonCode -------------------------------------------------

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_processPythonCode_504_on_sandbox_timeout(self, mock_session):
        mock_session.post.side_effect = requests.Timeout("simulated read timeout")
        resp = self.client.post(
            '/processPythonCode',
            json={"code": "    return 1", "nodeType": "DATA_LOADING", "input": {}},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 504, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_timeout')
        self.assertEqual(body['path'], '/exec')
        self.assertEqual(body['timeout_seconds'], 600)
        self.assertIn('did not respond', body['message'])
        # The response is structured JSON, not a raw exception string —
        # this is what fixes the "NetworkError when attempting to fetch
        # resource" the browser used to see.
        self.assertIsInstance(body['message'], str)

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_processPythonCode_502_on_sandbox_unreachable(self, mock_session):
        mock_session.post.side_effect = requests.ConnectionError("connection refused")
        resp = self.client.post(
            '/processPythonCode',
            json={"code": "    return 1", "nodeType": "DATA_LOADING", "input": {}},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 502, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_unreachable')
        self.assertIn('Could not reach the sandbox', body['message'])
        self.assertIn('/exec', body['message'])

    # ---- /processJavaScriptCode --------------------------------------------

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_processJavaScriptCode_504_on_sandbox_timeout(self, mock_session):
        mock_session.post.side_effect = requests.Timeout("simulated")
        resp = self.client.post(
            '/processJavaScriptCode',
            json={"code": "return 42;", "nodeType": "JS_COMPUTATION", "input": {}},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 504, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_timeout')
        self.assertEqual(body['path'], '/execJs')
        self.assertEqual(body['timeout_seconds'], 600)

    # ---- /get --------------------------------------------------------------

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_get_504_on_sandbox_timeout(self, mock_session):
        mock_session.get.side_effect = requests.Timeout("simulated")
        resp = self.client.get(
            '/get?fileName=art_test_id',
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 504, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_timeout')
        self.assertEqual(body['path'], '/get')
        self.assertEqual(body['timeout_seconds'], 300)

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_get_preview_504_on_sandbox_timeout(self, mock_session):
        mock_session.get.side_effect = requests.Timeout("simulated")
        resp = self.client.get(
            '/get-preview?fileName=art_test_id',
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 504, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_timeout')
        self.assertEqual(body['path'], '/get')
        # /get-preview keeps a tighter limit because the response is bounded
        # to maxRows by design.
        self.assertEqual(body['timeout_seconds'], 60)

    # ---- /installPackages --------------------------------------------------

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_installPackages_502_on_sandbox_unreachable(self, mock_session):
        mock_session.post.side_effect = requests.ConnectionError("refused")
        resp = self.client.post(
            '/installPackages',
            json={"packages": ["xarray"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 502, resp.data)
        body = resp.get_json()
        self.assertEqual(body['error'], 'sandbox_unreachable')

    # ---- Smoke test: timeout knobs are wired through to requests.post -----

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_exec_timeout_value_passes_through_to_requests(self, mock_session):
        """Regression test: bumping SANDBOX_EXEC_TIMEOUT must reach the
        underlying `requests.post(timeout=...)` call so the wait actually
        gets that long."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'stdout': [],
            'stderr': '',
            'output': {'path': 'art_x', 'dataType': 'dataframe'},
        }
        mock_session.post.return_value = mock_response

        self.client.post(
            '/processPythonCode',
            json={"code": "    return 1", "nodeType": "DATA_LOADING", "input": {}},
            headers=self._auth_headers(),
        )

        from utk_curio.backend.app.api.routes import SANDBOX_EXEC_TIMEOUT
        _, kwargs = mock_session.post.call_args
        self.assertEqual(kwargs['timeout'], SANDBOX_EXEC_TIMEOUT)
        self.assertEqual(SANDBOX_EXEC_TIMEOUT, 600)

    @patch("utk_curio.backend.app.api.routes._sandbox_session")
    def test_get_timeout_value_passes_through_to_requests(self, mock_session):
        mock_response = MagicMock()
        mock_response.json.return_value = {'data': '', 'dataType': 'str'}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        self.client.get('/get?fileName=x', headers=self._auth_headers())

        from utk_curio.backend.app.api.routes import SANDBOX_GET_TIMEOUT
        _, kwargs = mock_session.get.call_args
        self.assertEqual(kwargs['timeout'], SANDBOX_GET_TIMEOUT)
        self.assertEqual(SANDBOX_GET_TIMEOUT, 300)


if __name__ == "__main__":
    unittest.main()
