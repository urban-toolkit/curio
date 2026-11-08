"""SIGUSR1 makes the backend write every thread's Python stack to a file.

The 11-07 stress run's backend stalled with 153 to 664 threads and left no
stacks: which lock each thread waited on could only be read from the code. Now
the stress harness asks after a tier with failures (``tests/stress``), through
the probe's own ask, and the backend appends a dump (``backend/thread_stacks.py``).
faulthandler's dump stops after 100 threads, so a process with more than that
blocked on one lock shows whether every thread is there.
Names are imported in each test, so a checkout without them fails test by test.
"""

import os
import runpy
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

#: More threads than faulthandler's dump holds (100).
WAITERS = 150

# A process that registers the backend's handler with WAITERS threads blocked
# on one held lock, prints "ready" once each of them waits in
# wait_for_the_room_lock, then idles in its main thread as a server does. A
# file, not ``python -c``, so the dump can show each frame's source line.
_BLOCKED_PROCESS = f"""
import sys, threading, time
from utk_curio.backend import thread_stacks

def wait_for_the_room_lock(lock):
    with lock:
        pass

room_lock = threading.Lock()
room_lock.acquire()
waiters = [threading.Thread(target=wait_for_the_room_lock, args=(room_lock,),
                            name=f"waiter-{{number}}", daemon=True) for number in range({WAITERS})]
for waiter in waiters:
    waiter.start()
deadline = time.monotonic() + 60
while not all(sys._current_frames()[waiter.ident].f_code.co_name == "wait_for_the_room_lock"
              for waiter in waiters):
    if time.monotonic() > deadline:
        print("the waiters never all waited on the lock", flush=True)
        sys.exit(1)
    time.sleep(0.01)
print("ready" if thread_stacks.register() else "not registered", flush=True)
# Busy for the seconds the test names before it idles: the moment right after
# "ready", when the test's signal may come.
busy_until = time.monotonic() + float(sys.argv[1])
while time.monotonic() < busy_until:
    pass
while True:
    time.sleep(0.2)
"""


class TheDumpTest(unittest.TestCase):
    def test_every_thread_blocked_on_a_lock_shows_the_frame_it_waits_in(self):
        """The registration in a process of its own, asked as the stress
        probe asks the backend: SIGUSR1, then the dump read back from the
        file in the process's state folder."""
        self._check_the_dump(busy_seconds=0.0)

    def test_the_dump_finds_the_main_thread_busy_just_after_it_said_ready(self):
        """The test asks as soon as it reads "ready", so on a loaded machine
        the signal can find the main thread before it idles; held busy there
        for 5 seconds, it always does."""
        self._check_the_dump(busy_seconds=5.0)

    def _check_the_dump(self, *, busy_seconds):
        from utk_curio.backend.tests.stress.backend_probe import ask_for_stacks, stacks_file

        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        env = {**os.environ, "CURIO_STATE_DIR": state.name,
               "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))}
        script = Path(state.name, "blocked_on_the_room_lock.py")
        script.write_text(_BLOCKED_PROCESS, encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(script), str(busy_seconds)], env=env,
                                   cwd=state.name, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            first = process.stdout.readline().strip()
            if first != "ready":
                process.kill()
                self.fail(f"the process said {first!r}: {process.communicate()[1][-2000:]}")
            answer = ask_for_stacks(process.pid, stacks_file(env, state.name))
            # The process serves on, as the backend must: the signal did not end it.
            self.assertIsNone(process.poll())
        finally:
            process.kill()
            process.communicate()

        self.assertNotIn("problem", answer)
        self.assertNotIn("error", answer)
        stacks = answer["stacks"]
        self.assertEqual(answer["path"], str(Path(state.name, "backend-thread-stacks.txt")))
        self.assertIn(f"=== thread stacks of pid {process.pid} at ", stacks.splitlines()[0])
        self.assertIn(f": {WAITERS + 1} thread(s), ", stacks.splitlines()[0])
        self.assertTrue(stacks.endswith(f"=== end of the thread stacks of pid {process.pid} ===\n"))
        # The waiters share one stack, listed once with every one of their names.
        group = next(line for line in stacks.splitlines() if line.startswith(f"{WAITERS} thread(s): "))
        for number in range(WAITERS):
            self.assertIn(f"waiter-{number} [", group)
        self.assertIn("in wait_for_the_room_lock", stacks)
        self.assertIn("with lock:", stacks)
        # The main thread where the signal found it, not in the handler.
        self.assertIn("1 thread(s): MainThread [", stacks)
        self.assertIn("time.sleep(0.2)", stacks)
        self.assertNotIn("in on_signal", stacks)
        self.assertNotIn("in dump", stacks)

    def test_the_probe_finds_the_file_the_backend_writes(self):
        """The probe runs with nothing of Curio's, so it keeps its own copy of
        the path and the end line."""
        from utk_curio.backend import thread_stacks
        from utk_curio.backend.tests.stress.backend_probe import stacks_end_line, stacks_file

        for environ, cwd in (({"CURIO_LAUNCH_CWD": "/app"}, "/app/utk_curio"),
                             ({}, "/srv"),
                             ({"CURIO_STATE_DIR": "/state", "CURIO_LAUNCH_CWD": "/app"}, "/app/utk_curio"),
                             ({"CURIO_STATE_DIR": "rel"}, "/app")):
            with self.subTest(environ=environ, cwd=cwd):
                self.assertEqual(thread_stacks.stacks_path(environ, cwd), stacks_file(environ, cwd))
        self.assertEqual(thread_stacks.stacks_path({"CURIO_LAUNCH_CWD": "/app"}, "/app/utk_curio"),
                         Path("/app/.curio/backend-thread-stacks.txt"))
        self.assertEqual(thread_stacks.end_line(41), stacks_end_line(41))


class TheServerRegistersTest(unittest.TestCase):
    def test_serve_registers_the_dump_before_it_serves(self):
        """The server module run as the launcher runs it, ``python -m
        backend.server``, up to the point where it would serve."""
        from flask_socketio import SocketIO

        order = []
        with unittest.mock.patch("utk_curio.backend.thread_stacks.register",
                                 lambda: order.append("register") or True), \
                unittest.mock.patch.object(SocketIO, "run", lambda *args, **kwargs: order.append("serve")), \
                unittest.mock.patch("utk_curio.backend.app.monitor.open_files.start_sampler",
                                    lambda *args, **kwargs: None), \
                unittest.mock.patch("utk_curio.sandbox.util.duckdb_threads.release_default_connection",
                                    lambda *args, **kwargs: None):
            runpy.run_module("utk_curio.backend.server", run_name="__main__")

        self.assertEqual(order, ["register", "serve"])


if __name__ == "__main__":
    unittest.main()
