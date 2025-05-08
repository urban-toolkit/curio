import unittest
import json
from sandbox.running import *

class TestToJsonInput(unittest.TestCase):

    def test_simple_input(self):
        input_data = '{"dataType": "inputs", "data": {"key": "value"}}'
        expected_output = {"dataType": "inputs", "data": {"key": "value"}}
        
        result = toJsonInput(input_data)
        self.assertEqual(result, expected_output)

    def test_nested_outputs(self):
        # This test will raise a TypeError because the recursive call sends a dict to json.loads
        input_data = '{"dataType": "outputs", "data": [{"dataType": "outputs", "data": [{"key": "value"}]}]}'
        with self.assertRaises(TypeError):
            toJsonInput(input_data)

    def test_no_data_type(self):
        # This test will raise a KeyError because 'dataType' key is missing
        input_data = '{"data": {"key": "value"}}'
        with self.assertRaises(KeyError):
            toJsonInput(input_data)

    def test_invalid_json(self):
        # Tests invalid JSON formatting
        input_data = '{"dataType": "outputs", "data": [}'
        with self.assertRaises(json.JSONDecodeError):
            toJsonInput(input_data)

if __name__ == "__main__":
    unittest.main()