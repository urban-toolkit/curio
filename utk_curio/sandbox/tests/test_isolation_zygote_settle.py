"""The zygote's warm-up fork, minus the rest of the zygote.

``zygote._settle_before_serving`` forks once before the first request, so that
no real node is the zygote's first fork (its docstring says why). The fork is
plain POSIX and runs anywhere ``os.fork`` exists. The thread report needs
Linux's /proc and falls silent elsewhere. Both halves are pinned here, with the
fork mocked wherever the point is the bookkeeping rather than the fork itself.

The property that only a live zygote can show -- that it is single-threaded by
the time it serves -- is in test_isolation_linux.py.
"""

import io
import os
import unittest
import warnings
from contextlib import redirect_stderr
from unittest import mock

from utk_curio.sandbox.isolation import zygote

HAS_FORK = hasattr(os, "fork")

# A waitpid status for a child killed by signal 11: the low seven bits carry
# the signal number on both Linux and macOS.
KILLED_BY_SIGSEGV = 11


@unittest.skipUnless(HAS_FORK, "the warm-up fork needs os.fork")
class SettleBeforeServingTest(unittest.TestCase):
    def _settle(self, *, names, status=0):
        """Run the warm-up with the fork mocked. Returns (fork, waitpid, log)."""
        stderr = io.StringIO()
        with mock.patch.object(zygote, "_thread_names", side_effect=names), \
                mock.patch.object(zygote.os, "fork", return_value=4242) as fork, \
                mock.patch.object(zygote.os, "waitpid",
                                  return_value=(4242, status)) as waitpid, \
                redirect_stderr(stderr):
            zygote._settle_before_serving()
        return fork, waitpid, stderr.getvalue()

    def test_forks_exactly_once_and_reaps_the_child(self):
        fork, waitpid, _log = self._settle(names=[["python3"] * 3, ["python3"]])
        fork.assert_called_once_with()
        # Reaped synchronously, before serving, so the accept loop's
        # waitpid(-1) never sees a child it has no connection for.
        waitpid.assert_called_once_with(4242, 0)

    def test_reports_the_threads_the_fork_settled(self):
        _f, _w, log = self._settle(names=[["python3"] * 17, ["python3"]])
        self.assertIn("before the warm-up fork: 17 (python3 x17)", log)
        self.assertIn("after: 1 (python3 x1)", log)
        self.assertNotIn("warning", log)

    def test_warns_when_threads_survive_the_fork(self):
        _f, _w, log = self._settle(
            names=[["python3"] * 5, ["python3", "worker", "worker"]]
        )
        self.assertIn("still 3 threads after the warm-up fork", log)

    def test_is_silent_when_already_single_threaded(self):
        _f, _w, log = self._settle(names=[["python3"], ["python3"]])
        self.assertEqual(log, "")

    def test_is_silent_about_threads_without_proc(self):
        _f, _w, log = self._settle(names=[None, None])
        self.assertEqual(log, "")

    def test_reports_a_warmup_child_killed_by_a_signal(self):
        _f, _w, log = self._settle(
            names=[["python3"], ["python3"]], status=KILLED_BY_SIGSEGV
        )
        self.assertIn("died with signal 11", log)

    def test_a_failed_fork_does_not_stop_the_zygote(self):
        stderr = io.StringIO()
        with mock.patch.object(zygote, "_thread_names", return_value=["python3"]), \
                mock.patch.object(zygote.os, "fork",
                                  side_effect=OSError(11, "try again")), \
                redirect_stderr(stderr):
            zygote._settle_before_serving()  # must not raise
        self.assertIn("warm-up fork failed", stderr.getvalue())

    def test_a_real_fork_returns_to_the_caller(self):
        """Unmocked: the child exits at once and the caller carries on."""
        with warnings.catch_warnings(), redirect_stderr(io.StringIO()):
            # Python 3.12+ warns when a multi-threaded process forks, which a
            # test process with numpy loaded may well be. Expected here.
            warnings.simplefilter("ignore", DeprecationWarning)
            zygote._settle_before_serving()


class WarmUpTest(unittest.TestCase):
    def test_the_warmup_fork_comes_after_the_imports(self):
        """The imports are what start the threads; settling first is useless."""
        calls = []

        def imports():
            calls.append("imports")
            return {}

        with mock.patch.object(zygote, "build_namespace_template",
                               side_effect=imports), \
                mock.patch.object(zygote, "_settle_before_serving",
                                  side_effect=lambda: calls.append("settle")):
            zygote.Zygote("unused.sock").warm_up()
        self.assertEqual(calls, ["imports", "settle"])


class ThreadReportTest(unittest.TestCase):
    def test_describe_threads_counts_and_orders_by_frequency(self):
        self.assertEqual(
            zygote._describe_threads(["python3", "duckdb", "python3"]),
            "3 (python3 x2, duckdb x1)",
        )

    def test_thread_names_is_none_without_proc(self):
        with mock.patch.object(zygote.os, "listdir", side_effect=FileNotFoundError):
            self.assertIsNone(zygote._thread_names())

    @unittest.skipUnless(os.path.isdir("/proc/self/task"), "needs /proc")
    def test_thread_names_sees_at_least_this_thread(self):
        names = zygote._thread_names()
        self.assertGreaterEqual(len(names), 1)
        self.assertTrue(all(isinstance(name, str) and name for name in names))


if __name__ == "__main__":
    unittest.main()
