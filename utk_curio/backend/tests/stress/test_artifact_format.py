"""Fetching outputs as Arrow instead of JSON, and digesting what comes back.

The harness compares every user's output against a single-user baseline, so
whatever it fetches has to be digestible and stable. JSON has a canonical
form; an Arrow response is bytes plus metadata headers, and both halves have
to be in the digest or a change in the headers would pass unnoticed.
"""

import unittest

from utk_curio.backend.tests.stress.driver import (
    ARROW_IPC_MIME,
    VirtualUser,
    arrow_artifact_hash,
    artifact_hash,
)


class ArrowDigestTest(unittest.TestCase):
    HEADERS = {
        "Content-Type": ARROW_IPC_MIME,
        "X-Curio-Kind": "dataframe",
        "X-Curio-Filename": "1790201370084_b973a38f",
        "X-Curio-Encoded-Object-Columns": "tags",
    }

    def test_the_same_response_digests_the_same(self):
        a = arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS))
        b = arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS))
        self.assertEqual(a, b)

    def test_different_bytes_digest_differently(self):
        self.assertNotEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"other-bytes", dict(self.HEADERS)),
        )

    def test_the_metadata_headers_are_part_of_the_digest(self):
        """A kind or an encoded-column list changing is a real difference."""
        changed = dict(self.HEADERS, **{"X-Curio-Kind": "geodataframe"})
        self.assertNotEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", changed),
        )

    def test_the_artifact_id_is_not(self):
        """It is minted per execution, so hashing it reports every user as a
        mismatch. Same reason VOLATILE_ARTIFACT_FIELDS drops ``filename``."""
        renamed = dict(self.HEADERS, **{"X-Curio-Filename": "another_id"})
        self.assertEqual(
            arrow_artifact_hash(b"arrow-bytes", dict(self.HEADERS)),
            arrow_artifact_hash(b"arrow-bytes", renamed),
        )

    def test_header_case_does_not_matter(self):
        """requests gives a case-insensitive mapping; dict(...) may not."""
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

    def test_an_arrow_digest_is_not_a_json_digest(self):
        """They are never compared, and this is the reminder of why not."""
        self.assertNotEqual(
            arrow_artifact_hash(b"{}", {}),
            artifact_hash({}),
        )


class ArtifactFormatPlumbingTest(unittest.TestCase):
    """The format has to reach the user object, or the flag does nothing."""

    def _user(self, **kwargs):
        return VirtualUser(
            "http://backend", "stress_x_t1_u0", "example.json", {}, None, {},
            **kwargs,
        )

    def test_arrow_is_the_default(self):
        """The job measures what the canvas asks for.

        `fetchData` requests Arrow on every artifact fetch, so a harness
        defaulting to JSON would be measuring a path users no longer take.
        """
        self.assertEqual(self._user().artifact_format, "arrow")

    def test_json_is_still_reachable(self):
        """It is the fallback for kinds Arrow cannot serve, so it is still
        worth being able to measure on its own."""
        self.assertEqual(
            self._user(artifact_format="json").artifact_format, "json"
        )


class TheAcceptHeaderActuallyGoesOutTest(unittest.TestCase):
    """The whole mode is one request header, so pin that it is sent.

    Everything else could be right and the job would still measure the JSON
    path, silently, and report it as an Arrow number.
    """

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, arrow):
            self.arrow = arrow
            self.content = b"ARROW1" if arrow else b"{}"
            self.headers = (
                {"Content-Type": ARROW_IPC_MIME, "X-Curio-Kind": "dataframe"}
                if arrow else {"Content-Type": "application/json"}
            )

        def json(self):
            if self.arrow:
                raise AssertionError(
                    "the arrow path must not parse the body as JSON"
                )
            return {}

    class RecordingSession:
        def __init__(self, arrow):
            self.sent = []
            self.arrow = arrow

        def request(self, method, url, **kwargs):
            self.sent.append((method, url, kwargs.get("headers") or {}))
            return TheAcceptHeaderActuallyGoesOutTest.FakeResponse(self.arrow)

    def _user(self, artifact_format):
        user = VirtualUser(
            "http://backend", "stress_x_t1_u0", "example.json", {}, None, {},
            artifact_format=artifact_format,
        )
        user.session = self.RecordingSession(artifact_format == "arrow")
        return user

    def test_arrow_mode_sends_the_arrow_accept_header(self):
        user = self._user("arrow")
        response = user._call("GET", "/get", params={"fileName": "a1"},
                              accept=ARROW_IPC_MIME, raw=True)
        _, _, headers = user.session.sent[0]
        self.assertEqual(headers.get("Accept"), ARROW_IPC_MIME)
        # And the body comes back as bytes, not parsed.
        self.assertEqual(response["content"], b"ARROW1")

    def _fetch_one_artifact(self, artifact_format):
        """Drive the real artifact fetch, the way a tier does."""
        import types

        user = self._user(artifact_format)
        user.result.outputs["n1"] = {"path": "a1", "dataType": "dataframe"}
        user._compare_to_baseline(types.SimpleNamespace(id="n1"))
        return user.session.sent[0][2]

    def test_the_artifact_fetch_accepts_wkb_geometry(self):
        """Without this every spatial example in the mix comes back 415.

        The gate is deliberate -- a client that cannot decode WKB should not
        be handed it -- and the harness can take it, because it digests the
        response bytes rather than rendering them. This drives
        ``_compare_to_baseline`` rather than ``_call`` directly, because the
        header being reachable is not the same as it being sent.
        """
        headers = self._fetch_one_artifact("arrow")

        self.assertEqual(headers.get("Accept"), ARROW_IPC_MIME)
        self.assertEqual(headers.get("X-Curio-Accept-Geometry"), "wkb")

    def test_the_json_fetch_sends_neither(self):
        headers = self._fetch_one_artifact("json")

        self.assertNotEqual(headers.get("Accept"), ARROW_IPC_MIME)
        self.assertIsNone(headers.get("X-Curio-Accept-Geometry"))

    def test_json_mode_sends_no_arrow_accept(self):
        user = self._user("json")
        user._call("GET", "/get", params={"fileName": "a1"})
        _, _, headers = user.session.sent[0]
        self.assertNotEqual(headers.get("Accept"), ARROW_IPC_MIME)


class ReportRecordsTheFormatTest(unittest.TestCase):
    def test_the_tier_says_which_format_produced_it(self):
        from utk_curio.backend.tests.stress.report import markdown, tier_summary

        tier = tier_summary(100, [], 1.0, "burst", artifact_format="arrow")
        self.assertEqual(tier["artifact_format"], "arrow")
        rendered = markdown({
            "run_id": "x", "backend_url": "u", "profile": "burst",
            "tiers": [tier], "failed": False,
        })
        self.assertIn("(arrow artifacts)", rendered)

    def test_a_tier_always_names_its_format(self):
        """Never inferred from whatever the default was on the day: two tiers
        measured in different formats are not comparable, and the report is
        read long after the flag was set."""
        from utk_curio.backend.tests.stress.report import markdown, tier_summary

        rendered = markdown({
            "run_id": "x", "backend_url": "u", "profile": "burst",
            "tiers": [tier_summary(100, [], 1.0, "burst")], "failed": False,
        })
        self.assertIn("### 100 users (arrow artifacts)", rendered)


if __name__ == "__main__":
    unittest.main()
