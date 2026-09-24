"""Backend execution counters: bounds, correctness, and never raising.

No Flask app here on purpose. The counters module imports nothing from Flask so
that this suite stays a fast unit test of the arithmetic, which is the part
that has to be right under concurrency.
"""

import threading
import unittest

from utk_curio.backend.app.monitor import counters


class WindowBoundTests(unittest.TestCase):
    def setUp(self):
        counters.reset()

    def test_the_duration_window_is_bounded(self):
        # The whole "in-memory only, no new table" design rests on this: a
        # process serving a million executions must hold no more than one
        # serving two hundred.
        for i in range(1000):
            counters.record_execution(language="python", ok=True, duration_ms=i)
        snap = counters.snapshot()
        self.assertEqual(snap["total"], 1000)
        self.assertEqual(snap["durations"]["count"], counters.DURATION_WINDOW)

    def test_distinct_node_types_is_a_count_not_a_list(self):
        for i in range(5):
            counters.record_execution(
                language="python", node_type=f"pkg/node-{i}", ok=True,
            )
        snap = counters.snapshot()
        self.assertEqual(snap["distinctNodeTypes"], 5)
        # Node type ids are user-authored strings. On a public payload the ids
        # themselves would be a text channel, so only the count may escape.
        self.assertNotIn("nodeTypes", snap)

    def test_the_node_type_set_stops_growing_at_the_cap(self):
        for i in range(600):
            counters.record_execution(
                language="python", node_type=f"pkg/node-{i}", ok=True,
            )
        self.assertEqual(counters.snapshot()["distinctNodeTypes"], 500)


class ArithmeticTests(unittest.TestCase):
    def setUp(self):
        counters.reset()

    def test_ok_and_error_split(self):
        counters.record_execution(language="python", ok=True)
        counters.record_execution(language="python", ok=False)
        counters.record_execution(language="javascript", ok=False)
        snap = counters.snapshot()
        self.assertEqual((snap["total"], snap["ok"], snap["error"]), (3, 1, 2))
        self.assertEqual((snap["python"], snap["javascript"]), (2, 1))

    def test_percentiles_over_a_known_vector(self):
        for value in range(1, 101):
            counters.record_execution(language="python", ok=True, duration_ms=value)
        d = counters.snapshot()["durations"]
        self.assertEqual(d["p50Ms"], 50)
        self.assertEqual(d["p90Ms"], 90)
        self.assertEqual(d["p99Ms"], 99)
        self.assertEqual(d["maxMs"], 100)

    def test_an_empty_window_reports_none_not_zero(self):
        # Zero would read as "everything was instant" rather than "nothing ran".
        d = counters.snapshot()["durations"]
        self.assertIsNone(d["p50Ms"])
        self.assertIsNone(d["maxMs"])
        self.assertEqual(d["count"], 0)

    def test_buckets_are_a_fixed_shape_with_an_overflow_bin(self):
        for value in (50, 300, 800, 4000, 20000, 90000):
            counters.record_execution(language="python", ok=True, duration_ms=value)
        buckets = counters.snapshot()["durations"]["buckets"]
        self.assertEqual(len(buckets), 6)
        self.assertIsNone(buckets[-1]["leMs"])
        self.assertEqual([b["count"] for b in buckets], [1, 1, 1, 1, 1, 1])

    def test_every_sample_lands_in_exactly_one_bucket(self):
        for value in (1, 100, 101, 500, 501, 1000, 1001, 5000, 30000, 30001):
            counters.record_execution(language="python", ok=True, duration_ms=value)
        d = counters.snapshot()["durations"]
        self.assertEqual(sum(b["count"] for b in d["buckets"]), d["count"])


class NeverRaisesTests(unittest.TestCase):
    def setUp(self):
        counters.reset()

    def test_a_missing_duration_neither_raises_nor_corrupts_the_total(self):
        counters.record_execution(language="python", ok=True, duration_ms=None)
        snap = counters.snapshot()
        self.assertEqual(snap["total"], 1)
        self.assertEqual(snap["durations"]["count"], 0)

    def test_junk_arguments_are_swallowed(self):
        counters.record_execution(language=None, node_type=None, ok=None)
        self.assertEqual(counters.snapshot()["total"], 1)

    def test_the_in_flight_gauge_returns_to_zero_after_an_exception(self):
        with self.assertRaises(ValueError):
            with counters.in_flight():
                self.assertEqual(counters.snapshot()["inFlight"], 1)
                raise ValueError("sandbox blew up")
        self.assertEqual(counters.snapshot()["inFlight"], 0)


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        counters.reset()

    def test_counters_stay_coherent_under_threads(self):
        # The backend is a threaded Werkzeug process, so two nodes finishing at
        # once is the ordinary case, not an exotic one.
        def work():
            for i in range(500):
                counters.record_execution(
                    language="python", ok=(i % 2 == 0), duration_ms=i,
                )

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = counters.snapshot()
        self.assertEqual(snap["total"], 4000)
        self.assertEqual(snap["ok"] + snap["error"], 4000)


if __name__ == "__main__":
    unittest.main()
