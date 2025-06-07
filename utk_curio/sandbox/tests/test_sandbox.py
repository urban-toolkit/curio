import unittest
import tempfile
import os
import sys
import json
from utk_curio.sandbox.app import app
from flask import Flask, jsonify

# Modify sys.path to include the sandbox folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'sandbox')))


class TestSandbox(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_live(self):
        response = self.client.get('/live')
        self.assertEqual(response.data.decode('utf-8'), 'Sandbox is live.')
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()