"""dev/132 commit 1: what a candidate row actually gives you.

The owner's instruction splits the external lane in two — *"automatically
delegate the code to fetch external api datasets, if it must be downloaded
manually, it should include the steps to download in the portal and an import
button"*. That split must be a VERDICT the runtime recorded (`DEC-053`), so
it is read from what dev/67-4's probe already observed: content type, HTTP
status, and the page title of a non-data answer.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import verify


class TestClassifyAccess:
    def test_a_data_body_is_fetchable(self):
        for content_type in (
            "application/json", "application/geo+json", "text/csv",
            "application/octet-stream",
        ):
            verdict = verify.classify_access(
                {"status": "verified", "httpStatus": 200, "contentType": content_type}
            )
            assert verdict["access"] == verify.ACCESS_FETCHABLE, content_type
            assert content_type in verdict["why"]

    def test_a_json_shape_sample_is_enough_even_with_an_odd_content_type(self):
        verdict = verify.classify_access(
            {"status": "verified", "httpStatus": 200, "contentType": "text/plain",
             "sampleKeys": ["features", "type"]}
        )
        assert verdict["access"] == verify.ACCESS_FETCHABLE

    def test_a_page_at_the_data_url_is_a_manual_download(self):
        verdict = verify.classify_access({
            "status": "verified", "httpStatus": 200, "contentType": "text/html; charset=utf-8",
            "pageTitle": "GeoSampa — Downloads",
        })
        assert verdict["access"] == verify.ACCESS_MANUAL
        assert "GeoSampa" in verdict["why"]

    def test_a_gated_status_is_a_manual_download(self):
        for status in (401, 403, 451):
            verdict = verify.classify_access({
                "status": "unreachable", "httpStatus": status,
                "contentType": "text/html", "pageTitle": "Sign in",
            })
            assert verdict["access"] == verify.ACCESS_MANUAL
            assert str(status) in verdict["why"]

    def test_everything_else_is_unknown_and_says_why(self):
        assert verify.classify_access(None)["access"] == verify.ACCESS_UNKNOWN
        assert verify.classify_access(
            {"status": "unverified", "detail": "no probeable URL — the identifier was never checked"}
        )["why"].startswith("no probeable URL")
        assert verify.classify_access(
            {"status": "refused", "detail": "scheme not allowed"}
        )["access"] == verify.ACCESS_UNKNOWN
        # A 404 is not a portal: nothing observed says a human could download it.
        assert verify.classify_access(
            {"status": "unreachable", "httpStatus": 404, "detail": "the endpoint answered 404"}
        )["access"] == verify.ACCESS_UNKNOWN
        # 2xx with an unrecognized type is not silently upgraded.
        assert verify.classify_access(
            {"status": "verified", "httpStatus": 200, "contentType": "application/pdf"}
        )["access"] == verify.ACCESS_UNKNOWN


class TestAnArchiveIsAManualDownload:
    """The Data Lake refuses archives before reading a body
    (``datalakes/domain/formats.py``), so a probe must not call one data a
    loader can read. A person unpacks it and imports the file."""

    def test_an_archive_content_type_is_a_manual_download(self):
        for content_type in (
            "application/zip", "application/x-zip-compressed", "application/gzip",
            "application/zip; charset=binary",
        ):
            verdict = verify.classify_access(
                {"status": "verified", "httpStatus": 200, "contentType": content_type}
            )
            assert verdict["access"] == verify.ACCESS_MANUAL, content_type
            assert "archive" in verdict["why"]

    def test_an_archive_suffix_wins_over_a_generic_content_type(self):
        observation = {"status": "verified", "httpStatus": 200,
                       "contentType": "application/octet-stream"}
        assert verify.classify_access(
            observation, "https://data.example.org/tracts.zip"
        )["access"] == verify.ACCESS_MANUAL
        # Where the redirect landed is what was served.
        assert verify.classify_access(
            {**observation, "finalUrl": "https://cdn.example.org/tracts.tar.gz"},
            "https://data.example.org/tracts",
        )["access"] == verify.ACCESS_MANUAL
        assert verify.classify_access(
            observation, "https://data.example.org/tracts.csv"
        )["access"] == verify.ACCESS_FETCHABLE

    def test_the_steps_say_to_download_and_unpack_it(self):
        steps = verify.download_steps(
            {"url": "https://data.example.org/tracts.zip", "format": "Shapefile (zip)"},
            {"status": "verified", "contentType": "application/zip"},
        )
        assert steps[0] == "Download the archive: https://data.example.org/tracts.zip"
        assert "Unpack it" in steps[1]
        assert steps[-1].startswith("Then use Import dataset below")
        assert not any("portal page" in step for step in steps)


class TestDownloadSteps:
    ROW = {
        "name": "Setores censitários",
        "url": "https://portal.example.gov.br/downloads/setores",
        "format": "Shapefile (zip)",
        "requirement": "accept the portal's terms of use",
    }
    OBS = {"status": "verified", "contentType": "text/html", "pageTitle": "Downloads — Setores"}

    def test_the_steps_are_the_portal_url_the_observed_page_and_the_import(self):
        steps = verify.download_steps(self.ROW, self.OBS)
        assert steps[0].endswith(self.ROW["url"])
        assert "Downloads — Setores" in steps[1]
        assert "the portal describes the click path" in steps[1]
        assert "Shapefile (zip)" in steps[2]
        assert "accept the portal's terms of use" in steps[3]
        assert steps[-1].startswith("Then use Import dataset below")

    def test_a_redirect_names_where_the_portal_actually_landed(self):
        steps = verify.download_steps(
            self.ROW, {**self.OBS, "finalUrl": "https://portal.example.gov.br/en/downloads"}
        )
        assert steps[0].endswith("https://portal.example.gov.br/en/downloads")

    def test_nothing_is_invented_when_the_portal_gave_nothing(self):
        steps = verify.download_steps({"url": "https://x.example/data"}, {"status": "unreachable"})
        assert len(steps) == 3
        assert "use the page's own download control" in steps[1].lower()
        assert all(len(step) <= 200 for step in steps)

    def test_the_steps_are_bounded(self):
        steps = verify.download_steps(
            {"url": "https://x.example/" + "a" * 400, "format": "f" * 400,
             "requirement": "r" * 400},
            {"pageTitle": "t" * 400},
        )
        assert len(steps) <= 6 and all(len(step) <= 200 for step in steps)
