"""dev/126: a data-loading node's source state machine and its selection record.

Pure tests over the spec — the state machine is a function of the node's
Dataset Finder attachment plus the caller's grounding evidence, and a selection
resolves against the runtime's OWN persisted candidate rows (a client sends
keys, never a source).
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import dataset_resolution as dr

DF = "agent.curio.dataset-finder@1"
NB = "agent.curio.node-builder@1"


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
        state = dr.node_source_state(spec, "n1", grounded_literal='curio_data_path("d1")')
        assert state["state"] == dr.STATE_RESOLVED
        assert state["detail"] == 'curio_data_path("d1") already grounds this node'

    @pytest.mark.parametrize("count, words", [(1, "1 candidate"), (3, "3 candidates")])
    def test_candidates_pending_reports_the_count(self, count, words):
        """The count in words, as a person reads it: on 7430c0d5a4 it said
        "3 candidate(s)", which a Needs a source row shows on its tooltip."""
        spec = _spec_with_finder(status=dr.STATE_CANDIDATES_PENDING, candidates=count)
        state = dr.node_source_state(spec, "n1")
        assert state["state"] == dr.STATE_CANDIDATES_PENDING
        assert state["detail"] == f"{words} awaiting your selection"

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
        record = dr.source_record(spec, "n1")
        assert record["status"] == dr.STATE_NOT_NEEDED
        assert record["skippedBecause"] == "/data/areas.csv"
        # A recorded skip never suppresses a later discovery, and re-recording
        # the same literal writes nothing.
        assert dr.node_source_state(spec, "n1")["state"] == dr.STATE_UNRESOLVED
        rev = attachments.get_attachment(spec, "att-df")["revision"]
        assert dr.mark_skipped(spec, "att-df", literal="/data/areas.csv") is None
        assert attachments.get_attachment(spec, "att-df")["revision"] == rev
        assert dr.mark_candidates_pending(spec, "ghost", count=1) is None

    def test_a_skip_never_replaces_a_confirmed_selection(self):
        # Every Solve that resolves a node records why discovery was not
        # needed, and the project's Data Catalog is such a reason. The user's
        # confirmed pick is the node's source: the note must not erase it, or
        # the next round that misses it starts discovery all over again.
        picks = [{"lane": "external", "name": "Portal", "url": "https://x/y.json"}]
        spec = _spec_with_finder(status=dr.STATE_RESOLVED, picks=picks)
        rev = attachments.get_attachment(spec, "att-df")["revision"]
        literal = "the project's Data Catalog (3 dataset(s))"
        assert dr.mark_skipped(spec, "att-df", literal=literal) is None
        record = dr.source_record(spec, "n1")
        assert (record["status"], record["picks"]) == (dr.STATE_RESOLVED, picks)
        assert attachments.get_attachment(spec, "att-df")["revision"] == rev
        assert dr.confirmed_source(spec, "n1")["picks"][0]["url"] == "https://x/y.json"


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

    def test_a_catalog_pick_is_read_again_from_the_listing(self):
        """The card may be days old, as an external row's probe may be: a pick
        is checked against the Data Catalog listing as it is when the user
        confirms. A dataset it no longer holds is refused, and whether one is
        installed is the listing's answer, not the card's."""
        part = _part(catalog=[
            {"datasetId": "d1", "name": "Areas", "installed": True, "sourceType": "catalog"},
            {"datasetId": "gone", "name": "Gone", "installed": True, "sourceType": "catalog"},
        ])
        listing = [{"id": "d1", "name": "Areas", "installed": False}]
        (row,) = dr.resolve_picks(part, [{"lane": "catalog", "key": "d1"}], catalog_rows=listing)
        assert (row["datasetId"], row["installed"]) == ("d1", False)
        with pytest.raises(dr.DatasetResolutionError, match="not in the Data Catalog"):
            dr.resolve_picks(part, [{"lane": "catalog", "key": "gone"}], catalog_rows=listing)


class TestRecordSelection:
    def test_an_installed_catalog_pick_resolves_the_node(self):
        spec = _spec_with_finder()
        state = dr.record_selection(spec, "att-df", [
            {"lane": "catalog", "datasetId": "d1", "name": "Areas", "installed": True},
        ])
        assert state["status"] == dr.STATE_RESOLVED
        source = dr.confirmed_source(spec, "n1")
        assert source["picks"][0]["datasetId"] == "d1"
        assert "curio_data_path" in source["note"]

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
        from utk_curio.backend.app.agents.application.turns import delegates as services

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
        from utk_curio.backend.app.agents.application.turns import delegates as services

        spec = self._spec()
        # Content generation is the Node Builder's own mode, so NB is the delegate.
        home, _ = services._delegation_home(
            spec, NB, "node.content.generate", {},
            node_id="n1", user_key="1",
        )
        assert home["coord"] == NB
        # The delegate does not pick the home: another agent's task for the
        # same node lands at that Node Builder too.
        other, _ = services._delegation_home(
            spec, "agent.curio.researcher@1", "research.verify", {},
            node_id="n1", user_key="1",
        )
        assert other["coord"] == NB and other["attachmentId"] == home["attachmentId"]

    def test_discovery_on_an_incompatible_node_falls_back_to_dev_72(self):
        from utk_curio.backend.app.agents.application.turns import delegates as services

        spec = self._spec(node_type="curio.builtin/vis-vega")
        home, _ = services._delegation_home(
            spec, DF, "dataset.discover", {}, node_id="n1", user_key="1",
        )
        assert home["coord"] == NB  # the Dataset Finder cannot live there


class TestWhatMayBeALoadersSource:
    """What may be the source of a loader with a Dataset Finder of its own,
    before its first round (``grounding._dataflow_grounded_literal``). With
    nothing, its Finder is asked before its builder: a dataset the Data
    Catalog only offers, such as one Curio ships, is nothing of the kind
    until the goal names it. Step 5.3 of the agent chat plan."""

    NEIGHBORHOODS = "data.cityofchicago.neighborhoods"

    def _judged(self, goal: str, *, titles: dict | None = None, **context) -> str | None:
        """What may be the source of a loader whose goal is *goal*, with a Data
        Catalog of *titles* (``{dataset id: title}``, Chicago Neighborhoods
        alone by default)."""
        from utk_curio.backend.app.agents.application import source_grounding as sg
        from utk_curio.backend.app.agents.application.turns import grounding

        titles = titles if titles is not None else {self.NEIGHBORHOODS: "Chicago Neighborhoods"}
        catalog = {dataset_id: sg.CatalogRef(dataset_id, title, "geojson", "") for dataset_id, title in titles.items()}
        ctx = sg.GroundingContext(catalog_ids=catalog, is_data_loading=True, code_engine="python", **context)
        return grounding._dataflow_grounded_literal({"id": "n1", "goal": goal}, ctx)

    def test_a_shipped_dataset_is_a_source_once_the_goal_names_its_title(self):
        assert self._judged("CPL branches: load the locations of Chicago Public Library branches") is None
        named = self._judged("Neighborhoods: load the Chicago neighborhood boundaries")
        assert named and "Chicago Neighborhoods" in named, named

    def test_numbers_the_goal_gives_that_the_user_typed_may_be_its_source(self):
        typed = ("Table the count 12, 15 and 20.",)
        given = self._judged("Counts: load the count 12, 15 and 20", user_messages=typed)
        assert given and "12, 15, 20" in given, given
        # Typed in no message of this conversation, or given by no goal: no source.
        assert self._judged("Counts: load the count 12, 15 and 20") is None
        assert self._judged("Counts: load the counts", user_messages=typed) is None

    def test_a_saved_key_whose_host_the_goal_names_may_be_its_source(self):
        from utk_curio.backend.app.agents.application import source_grounding as sg

        keys = {"census": sg.SecretRef("census", "api.census.gov")}
        named = self._judged("Tracts: load the tract population from api.census.gov", secrets=keys)
        assert named and "census" in named, named
        assert self._judged("Tracts: load the tract population", secrets=keys) is None

    def test_a_title_in_the_singular_is_named_by_its_plural(self):
        """A goal names a title in the plural, whatever its ending: "-ies",
        "-es" or "-s". On 271aec86a4 only a last "s" was taken off, so
        "boundaries" did not name "Chicago Boundary", nor "branches" "CPL
        Branch". Found by the review of #1642."""
        boundary = self._judged("Boundaries: load the Chicago boundaries",
                                titles={"data.city.boundary": "Chicago Boundary"})
        assert boundary and "'Chicago Boundary'" in boundary, boundary
        branch = self._judged("Branches: load the CPL branches", titles={"data.cpl.branches": "CPL Branch"})
        assert branch and "'CPL Branch'" in branch, branch

    def test_a_title_is_named_by_its_words_together_and_in_order(self):
        """A goal names a title when it holds the title's words together and
        in order. A goal about other data that holds them apart names none:
        "Chicago crime counts by community area" is about crimes. On
        271aec86a4 every word of the title anywhere in the goal named it.
        Found by the review of #1642."""
        areas = {"data.city.areas": "Chicago Community Areas"}
        assert self._judged("Crimes: load Chicago crime counts by community area", titles=areas) is None
        named = self._judged("Areas: load the Chicago community areas", titles=areas)
        assert named and "'Chicago Community Areas'" in named, named

    def test_a_title_of_one_generic_word_names_no_goal(self):
        """An import titled "Data" says nothing of what it holds, so no goal
        names it. On 271aec86a4 every goal that said "data" named it. Found
        by the review of #1642."""
        assert self._judged("Parks: load the parks data", titles={"user.import.rows": "Data"}) is None

    def test_a_lone_number_a_year_or_an_id_is_no_source(self):
        """A number the user wrote that the goal repeats is no data when it is
        a year, or one number alone, such as the 311 of a city service: the
        loader's Finder is asked. On 271aec86a4 any number both wrote counted
        as values the user typed. Found by the review of #1642."""
        assert self._judged("Crimes: load the 2023 crimes", user_messages=("Map the crimes of 2023.",)) is None
        assert self._judged("Requests: load the 311 service requests", user_messages=("Map the 311 requests.",)) is None
        assert self._judged(
            "Calls: load the 311 calls of 2022 and 2023", user_messages=("Show the 311 calls in 2022 and 2023.",),
        ) is None

    def test_values_the_user_typed_with_their_labels_may_be_its_source(self):
        """Values the user typed each after its label are data, two as much as
        several bare numbers, and so is a year typed as a label's value."""
        rents = self._judged("Rents: load Loop 2450 and Pilsen 1500", user_messages=("Rents: Loop 2450, Pilsen 1500",))
        assert rents and "1500, 2450" in rents, rents
        built = self._judged("Years built: load Loop 1925 and Pilsen 1910",
                             user_messages=("Built: Loop 1925, Pilsen 1910",))
        assert built and "1910, 1925" in built, built
