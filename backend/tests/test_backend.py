import unittest
import tempfile
import os
import sys
import json
from flask import Flask, jsonify
from backend.app.api.routes import bp

# Initialize the Flask app for testing
app = Flask(__name__)
app.register_blueprint(bp)

# Modify sys.path to include the backend folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

test_data = {
    "workflow": "test_workflow",
    "data": {
        "workflow_name": "test_workflow",  # Make sure this matches the workflow name inserted above
        "activity_name": "COMPUTATION_ANALYSIS",  # Include the activity name in the request
        "activityexec_start_time": "2025-05-09T02:00:00",
        "activityexec_end_time": "2025-05-09T03:00:00",
        "types_input": {"input_relation_1": 1},  # Sample input data
        "types_output": {"output_relation_1": 1},  # Sample output data
        "activity_source_code": "return sum(args[0]) / len(args[0])",
        "input": "[0,1,2,3,4,5]"
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

    def test_process_python_code(self):
        test_code = {"code": test_data["data"]["activity_source_code"],
                     "input": test_data["data"]["input"],
                     "boxType": test_data["data"]["activity_name"]
                    }
        response = self.client.post('/processPythonCode', json=test_code)
        self.assertEqual(response.status_code, 200)

    def test_prov(self):

        response = self.client.get('/truncateDBProv')
        self.assertEqual(response.status_code, 200)

        response = self.client.post('/saveWorkflowProv', json=test_data)
        self.assertEqual(response.status_code, 200)
    
        response = self.client.post('/newBoxProv', json=test_data)
        self.assertEqual(response.status_code, 200)

        # response = self.client.post('/boxExecProv', json=test_data)
        # self.assertEqual(response.status_code, 200)

        response = self.client.post('/getBoxGraph', json=test_data)
        self.assertEqual(response.status_code, 200)

        response = self.client.post('/deleteBoxProv', json=test_data)
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()