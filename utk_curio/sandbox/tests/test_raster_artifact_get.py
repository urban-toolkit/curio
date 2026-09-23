"""Serving a raster resolves its path explicitly, not by moving the cwd.

A raster is the one artifact kind stored as a free-form path rather than as a
payload or a path under the shared data directory, so re-opening it was the
only read on the ``/get`` route that needed the process working directory.
That single dependency is why the route held the sandbox's process-wide
execution lock across its whole DuckDB load: ``os.chdir`` is process-wide,
Flask serves threaded, and ``/exec`` moves the cwd too. It cost 2.64s of lock
hold per artifact fetch, and 78% of the blocked time in the 100-user stress
run was spent waiting on that lock.

Only one of these needs rasterio. The rest inject a fake module, because
rasterio is an optional dependency that ships with a node package rather than
with the sandbox, and the contract under test is which path string gets opened.
"""

import os
import sys
import types
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import get_connection, init_db, release_connection


class ResolveRasterSourceTest(unittest.TestCase):
    """The resolution itself, with no store and no route involved."""

    def test_a_relative_path_resolves_against_the_launch_dir(self):
        """What the in-process writer stores: whatever the user opened.

        ``execute_code`` chdirs to the launch directory before user code runs,
        so ``rasterio.open("data/x.tif")`` records a string that only means
        anything relative to that directory.
        """
        with mock.patch.dict(os.environ, {"CURIO_LAUNCH_CWD": "/launch"}):
            self.assertEqual(
                parsers._resolve_raster_source("data/x.tif"), "/launch/data/x.tif"
            )

    def test_an_absolute_path_is_returned_unchanged(self):
        """What staging stores, and why one join covers both writers.

        pathlib discards the left operand when the right is absolute, so the
        join is the identity here. Rewrite this as os.path.join and isolated
        rasters break.
        """
        with mock.patch.dict(os.environ, {"CURIO_LAUNCH_CWD": "/launch"}):
            self.assertEqual(
                parsers._resolve_raster_source("/data/artifacts/a.tif"),
                "/data/artifacts/a.tif",
            )

    def test_without_a_launch_dir_the_stored_string_stands(self):
        """Nobody chdirs in that configuration, so nothing should move."""
        env = {k: v for k, v in os.environ.items() if k != "CURIO_LAUNCH_CWD"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(parsers._resolve_raster_source("x.tif"), "x.tif")


class FakeDatasetReader:
    """Stands in for rasterio's DatasetReader, which echoes its path in .name."""

    def __init__(self, path):
        self.name = path


class RasterGetTestCase(unittest.TestCase):
    """``/get`` for a raster, driven through the real route."""

    def setUp(self):
        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.launch_dir = Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": str(self.launch_dir),
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        (self.launch_dir / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def insert_raster(self, art_id, value_str):
        get_connection().execute(
            "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, ?, ?, ?)",
            [art_id, "node-1", "raster", value_str],
        )

    def install_fake_rasterio(self):
        """A rasterio that records the exact string it was asked to open."""
        opened = []
        module = types.ModuleType("rasterio")
        module.io = types.SimpleNamespace(DatasetReader=FakeDatasetReader)

        def fake_open(path, *args, **kwargs):
            opened.append(str(path))
            return FakeDatasetReader(str(path))

        module.open = fake_open
        patch = mock.patch.dict(sys.modules, {"rasterio": module})
        patch.start()
        self.addCleanup(patch.stop)
        return opened

    def test_a_relative_raster_is_opened_against_the_launch_dir(self):
        """The route no longer chdirs, so the path has to carry the directory.

        This is the test that fails without the resolution: the process cwd
        during a test run is the repo, not the launch dir, so the bare relative
        string would be opened against the wrong place.
        """
        opened = self.install_fake_rasterio()
        rel = "rasters/elevation.tif"
        (self.launch_dir / "rasters").mkdir(parents=True, exist_ok=True)
        (self.launch_dir / rel).write_bytes(b"II*\x00 not really a tif")
        self.insert_raster("r1", rel)

        body = self.client.get("/get", query_string={"fileName": "r1"}).get_json()

        self.assertEqual(opened, [str(self.launch_dir / rel)])
        self.assertEqual(body["dataType"], "raster")
        self.assertEqual(body["data"], str(self.launch_dir / rel))

    def test_an_absolute_raster_is_opened_as_stored(self):
        """What every isolated execution writes."""
        opened = self.install_fake_rasterio()
        absolute = self.launch_dir / ".curio" / "data" / "artifacts" / "r2.tif"
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(b"II*\x00 not really a tif")
        self.insert_raster("r2", str(absolute))

        body = self.client.get("/get", query_string={"fileName": "r2"}).get_json()

        self.assertEqual(opened, [str(absolute)])
        self.assertEqual(body["data"], str(absolute))

    def test_a_real_geotiff_round_trips(self):
        """The same contract against the actual library, when it is installed."""
        rasterio = __import__("pytest").importorskip("rasterio")
        import numpy as np

        rel = "rasters/real.tif"
        path = self.launch_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            path, "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8",
        ) as dst:
            dst.write(np.array([[1, 2], [3, 4]], dtype="uint8"), 1)
        self.insert_raster("r3", rel)

        body = self.client.get("/get", query_string={"fileName": "r3"}).get_json()

        self.assertEqual(body["dataType"], "raster")
        self.assertEqual(body["data"], str(path))


class ServingTakesNoExecutionLockTest(unittest.TestCase):
    """The point of the whole change, pinned where a future edit would break it."""

    def setUp(self):
        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def _acquisitions(self):
        from utk_curio.sandbox.app.worker import _exec_lock

        return {
            label: entry["acquisitions"]
            for label, entry in _exec_lock.snapshot()["labels"].items()
        }

    def test_serving_an_artifact_takes_no_execution_lock(self):
        import pandas as pd

        name = parsers.save_dataset_parquet(pd.DataFrame({"n": [1, 2]}), "dataframe")
        self.assertIsNotNone(name)

        before = self._acquisitions()
        response = self.client.get("/get", query_string={"fileName": name})
        after = self._acquisitions()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            before, after,
            f"serving an artifact acquired the execution lock: {before} -> {after}",
        )

    def test_serving_works_while_another_thread_holds_the_lock_elsewhere(self):
        """A node execution in flight must not delay or misdirect a fetch.

        Holding the lock and chdir'ing away is what an in-process ``/exec``
        does. Before this change the fetch queued behind it; now it has to
        both proceed and read the right file.
        """
        import threading

        import pandas as pd

        from utk_curio.sandbox.app.worker import _exec_lock

        name = parsers.save_dataset_parquet(pd.DataFrame({"n": [7]}), "dataframe")
        holding = threading.Event()
        release = threading.Event()
        original_cwd = os.getcwd()

        def hold_and_wander():
            with _exec_lock.hold("exec_in_process"):
                os.chdir("/")
                try:
                    holding.set()
                    release.wait(10)
                finally:
                    os.chdir(original_cwd)

        thread = threading.Thread(target=hold_and_wander)
        thread.start()
        try:
            self.assertTrue(holding.wait(5))
            response = self.client.get("/get", query_string={"fileName": name})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["data"]["n"], [7])
        finally:
            release.set()
            thread.join(10)


class ArtifactSlotsAreTakenTest(ServingTakesNoExecutionLockTest):
    """The route holds the bounded gate, not the mutex.

    The pair matters: the first test of this file's other class says node
    executions no longer wait behind fetches, and this one says fetches are
    still capped so a hundred of them cannot claim the container's memory at
    once. Both failed in one direction or the other before this change.
    """

    def _artifact_acquisitions(self):
        from utk_curio.sandbox.app.worker import _artifact_slots

        labels = _artifact_slots.snapshot()["labels"]
        return labels.get("artifact_load", {}).get("acquisitions", 0)

    def test_serving_an_artifact_takes_an_artifact_slot(self):
        import pandas as pd

        name = parsers.save_dataset_parquet(pd.DataFrame({"n": [1]}), "dataframe")
        before = self._artifact_acquisitions()
        response = self.client.get("/get", query_string={"fileName": name})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._artifact_acquisitions(), before + 1)

    def test_the_gate_reports_a_ceiling_above_one(self):
        """One slot would be the mutex again under a different name."""
        from utk_curio.sandbox.app.worker import _artifact_slots

        self.assertGreaterEqual(_artifact_slots.snapshot()["slots"], 2)


if __name__ == "__main__":
    unittest.main()
