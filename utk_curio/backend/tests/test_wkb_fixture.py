"""The committed WKB fixture still says what shapely says.

The frontend's WKB decoder is tested against a committed fixture so that suite
needs no Python. That only means anything if the fixture matches what the
encoder actually produces, which is what this checks. If shapely changes its
output, this fails here rather than leaving the frontend testing itself
against a stale idea of the format.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
           / "tests" / "fixtures" / "wkb-geometries.json")
GENERATOR = REPO_ROOT / "scripts" / "generate_wkb_fixture.py"


class WkbFixtureTest(unittest.TestCase):
    def test_the_fixture_is_what_the_generator_produces(self):
        import pytest

        pytest.importorskip("shapely")
        committed = json.loads(FIXTURE.read_text())
        before = FIXTURE.read_text()
        try:
            subprocess.run(
                [sys.executable, str(GENERATOR)], cwd=REPO_ROOT, check=True,
                capture_output=True,
            )
            regenerated = json.loads(FIXTURE.read_text())
        finally:
            FIXTURE.write_text(before)

        self.assertEqual(
            committed, regenerated,
            "the committed WKB fixture no longer matches shapely's output; "
            "run scripts/generate_wkb_fixture.py and review the diff",
        )

    def test_it_covers_both_byte_orders_and_every_geometry_type(self):
        """A decoder that ignores the endianness flag passes little-endian
        tests by luck, and an empty geometry is the case that crashes one."""
        cases = json.loads(FIXTURE.read_text())
        for name in ("point", "linestring", "polygon", "multipoint",
                     "multilinestring", "multipolygon", "geometrycollection",
                     "empty_point", "empty_polygon"):
            self.assertIn(name, cases)
            self.assertIn(f"{name}_big_endian", cases)


if __name__ == "__main__":
    unittest.main()
