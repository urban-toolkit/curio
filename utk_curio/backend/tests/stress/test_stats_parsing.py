"""The stats log tells you whether the machine was busy or just waiting.

A tier can be slow because the host is saturated or because everything is
queued on one mutex, and those want opposite fixes: more capacity versus less
serialization. Docker reports CPU as a percentage of one core, so the reading
that separates them is cores busy against cores present.

Every stress run before this wrote three fields per line, so both formats
have to parse: the old logs are the baseline anyone will compare against.
"""

import os
import tempfile
import unittest

from utk_curio.backend.tests.stress.report import peak_container_stats


class StatsLogParsingTest(unittest.TestCase):
    def _log(self, text):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        )
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_the_old_three_field_format_still_parses(self):
        path = self._log(
            "curio|352.9MiB / 377.4GiB|138\n"
            "curio|9.9GiB / 377.4GiB|1313\n"
        )
        stats = peak_container_stats(path)
        self.assertEqual(stats["peak_memory_mib"], round(9.9 * 1024, 1))
        self.assertEqual(stats["peak_pids"], 1313)
        # Nothing invented for a column the log does not have.
        self.assertNotIn("peak_cpu_percent", stats)
        self.assertNotIn("peak_cores_busy", stats)

    def test_cpu_is_read_as_cores_busy(self):
        """800% of one core is eight cores, which is the number to compare."""
        path = self._log(
            "curio|200.00%|1GiB / 377.4GiB|100\n"
            "curio|800.00%|2GiB / 377.4GiB|200\n"
        )
        stats = peak_container_stats(path)
        self.assertEqual(stats["peak_cpu_percent"], 800.0)
        self.assertEqual(stats["peak_cores_busy"], 8.0)
        self.assertEqual(stats["mean_cpu_percent"], 500.0)
        # And the memory and PID columns still land in the right place.
        self.assertEqual(stats["peak_memory_mib"], 2048.0)
        self.assertEqual(stats["peak_pids"], 200)

    def test_the_host_line_carries_load_and_core_count(self):
        path = self._log(
            "curio|100.00%|1GiB / 377.4GiB|100\n"
            "HOST|3.20|2.90|2.50|64\n"
            "HOST|11.75|9.10|6.00|64\n"
        )
        stats = peak_container_stats(path)
        self.assertEqual(stats["peak_host_load"], 11.75)
        self.assertEqual(stats["host_cores"], 64)

    def test_a_host_line_is_not_mistaken_for_a_container(self):
        """Its second field is a load average, not a memory reading."""
        path = self._log("HOST|3.20|2.90|2.50|64\n")
        self.assertIsNone(peak_container_stats(path))

    def test_a_missing_log_is_simply_absent(self):
        self.assertIsNone(peak_container_stats("/nonexistent/docker-stats.log"))
        self.assertIsNone(peak_container_stats(None))


if __name__ == "__main__":
    unittest.main()
