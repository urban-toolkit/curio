"""The contract tests cannot fail for a reason outside our control.

That claim is what lets them run in ordinary CI, so it is worth testing rather
than asserting in a docstring. These drive the helpers in
``test_provider_contracts`` through every failure mode a portal can present and
check each one SKIPS.

Deliberately not marked ``contract``: these open no socket, because the
failures are injected.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import egress
from utk_curio.backend.tests.test_datalakes import test_provider_contracts as contracts


def _fixed(**over):
    """An ``egress.fetch`` that returns one canned result."""
    base = dict(
        url="https://p.example", final_url="https://p.example", status=200,
        content_type="application/json", body='{"ok": true}',
    )
    base.update(over)
    return lambda url, **kwargs: egress.EgressResult(**base)


class TestEverythingOutsideOurControlSkips:
    @pytest.mark.parametrize(
        "boom",
        [
            OSError("connection refused"),
            TimeoutError("timed out"),
            egress.EgressRefused("resolves to a private address"),
            ValueError("unparseable URL"),
        ],
    )
    def test_a_transport_failure_skips(self, monkeypatch, boom):
        def _raise(url, **kwargs):
            raise boom

        monkeypatch.setattr(contracts.egress, "fetch", _raise)
        with pytest.raises(pytest.skip.Exception, match="unreachable"):
            contracts.probe("https://p.example")

    @pytest.mark.parametrize("status", [301, 403, 404, 429, 500, 503])
    def test_a_non_2xx_skips(self, monkeypatch, status):
        monkeypatch.setattr(contracts.egress, "fetch", _fixed(status=status))
        with pytest.raises(pytest.skip.Exception, match=str(status)):
            contracts.probe("https://p.example")

    def test_a_waf_challenge_or_maintenance_page_skips(self, monkeypatch):
        """A 200 that is HTML rather than JSON. Every captive portal, WAF and
        'we are down for maintenance' page looks exactly like this, and none of
        them is a contract change."""
        monkeypatch.setattr(
            contracts.egress, "fetch",
            _fixed(body="<html>Request Rejected</html>", content_type="text/html"),
        )
        with pytest.raises(pytest.skip.Exception, match="did not answer JSON"):
            contracts.probe_json("https://p.example")

    def test_a_2xx_with_json_does_NOT_skip(self, monkeypatch):
        """The one path that reaches an assertion. If this skipped too, the
        tests would be decorative."""
        monkeypatch.setattr(contracts.egress, "fetch", _fixed())
        assert contracts.probe_json("https://p.example") == {"ok": True}


class TestTheShapeAssertionsStillBite:
    """A skip-happy helper would make the whole file decorative, so prove the
    surviving path actually fails on a changed shape."""

    def test_socrata_fails_when_resource_id_disappears(self, monkeypatch):
        monkeypatch.setattr(
            contracts.egress, "fetch",
            _fixed(body='{"results": [{"resource": {"name": "x"}}]}'),
        )
        with pytest.raises(AssertionError, match="resource.id"):
            contracts.test_socrata_search_still_carries_resource_id_and_name()

    def test_socrata_skips_rather_than_fails_on_an_empty_result_set(self, monkeypatch):
        """A query matching nothing today is not a contract change."""
        monkeypatch.setattr(contracts.egress, "fetch", _fixed(body='{"results": []}'))
        with pytest.raises(pytest.skip.Exception, match="no results"):
            contracts.test_socrata_search_still_carries_resource_id_and_name()

    def test_ckan_fails_when_resources_stops_being_a_list(self, monkeypatch):
        monkeypatch.setattr(
            contracts.egress, "fetch",
            _fixed(body='{"success": true, "result": {"results": [{"id": "a", "resources": {}}]}}'),
        )
        with pytest.raises(AssertionError, match="resources"):
            contracts.test_ckan_package_search_still_nests_results_under_result()

    def test_arcgis_fails_when_attributes_disappears(self, monkeypatch):
        monkeypatch.setattr(
            contracts.egress, "fetch", _fixed(body='{"data": [{"id": "x"}]}')
        )
        with pytest.raises(AssertionError, match="attributes"):
            contracts.test_arcgis_hub_still_answers_json_api()

    def test_wfs_skips_when_the_document_is_truncated(self, monkeypatch):
        """A capabilities document outgrowing our metadata bound is a capacity
        question, not a portal changing its contract."""
        monkeypatch.setattr(
            contracts.egress, "fetch",
            _fixed(body="<wfs:WFS_Capabilities>", content_type="application/xml"),
        )
        # `truncated` is a field on the result, so build one that says so.
        original = contracts.egress.fetch

        def _truncated(url, **kwargs):
            result = original(url, **kwargs)
            result.truncated = True
            return result

        monkeypatch.setattr(contracts.egress, "fetch", _truncated)
        with pytest.raises(pytest.skip.Exception, match="exceeded"):
            contracts.test_geosampa_wfs_still_publishes_feature_types()
