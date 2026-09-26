"""The committed Arrow artifact fixture still matches the real code path.

The frontend's adapter is tested against a GeoDataFrame saved and served the
way the sandbox really does it, committed so the frontend suite needs no
Python. This is what keeps that fixture honest: if the wire shape changes --
a header, the schema spelling, the GeoJSON the JSON path emits -- it fails
here rather than leaving the frontend asserting against a stale contract.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
           / "tests" / "fixtures" / "arrow-geodataframe.json")
GENERATOR = REPO_ROOT / "scripts" / "generate_arrow_fixture.py"


class ArrowFixtureTest(unittest.TestCase):
    def test_the_fixture_matches_what_the_sandbox_produces(self):
        import pytest

        pytest.importorskip("geopandas")
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

        # The artifact id is minted per run, so it and the bytes that carry it
        # are not comparable; everything that describes the SHAPE is.
        for payload in (committed, regenerated):
            payload["headers"].pop("X-Curio-Filename", None)
            payload["json_envelope"].pop("filename", None)
            payload.pop("arrow_base64", None)

        self.assertEqual(
            committed, regenerated,
            "the committed Arrow fixture no longer matches the sandbox; run "
            "scripts/generate_arrow_fixture.py and review the diff",
        )

    def test_it_carries_both_encodings_of_the_same_artifact(self):
        fixture = json.loads(FIXTURE.read_text())
        self.assertTrue(fixture["arrow_base64"])
        self.assertEqual(fixture["headers"]["X-Curio-Kind"], "geodataframe")
        self.assertEqual(
            fixture["json_envelope"]["data"]["type"], "FeatureCollection"
        )


if __name__ == "__main__":
    unittest.main()
