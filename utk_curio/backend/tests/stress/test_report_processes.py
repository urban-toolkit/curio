"""What a tier's report says of each backend process (``report.py``, ``run.py``).

With several backend processes each room's dataflow belongs to one of them,
by the same rule nginx routes by (``backend_processes.shard_of``), and hashing
puts several rooms on some process and none on another. So each room is
reported with its process, each process gets a block of its own (its rooms,
their sync, their agents' turns and phases, and its own threads, memory and
CPU as the probe read them), and the summary shows those blocks when there are
several processes. The harness takes the count from the stack it measures.
Names are imported in each test, so a checkout without them fails test by test.
"""

import io
import unittest
from contextlib import redirect_stdout

MIB = 1024 * 1024
#: Dataflow ids whose first two hex digits are 0x0a, 0x1b and 0x2d: processes
#: 0, 1 and 1 of two, and 2, 3 and 1 of four.
FIRST, SECOND, THIRD = ("0a000000-0000-4000-8000-000000000000", "1b000000-0000-4000-8000-000000000000",
                        "2d000000-0000-4000-8000-000000000000")


def _room(index: int, project_id: str, sync_seconds: list, turn_seconds: list | None = None) -> dict:
    room = {
        "room": index, "project_id": project_id, "members": 5, "tabs": 5,
        "transports": ["websocket"], "doc_ids": ["d0"], "updates": len(sync_seconds),
        "keystrokes": 3, "drags": 1, "deliveries": 16, "sync_seconds": list(sync_seconds),
        "unsynced": 0, "diverged": False, "doc_state_bytes": 4096,
    }
    if turn_seconds is not None:
        room["agents"] = {
            "early": True, "members": 5, "asked": len(turn_seconds),
            "ends": {"done": len(turn_seconds), "error": 0, "withdrawn": 0, "never": 0},
            "turn_seconds": list(turn_seconds), "phases": {"prepared": [value / 2 for value in turn_seconds]},
            "writes": {"landed": len(turn_seconds), "changed_meanwhile": 0, "refused": 0, "none": 0},
            "unsynced": 0, "present_at_end": [], "tabs_showing_agents": 0, "turn_events_told": 9,
            "diverged": False, "turns": [],
        }
    return room


def _reading(at: float, *processes) -> dict:
    """A probe reading of a start's backends, each ``(number, threads, rss
    MiB, cpu seconds)``."""
    each = [{"process": number, "pid": 100 + number, "threads": threads, "rss_bytes": rss * MIB,
             "cpu_seconds": cpu} for number, threads, rss, cpu in processes]
    return {"pid": 100, "threads": sum(one["threads"] for one in each),
            "rss_bytes": sum(one["rss_bytes"] for one in each),
            "cpu_seconds": sum(one["cpu_seconds"] for one in each), "at": at, "processes": each}


class TheRoomToProcessMapTest(unittest.TestCase):
    def test_each_room_is_reported_with_the_process_that_owns_its_dataflow(self):
        from utk_curio.backend.tests.stress.report import agents_summary, socket_summary

        rooms = [_room(0, FIRST, [0.01], [1.0]), _room(1, SECOND, [0.02], [2.0]), _room(2, THIRD, [0.03], [3.0])]
        of_four = socket_summary(rooms, processes=4)
        of_two = agents_summary(rooms, processes=2)
        of_one = socket_summary(rooms)

        self.assertEqual([room["process"] for room in of_four["per_room"]], [2, 3, 1])
        self.assertEqual([(room["project_id"], room["process"]) for room in of_two["per_room"]],
                         [(FIRST, 0), (SECOND, 1), (THIRD, 1)])
        self.assertEqual([room["process"] for room in of_one["per_room"]], [0, 0, 0])

    def test_each_process_has_its_rooms_sync_turns_phases_and_its_own_reading(self):
        from utk_curio.backend.tests.stress.report import backend_summary, process_summary

        rooms = [_room(0, FIRST, [0.010, 0.030], [4.0]), _room(1, SECOND, [0.100, 0.300], [10.0, 20.0]),
                 _room(2, THIRD, [0.200], [30.0])]
        backend = backend_summary(_reading(0.0, (0, 50, 400, 10.0), (1, 70, 600, 20.0)), [],
                                  _reading(10.0, (0, 55, 450, 15.0), (1, 90, 900, 60.0)), 1.0)
        block = process_summary(rooms, 2, backend)
        home, other = block

        self.assertEqual([entry["process"] for entry in block], [0, 1])
        self.assertEqual((home["rooms"], other["rooms"]), ([0], [1, 2]))
        self.assertEqual((home["sync_ms"]["count"], home["sync_ms"]["max"]), (2, 30.0))
        self.assertEqual((other["sync_ms"]["count"], other["sync_ms"]["max"]), (3, 300.0))
        self.assertEqual((home["turn_s"]["count"], other["turn_s"]["count"], other["turn_s"]["max"]), (1, 3, 30.0))
        self.assertEqual(other["phases_s"]["prepared"]["max"], 15.0)
        self.assertEqual(other["backend"]["threads"], {"start": 70, "peak": 90, "end": 90})
        self.assertEqual(other["backend"]["rss_mib"], {"start": 600.0, "peak": 900.0, "end": 900.0})
        self.assertEqual((home["backend"]["cpu"]["cores_busy"], other["backend"]["cpu"]["cores_busy"]), (0.5, 4.0))

    def test_a_process_holding_no_room_is_still_reported(self):
        from utk_curio.backend.tests.stress.report import process_summary

        block = process_summary([_room(0, SECOND, [0.01])], 2, None)

        self.assertEqual([(entry["process"], entry["rooms"]) for entry in block], [(0, []), (1, [0])])
        self.assertIsNone(block[0]["sync_ms"], "a process with no room has no sync time, never a zero")
        self.assertIsNone(block[0]["backend"])

    def test_the_summary_shows_each_process_only_when_there_are_several(self):
        from utk_curio.backend.tests.stress.report import markdown, process_summary, tier_summary

        rooms = [_room(0, FIRST, [0.01], [1.0]), _room(1, SECOND, [0.02], [2.0])]

        def report(processes: int) -> str:
            tier = tier_summary(10, [], 1.0, "burst")
            tier["processes"] = process_summary(rooms, processes, None)
            return markdown({"run_id": "x", "backend_url": "u", "profile": "burst", "tiers": [tier],
                             "failed": False, "backend_processes": processes})

        several, one = report(2), report(1)

        self.assertIn("| Tier | Process |", several)
        self.assertEqual(several.count("| 10 | "), 3, several)
        self.assertNotIn("| Tier | Process |", one)


class TheProcessCountTest(unittest.TestCase):
    def test_the_harness_counts_the_processes_the_stack_runs(self):
        from utk_curio.backend.tests.stress.backend_probe import ProbeError
        from utk_curio.backend.tests.stress.run import backend_process_count

        class Stack:
            def read(self, project_ids=()):
                return {"pid": 100, "threads": 1, "rss_bytes": 1, "cpu_seconds": 0.0, "count": 4}

        class Down:
            def read(self, project_ids=()):
                raise ProbeError("no process here serves -m backend.server")

        said = io.StringIO()
        with redirect_stdout(said):
            told = backend_process_count(8, Stack())
        self.assertEqual(told, 4, "a count the stack does not run would map every room to the wrong process")
        self.assertIn("4", said.getvalue())
        self.assertEqual(backend_process_count(None, Stack()), 4)
        self.assertEqual(backend_process_count(8, None), 8)
        self.assertEqual(backend_process_count(8, Down()), 8)
        self.assertEqual(backend_process_count(None, None), 1)


if __name__ == "__main__":
    unittest.main()
