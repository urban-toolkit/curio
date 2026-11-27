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

    def _judged(self, goal: str, *, titles: dict | None = None, node_title: str = "", **context) -> str | None:
        """What may be the source of a loader whose goal is *goal*, titled
        *node_title*, with a Data Catalog of *titles* (``{dataset id:
        title}``, Chicago Neighborhoods alone by default)."""
        from utk_curio.backend.app.agents.application import source_grounding as sg
        from utk_curio.backend.app.agents.application.turns import grounding

        titles = titles if titles is not None else {self.NEIGHBORHOODS: "Chicago Neighborhoods"}
        catalog = {dataset_id: sg.CatalogRef(dataset_id, title, "geojson", "") for dataset_id, title in titles.items()}
        ctx = sg.GroundingContext(catalog_ids=catalog, is_data_loading=True, code_engine="python", **context)
        return grounding._dataflow_grounded_literal({"id": "n1", "goal": goal, "title": node_title}, ctx)

    def test_a_shipped_dataset_is_a_source_once_the_goal_names_its_title(self):
        assert self._judged("CPL branches: load the locations of Chicago Public Library branches") is None
        named = self._judged("Neighborhoods: load the Chicago neighborhood boundaries")
        assert named and "Chicago Neighborhoods" in named, named

    def test_numbers_the_goal_gives_that_the_user_typed_may_be_its_source(self):
        typed = ("Table the count: Loop 12, Pilsen 15, Hyde Park 20.",)
        given = self._judged("Counts: load the count, Loop 12, Pilsen 15 and Hyde Park 20", user_messages=typed)
        assert given and "12, 15, 20" in given, given
        # Typed in no message of this conversation, or given by no goal: no source.
        assert self._judged("Counts: load the count, Loop 12, Pilsen 15 and Hyde Park 20") is None
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

    def test_the_chat_grounds_a_loader_only_by_a_path_its_goal_or_title_names(self):
        """What the user said in the chat that asked is a loader's source only
        when it is tied to that loader: a path whose file its goal or title
        names. A request for synthetic data there, or a URL a candidates card
        there verified for no node, grounds no loader; its own goal must ask.
        On 6031770487 each grounded every loader of the plan, so a plan that
        loads library branches and crimes loaded both from the branches'
        file. Found by the second review of #1642."""
        said = ("My branches are in /data/cpl_branches.csv",)
        branches = self._judged("Branches: load the locations of the CPL branches", user_messages=said)
        assert branches and "/data/cpl_branches.csv" in branches, branches
        titled = self._judged("Locations: load the locations", node_title="CPL branches", user_messages=said)
        assert titled and "/data/cpl_branches.csv" in titled, titled
        crimes = "Crimes: load the crimes by community area"
        assert self._judged(crimes, user_messages=said) is None
        assert self._judged(crimes, user_messages=("Make a demo with synthetic data.",)) is None
        verified = {"https://data.example.org/cpl_branches.csv": {"status": "verified", "httpStatus": 200}}
        assert self._judged(crimes, user_messages=("plan it",), verified_urls=verified) is None

    def test_a_saved_output_or_a_title_of_verbs_names_no_goal(self):
        """A goal names only datasets the user or Curio put in the Data
        Catalog. The listing also holds every saved node output of the
        account, of any dataflow, titled after its node, and none of them is
        named; nor is a title of verbs alone, such as "Load". On 6031770487 an
        old output titled "Library branches" named the goal "load the library
        branches", and one titled "Load" named any goal that loads. Found by
        the second review of #1642."""
        from utk_curio.backend.app.agents.application import source_grounding as sg
        from utk_curio.backend.app.agents.application.turns import grounding

        items = [
            {"id": "computed.df-old.n7@1", "title": "Library branches", "format": "csv", "origin": "computed",
             "producerNodeId": "n7"},
            {"id": "computed.df-old.n8@1", "title": "Load", "format": "csv", "origin": "computed",
             "producerNodeId": "n8"},
            {"id": "user.load", "title": "Load", "format": "csv", "origin": "imported"},
        ]
        _by_path, by_id = grounding._catalog_grounding_refs("p-1", items)
        ctx = sg.GroundingContext(catalog_ids=by_id, is_data_loading=True, code_engine="python")
        for goal in ("Branches: load the library branches", "Parks: load the parks"):
            assert grounding._dataflow_grounded_literal({"id": "n1", "goal": goal}, ctx) is None, goal
        # A dataset imported under the output's title is named.
        items.append({"id": "user.library-branches", "title": "Library branches", "format": "csv", "origin": "imported"})
        _by_path, by_id = grounding._catalog_grounding_refs("p-1", items)
        named = grounding._dataflow_grounded_literal(
            {"id": "n1", "goal": "Branches: load the library branches"}, sg.GroundingContext(catalog_ids=by_id),
        )
        assert named and "'Library branches'" in named, named

    def test_a_title_is_named_by_its_short_words_too(self):
        """Every word of a title is in the phrase a goal must hold, short ones
        too: "LA Parks" is not named by "load the Chicago parks", nor "NY Taxi"
        by "load the Chicago taxi trips". On 6031770487 words under three
        letters were dropped first, so both were. Found by the second review
        of #1642."""
        titles = {"data.la.parks": "LA Parks", "data.ny.taxi": "NY Taxi"}
        assert self._judged("Parks: load the Chicago parks", titles=titles) is None
        assert self._judged("Trips: load the Chicago taxi trips", titles=titles) is None
        named = self._judged("Parks: load the LA parks", titles=titles)
        assert named and "'LA Parks'" in named, named

    def test_numbers_with_one_label_or_none_are_no_source(self):
        """Typed values are data only as labels' values, each label its own,
        two or more of them. A label written before several numbers names ids
        ("ward 1 and ward 2"), and numbers with no label say how many, which or
        when: zip codes, the hours of a day, "the 3 largest parks within 5 km".
        On 6031770487 any three numbers counted, and so did two after one
        label. Found by the second review of #1642."""
        for goal, said in (
            ("Wards: load ward 1 and ward 2", "Compare ward 1 and ward 2."),
            ("Routes: load route 9 and route 66", "Map route 9 and route 66."),
            ("Tracts: load tract 8391 and tract 8392", "Show tract 8391 and tract 8392."),
            ("Zips: load the zip codes 60601, 60602 and 60603", "Use the zip codes 60601, 60602 and 60603."),
            ("Trips: load the trips between 8 and 10 am, 12 and 2 pm", "Trips between 8 and 10 am, 12 and 2 pm."),
            ("Parks: load the 3 largest parks within 5 km and 10 minutes",
             "Find the 3 largest parks within 5 km and 10 minutes."),
        ):
            assert self._judged(goal, user_messages=(said,)) is None, goal
        rents = self._judged("Rents: load Loop 2450, Pilsen 1500 and Hyde Park 1700",
                             user_messages=("Rents: Loop 2450, Pilsen 1500, Hyde Park 1700",))
        assert rents and "1500, 1700, 2450" in rents, rents

    def test_a_plural_folds_a_last_e_and_keeps_ss_us_and_is(self):
        """How a title's words are read in the singular: a last "e" goes as
        "-es" does, so "Houses" is named by "each house", and a word that ends
        in "ss", "us" or "is" is no plural, so "Street Addresses" is named by
        "each street address", "Permit Statuses" by "the permit status", and
        "analysis" stays whole."""
        from utk_curio.backend.app.agents.application.turns import grounding

        for title, goal in (
            ("Houses", "Homes: load each house"),
            ("Street Addresses", "Addresses: load each street address"),
            ("Permit Statuses", "Permits: load the permit status of each permit"),
        ):
            named = self._judged(goal, titles={"data.city.items": title})
            assert named and repr(title) in named, (title, goal, named)
        stems = [grounding._word_stem(word) for word in ("house", "houses", "address", "census", "analysis")]
        assert stems == ["hous", "hous", "address", "census", "analysis"], stems
