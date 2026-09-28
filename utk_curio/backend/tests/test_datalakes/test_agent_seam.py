"""The Data Lake Catalog as an agent surface.

The Dataset Finder's external lane used to dead-end: it could *name* a portal
dataset and nothing could act on it, so the only move was a handoff to Node
Builder to write fetch code. These cover what makes it actionable, and the
guard rails on that.

The structural one matters most: a download writes bytes into the user's store
and mints a catalog row, so it is a **mutate** contract. It goes through the
proposal/apply path and cannot be executed by the model loop at all.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import content, tools, verify
from utk_curio.backend.app.agents.services import (
    _egress_cost,
    _LazyRoster,
    _mint_row_acquirable,
    _verify_candidate_parts,
)


class TestTheContracts:
    def test_the_roster_and_search_are_reads(self):
        assert tools.REGISTRY["datalake.sources"].effect == "read"
        assert tools.REGISTRY["datalake.search"].effect == "read"

    def test_a_download_is_a_mutate(self):
        assert tools.REGISTRY["datalake.acquire"].effect == "mutate"

    def test_a_download_cannot_be_executed_by_the_model_loop(self, monkeypatch):
        """The gate is structural, not a flag: the read executor has no branch
        for it, so a granted mutate contract falls through to "unknown read
        tool" and can only ever mint a proposal."""
        from utk_curio.backend.app.projects import storage as projects_storage

        # A spec exists, so the fall-through is reached rather than the earlier
        # "no saved project spec" guard - which would pass this test for the
        # wrong reason.
        monkeypatch.setattr(projects_storage, "read_spec", lambda *a, **k: {"nodes": []})
        status, text = tools.execute_read_tool(
            "datalake.acquire", user_key="1", project_id="p", target=None, params={}
        )
        assert status == "error"
        assert "unknown read tool" in text

    def test_the_read_tools_reach_their_own_branch(self, monkeypatch, app, shipped_root):
        """The twin of the above: proving the fall-through is reached for the
        mutate contract means little unless the reads are NOT falling through
        to it."""
        status, _text = tools.execute_read_tool(
            "datalake.sources", user_key="1", project_id="p", target=None, params={}
        )
        assert status == "ok"

    def test_the_search_description_warns_about_the_fan_out_cost(self):
        """A model that does not know a fan-out costs one call per portal will
        spend the whole run budget on its first search."""
        description = tools.REGISTRY["datalake.search"].description
        assert "PER PORTAL" in description
        assert "sourceId" in description

    def test_the_acquire_description_says_review_comes_first(self):
        description = tools.REGISTRY["datalake.acquire"].description
        assert "review" in description.lower()
        assert "without their approval" in description


class TestTheEgressBudget:
    def test_the_roster_is_free(self):
        """It reads manifests off disk. Charging it would burn a run's
        allowance on a call that contacts nobody."""
        from utk_curio.backend.app.agents.services import _EGRESS_TOOLS

        assert "datalake.sources" not in _EGRESS_TOOLS

    def test_a_targeted_search_costs_one(self):
        assert _egress_cost("datalake.search", {"sourceId": "lake.a.b@1"}) == 1

    def test_a_fan_out_costs_one_per_portal(self, app, shipped_root):
        """A flat tick would let one tool call issue five requests against a
        budget of four - the same undercount CallBudget's docstring records
        being fixed once already."""
        cost = _egress_cost("datalake.search", {})
        assert cost > 1, "the shipped set has several searchable portals"

    def test_an_unreadable_roster_falls_back_to_one(self, monkeypatch):
        """A cost calculation must never fail a run."""
        monkeypatch.setattr(
            tools, "_datalake_service", lambda: (_ for _ in ()).throw(RuntimeError("no"))
        )
        assert _egress_cost("datalake.search", {}) == 1

    def test_other_tools_still_cost_one(self):
        assert _egress_cost("web.fetch", {}) == 1


class TestTheCandidateLane:
    def _part(self, **row):
        base = {"name": "Bike Routes", "sourceType": "portal"}
        base.update(row)
        return {"type": "datasetCandidates", "lanes": {"external": [base]}}

    def test_a_row_with_neither_field_parses_as_before(self):
        row = content._parse_candidate_row(
            {"name": "X", "sourceType": "portal", "url": "https://a.example/x"}, "external"
        )
        assert row is not None
        assert "sourceId" not in row and "resourceId" not in row

    def test_a_row_may_carry_a_grounded_coordinate(self):
        row = content._parse_candidate_row(
            {
                "name": "X",
                "sourceType": "lake",
                "sourceId": "lake.a.b@1",
                "resourceId": "abcd-1234",
            },
            "external",
        )
        assert row["sourceId"] == "lake.a.b@1"
        assert row["resourceId"] == "abcd-1234"

    def test_half_a_coordinate_invalidates_the_row(self):
        """Fail-open to text, the same rule every other field follows."""
        for partial in ({"sourceId": "lake.a.b@1"}, {"resourceId": "abcd-1234"}):
            assert (
                content._parse_candidate_row(
                    {"name": "X", "sourceType": "portal", **partial}, "external"
                )
                is None
            )

    def test_lake_is_an_accepted_source_type(self):
        assert "lake" in content._CANDIDATE_SOURCE_TYPES

    def test_the_byte_budget_grew_with_the_fields(self):
        """Derived rather than picked, so a widened field cannot silently
        re-open the #269 leak - which means it has to actually be re-derived."""
        assert content._CANDIDATE_ROW_MAX_BYTES >= 2 * content._CANDIDATE_NAME_MAX_CHARS


class TestOnlyTheRuntimeSaysActionable:
    """The model may NAME a source; it may not claim Curio can download it.

    This is the catalog lane's mandatory-``datasetId`` discipline applied one
    lane over. One function answers it, from the roster and the probe.
    """

    CHICAGO = {"sourceId": "lake.cityofchicago.data-portal@1", "resourceId": "ijzp-q8t2"}
    DIRECT = "lake.curio.direct-url@1"
    URL = "https://data.example.org/areas.geojson"
    GEOJSON = {"status": "verified", "httpStatus": 200, "contentType": "application/geo+json"}

    def _row(self, **fields):
        row = {"name": "Bike Routes", "sourceType": "lake", **fields}
        if "verification" in row:
            row["access"] = verify.classify_access(row["verification"], row.get("url"))["access"]
        _mint_row_acquirable(row, _LazyRoster())
        return row

    def test_a_model_claim_is_stripped(self, app, shipped_root):
        assert self._row(acquirable=True).get("acquirable") is None

    def test_a_real_connector_source_is_marked(self, app, shipped_root):
        assert self._row(**self.CHICAGO)["acquirable"] is True

    def test_the_run_grant_does_not_decide_it(self, app, shipped_root):
        # A person confirming the row uses the download route, which needs only
        # their sign-in; there is no grant to consult here at all.
        row = {"name": "Bike Routes", "sourceType": "lake", **self.CHICAGO}
        parts = [{"type": "datasetCandidates", "lanes": {"external": [row]}}]
        _verify_candidate_parts(parts)
        assert row["acquirable"] is True

    def test_a_connector_row_whose_landing_page_is_a_portal_is_still_downloadable(
        self, app, shipped_root
    ):
        row = self._row(**self.CHICAGO, url="https://data.cityofchicago.org/d/ijzp-q8t2",
                        verification={"status": "verified", "httpStatus": 200,
                                      "contentType": "text/html"})
        assert row["access"] == verify.ACCESS_MANUAL
        assert row["acquirable"] is True

    def test_an_invented_source_is_not_marked(self, app, shipped_root):
        assert self._row(sourceId="lake.made.up@1", resourceId="x").get("acquirable") is None

    def test_a_row_with_no_coordinate_is_not_marked(self, app, shipped_root):
        assert self._row(url="https://a.example/x").get("acquirable") is None

    def test_a_direct_url_row_needs_the_probe(self, app, shipped_root):
        row = self._row(sourceId=self.DIRECT, resourceId=self.URL, url=self.URL,
                        verification=self.GEOJSON)
        assert row["acquirable"] is True

    def test_a_direct_url_row_is_refused_on_any_missing_condition(self, app, shipped_root):
        http = self.URL.replace("https://", "http://")
        cases = {
            "not https": dict(resourceId=http, url=http, verification=self.GEOJSON),
            "resourceId is not the probed url": dict(
                resourceId="https://elsewhere.example/x.geojson", url=self.URL,
                verification=self.GEOJSON),
            "the probe saw a page": dict(resourceId=self.URL, url=self.URL, verification={
                "status": "verified", "httpStatus": 200, "contentType": "text/html"}),
            "a type the source cannot store": dict(resourceId=self.URL, url=self.URL, verification={
                "status": "verified", "httpStatus": 200,
                "contentType": "application/octet-stream"}),
            "an archive": dict(resourceId=self.URL, url=self.URL, verification={
                "status": "verified", "httpStatus": 200, "contentType": "application/zip"}),
        }
        for why, fields in cases.items():
            assert self._row(sourceId=self.DIRECT, **fields).get("acquirable") is None, why

    def test_a_charset_parameter_does_not_hide_the_type(self, app, shipped_root):
        row = self._row(sourceId=self.DIRECT, resourceId=self.URL, url=self.URL,
                        verification={**self.GEOJSON,
                                      "contentType": "application/geo+json; charset=utf-8"})
        assert row["acquirable"] is True


class TestTheInstructionIsGrantShaped:
    def test_a_run_without_the_lake_tool_gets_the_old_text_byte_identical(self):
        """Changing the prompt for every existing agent would be a behaviour
        change nobody asked for."""
        without = content.tail_instruction([("catalog.search", "x")])
        assert content.CANDIDATES_LAKE_ADDENDUM not in without

    def test_a_run_with_it_is_told_about_the_fields(self):
        with_lake = content.tail_instruction(
            [("catalog.search", "x"), ("datalake.search", "y")]
        )
        assert content.CANDIDATES_LAKE_ADDENDUM in with_lake
        assert "sourceId" in with_lake

    def test_the_lake_tool_alone_still_unlocks_the_schema(self):
        """A run that can search portals can fill the external lane even
        without the Data Catalog tool."""
        only_lake = content.tail_instruction([("datalake.search", "y")])
        assert content.CANDIDATES_INSTRUCTION in only_lake

    def test_the_addendum_forbids_inventing_a_pair(self):
        assert "Never invent" in content.CANDIDATES_LAKE_ADDENDUM


class TestTheRosterExecutor:
    def test_it_reports_sources_without_a_credential_value(self, app, shipped_root):
        status, text = tools.execute_read_tool(
            "datalake.sources", user_key="1", project_id="p", target=None, params={}
        )
        assert status == "ok"
        payload = json.loads(text)
        assert payload["sources"]
        blob = json.dumps(payload).lower()
        assert "token" not in blob or "credentialready" in blob
        for row in payload["sources"]:
            assert set(row) == {
                "sourceId", "name", "provider", "publisher", "description",
                "formats", "searchable", "credentialReady",
            }
