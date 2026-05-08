"""End-to-end timeout-stress test: load a very large DataFrame, then fetch a preview.

This test spins up the **sandbox** subprocess on a free port and points the
in-process Flask backend at it via monkey-patching. It then exercises the
full bridge:

    POST /processPythonCode    (backend -> sandbox /exec)
    GET  /get-preview          (backend -> sandbox /get with maxRows)
    GET  /get                  (backend -> sandbox /get full payload)

The test is intentionally heavy so it stresses the new timeout knobs
(``SANDBOX_EXEC_TIMEOUT``, ``SANDBOX_GET_TIMEOUT``) and verifies that:

1. The DataFrame survives the parquet round-trip through DuckDB intact.
2. ``/get-preview`` returns exactly the documented 100 rows alongside the
   real ``totalRows`` count.
3. ``/get`` returns the full payload — this is the request that used to
   surface as ``NetworkError when attempting to fetch resource`` when the
   60s ``timeout`` in routes.py was hit.

Skipped automatically when the sandbox subprocess cannot be started in
the test environment (e.g. CI without geopandas / rasterio installed).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
from flask import Flask

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SANDBOX_BOOT_TIMEOUT_S = 90  # importing geopandas / rasterio is slow on a cold cache


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_live(port: int, proc: subprocess.Popen, deadline: float) -> bool:
    """Poll the sandbox /live endpoint until it responds 200 or the deadline passes."""
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/live", timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def _shutdown_sandbox(proc: subprocess.Popen) -> None:
    """Cleanly shut down the sandbox subprocess.

    Just sends the platform-appropriate terminate signal. The sandbox itself
    is responsible for taking down any reloader-spawned worker (see
    ``_kill_descendants`` and ``_self_destruct_when_parent_dies`` in
    ``utk_curio/sandbox/server.py``). The leak guard in this helper is a
    safety net only — if it ever has to actually kill anything, the
    sandbox-side cleanup has regressed.
    """
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class TestLargeDataFrameE2E(unittest.TestCase):
    """Stress-test the full backend <-> sandbox bridge with a 50M-row DataFrame."""

    sandbox_proc: subprocess.Popen | None = None
    sandbox_port: int = 0

    @classmethod
    def setUpClass(cls):
        # Start a sandbox subprocess on a free port
        cls.sandbox_port = _free_port()
        env = os.environ.copy()
        env["FLASK_SANDBOX_HOST"] = "127.0.0.1"
        env["FLASK_SANDBOX_PORT"] = str(cls.sandbox_port)
        env["CURIO_LAUNCH_CWD"] = REPO_ROOT
        # Use a dedicated DuckDB store so the test cannot collide with a running
        # `curio start` instance writing to the same path.
        env["CURIO_SHARED_DATA"] = ".curio/test-large-df-data/"
        env["PYTHONUNBUFFERED"] = "1"

        try:
            cls.sandbox_proc = subprocess.Popen(
                [sys.executable, "-m", "utk_curio.sandbox.server"],
                env=env,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as e:
            raise unittest.SkipTest(f"Could not spawn sandbox: {e}")

        deadline = time.time() + SANDBOX_BOOT_TIMEOUT_S
        if not _wait_for_live(cls.sandbox_port, cls.sandbox_proc, deadline):
            # Capture a slice of stdout for diagnosis, then skip cleanly.
            try:
                stdout, _ = cls.sandbox_proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout = b""
            _shutdown_sandbox(cls.sandbox_proc)
            tail = (stdout or b"").decode(errors="replace")[-2000:]
            raise unittest.SkipTest(
                f"Sandbox did not become ready within {SANDBOX_BOOT_TIMEOUT_S}s. "
                f"Sandbox log tail:\n{tail}"
            )

        # Build a Flask app with just the API blueprint and point it at the live sandbox.
        from utk_curio.backend.app.api.routes import bp
        from utk_curio.backend.app.api import routes as routes_module

        cls._original_api_port = routes_module.api_port
        routes_module.api_port = cls.sandbox_port

        cls.app = Flask(__name__)
        cls.app.register_blueprint(bp)
        cls.client = cls.app.test_client()
        cls._routes_module = routes_module

        # Stub auth — same pattern as TestSandboxTransportErrors.
        cls._user_patch = patch(
            "utk_curio.backend.app.users.dependencies.get_current_user",
            return_value=MagicMock(is_guest=False),
        )
        cls._user_patch.start()

    @classmethod
    def tearDownClass(cls):
        _shutdown_sandbox(cls.sandbox_proc)

        # Restore the routes module's port so subsequent tests in the same
        # process see the original value.
        if hasattr(cls, "_routes_module") and hasattr(cls, "_original_api_port"):
            cls._routes_module.api_port = cls._original_api_port

        if hasattr(cls, "_user_patch"):
            cls._user_patch.stop()

    def _auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def _run_load(self, code: str, *, node_type: str = "DATA_LOADING"):
        """Indent the user code as a function body (mirrors PythonInterpreter.ts)
        and POST to /processPythonCode. Returns the parsed JSON response."""
        indented = textwrap.indent(textwrap.dedent(code).strip("\n"), "    ") + "\n"
        resp = self.client.post(
            "/processPythonCode",
            json={"code": indented, "nodeType": node_type, "input": {}},
            headers=self._auth_headers(),
        )
        return resp

    def test_one_million_row_load_and_preview(self):
        """The original NetworkError reproducer: 50M-row DataFrame load,
        then preview. Should complete well under the new 600s / 300s timeouts."""
        code = """\
            import pandas as pd
            import numpy as np
            rng = np.random.default_rng(42)
            n = 50_000_000
            df = pd.DataFrame({
                'id': np.arange(n, dtype=np.int64),
                'value': rng.standard_normal(n),
                'category': rng.choice(['A', 'B', 'C', 'D'], n),
                'lat': rng.uniform(41.6, 42.1, n),
                'lon': rng.uniform(-87.95, -87.5, n),
            })
            return df
        """

        # Step 1: load — exercises /processPythonCode + sandbox /exec + save_to_duckdb.
        t0 = time.perf_counter()
        load_resp = self._run_load(code)
        load_elapsed = time.perf_counter() - t0

        self.assertEqual(load_resp.status_code, 200, load_resp.data)
        load_body = load_resp.get_json()
        self.assertEqual(load_body["stderr"], "", load_body["stderr"])
        artifact_id = load_body["output"]["path"]
        self.assertTrue(artifact_id, "no artifact id returned")
        self.assertEqual(load_body["output"]["dataType"], "dataframe")
        # Generous upper bound: real measurements are ~30-120s for 50M rows.
        # The new SANDBOX_EXEC_TIMEOUT is 600s so anything under that is
        # acceptable; we cap the assert at 300s to catch a regression where
        # something becomes pathologically slow.
        self.assertLess(load_elapsed, 300, f"load took {load_elapsed:.1f}s")

        # Step 2: preview — exercises /get-preview + sandbox /get with maxRows.
        # This is the request a DATA_POOL display issues; before the fix it
        # could fail with a 60s timeout.
        t0 = time.perf_counter()
        preview_resp = self.client.get(
            f"/get-preview?fileName={artifact_id}",
            headers=self._auth_headers(),
        )
        preview_elapsed = time.perf_counter() - t0

        self.assertEqual(preview_resp.status_code, 200, preview_resp.data)
        preview_body = preview_resp.get_json()
        self.assertEqual(preview_body["dataType"], "dataframe")
        self.assertEqual(preview_body["totalRows"], 50_000_000)
        self.assertEqual(preview_body["previewRows"], 100)
        self.assertTrue(preview_body.get("preview"))
        # Confirm the preview really truncated by checking row count of a column.
        first_col_data = next(iter(preview_body["data"].values()))
        self.assertEqual(len(first_col_data), 100)
        self.assertLess(preview_elapsed, 60, f"preview took {preview_elapsed:.1f}s")

    def test_worker_self_destructs_when_supervisor_killed(self):
        """Regression test for the parent-watchdog in sandbox/server.py.

        With ``use_reloader=True`` Werkzeug forks a supervisor + worker.
        Calling ``Popen.terminate()`` on the supervisor:

          - On POSIX, sends SIGTERM. The supervisor's signal handler runs
            and kills the worker on the way out.
          - On Windows, calls ``TerminateProcess`` directly. NO signal is
            delivered, so the supervisor's atexit/signal handlers never run.

        Without the parent-watchdog (``_self_destruct_when_parent_dies``),
        the Windows path leaves the worker alive holding the DuckDB lock.
        The next ``curio start`` then fails with "file in use".

        This test starts an *additional* sandbox subprocess (separate from
        the class-level one), snapshots its child PIDs, terminates it, and
        asserts every snapshotted PID is gone within a few seconds.
        """
        try:
            import psutil  # type: ignore
        except ImportError:
            self.skipTest("psutil not available")

        port = _free_port()
        env = os.environ.copy()
        env["FLASK_SANDBOX_HOST"] = "127.0.0.1"
        env["FLASK_SANDBOX_PORT"] = str(port)
        env["CURIO_LAUNCH_CWD"] = REPO_ROOT
        # Separate DuckDB store so a leak here is obvious and doesn't trash the
        # other tests' artifacts.
        env["CURIO_SHARED_DATA"] = ".curio/test-watchdog-data/"
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-m", "utk_curio.sandbox.server"],
            env=env, cwd=REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.time() + SANDBOX_BOOT_TIMEOUT_S
            self.assertTrue(
                _wait_for_live(port, proc, deadline),
                "second sandbox failed to come up",
            )

            # Snapshot the worker PID(s) BEFORE killing the supervisor —
            # once the supervisor is dead, its children records vanish.
            try:
                supervisor = psutil.Process(proc.pid)
                worker_pids = [c.pid for c in supervisor.children(recursive=True)]
            except psutil.NoSuchProcess:
                worker_pids = []
            self.assertGreaterEqual(
                len(worker_pids), 1,
                "expected the reloader to have spawned at least one worker",
            )

            # Hard-kill the supervisor specifically WITHOUT touching the worker —
            # this is the Windows TerminateProcess path that the watchdog
            # exists to handle.
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

            # Watchdog polls os.getppid() every 1s, so give it a generous
            # margin before declaring failure.
            deadline = time.time() + 10
            still_alive: list[int] = []
            while time.time() < deadline:
                still_alive = [pid for pid in worker_pids
                               if psutil.pid_exists(pid)]
                if not still_alive:
                    break
                time.sleep(0.25)

            self.assertEqual(
                still_alive, [],
                f"sandbox worker(s) {still_alive} survived after supervisor was "
                "killed — the parent-watchdog in sandbox/server.py "
                "(_self_destruct_when_parent_dies) regressed",
            )
        finally:
            _shutdown_sandbox(proc)
            # Best-effort cleanup of any survivor we still see (would only run
            # if the assertion above failed, in which case we don't want to
            # leak processes onto the host).
            for pid in worker_pids if 'worker_pids' in dir() else []:
                try:
                    psutil.Process(pid).kill()
                except psutil.NoSuchProcess:
                    pass

    def test_full_get_returns_complete_payload(self):
        """The /get path serializes the *entire* DataFrame to JSON.
        For a moderately large frame this is the request that used to drop
        with NetworkError under the old 60s backend->sandbox timeout."""
        code = """\
            import pandas as pd
            import numpy as np
            rng = np.random.default_rng(7)
            n = 10_000_000
            df = pd.DataFrame({
                'id': np.arange(n, dtype=np.int64),
                'value': rng.standard_normal(n),
            })
            return df
        """

        load_resp = self._run_load(code)
        self.assertEqual(load_resp.status_code, 200, load_resp.data)
        artifact_id = load_resp.get_json()["output"]["path"]

        t0 = time.perf_counter()
        get_resp = self.client.get(
            f"/get?fileName={artifact_id}",
            headers=self._auth_headers(),
        )
        get_elapsed = time.perf_counter() - t0

        self.assertEqual(get_resp.status_code, 200, get_resp.data[:500])
        get_body = get_resp.get_json()
        self.assertEqual(get_body["dataType"], "dataframe")
        # No truncation when maxRows isn't set — we get every row back.
        first_col = next(iter(get_body["data"].values()))
        self.assertEqual(len(first_col), 10_000_000)
        # The new SANDBOX_GET_TIMEOUT is 300s; this should land well under
        # the OLD 60s limit too, but the test exists so a regression that
        # blows past 300s shows up clearly rather than as NetworkError.
        self.assertLess(get_elapsed, 300, f"/get took {get_elapsed:.1f}s")


if __name__ == "__main__":
    unittest.main()
