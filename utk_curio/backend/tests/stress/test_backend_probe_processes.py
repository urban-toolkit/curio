"""The probe reads every backend process of a start (``backend_probe.py``).

``curio.py start --backend-processes N`` runs N backends, each started with
its number (``CURIO_BACKEND_PROCESS``) and the count (``CURIO_BACKEND_PROCESSES``),
and none under Werkzeug's reloader. So the probe reads every process that
serves ``-m backend.server`` (the reloader's child alone when there is one),
sums their threads, resident memory and CPU seconds, lists each by its number
with its own, names a process it did not find, and asks each for its thread
stacks. A start of one process reads as before. Names are imported in each
test, so a checkout without them fails test by test.
"""

import unittest

BACKEND = ["/usr/local/bin/python", "-u", "-m", "backend.server"]


class EveryBackendProcessTest(unittest.TestCase):
    def test_every_backend_of_a_start_serves_and_with_the_reloader_its_child_alone(self):
        from utk_curio.backend.tests.stress.backend_probe import serving_backends

        start = [
            (10, 1, ["python", "curio.py", "start", "all", "--backend-processes", "3"]),
            (13, 10, BACKEND), (11, 10, BACKEND), (12, 10, BACKEND),
            (14, 10, ["/usr/local/bin/python", "-u", "-m", "sandbox.server"]),
            (15, 10, ["nginx", "-c", "/app/.curio/backend-router/nginx.conf"]),
        ]
        reloader = [(20, 1, BACKEND), (21, 20, BACKEND)]

        self.assertEqual(serving_backends(start, own_pid=99), [11, 12, 13])
        self.assertEqual(serving_backends(reloader, own_pid=99), [21])
        self.assertEqual(serving_backends([(30, 1, BACKEND)], own_pid=30), [])

    def test_a_reading_sums_every_process_and_lists_each_by_its_number(self):
        from utk_curio.backend.tests.stress.backend_probe import combined, count_of, number_of

        each = [
            {"pid": 12, "threads": 40, "rss_bytes": 300, "cpu_seconds": 1.25, "process": 1, "count": 2},
            {"pid": 11, "threads": 60, "rss_bytes": 500, "cpu_seconds": 2.5, "process": 0, "count": 2},
        ]
        reading = combined(each)
        home_alone = combined(each[1:])
        other_alone = combined(each[:1])

        self.assertEqual({key: reading[key] for key in ("pid", "threads", "rss_bytes", "cpu_seconds", "count")},
                         {"pid": 11, "threads": 100, "rss_bytes": 800, "cpu_seconds": 3.75, "count": 2})
        self.assertEqual(reading["processes"], [
            {"process": 0, "pid": 11, "threads": 60, "rss_bytes": 500, "cpu_seconds": 2.5},
            {"process": 1, "pid": 12, "threads": 40, "rss_bytes": 300, "cpu_seconds": 1.25},
        ])
        self.assertNotIn("missing", reading)
        self.assertEqual((home_alone["missing"], other_alone["missing"]), ([1], [0]))
        self.assertEqual((number_of({"CURIO_BACKEND_PROCESS": "3", "CURIO_BACKEND_PROCESSES": "8"}),
                          count_of({"CURIO_BACKEND_PROCESS": "3", "CURIO_BACKEND_PROCESSES": "8"})), (3, 8))
        self.assertEqual((number_of({}), count_of({})), (0, 1), "a backend the launcher named nothing is one of one")

    def test_each_processs_thread_stacks_come_back_together(self):
        from utk_curio.backend.tests.stress.backend_probe import combined_stacks

        home = {"pid": 11, "path": "/app/.curio/backend-thread-stacks-0.txt",
                "stacks": "=== thread stacks of pid 11 ===\nmain\n", "process": 0}
        other = {"pid": 12, "path": "/app/.curio/backend-thread-stacks-1.txt", "stacks": "partial",
                 "problem": "no whole dump in 20 s", "process": 1}
        together = combined_stacks([other, home])
        alone = combined_stacks([home])
        unasked = combined_stacks([{"error": "process 11 does not handle SIGUSR1", "process": 0}])

        self.assertEqual((together["pid"], together["path"]), (11, home["path"]))
        self.assertLess(together["stacks"].index(home["stacks"]), together["stacks"].index("partial"))
        self.assertIn("process 1", together["problem"])
        self.assertIn("no whole dump in 20 s", together["problem"])
        self.assertEqual([one["process"] for one in together["processes"]], [0, 1])
        self.assertEqual(alone, {"pid": 11, "path": home["path"], "stacks": home["stacks"]})
        self.assertEqual(unasked, {"error": "process 11 does not handle SIGUSR1"})


if __name__ == "__main__":
    unittest.main()
