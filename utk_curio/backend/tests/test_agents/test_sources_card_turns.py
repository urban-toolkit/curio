"""The turns around a loader's Sources card, as the signed-off boards of the
leaner chat draw them (step 7.1 of the owner's agent chat plan, part 2:
boards S04, S05 and S08).

- The chat that asked for a loader's candidates asks for its source and
  counts what the loader's Dataset Finder found ("Pick a source for **Load
  boundaries**. Its Dataset Finder found 3."), and its card lists the rows
  in the order of the Finder's own card.
- A card's rows are one list, best first across its two lanes
  (``rowOrder``), by what can be done with each row, then its fit.
- A pick's Source recorded turns are kept for the agents: the card's
  Recorded line says the pick and what comes of it, in every chat.
- What comes of a pick that ended a plan's wait names the node ("The
  Dataflow Builder builds Load boundaries from it.").
- A search another agent asks of a Dataset Finder is one quiet line in the
  Finder's chat ("Asked by the Dataflow Builder: find a source for Load
  boundaries."), and the card of the delegated run's trace is a run detail.
- A pick Curio downloads keeps where its data comes from, which the card's
  Recorded line names: the portal, not the Data Catalog it lands in.

Each check here fails at its own assertion on the branch before this part
(cb7f1cf23e), and the last one on the branch before it was found (b91cb6cd28).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application.solve import budgets
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import URL, _Harness
from utk_curio.backend.tests.test_agents.test_fetch_delegation import (
    CHICAGO,
    PORTAL_OBSERVATION,
    _discovery_harness,
    _FakeDiscovery,
    _select,
)


def _candidates(found: int) -> str:
    """The Finder's reply: *found* portal rows, each a good fit."""
    rows = [{
        "name": f"Chicago community areas {i}", "sourceType": "portal",
        "url": f"https://data.example.org/areas-{i}.geojson", "format": "geojson",
        "fit": {"score": 90, "rationale": "the boundaries the goal asks for"},
    } for i in range(found)]
    return json.dumps({"datasetCandidates": {"lanes": {"external": rows, "catalog": []}}})


class TestTheChatThatAsked:
    def test_it_asks_for_the_loaders_source_and_counts_what_its_finder_found(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The line over the card in the Dataflow Builder's chat, which the
        Builder's next runs read too. Before, it said "**Load boundaries**
        needs a source. Its Dataset Finder found 3 candidates: pick one with
        Use this source.", and its card drew the rows lane by lane."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=[_candidates(3)])
        h.solve()
        asked = [
            (turn, part) for turn in h.session_turns(h.att) for part in (turn.get("content") or [])
            if part.get("type") == "sourcePick"
        ]
        assert [turn.get("text") for turn, _part in asked] == [
            "Pick a source for **Load boundaries**. Its Dataset Finder found 3."
        ]
        own = next(
            part for turn in h.session_turns(h.finder_attachment_id()) for part in (turn.get("content") or [])
            if part.get("type") == "datasetCandidates"
        )
        assert own.get("rowOrder") and asked[0][1].get("rowOrder") == own["rowOrder"], (asked[0][1], own)


class TestOneList:
    def test_a_cards_rows_are_one_list_best_first_across_its_lanes(self):
        """A row the dataflow holds comes before a portal page, whichever lane
        each is in: the card is one list. Before, the card had no such list
        and drew the external lane whole, then the Data Catalog's."""
        part = {"lanes": {
            "external": [
                {"name": "Portal page", "access": "manual-download", "fit": {"score": 95, "rationale": "a"}},
                {"name": "Fetchable", "access": "fetchable", "fit": {"score": 60, "rationale": "b"}},
            ],
            "catalog": [
                {"name": "Held", "installed": False, "fit": {"score": 90, "rationale": "c"}},
                {"name": "Installed", "installed": True, "fit": {"score": 55, "rationale": "d"}},
            ],
        }}
        content.rank_candidates(part)
        names = [part["lanes"][lane][index]["name"] for lane, index in part.get("rowOrder") or []]
        assert names == ["Fetchable", "Installed", "Held", "Portal page"], part
        # Each lane still keeps its own rows, ranked, and the lanes their order.
        assert part["laneOrder"] == ["external", "catalog"], part


class TestThePick:
    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_its_source_recorded_turns_are_kept_for_the_agents(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Board S08: no chat draws a Source recorded turn, since the card's
        Recorded line says the pick and what comes of it; the agents still
        read it. Before, both chats drew it under the card."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        h.select(URL)
        for attachment_id in (h.finder_attachment_id(), h.att):
            turns = h.session_turns(attachment_id)
            recorded = [t for t in turns if (t.get("text") or "").startswith("Source recorded for Load boundaries")]
            assert len(recorded) == 1, [t.get("text") for t in turns]
            assert recorded[0].get("forAgents") is True, recorded[0]
            context = "\n".join(m["content"] for m in sessions.context_messages(turns))
            assert recorded[0]["text"] in context, context

    @pytest.mark.parametrize("paused_by", ["the row's Solve", "Build & validate"])
    def test_what_comes_of_a_pick_that_ended_a_plans_wait_names_the_node(
        self, client, user_and_token, tmp_curio, monkeypatch, paused_by
    ):
        """Board S05: "Recorded: Chicago Neighborhoods (Data Catalog). The
        Dataflow Builder builds CPL branches from it." The record's ``next``
        is the line's end, in every chat. Before, it said "The Dataflow
        Builder goes on with its plan and builds the loader from this
        source.", naming no node."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        if paused_by == "Build & validate":
            h.simulate("auto")
        else:
            h.validate("load")
        delegated = h.select(URL).get("delegated") or {}
        assert delegated.get("status") == "plan-waiting", delegated
        record = dr.source_record(h.spec(), h.load) or {}
        assert record.get("next") == "The Dataflow Builder builds Load boundaries from it.", record


class TestTheFindersChat:
    def test_a_search_another_agent_asked_for_says_who_asked_and_for_which_node(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Board S08: "Asked by the Dataflow Builder: find a source for CPL
        branches." The Finder still reads the task's own words. Before, the
        chat drew the task as the person's own message."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        turns = h.session_turns(h.finder_attachment_id())
        framing = [
            t for t in turns
            if t.get("role") == "user" and (t.get("text") or "").startswith(sessions.DELEGATED_TURN_PREFIX)
        ]
        assert len(framing) == 1, [t.get("text") for t in turns]
        assert framing[0].get("asked") == {"by": "Dataflow Builder", "task": "find a source for Load boundaries"}, framing[0]
        context = "\n".join(m["content"] for m in sessions.context_messages(turns))
        assert framing[0]["text"] in context, context

    def test_the_card_of_the_delegated_runs_trace_is_a_run_detail(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Board S08 draws no Delegated task card: it is the run's trace,
        which Show run details draws. Before, every chat drew it."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        cards = [
            part for turn in h.session_turns(h.finder_attachment_id()) for part in (turn.get("content") or [])
            if part.get("type") == "card" and str(part.get("title") or "").startswith("Delegated task")
        ]
        assert len(cards) == 1, cards
        assert cards[0].get("runDetails") is True, cards[0]


class _NamedDiscovery(_FakeDiscovery):
    """The Discovery Catalog as the pick sees it, its Chicago source named as
    the catalog names it."""

    def get_manifest(self, source_id):
        if source_id != CHICAGO:
            raise KeyError(source_id)
        return SimpleNamespace(name="City of Chicago Data Portal", provider=SimpleNamespace(type="socrata"))


class TestADownloadedPick:
    """Dev check of #1652 (11-28): a Chicago Data Portal row the pick downloaded
    read "Recorded: Libraries - Locations, Contact Information, and Usual Hours
    of Operation (Data Catalog).". The card's Recorded line names where its
    pick comes from (board S05), from the pick the record keeps: before, the
    catalog pick a download became kept no word of the portal."""

    @pytest.fixture(autouse=True)
    def _no_builder(self, monkeypatch):
        """The pick of a downloaded row starts the loader's builder: not here."""
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.solve.node_solve.solve_node_stream",
            lambda *a, **k: None,
        )

    @pytest.mark.parametrize("landed", [True, False], ids=["downloaded", "still downloading"])
    def test_it_keeps_the_portal_it_comes_from(self, client, user_and_token, tmp_curio, monkeypatch, landed):
        user, token = user_and_token
        if landed:
            dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
            fake = _NamedDiscovery(started={"dataset": {"id": dataset_id}, "alreadyPresent": True})
        else:
            fake = _NamedDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.verify.verify_external_source",
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, finder_id, [{"lane": "external", "key": "https://data.example.org/areas.geojson"}]).get_json()
        assert fake.calls == [(CHICAGO, "cauq-8yn6", None)], fake.calls
        picks = (dr.source_record(h.spec(), h.load) or {}).get("picks") or []
        assert [pick.get("provider") for pick in picks] == ["City of Chicago Data Portal"], picks
        assert body["picks"][0].get("provider") == "City of Chicago Data Portal", body["picks"]
