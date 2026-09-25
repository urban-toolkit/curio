"""How the harness fetches node outputs, and how it digests what comes back.

The harness fetches artifacts as Arrow, the way the canvas does. There is no
format switch: JSON survives as the *client* fallback for kinds Arrow cannot
serve (a dict, a list, a raster), which `fetchData` handles, and measuring a
path users no longer take was only ever worth doing while the Arrow work
needed attributing.

What still needs pinning is the request actually going out as Arrow, and the
digest being stable, since the whole run compares every user against a
single-user baseline.
"""

import types
import unittest

from utk_curio.backend.tests.stress.driver import (
    ARROW_GEOMETRY_HEADERS,
    ARROW_IPC_MIME,
    VirtualUser,
    arrow_artifact_hash,
)


class ArrowDigestTest(unittest.TestCase):
    HEADERS = {
        "Content-Type": ARROW_IPC_MIME,
        "X-Curio-Kind": "dataframe",
        "X-Curio-Filename": "1790201370084_b973a38f",
        "X-Curio-Encoded-Object-Columns": "tags",
    }

    def test_the_same_response_digests_the_same(self):
        self.assertEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
        )

    def test_different_bytes_digest_differently(self):
        self.assertNotEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"other-bytes", dict(self.HEADERS)),
        )

    def test_the_metadata_headers_are_part_of_the_digest(self):
        """The headers carry what the JSON body used to carry inline, so a
        change in them is a real difference in the artifact."""
        changed = dict(self.HEADERS, **{"X-Curio-Kind": "geodataframe"})
        self.assertNotEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", changed),
        )

    def test_the_artifact_id_is_not(self):
        """It is minted per execution, so hashing it would report every user
        as a mismatch against the baseline."""
        renamed = dict(self.HEADERS, **{"X-Curio-Filename": "another_id"})
        self.assertEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", renamed),
        )

    def test_header_case_does_not_matter(self):
        """requests gives a case-insensitive mapping; a plain dict does not."""
        lowered = {k.lower(): v for k, v in self.HEADERS.items()}
        self.assertEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", lowered),
        )

    def test_unrelated_headers_are_ignored(self):
        """Dates and content-length differ per response and mean nothing."""
        noisy = dict(self.HEADERS, Date="Tue, 23 Sep 2026 22:00:00 GMT",
                     **{"Content-Length": "1234"})
        self.assertEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", noisy),
        )


class TheRequestGoesOutAsArrowTest(unittest.TestCase):
    """Everything else could be right while the job measured the fallback.

    Two defects in exactly that shape reached CI: the backend dropped the WKB
    opt-in, and before that the harness never sent it. Both looked like
    success, because a JSON fallback still returns the artifact.
    """

    class FakeResponse:
        status_code = 200
        content = b"ARROW1"
        headers = {"Content-Type": ARROW_IPC_MIME, "X-Curio-Kind": "dataframe"}
        text = ""

        def json(self):
            raise AssertionError("the arrow path must not parse the body as JSON")

    class RecordingSession:
        def __init__(self):
            self.sent = []

        def request(self, method, url, **kwargs):
            self.sent.append((method, url, kwargs.get("headers") or {}))
            return TheRequestGoesOutAsArrowTest.FakeResponse()

    def _fetch_one_artifact(self):
        """Drive the real artifact fetch, the way a tier does."""
        user = VirtualUser(
            "http://backend", "stress_x_t1_u0", "example.json", {}, None, {},
        )
        user.session = self.RecordingSession()
        user.result.outputs["n1"] = {"path": "a1", "dataType": "dataframe"}
        user._compare_to_baseline(types.SimpleNamespace(id="n1"))
        return user.session.sent[0][2]

    def test_the_fetch_asks_for_arrow(self):
        self.assertEqual(self._fetch_one_artifact().get("Accept"), ARROW_IPC_MIME)

    def test_the_fetch_accepts_wkb_geometry(self):
        """Without it every spatial example in the mix comes back 415."""
        headers = self._fetch_one_artifact()
        self.assertEqual(
            headers.get("X-Curio-Accept-Geometry"),
            ARROW_GEOMETRY_HEADERS["X-Curio-Accept-Geometry"],
        )


class TheReportNamesTheWireTest(unittest.TestCase):
    def test_a_report_says_its_artifacts_were_arrow(self):
        """A report outlives the run that made it, and the wire changed."""
        from utk_curio.backend.tests.stress.report import markdown, tier_summary

        rendered = markdown({
            "run_id": "x", "backend_url": "u", "profile": "burst",
            "tiers": [tier_summary(100, [], 1.0, "burst")], "failed": False,
        })
        self.assertIn("arrow artifacts", rendered)


if __name__ == "__main__":
    unittest.main()
