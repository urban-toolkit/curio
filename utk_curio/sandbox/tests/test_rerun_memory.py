"""Re-running a dataflow in a local sandbox (#408).

The report: a dataflow of four geopandas loaders feeding a chart, re-run again
and again on a 16 GB Linux laptop in a local launch, until the OOM killer took
the sandbox. ``_rerun_memory.py`` replays that shape against a real sandbox
process; these tests hold the result to what #408 turned out to be about.

What the replay found on Linux (ubuntu-latest, 16 GB, the reporter's build and
main, 200k and 800k polygons per loader, with and without gc, malloc_trim and
MALLOC_ARENA_MAX=2):

* The sandbox does **not** keep memory across re-runs. After every cycle its
  RSS falls back to within a few hundred MB of idle, and no cleanup changed
  that. The two retention tests below hold that line.
* A re-run's peak comes from **serving** its outputs, not computing them. The
  canvas fetches every output at once, and each full fetch held the artifact
  three times over (the Arrow table, the IPC stream, a ``bytes`` copy of it):
  fetching added two to three times what the loaders themselves did, about
  3.7 GB at 800k polygons. Re-running repeats that spike, and on a laptop
  already running an IDE and a browser the spike is what the OOM killer sees.

Run on any machine with ``python -m pytest`` on this file; override the size
with ``CURIO_RERUN_ROWS`` / ``CURIO_RERUN_CYCLES``, or use the module's CLI for
the per-request table.
"""

import os
import sys
import textwrap
import unittest
import weakref
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

from utk_curio.sandbox.tests import _rerun_memory

ROWS = int(os.environ.get("CURIO_RERUN_ROWS", "200000"))
CYCLES = int(os.environ.get("CURIO_RERUN_CYCLES", "3"))


@pytest.fixture(scope="module")
def replay():
    """One replay of the dataflow, shared by every assertion about it.

    In a directory of its own that is removed afterwards, not pytest's tmp_path:
    the inputs alone are about 80 MB at the default size, and pytest keeps its
    last three temp trees.
    """
    with TemporaryDirectory(prefix="curio-rerun-") as workdir:
        report = _rerun_memory.run(rows=ROWS, cycles=CYCLES, workdir=Path(workdir),
                                   log=lambda _: None)
    print("\n" + report.table())
    return report


def test_serving_a_rerun_costs_no_more_than_computing_it(replay):
    assert replay.checks()["serve"] is None, replay.table()


def test_a_rerun_does_not_grow_the_sandbox(replay):
    assert replay.checks()["growth"] is None, replay.table()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="RSS at rest measures the allocator elsewhere: macOS keeps freed pages "
           "for reuse until the system asks for them back",
)
def test_a_rerun_gives_its_memory_back(replay):
    assert replay.checks()["at_rest"] is None, replay.table()


class FinishedRunHoldsNothingTest(unittest.TestCase):
    """In-process execution drops the run's frames as soon as it returns.

    Checked with weakrefs rather than RSS, so it means the same thing on every
    platform: nothing in the worker (namespace, traceback, cache) keeps the
    input or the output alive after the node has finished.
    """

    def setUp(self):
        from utk_curio.sandbox.util.db import init_db, release_connection

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        self.dataset = Path(self._tmp.name) / "buildings.parquet"
        _rerun_memory.write_dataset(self.dataset, 20_000, seed=0)

    def test_neither_input_nor_output_outlives_the_run(self):
        import builtins

        from utk_curio.sandbox.app.worker import execute_code

        probes = []
        builtins._curio_rerun_probes = probes
        self.addCleanup(delattr, builtins, "_curio_rerun_probes")
        load = textwrap.indent(
            "import builtins, weakref\nimport geopandas as gpd\n"
            f"frame = gpd.read_parquet({str(self.dataset)!r})\n"
            "builtins._curio_rerun_probes.append(weakref.ref(frame))\n"
            "return frame\n", "    ")
        shape = textwrap.indent(
            "import builtins, weakref\n"
            "builtins._curio_rerun_probes.append(weakref.ref(arg))\n"
            "tall = arg[arg['stories'] > 1]\n"
            "builtins._curio_rerun_probes.append(weakref.ref(tall))\n"
            "return tall\n", "    ")

        for _ in range(3):
            loaded = execute_code(load, "", "DATA_LOADING", "", launch_dir=self._tmp.name,
                                  session_id="probe")
            self.assertEqual(loaded["stderr"], "")
            shaped = execute_code(shape, loaded["output"]["path"], "DATA_TRANSFORMATION",
                                  loaded["output"]["dataType"], launch_dir=self._tmp.name,
                                  session_id="probe")
            self.assertEqual(shaped["stderr"], "")
            alive = [ref for ref in probes if ref() is not None]
            self.assertEqual(alive, [], "a finished run still holds its frames")
