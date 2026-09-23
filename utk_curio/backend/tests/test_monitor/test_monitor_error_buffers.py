"""The error ring buffers: bounds, dedup, ordering, and buffer separation.

Route-level behaviour (what the browser posts, what the gate lets through) is
covered separately once the routes exist. This file is the data structure.
"""

import unittest

from utk_curio.backend.app.monitor import errors


class WindowTests(unittest.TestCase):
    def setUp(self):
        errors.reset()

    def test_the_server_window_is_bounded(self):
        for i in range(300):
            errors.record("backend", summary=f"failure {i}")
        self.assertEqual(len(errors.snapshot()["errors"]), errors.SERVER_WINDOW)

    def test_errors_come_back_newest_first(self):
        errors.record("backend", summary="first")
        errors.record("node", summary="second")
        got = [e["summary"] for e in errors.snapshot()["errors"]]
        self.assertEqual(got[:2], ["second", "first"])

    def test_same_second_entries_are_still_newest_first(self):
        # Timestamps are second-resolution, so a burst of failures ties on the
        # stamp. Without a tiebreak a stable sort hands them back oldest-first,
        # which reads as a page that is not updating.
        for i in range(5):
            errors.record("node", summary=f"burst {i}")
        got = [e["summary"] for e in errors.snapshot()["errors"]]
        self.assertEqual(got, [f"burst {i}" for i in reversed(range(5))])

    def test_identical_errors_collapse_with_a_count(self):
        for _ in range(5):
            errors.record("node", summary="same", detail="same detail")
        entries = errors.snapshot()["errors"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["count"], 5)

    def test_different_details_do_not_collapse(self):
        errors.record("node", summary="KeyError", detail="line 1")
        errors.record("node", summary="KeyError", detail="line 2")
        self.assertEqual(len(errors.snapshot()["errors"]), 2)

    def test_detail_and_summary_are_capped(self):
        errors.record("node", summary="s" * 50_000, detail="d" * 50_000)
        entry = errors.snapshot()["errors"][0]
        self.assertEqual(len(entry["detail"]), errors.DETAIL_CHARS)
        self.assertEqual(len(entry["summary"]), errors.SUMMARY_CHARS)

    def test_recording_never_raises_on_junk(self):
        errors.record("node", summary=None, detail=None, context=None)
        self.assertTrue(errors.snapshot()["errors"])

    def test_the_internal_sort_key_never_escapes(self):
        errors.record("node", summary="one")
        self.assertNotIn("_at", errors.snapshot()["errors"][0])


class BufferSeparationTests(unittest.TestCase):
    """The reason client reports get their own deque.

    POST /api/monitor/errors/client is unauthenticated. If browser reports
    shared a window with server failures, anyone could evict every real error
    by posting junk.
    """

    def setUp(self):
        errors.reset()

    def test_client_spam_cannot_evict_a_server_error(self):
        errors.record("node", summary="the real failure", detail="traceback")
        for i in range(200):
            errors.record("client", summary=f"spam {i}")

        entries = errors.snapshot()["errors"]
        summaries = [e["summary"] for e in entries]
        self.assertIn("the real failure", summaries)
        # The flood is bounded by its own, smaller window.
        client = [e for e in entries if e["source"] == "client"]
        self.assertEqual(len(client), errors.CLIENT_WINDOW)

    def test_dropped_client_reports_are_counted(self):
        errors.record_dropped_client()
        errors.record_dropped_client()
        self.assertEqual(errors.snapshot()["droppedClient"], 2)


class SandboxMergeTests(unittest.TestCase):
    def setUp(self):
        errors.reset()

    def test_sandbox_entries_merge_into_the_ordering(self):
        errors.record("node", summary="local")
        proxied = [{"at": "2099-01-01T00:00:00Z", "source": "sandbox",
                    "summary": "from the sandbox", "detail": "", "count": 1}]
        entries = errors.snapshot(sandbox_entries=proxied)["errors"]
        self.assertEqual(entries[0]["summary"], "from the sandbox")

    def test_a_missing_sandbox_is_simply_absent(self):
        errors.record("node", summary="local")
        entries = errors.snapshot(sandbox_entries=None)["errors"]
        self.assertEqual([e["source"] for e in entries], ["node"])


class SummariseTracebackTests(unittest.TestCase):
    def test_the_last_line_of_a_traceback_is_the_exception(self):
        text = (
            "Traceback (most recent call last):\n"
            '  File "/tmp/node.py", line 3, in <module>\n'
            "    df['population']\n"
            "KeyError: 'population'\n"
        )
        self.assertEqual(errors.summarise_traceback(text), "KeyError: 'population'")

    def test_empty_text_summarises_to_empty(self):
        self.assertEqual(errors.summarise_traceback(""), "")
        self.assertEqual(errors.summarise_traceback(None), "")


if __name__ == "__main__":
    unittest.main()
