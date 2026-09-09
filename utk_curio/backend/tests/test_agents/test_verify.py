"""dev/67-4 (DEC-053) — the provider-agnostic verification gate: the generic
probe covers ANY dataset API; Socrata is a refinement, not the gate."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import verify


def _resolver(host_map=None):
    mapping = host_map or {"data.example.gov": ["93.184.216.34"]}

    def _resolve(host):
        if host in mapping:
            return mapping[host]
        raise OSError(f"unknown host {host}")

    return _resolve


def _request(responses):
    """responses: url substring → (status, body dict|str)."""

    def _fn(method, url):
        for marker, (status, body) in responses.items():
            if marker in url:
                text = body if isinstance(body, str) else json.dumps(body)
                return status, {"Content-Type": "application/json"}, text.encode(), None
        return 404, {"Content-Type": "application/json"}, b"{}", None

    return _fn


class TestGenericGate:
    def test_any_dataset_api_verifies_through_the_generic_probe(self):
        # An arbitrary (non-Socrata) API — the owner's generalization: the
        # gate covers ANY dataset API connection, not one vendor.
        outcome = verify.verify_external_source(
            "https://data.example.gov/api/records/v1?limit=1",
            request_fn=_request({"records": (200, {"total": 12, "records": []})}),
            resolver=_resolver(),
        )
        assert outcome["status"] == "verified"
        assert outcome["httpStatus"] == 200
        assert outcome["sampleKeys"] == ["records", "total"]
        assert outcome["checkedAt"]

    def test_error_statuses_are_unreachable_with_evidence(self):
        outcome = verify.verify_external_source(
            "https://data.example.gov/api/gone",
            request_fn=_request({}), resolver=_resolver(),
        )
        assert outcome["status"] == "unreachable"
        assert outcome["httpStatus"] == 404

    def test_transport_failure_is_unreachable_and_ssrf_is_refused(self):
        def _boom(method, url):
            raise ConnectionError("timed out")

        outcome = verify.verify_external_source(
            "https://data.example.gov/x", request_fn=_boom, resolver=_resolver(),
        )
        assert outcome["status"] == "unreachable"
        outcome = verify.verify_external_source(
            "https://metadata.internal/x",
            resolver=_resolver({"metadata.internal": ["169.254.169.254"]}),
        )
        assert outcome["status"] == "refused"

    def test_a_redirect_to_an_html_page_is_named_not_hidden(self):
        # The Census API's key-less answer (dev/115 live re-test, 2026-09-08):
        # 302 → /data/missing_key.html, 200 text/html. "verified" by status,
        # but the outcome now says where it landed and what the page is.
        def _fn(method, url):
            if url.endswith("/missing_key.html"):
                body = b"<html><head><title>Missing <b>Key</b></title></head><body>x</body></html>"
                return 200, {"Content-Type": "text/html;charset=utf-8"}, body, None
            return 302, {}, b"", "https://data.example.gov/data/missing_key.html"

        outcome = verify.verify_external_source(
            "https://data.example.gov/data/2022/acs/acs5?get=NAME&for=tract:*",
            request_fn=_fn, resolver=_resolver(),
        )
        assert outcome["status"] == "verified" and outcome["httpStatus"] == 200
        assert outcome["finalUrl"] == "https://data.example.gov/data/missing_key.html"
        assert outcome["pageTitle"] == "Missing Key"
        assert "_body" not in outcome

    def test_a_plain_text_error_answer_is_sampled(self):
        def _fn(method, url):
            return 400, {"Content-Type": "text/plain"}, b"error: unknown/unsupported geography heirarchy\n", None

        outcome = verify.verify_external_source(
            "https://data.example.gov/x", request_fn=_fn, resolver=_resolver(),
        )
        assert outcome["status"] == "unreachable" and outcome["httpStatus"] == 400
        assert outcome["bodySample"] == "error: unknown/unsupported geography heirarchy"
        assert "finalUrl" not in outcome  # no redirect happened
        # JSON answers keep the shape sample and never grow a body sample.
        ok = verify.verify_external_source(
            "https://data.example.gov/records",
            request_fn=_request({"records": (200, {"total": 1})}), resolver=_resolver(),
        )
        assert "bodySample" not in ok and "pageTitle" not in ok

    def test_no_url_is_loudly_unverified(self):
        outcome = verify.verify_external_source(None)
        assert outcome["status"] == "unverified"
        assert "never checked" in outcome["detail"]


class TestSocrataRefinement:
    def test_socrata_urls_dispatch_to_the_refinement(self):
        # The exact hallucination shape from session 89ae8123: a Socrata
        # resource URL whose 4x4 id must actually exist.
        responses = _request({
            "/api/views/abcd-1234.json": (200, {
                "name": "Chicago Heat Deaths 2024",
                "columns": [{"fieldName": "week"}, {"fieldName": "deaths"}],
            }),
        })
        outcome = verify.verify_external_source(
            "https://data.cityofchicago.org/resource/abcd-1234.json",
            request_fn=responses,
            resolver=_resolver({"data.cityofchicago.org": ["93.184.216.34"]}),
        )
        assert outcome["status"] == "verified"
        assert outcome["provider"] == "socrata"
        assert outcome["datasetId"] == "abcd-1234"
        assert outcome["datasetName"] == "Chicago Heat Deaths 2024"
        assert outcome["columns"] == ["week", "deaths"]

    def test_a_hallucinated_socrata_id_is_unreachable_by_name(self):
        outcome = verify.verify_external_source(
            "https://data.cityofchicago.org/resource/fake-0000.json",
            request_fn=_request({}),
            resolver=_resolver({"data.cityofchicago.org": ["93.184.216.34"]}),
        )
        assert outcome["status"] == "unreachable"
        assert outcome["provider"] == "socrata"
        assert outcome["datasetId"] == "fake-0000"
