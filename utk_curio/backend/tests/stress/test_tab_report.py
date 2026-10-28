"""What a tier's report says of its users' tabs and of the backend's process.

Each tier's users also type and drag in shared dataflows over Socket.IO
(``sockets.py``), so its report gives how long an update took to be in every
other tab of its room, the updates that never were, the backend's threads and
memory before, at the peak of and after the tier, and the doc files the
tier's shared dataflows left on disk. A number the run could not take reads as
not measured, never as a zero, and the wire is named, as the artifacts' is.
Names are imported in each test, so a checkout without them fails test by test.
"""

import unittest


def _room(**overrides):
    room = {
        "room": 0, "project_id": "p0", "members": 5, "tabs": 5,
        "transports": ["websocket"], "doc_ids": ["d0"], "updates": 4,
        "keystrokes": 3, "drags": 1, "deliveries": 16,
        "sync_seconds": [0.010, 0.020, 0.030, 0.040], "unsynced": 0,
        "diverged": False, "doc_state_bytes": 4096,
    }
    room.update(overrides)
    return room


def _tier(**extra):
    from utk_curio.backend.tests.stress.report import tier_summary

    return tier_summary(5, [], 1.0, "burst", **extra)


def _markdown(*tiers):
    from utk_curio.backend.tests.stress.report import markdown

    return markdown({"run_id": "x", "backend_url": "u", "profile": "burst",
                     "tiers": list(tiers), "failed": False})


class SyncTimesTest(unittest.TestCase):
    def test_sync_times_are_milliseconds_with_their_count_and_total(self):
        from utk_curio.backend.tests.stress.report import socket_summary

        tabs = socket_summary([_room(), _room(room=1, project_id="p1", sync_seconds=[0.5])])
        # Nearest rank, as every percentile of the report: of five, the second.
        self.assertEqual(tabs["sync_ms"], {
            "count": 5, "total": 600.0, "p50": 20.0, "p95": 500.0, "max": 500.0,
        })
        self.assertEqual((tabs["rooms"], tabs["tabs"], tabs["updates"]), (2, 10, 8))
        self.assertEqual((tabs["keystrokes"], tabs["drags"], tabs["deliveries"]), (6, 2, 32))
        self.assertEqual(tabs["transports"], ["websocket"])
        self.assertEqual([room["sync_ms"]["count"] for room in tabs["per_room"]], [4, 1])

    def test_rooms_with_no_second_tab_report_no_sync_time_rather_than_zero(self):
        from utk_curio.backend.tests.stress.report import socket_summary

        tabs = socket_summary([_room(tabs=1, members=1, sync_seconds=[], deliveries=0)])
        self.assertIsNone(tabs["sync_ms"])
        self.assertIn("no other tab", _markdown(_tier(sockets=tabs)))

    def test_a_tier_with_no_rooms_has_no_tabs_section(self):
        from utk_curio.backend.tests.stress.report import socket_summary

        self.assertIsNone(socket_summary([]))
        self.assertNotIn("| Rooms |", _markdown(_tier()))

    def test_unsynced_updates_and_diverged_rooms_are_counted_and_shown(self):
        from utk_curio.backend.tests.stress.report import socket_summary

        tabs = socket_summary([_room(unsynced=3), _room(room=1, diverged=True)])
        self.assertEqual((tabs["unsynced"], tabs["diverged_rooms"]), (3, 1))
        row = next(line for line in _markdown(_tier(sockets=tabs)).splitlines()
                   if line.startswith("| 5 | 2 |"))
        self.assertTrue(row.endswith("| 3 | 1 |"), row)

    def test_the_doc_a_joining_tab_downloads_is_its_largest_rooms(self):
        from utk_curio.backend.tests.stress.report import socket_summary

        tabs = socket_summary([_room(doc_state_bytes=2048), _room(room=1, doc_state_bytes=8192)])
        self.assertEqual(tabs["doc_state_bytes"], {"max": 8192, "total": 10240})
        self.assertIn("8.0 KiB at most", _markdown(_tier(sockets=tabs)))


class BackendProcessTest(unittest.TestCase):
    MIB = 1024 * 1024

    def test_threads_and_memory_give_start_peak_and_end(self):
        from utk_curio.backend.tests.stress.report import backend_summary

        start = {"pid": 7, "threads": 40, "rss_bytes": 100 * self.MIB}
        samples = [{"t": 1.0, "threads": 140, "rss_bytes": 300 * self.MIB},
                   {"t": 2.0, "threads": 90, "rss_bytes": 250 * self.MIB}]
        end = {"pid": 7, "threads": 42, "rss_bytes": 180 * self.MIB}
        backend = backend_summary(start, samples, end, 1.0)
        self.assertEqual(backend["threads"], {"start": 40, "peak": 140, "end": 42})
        self.assertEqual(backend["rss_mib"], {"start": 100.0, "peak": 300.0, "end": 180.0})
        self.assertEqual((backend["measured"], backend["samples"], backend["pid"]), (True, 2, 7))
        row = next(line for line in _markdown(_tier(backend=backend)).splitlines()
                   if line.startswith("| 5 | 40"))
        self.assertIn("40 / 140 / 42", row)
        self.assertIn("100.0 / 300.0 / 180.0", row)

    def test_a_peak_counts_the_readings_before_and_after_the_tier(self):
        from utk_curio.backend.tests.stress.report import backend_summary

        backend = backend_summary({"threads": 50, "rss_bytes": 0}, [],
                                  {"threads": 20, "rss_bytes": 0}, 1.0)
        self.assertEqual(backend["threads"], {"start": 50, "peak": 50, "end": 20})

    def test_a_missing_reading_is_none_and_never_zero(self):
        from utk_curio.backend.tests.stress.report import backend_summary

        backend = backend_summary(None, [{"threads": 9, "rss_bytes": self.MIB}], None, 1.0,
                                  "before the tier: no process here serves -m backend.server")
        self.assertEqual(backend["threads"], {"start": None, "peak": 9, "end": None})
        self.assertIn("before the tier", backend["problem"])

    def test_a_backend_the_probe_never_read_is_not_measured_and_says_why(self):
        from utk_curio.backend.tests.stress.report import backend_summary, doc_files_summary

        why = "after the tier: exit 1: Error response from daemon: No such container"
        backend = backend_summary(None, [], None, 1.0, why)
        self.assertEqual(backend, {"measured": False, "problem": why})
        files = doc_files_summary(None, why)
        self.assertEqual(files, {"measured": False, "problem": why})
        rendered = _markdown(_tier(backend=backend, doc_files=files))
        self.assertIn(f"not measured: {why}", rendered)
        row = next(line for line in rendered.splitlines() if line.startswith("| 5 | not measured"))
        self.assertNotIn("| 0 |", row)


class DocFilesTest(unittest.TestCase):
    def test_the_doc_files_add_up_per_tier(self):
        from utk_curio.backend.tests.stress.report import doc_files_summary

        files = doc_files_summary({
            "p1": [{"doc": "a" * 32, "day": "2026-10-28", "bin_bytes": 1000, "updates_bytes": 5000},
                   {"doc": "a" * 32, "day": "2026-10-29", "bin_bytes": 3000, "updates_bytes": 100}],
            "p2": [{"doc": "b" * 32, "day": "2026-10-28", "bin_bytes": 2000, "updates_bytes": None}],
            "p3": [],
        })
        self.assertEqual((files["dataflows"], files["docs"], files["segments"]), (3, 2, 3))
        self.assertEqual(files["bin_bytes"], {"total": 6000, "max": 3000})
        self.assertEqual(files["updates_bytes"], {"total": 5100, "max": 5000})
        self.assertEqual(files["without_log"], ["p3"])
        self.assertEqual({entry["project_id"] for entry in files["files"]}, {"p1", "p2"})
        row = next(line for line in _markdown(_tier(doc_files=files)).splitlines()
                   if line.startswith("| 5 |"))
        self.assertIn("| 2 | 5.9 KiB | 5.0 KiB |", row)


class TheReportNamesTheTabsWireTest(unittest.TestCase):
    def test_a_report_says_its_tabs_connected_over_websocket(self):
        """As with the artifacts: a reader comparing reports needs to know
        what the tabs connected over."""
        from utk_curio.backend.tests.stress.report import socket_summary

        title = _markdown(_tier(sockets=socket_summary([_room()]))).splitlines()[0]
        self.assertIn("arrow artifacts", title)
        self.assertIn("tabs over websocket", title)

    def test_a_report_with_no_tabs_names_none(self):
        self.assertNotIn("tabs over", _markdown(_tier()).splitlines()[0])


class TheTabsFailuresAreFailuresTest(unittest.TestCase):
    def test_a_tabs_failure_kinds_are_counted_and_fail_the_tier(self):
        from utk_curio.backend.tests.stress.driver import FAILURE_KINDS, Sample, UserResult
        from utk_curio.backend.tests.stress.report import build_report, tier_summary

        for kind in ("socket", "unsynced", "diverged"):
            self.assertIn(kind, FAILURE_KINDS)
        result = UserResult(user="u", example="e.json", started_at=0.0)
        result.samples += [
            Sample("socket yjs update", None, None, 0.1, False, "the server answered None", "socket"),
            Sample("socket settle", None, None, 60.0, False, "1 of its updates ...", "unsynced"),
            Sample("socket converge", None, None, 0.0, False, "its doc differs", "diverged"),
        ]
        tier = tier_summary(5, [result], 1.0, "burst")
        self.assertEqual(tier["failures_by_kind"], {"socket": 1, "unsynced": 1, "diverged": 1})
        self.assertTrue(build_report("x", "u", [tier])["failed"])


if __name__ == "__main__":
    unittest.main()
