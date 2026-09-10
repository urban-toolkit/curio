"""dev/126: a data-loading node's source state machine and its selection record.

Pure tests over the spec — the state machine is a function of the node's
Dataset Finder attachment plus the caller's grounding evidence, and a selection
resolves against the runtime's OWN persisted candidate rows (a client sends
keys, never a source).
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import attachments, dataset_resolution as dr

DF = "agent.dataset-finder@1.0.0"
NB = "agent.node-builder@1.0.0"


def _spec_with_finder(**record):
    spec = {"dataflow": {"nodes": [{"id": "n1", "type": "curio.builtin/data-loading"}],
                         "edges": [], "agents": [DF, NB], "agentAttachments": []}}
    attachments.attach(spec, DF, {"kind": "node", "targetId": "n1"},
                       attachment_id="att-df", session_id="s-df")
    attachments.attach(spec, NB, {"kind": "node", "targetId": "n1"},
                       attachment_id="att-nb", session_id="s-nb")
    if record:
        attachments.get_attachment(spec, "att-df")[dr.RECORD_KEY] = record
    return spec


def _part(catalog=(), external=()):
    return {"type": "datasetCandidates",
            "lanes": {"catalog": list(catalog), "external": list(external)}}


class TestNodeSourceState:
    def test_no_attachment_is_unresolved(self):
        spec = {"dataflow": {"nodes": [{"id": "n1"}], "agentAttachments": []}}
        state = dr.node_source_state(spec, "n1")
        assert state["state"] == dr.STATE_UNRESOLVED
        assert state["attachmentId"] is None

    def test_the_finder_attachment_is_found_by_node(self):
        spec = _spec_with_finder()
        assert dr.finder_attachment(spec, "n1")["attachmentId"] == "att-df"
        assert dr.finder_attachment(spec, "other") is None
        state = dr.node_source_state(spec, "n1")
        assert (state["state"], state["attachmentId"]) == (dr.STATE_UNRESOLVED, "att-df")

    def test_grounded_literal_resolves_and_says_why(self):
        spec = _spec_with_finder()
        state = dr.node_source_state(spec, "n1", grounded_literal='curio_dataset_path("d1")')
        assert state["state"] == dr.STATE_RESOLVED
        assert state["detail"] == 'curio_dataset_path("d1") already grounds this node'

    def test_candidates_pending_reports_the_count(self):
        spec = _spec_with_finder(status=dr.STATE_CANDIDATES_PENDING, candidates=3)
        state = dr.node_source_state(spec, "n1")
        assert state["state"] == dr.STATE_CANDIDATES_PENDING
        assert "3 candidate(s)" in state["detail"]

    def test_awaiting_install_names_the_pick(self):
        spec = _spec_with_finder(
            status=dr.STATE_AWAITING_INSTALL,
            picks=[{"lane": "catalog", "datasetId": "d1", "name": "Areas"}],
        )
        state = dr.node_source_state(spec, "n1")
        assert state["state"] == dr.STATE_AWAITING_INSTALL
        assert "Areas" in state["detail"] and "reviewed install" in state["detail"]

    def test_a_recorded_resolution_wins_over_everything(self):
        spec = _spec_with_finder(
            status=dr.STATE_RESOLVED,
            picks=[{"lane": "external", "name": "Portal", "url": "https://x/y.json"}],
        )
        state = dr.node_source_state(spec, "n1", grounded_literal="/tmp/other.csv")
        assert state["state"] == dr.STATE_RESOLVED
        assert state["detail"] == "Portal"

    def test_a_grounded_source_wins_over_a_pending_card(self):
        # The user solved it another way (typed a path, installed the dataset):
        # re-discovering would only cost a model call and a review gate.
        spec = _spec_with_finder(status=dr.STATE_CANDIDATES_PENDING, candidates=2)
        state = dr.node_source_state(spec, "n1", grounded_literal="/data/areas.csv")
        assert state["state"] == dr.STATE_RESOLVED

    def test_marks_are_recorded_with_a_revision_bump(self):
        spec = _spec_with_finder()
        before = attachments.get_attachment(spec, "att-df")["revision"]
        dr.mark_candidates_pending(spec, "att-df", count=4)
        assert attachments.get_attachment(spec, "att-df")["revision"] == before + 1
        assert dr.source_record(spec, "n1")["candidates"] == 4
        dr.mark_skipped(spec, "att-df", literal="/data/areas.csv")
        assert dr.source_record(spec, "n1")["status"] == dr.STATE_RESOLVED
        assert dr.source_record(spec, "n1")["skippedBecause"] == "/data/areas.csv"
        assert dr.mark_candidates_pending(spec, "ghost", count=1) is None


class TestResolvePicks:
    def test_keys_resolve_to_the_runtime_rows(self):
        part = _part(
            catalog=[{"datasetId": "d1", "name": "Areas", "installed": True,
                      "sourceType": "catalog"}],
            external=[{"url": "https://x/y.json", "name": "Portal", "sourceType": "api",
                       "verification": {"status": "verified"}}],
        )
        rows = dr.resolve_picks(part, [
            {"lane": "catalog", "key": "d1"}, {"lane": "external", "key": "https://x/y.json"},
        ])
        assert [r["name"] for r in rows] == ["Areas", "Portal"]
        assert rows[0]["lane"] == "catalog" and rows[1]["verification"]["status"] == "verified"

    def test_an_unknown_key_is_refused_by_name(self):
        part = _part(catalog=[{"datasetId": "d1", "name": "Areas"}])
        with pytest.raises(dr.DatasetResolutionError, match="not a catalog candidate"):
            dr.resolve_picks(part, [{"lane": "catalog", "key": "d2"}])

    def test_a_client_supplied_url_cannot_smuggle_a_source(self):
        part = _part(external=[{"url": "https://x/y.json", "name": "Portal"}])
        with pytest.raises(dr.DatasetResolutionError):
            dr.resolve_picks(part, [{"lane": "external", "key": "https://evil/z.json"}])

    def test_shape_refusals(self):
        part = _part(catalog=[{"datasetId": "d1", "name": "Areas"}])
        with pytest.raises(dr.DatasetResolutionError, match="no dataset candidates"):
            dr.resolve_picks(None, [{"lane": "catalog", "key": "d1"}])
        with pytest.raises(dr.DatasetResolutionError, match="non-empty list"):
            dr.resolve_picks(part, [])
        with pytest.raises(dr.DatasetResolutionError, match="needs a lane"):
            dr.resolve_picks(part, [{"lane": "nope", "key": "d1"}])
        with pytest.raises(dr.DatasetResolutionError, match="at most"):
            dr.resolve_picks(part, [{"lane": "catalog", "key": "d1"}] * (dr.MAX_PICKS + 1))

    def test_duplicate_picks_collapse(self):
        part = _part(catalog=[{"datasetId": "d1", "name": "Areas"}])
        rows = dr.resolve_picks(part, [
            {"lane": "catalog", "key": "d1"}, {"lane": "catalog", "key": "d1"},
        ])
        assert len(rows) == 1


class TestRecordSelection:
    def test_an_installed_catalog_pick_resolves_the_node(self):
        spec = _spec_with_finder()
        state = dr.record_selection(spec, "att-df", [
            {"lane": "catalog", "datasetId": "d1", "name": "Areas", "installed": True},
        ])
        assert state["status"] == dr.STATE_RESOLVED
        source = dr.confirmed_source(spec, "n1")
        assert source["picks"][0]["datasetId"] == "d1"
        assert "curio_dataset_path" in source["note"]

    def test_an_uninstalled_catalog_pick_awaits_the_reviewed_install(self):
        spec = _spec_with_finder()
        state = dr.record_selection(spec, "att-df", [
            {"lane": "catalog", "datasetId": "d1", "name": "Areas", "installed": False},
        ])
        assert state["status"] == dr.STATE_AWAITING_INSTALL
        assert dr.confirmed_source(spec, "n1") is None
        # The applied install resolves exactly the nodes awaiting that dataset.
        assert dr.mark_dataset_installed(spec, "other") == []
        assert dr.mark_dataset_installed(spec, "d1") == ["att-df"]
        assert dr.source_record(spec, "n1")["status"] == dr.STATE_RESOLVED
        assert dr.confirmed_source(spec, "n1")["picks"][0]["installed"] is True

    def test_an_unreachable_external_pick_does_not_resolve(self):
        spec = _spec_with_finder()
        state = dr.record_selection(spec, "att-df", [
            {"lane": "external", "url": "https://x/y.json", "name": "Portal",
             "verification": {"status": "unreachable"}},
        ])
        assert state["status"] == dr.STATE_CANDIDATES_PENDING
        assert dr.confirmed_source(spec, "n1") is None

    def test_a_verified_external_pick_resolves(self):
        spec = _spec_with_finder()
        state = dr.record_selection(spec, "att-df", [
            {"lane": "external", "url": "https://x/y.json", "name": "Portal",
             "verification": {"status": "verified"}},
        ])
        assert state["status"] == dr.STATE_RESOLVED
        assert dr.confirmed_source(spec, "n1")["picks"][0]["url"] == "https://x/y.json"

    def test_a_missing_attachment_is_reported_not_raised(self):
        spec = _spec_with_finder()
        assert dr.record_selection(spec, "ghost", [{"lane": "catalog", "datasetId": "d"}]) is None


class TestDelegationHome:
    """dev/126: discovery work homes at the node's OWN Dataset Finder; every
    other capability keeps dev/72's Node Builder default."""

    def _spec(self, node_type="curio.builtin/data-loading", agents=(DF, NB)):
        return {"dataflow": {"nodes": [{"id": "n1", "type": node_type}], "edges": [],
                             "agents": list(agents), "agentAttachments": []}}

    def test_discovery_homes_at_the_finder(self):
        from utk_curio.backend.app.agents import services

        spec = self._spec()
        home, created = services._delegation_home(
            spec, DF, "dataset.discover", {}, node_id="n1", user_key="1",
        )
        assert created is True
        assert home["coord"] == DF
        assert home["target"] == {"kind": "node", "targetId": "n1"}
        # Idempotent: the second task reuses the same home.
        again, created_again = services._delegation_home(
            spec, DF, "dataset.discover", {}, node_id="n1", user_key="1",
        )
        assert created_again is False
        assert again["attachmentId"] == home["attachmentId"]

    def test_content_generation_keeps_the_node_builder_home(self):
        from utk_curio.backend.app.agents import services

        spec = self._spec()
        home, _ = services._delegation_home(
            spec, "agent.node-content-builder@1.0.0", "node.content.generate", {},
            node_id="n1", user_key="1",
        )
        assert home["coord"] == NB

    def test_discovery_on_an_incompatible_node_falls_back_to_dev_72(self):
        from utk_curio.backend.app.agents import services

        spec = self._spec(node_type="curio.builtin/vis-vega")
        home, _ = services._delegation_home(
            spec, DF, "dataset.discover", {}, node_id="n1", user_key="1",
        )
        assert home["coord"] == NB  # the Dataset Finder cannot live there
