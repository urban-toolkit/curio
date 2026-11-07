"""The sandbox's ``/monitor`` reply counts this process's open files and reads
its soft limit on them, beside its memory: what the backend samples every hour
(``backend/app/monitor/open_files.py``)."""

import os
import resource
import tempfile
import unittest

#: The files the test holds open while it asks.
HELD = 100
#: What other threads of the test process may open or close meanwhile.
SLACK = 10


class MonitorOpenFilesTest(unittest.TestCase):
    def _monitor(self) -> dict:
        from utk_curio.sandbox.app.api import app

        token = os.environ.get("CURIO_SANDBOX_TOKEN")
        headers = {"X-Curio-Sandbox-Token": token} if token else {}
        response = app.test_client().get("/monitor", headers=headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        return response.get_json()

    def test_the_reply_counts_this_process_open_files_beside_its_memory(self):
        before = self._monitor()
        self.assertIn("rss_bytes", before)
        self.assertIn("open_files", before)
        self.assertIsInstance(before["open_files"], int)
        self.assertGreater(before["open_files"], 0)

        with tempfile.TemporaryDirectory() as folder:
            held = [open(os.path.join(folder, f"held-{n}"), "w", encoding="utf-8") for n in range(HELD)]
            try:
                during = self._monitor()
            finally:
                for handle in held:
                    handle.close()

        self.assertGreaterEqual(during["open_files"] - before["open_files"], HELD - SLACK,
                                (before["open_files"], during["open_files"]))

    def test_the_reply_reads_the_soft_limit(self):
        soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        expected = None if soft == resource.RLIM_INFINITY or soft < 0 else soft
        self.assertIn("open_files_limit", self._monitor())
        self.assertEqual(self._monitor()["open_files_limit"], expected)
