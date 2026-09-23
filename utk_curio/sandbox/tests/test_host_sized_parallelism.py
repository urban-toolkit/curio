"""How many nodes may run at once, and what the count is read from.

Both pools that bound concurrent execution size themselves to the host. The
numbers they arrive at decide how much memory the instance promises and how
many PIDs it may claim, so what is pinned here is the arithmetic and, just as
much, the order the inputs are read in: a container that reports the host's
memory instead of its own limit sizes a pool to memory it cannot touch.

Runs everywhere. Nothing here forks; the cgroup files are fixtures on disk.
"""

import os
import unittest
from unittest import mock

from utk_curio.sandbox.app import worker
from utk_curio.sandbox.isolation import runner, supervisor
from utk_curio.sandbox.util import hostlimits

GiB_IN_MB = 1024


def sized(cores, memory_mb, pids_max=None, budget_mb=4096):
    """The isolated pool's default on a host with these three numbers."""
    with mock.patch.object(os, "cpu_count", return_value=cores), mock.patch.object(
        hostlimits, "visible_memory_mb", return_value=memory_mb
    ), mock.patch.object(hostlimits, "visible_pids_max", return_value=pids_max):
        return runner._default_parallelism(budget_mb)


def js_sized(cores, memory_mb):
    with mock.patch.object(os, "cpu_count", return_value=cores), mock.patch.object(
        hostlimits, "visible_memory_mb", return_value=memory_mb
    ):
        return worker._default_js_parallelism()


class VisibleMemoryTest(unittest.TestCase):
    """What the process may spend, not what the machine happens to have."""

    def _hostlimits_reading(self, files, phys_pages=None):
        """Run visible_memory_mb against a fake /sys/fs/cgroup."""
        real_open = open

        def fake_open(path, *args, **kwargs):
            if path in files:
                import io

                return io.StringIO(files[path])
            raise FileNotFoundError(path)

        def fake_sysconf(name):
            if phys_pages is None:
                raise ValueError(name)
            return phys_pages if name == "SC_PHYS_PAGES" else 4096

        with mock.patch("builtins.open", fake_open), mock.patch.object(
            os, "sysconf", fake_sysconf
        ):
            self.assertIsNotNone(real_open)  # keep the reference honest
            return hostlimits.visible_memory_mb()

    def test_a_cgroup_limit_wins_over_the_hosts_total(self):
        """The whole point: in a container, sysconf describes someone else."""
        # 8GB limit on a host with 377GB of RAM (4KB pages).
        visible = self._hostlimits_reading(
            {"/sys/fs/cgroup/memory.max": "8589934592\n"},
            phys_pages=377 * 1024 * 256,
        )
        self.assertEqual(visible, 8192)

    def test_cgroup_v2_max_means_unlimited_and_falls_through(self):
        visible = self._hostlimits_reading(
            {"/sys/fs/cgroup/memory.max": "max\n"}, phys_pages=4 * 1024 * 256
        )
        self.assertEqual(visible, 4096)

    def test_cgroup_v1_sentinel_means_unlimited_and_falls_through(self):
        visible = self._hostlimits_reading(
            {"/sys/fs/cgroup/memory/limit_in_bytes": "9223372036854771712\n"},
            phys_pages=4 * 1024 * 256,
        )
        self.assertEqual(visible, 4096)

    def test_none_when_nothing_can_be_read(self):
        """No guess. The callers keep their old constant on a None."""
        self.assertIsNone(self._hostlimits_reading({}, phys_pages=None))

    def test_garbage_is_not_a_limit(self):
        self.assertIsNone(
            self._hostlimits_reading(
                {"/sys/fs/cgroup/memory.max": "not-a-number"}, phys_pages=None
            )
        )


class IsolatedPoolSizingTest(unittest.TestCase):
    def test_a_big_host_is_no_longer_held_to_eight(self):
        """utk: 64 threads, 377GB. The old flat cap said 8 on this machine."""
        self.assertEqual(sized(cores=64, memory_mb=377 * GiB_IN_MB), 32)

    def test_memory_binds_before_cores_on_a_small_vm(self):
        """16 cores would say 8, and 8 x 4096MB is the VM's entire RAM."""
        self.assertEqual(sized(cores=16, memory_mb=32 * GiB_IN_MB), 4)

    def test_the_container_limit_is_what_counts_not_the_host(self):
        """Many cores, tiny cgroup: the pool must fit the container."""
        self.assertEqual(sized(cores=64, memory_mb=8 * GiB_IN_MB), 2)

    def test_the_floor_holds_on_a_machine_with_nothing_to_spare(self):
        self.assertEqual(sized(cores=2, memory_mb=2 * GiB_IN_MB), 2)

    def test_the_ceiling_holds_on_a_machine_with_everything(self):
        self.assertEqual(
            sized(cores=256, memory_mb=2048 * GiB_IN_MB),
            runner.MAX_DEFAULT_PARALLELISM,
        )

    def test_undetectable_memory_keeps_the_historical_cap(self):
        """A wrong guess here is an OOM kill, so it does not guess."""
        self.assertEqual(sized(cores=64, memory_mb=None), 8)

    def test_a_smaller_per_node_budget_buys_more_slots(self):
        """The two numbers multiply, so the count cannot ignore the budget."""
        self.assertEqual(sized(cores=16, memory_mb=32 * GiB_IN_MB, budget_mb=1024), 8)


class PidCeilingTest(unittest.TestCase):
    """A PID ceiling buys fewer children, never thinner ones.

    Squeezing the shared RLIMIT_NPROC allowance instead is what failed nodes
    inside numpy and pyogrio with "can't start new thread" in the 100-user
    run, so the ceiling has to land on the count.
    """

    def test_a_low_pid_ceiling_lowers_the_count(self):
        # 4096 PIDs, half of it for node children, 256 each: eight children.
        self.assertEqual(
            sized(cores=64, memory_mb=377 * GiB_IN_MB, pids_max=4096), 8
        )

    def test_a_ceiling_with_room_does_not(self):
        self.assertEqual(
            sized(cores=64, memory_mb=377 * GiB_IN_MB, pids_max=32768), 32
        )

    def test_the_allowance_per_child_never_shrinks(self):
        per_child = supervisor.DEFAULT_LIMITS["nproc"]
        for parallelism in (2, 8, 32):
            self.assertEqual(
                runner._default_nproc(parallelism), per_child * parallelism
            )


class NodePoolSizingTest(unittest.TestCase):
    """The Node pool's memory term may lower it, never raise it.

    These children compete for cores with the isolated pool, which already
    takes half the cores on its own, so the cap stays where it was.
    """

    def test_a_big_host_keeps_the_existing_cap(self):
        self.assertEqual(
            js_sized(cores=64, memory_mb=377 * GiB_IN_MB),
            worker.MAX_DEFAULT_JS_PARALLELISM,
        )

    def test_a_memory_poor_host_gets_fewer(self):
        """A quarter of 8GB at ~1GB a child: two, not the eight cores allow."""
        self.assertEqual(js_sized(cores=16, memory_mb=8 * GiB_IN_MB), 2)

    def test_undetectable_memory_keeps_the_historical_cap(self):
        self.assertEqual(
            js_sized(cores=64, memory_mb=None), worker.MAX_DEFAULT_JS_PARALLELISM
        )

    def setUp(self):
        worker._js_slots = None

    def tearDown(self):
        worker._js_slots = None


if __name__ == "__main__":
    unittest.main()
