"""Step 5.6 of the agent chat plan: what the dev check of #1652 found.

On dev 0.17.441 (11-28, ci-reports/finder-candidates-dev-1128/SUMMARY.md):

- After the owner's Apply of an invited editor's pick, nothing built the
  loader: the Apply ended the plan's pause and started nothing, and the pick
  had told the editor to press a Resume the plan line no longer showed.
- One row of a Finder's card whose reason ran past 160 characters voided the
  whole card ("Dataset Finder returned no usable candidates"), and the loader
  was then built and approved from a dataset nobody picked, which its
  dataflow did not hold.
- The owner's request card named no loader, only a node id.
- A pick's portal download landed titled by its file name, outside the
  dataflow, where a catalog pick's dataset joins it.
- A sentence that started with a dataset's name capitalized it.
- A Hub row linking its ``/about`` page read Verified, though the page is no
  data: the check probed the item's metadata in its place.
- Once one loader's pick added a dataset to the dataflow, another loader's
  card still said Not installed for it.

Names main lacks are read inside each test, so the module imports on main and
each test fails at its own check.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.application.proposals import acquire
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.discovery.service import DiscoveryService
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import (
    _a_dataset,
    _Harness,
    _reads,
)
from utk_curio.backend.tests.test_agents.test_editors_drive_agents import BOB_TOKEN, _account
from utk_curio.backend.tests.test_agents.test_fetch_delegation import _plan_session, _select
from utk_curio.backend.tests.test_agents.test_finder_candidates_usable import (
    CHICAGO,
    LIBRARIES,
    LIBRARIES_NAME,
    _downloads,
    _held_by_the_dataflow,
    _requests_of,
    _the_portals,
)

#: How a pick that waits for the owner says what comes once she adds the
#: dataset: the plan's agent, in the words a direct pick's answer gives
#: (``_plan_waiting``), which go on after it.
ONCE_ADDED = "once it is added, the Dataflow Builder "
#: A dataset named as the dev check's download was, in lower case.
LOWER_NAME = "x8fc-8rcq.geojson (Chicago Public Library locations)"
#: A fit reason as long as the dev check's 100-year loader's (179 characters there).
LONG_REASON = (
    "Peak water depths at the river gauge for the simulated 10-, 50- and 100-year storms, "
    "one row per storm and return period, which is exactly what this 100-year loader keeps."
)
LONG_COVERAGE = (
    "The river gauge on the Chicago River at the Lake Street bridge, the simulated 10-, 50- and "
    "100-year design storms of the 2024 study, every fifteen minutes through each storm's peak."
)


def _catalog_reply(*rows) -> str:
    """The Finder's reply holding *rows* in its Data Catalog lane, each
    ``(dataset id, name, fit, rationale)``."""
    return json.dumps({"datasetCandidates": {"lanes": {"external": [], "catalog": [
        {"name": name, "sourceType": "catalog", "datasetId": dataset_id,
         "fit": {"score": fit, "rationale": rationale}}
        for dataset_id, name, fit, rationale in rows
    ]}}})


def _listed(h, token: str) -> dict:
    """The dataflow's agents as the canvas of the account of *token* lists
    them, by attachment id."""
    r = h.client.get(f"/api/agents/projects/{h.pid}/attachments", headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    return {card["attachmentId"]: card for card in r.get_json()["attachments"]}


def _goes_on(h, token: str) -> dict:
    """What the tab of the account of *token* is told to go on with, once the
    owner added the dataset a pick waited for: the answer a direct pick gives
    (``plan-waiting``), or nothing."""
    r = h.client.post(
        f"/api/agents/projects/{h.pid}/attachments/{h.finder_attachment_id()}/dataset-selection/goes-on",
        headers=_auth(token),
    )
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True))
    return r.get_json().get("delegated") or {}


def _an_editors_pick_waits(client, db, user_and_token, monkeypatch, *, whose: str = "his",
                           name: str = "Library branches"):
    """A plan whose loader paused for its source, and Bob's pick of the
    dataset *name*, of his own Data Catalog (*whose* ``his``) or of Alice's,
    the owner (``hers``), which waits for her review. Alice's run made the
    card of her dataset, as on dev; Bob's run made the card of his. Returns
    ``(harness, alice's token, bob, dataset id, the pick's answer)``."""
    from utk_curio.backend.app.projects import access

    alice, alice_token = user_and_token
    bob = _account(db, "bob", "Bob", BOB_TOKEN)
    dataset_id = _a_dataset(bob if whose == "his" else alice, name)
    h = _Harness(client, alice, alice_token, monkeypatch,
                 discover_replies=[_catalog_reply((dataset_id, name, 90, "the branches the loader asks for"))],
                 dl_replies=[_reads(dataset_id)])
    access.add_editor(alice, h.pid, "bob")
    if whose == "his":
        h.token = BOB_TOKEN
    done = h.simulate("auto")[-1][1]
    assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
    h.token = BOB_TOKEN
    picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
    assert picked.status_code == 200, picked.get_data(as_text=True)
    body = picked.get_json()
    assert body["status"] == dr.STATE_AWAITING_INSTALL, body
    return h, alice_token, bob, dataset_id, body


def _the_owner_applies(client, h, alice_token) -> list[dict]:
    """Alice applies Bob's request from her Data Catalog's drawer. Returns
    the requests her review held."""
    requests = _requests_of(client, h, alice_token)
    applied = client.post(f"/api/dataflows/{h.pid}/datasets/requests/{requests[0]['proposalId']}/apply",
                          headers=_auth(alice_token))
    assert applied.status_code == 200, applied.get_data(as_text=True)
    return requests


# ── 1. The owner's Apply lets the plan go on, from the editor's tab ───────────


class TestTheOwnersApplyLetsThePlanGoOn:
    """On dev the owner's Apply ended the pause of the plan the editor's pick
    waited on and started nothing: the line read "Planned · 4 nodes, 4 to
    solve" with no Resume, and nothing built the loader in 421 s. A direct
    pick's answer (``plan-waiting``) has the plan go on by itself from the tab
    that picked. Now the Apply keeps that same answer for the editor who
    picked, whose tab takes it once and goes on with it: never the owner's,
    whose Apply approves adding the dataset, not spending a build."""

    @pytest.mark.parametrize("whose", ["his", "hers"])
    def test_the_editors_tab_is_told_to_go_on_as_a_direct_pick_is_and_only_his(
        self, client, db, user_and_token, tmp_curio, monkeypatch, whose
    ):
        h, alice_token, bob, _dataset_id, _body = _an_editors_pick_waits(
            client, db, user_and_token, monkeypatch, whose=whose,
        )
        _the_owner_applies(client, h, alice_token)
        # The Apply ended the wait, and the pause with it (as before).
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session
        # Every tab reads who picked and how the plan goes on.
        record = _listed(h, BOB_TOKEN)[h.finder_attachment_id()]["sourceRecord"]
        assert record.get("pickedBy") == str(bob.id), record
        assert (record.get("goesOn") or {}).get("continueWith") == "build", record
        # The owner's tab is told nothing to run, and her ask takes nothing.
        assert _goes_on(h, alice_token) == {}
        delegated = _goes_on(h, BOB_TOKEN)
        assert {key: delegated.get(key) for key in ("status", "attachmentId", "nodeId", "ref", "running",
                                                     "continueWith")} == {
            "status": "plan-waiting", "attachmentId": h.att, "nodeId": h.load, "ref": "load", "running": None,
            "continueWith": "build"}, delegated
        # It says what comes, naming no control, and the record every tab
        # shows says the same sentence (``next``).
        reason = delegated.get("reason") or ""
        assert reason.startswith("the Dataflow Builder ") and "Resume" not in reason, delegated
        assert record.get("next") == reason[:1].upper() + reason[1:] + ".", record
        # Once: another tab of his, or a reload, is told nothing more.
        assert _goes_on(h, BOB_TOKEN) == {}
        assert "goesOn" not in (_listed(h, BOB_TOKEN)[h.finder_attachment_id()]["sourceRecord"] or {})

    def test_his_tabs_build_then_builds_the_loader(self, client, db, user_and_token, tmp_curio, monkeypatch):
        h, alice_token, _bob, dataset_id, _body = _an_editors_pick_waits(client, db, user_and_token, monkeypatch)
        _the_owner_applies(client, h, alice_token)
        assert _goes_on(h, BOB_TOKEN).get("continueWith") == "build"
        # What his tab does with it: the Build & validate it names, as his.
        h.token = BOB_TOKEN
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "completed", done
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load)

    def test_a_go_on_waits_for_his_next_tab_and_goes_once_the_plan_went_on_without_it(
        self, client, db, user_and_token, tmp_curio, monkeypatch
    ):
        """His tab was closed when she applied: the go-on waits for his next
        tab, as nothing runs a build with no tab. If the plan goes on first,
        by her Build & validate, that tab is told nothing to run."""
        h, alice_token, _bob, dataset_id, _body = _an_editors_pick_waits(client, db, user_and_token, monkeypatch)
        _the_owner_applies(client, h, alice_token)
        assert (_listed(h, BOB_TOKEN)[h.finder_attachment_id()]["sourceRecord"].get("goesOn") or {}).get(
            "continueWith") == "build"
        h.token = alice_token
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "completed", done
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load)
        assert _goes_on(h, BOB_TOKEN) == {}

    def test_outside_a_plan_his_tab_has_the_loaders_builder_write_it(
        self, client, db, user_and_token, tmp_curio, monkeypatch
    ):
        """No plan waited for the loader: Bob's Solve this node asked its
        Finder. A direct pick outside a plan starts the node's builder; once
        the owner adds the dataset Bob picked, his tab's take starts it,
        through the same code, and his pick said so, naming no control. On
        main it told him to Solve the node, in a chat that has no Solve."""
        from utk_curio.backend.app.projects import access
        from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import _solve_this_node
        from utk_curio.backend.tests.test_agents.test_fetch_delegation import _drain

        alice, alice_token = user_and_token
        bob = _account(db, "bob", "Bob", BOB_TOKEN)
        dataset_id = _a_dataset(bob, "Library branches")
        h = _Harness(client, alice, alice_token, monkeypatch,
                     discover_replies=[_catalog_reply((dataset_id, "Library branches", 90, "the branches"))],
                     dl_replies=[_reads(dataset_id)])
        access.add_editor(alice, h.pid, "bob")
        h.token = BOB_TOKEN
        assert _solve_this_node(h, h.node_builder_attachment_id()).get("verdict") == "awaiting-source"
        picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        reason = (picked.get_json().get("delegated") or {}).get("reason") or ""
        assert "once it is added, the node's builder writes the loader" in reason, reason
        assert "Solve" not in reason and "Resume" not in reason, reason
        _the_owner_applies(client, h, alice_token)
        assert _goes_on(h, alice_token) == {}
        delegated = _goes_on(h, BOB_TOKEN)
        assert (delegated.get("status"), delegated.get("nodeId")) == ("delegating", h.load), delegated
        events = _drain(h, delegated["attachmentId"])
        assert next(p for k, p in events if k == "done")["verdict"] == "pass"
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load)
        assert _goes_on(h, BOB_TOKEN) == {}

    def test_the_pick_says_the_plan_goes_on_once_it_is_added_and_names_no_control(
        self, client, db, user_and_token, tmp_curio, monkeypatch
    ):
        """On dev the pick said "once it is added, press Resume in the
        Dataflow Builder's chat", a Resume the owner's Apply took off the line.
        The pick's answer, the record every tab shows and both chats' Source
        recorded turns say what comes once the owner adds it, and name no
        control; and the dataset keeps its own name's case (step 6)."""
        h, _alice_token, _bob, _dataset_id, body = _an_editors_pick_waits(
            client, db, user_and_token, monkeypatch, name=LOWER_NAME,
        )
        said = [
            (body.get("delegated") or {}).get("reason") or "",
            dr.source_record(h.spec(), h.load).get("next") or "",
            *[h.session_turns(chat)[-1].get("text") or "" for chat in (h.finder_attachment_id(), h.att)],
        ]
        for text in said:
            assert "Resume" not in text and "press" not in text, text
            assert ONCE_ADDED in text, text
            assert "Alice" in text and LOWER_NAME in text, text
            assert LOWER_NAME[0].upper() + LOWER_NAME[1:] not in text, text


# ── 2. A free-text field over its limit is cut on a word, not the card ────────


class TestAFieldOverItsLimitIsCutNotTheCard:
    """On dev, the 100-year loader's Finder offered the right dataset at fit
    97 with a 179-character reason. The limit is 160, the parser refused the
    row, and one refused row voided the whole card, so the loader got no card.
    A free-text field over its limit is cut on a word now, and the row stays;
    a name, an id, a link or a score that breaks the contract still voids it."""

    def test_a_reason_and_a_coverage_over_their_limit_are_cut_on_a_word_and_every_row_kept(self):
        long_row = {"name": "Storm peaks", "sourceType": "catalog", "datasetId": "imported.peaks",
                    "fit": {"score": 97, "rationale": LONG_REASON}}
        short_row = {"name": "Storm gauges", "sourceType": "catalog", "datasetId": "imported.gauges",
                     "fit": {"score": 70, "rationale": "the gauges"}}
        portal_row = {"name": "Storm depths", "sourceType": "portal", "url": "https://data.example.org/depths.csv",
                      "coverage": LONG_COVERAGE}
        parsed = content._parse_dataset_candidates({"lanes": {"catalog": [long_row, short_row],
                                                              "external": [portal_row]}})
        assert parsed is not None, "one field over its limit voided the card"
        [peaks, gauges] = parsed["lanes"]["catalog"]
        [depths] = parsed["lanes"]["external"]
        assert gauges["fit"] == {"score": 70, "rationale": "the gauges"}, gauges
        assert peaks["fit"]["score"] == 97, peaks
        for cut, whole in ((peaks["fit"]["rationale"], LONG_REASON), (depths["coverage"], LONG_COVERAGE)):
            assert len(cut) <= content._CANDIDATE_TEXT_MAX_CHARS and cut.endswith("…"), cut
            body = cut[:-1]
            assert whole.startswith(body) and not whole[len(body)].isalnum(), f"{cut!r} halves a word"

    def test_a_field_whose_first_word_alone_passes_its_limit_is_left_empty_never_cut(self):
        """One word longer than the bound, such as a long link, cannot be cut
        on a word: the field is left out of the row (a reason, empty), and the
        row stays, with no word cut in the middle."""
        token = "https://data.example.org/" + "peaks" * 40
        row = {"name": "Storm peaks", "sourceType": "catalog", "datasetId": "imported.peaks",
               "coverage": token, "fit": {"score": 97, "rationale": token}}
        parsed = content._parse_dataset_candidates({"lanes": {"catalog": [row], "external": []}})
        assert parsed is not None, "one word over its limit voided the card"
        [kept] = parsed["lanes"]["catalog"]
        assert kept["fit"] == {"score": 97, "rationale": ""}, kept
        assert "coverage" not in kept, kept

    def test_a_chats_own_block_with_a_reason_over_its_limit_is_a_card(self):
        reply = ("I found it.\n\n```curio.v1\n"
                 + _catalog_reply(("imported.peaks", "Storm peaks", 97, LONG_REASON)) + "\n```")
        _visible, parts = content.extract_content(reply)
        assert [part.get("type") for part in parts] == ["datasetCandidates"], parts

    def test_a_loaders_card_with_a_reason_over_its_limit_is_offered_and_waits_for_its_pick(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Example table: peak depths of simulated storms")
        h = _Harness(client, user, token, monkeypatch,
                     discover_replies=[_catalog_reply((dataset_id, "Peak depths", 97, LONG_REASON))],
                     dl_replies=[_reads(dataset_id)])
        done = h.simulate("auto")[-1][1]
        cards = [part for turn in h.session_turns(h.finder_attachment_id())
                 for part in turn.get("content") or [] if part.get("type") == "datasetCandidates"]
        assert cards, "the Finder's card was voided"
        [row] = cards[-1]["lanes"]["catalog"]
        assert row["datasetId"] == dataset_id and row["fit"]["score"] == 97, row
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
        assert h.node_content(h.load) == ""


# ── 3. A loader with its own Finder is built only from a dataset tied to it ───


class TestALoaderIsBuiltOnlyFromADatasetTiedToIt:
    """On dev the 100-year loader's Finder was asked first, as #1642 asks it:
    the dataflow held no dataset, and the Data Catalog's listing holds every
    dataset Curio ships, which says nothing of the loader. Its card was voided
    (step 2), so its rounds went on, as for a Finder that found nothing, and
    its Node Builder, handed the account's listing, wrote
    ``curio_load_data("data.curio.example-peak-depths")``, which the round's
    check grounded on that listing: the build approved a loader of a dataset
    nobody picked and the dataflow did not hold. #1652 meant such a loader to
    keep its own rounds and their failure. A loader with its own Dataset
    Finder is built only from a dataset tied to it, as #1642's first attempt
    is: the dataflow's, one its goal names, one picked for it, its widget's or
    its code's."""

    @pytest.mark.parametrize("entry", ["row-solve", "solve"])
    @pytest.mark.parametrize("finder_said", ["nothing", "under-the-floor"])
    def test_a_loader_whose_finder_left_no_card_is_not_built_from_a_dataset_nobody_picked(
        self, client, user_and_token, tmp_curio, monkeypatch, finder_said, entry
    ):
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Storm peaks")
        reply = ("I could not find a source for this loader." if finder_said == "nothing"
                 else _catalog_reply((dataset_id, "Storm peaks", 25, "a neighbour of the data, not the data")))
        h = _Harness(client, user, token, monkeypatch, discover_replies=[reply], dl_replies=[_reads(dataset_id)])
        if entry == "solve":
            outcome = h.solve()["results"][h.load]
            built = outcome.get("status") == "solved"
        else:
            outcome = h.validate("load")[-1][1]
            built = outcome.get("verdict") == "pass"
        assert h.dl_calls, "the loader's rounds never ran"
        assert dataset_id not in h.dl_calls[0], "its Node Builder was handed a dataset nothing ties to the loader"
        assert not built, outcome
        assert h.node_content(h.load) == ""
        assert dataset_id not in _held_by_the_dataflow(h)


# ── 4. The owner's request card names the loader ─────────────────────────────


class TestTheRequestNamesTheLoader:
    """On dev the owner's card read "Add dataset · x8fc-8rcq.geojson" and
    named no loader: the request carried only the node's id, though #1652
    said it names the loader."""

    @pytest.mark.parametrize("whose", ["his", "hers"])
    def test_an_editors_pick_asks_for_the_dataset_naming_the_loader(
        self, client, db, user_and_token, tmp_curio, monkeypatch, whose
    ):
        h, alice_token, _bob, dataset_id, _body = _an_editors_pick_waits(
            client, db, user_and_token, monkeypatch, whose=whose,
        )
        [request] = _requests_of(client, h, alice_token)
        assert (request["datasetId"], request["nodeIds"]) == (dataset_id, [h.load]), request
        assert request.get("nodeNames") == {h.load: "Load boundaries"}, request


# ── 5. A pick's download keeps the portal's title and joins the dataflow ─────


def _a_libraries_card(client, user, token, monkeypatch) -> _Harness:
    """A loader whose Finder offers Chicago's library branches by their
    portal's coordinate, under a name of its own, not the portal's title."""
    reply = json.dumps({"datasetCandidates": {"lanes": {"catalog": [], "external": [{
        "name": "Chicago library branches", "sourceType": "discovery", "sourceId": CHICAGO,
        "resourceId": LIBRARIES, "format": "geojson", "fit": {"score": 96, "rationale": "the branches"},
    }]}}})
    h = _Harness(client, user, token, monkeypatch, discover_replies=[reply])
    h.validate("load")
    return h


class TestAPicksDownloadIsNamedAndJoinsTheDataflow:
    """On dev the pick of the portal's library branches downloaded them as
    ``imported.xefd08dde184e``, titled ``x8fc-8rcq.geojson`` in the Data
    Catalog where the portal calls them "Libraries - Locations, Contact
    Information, and Usual Hours of Operation", and left the dataflow without
    them, where a pick of a Data Catalog row adds it."""

    def test_the_download_keeps_the_portals_title_and_joins_the_dataflow(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        _the_portals(monkeypatch)
        landed = _a_dataset(user, "x8fc-8rcq.geojson")
        asked: list[dict] = []

        def _start(self, dir_name, resource_id, **kwargs):
            asked.append({"source": dir_name, "resource": resource_id, **kwargs})
            return {"jobId": "job-1", "status": "queued"}

        monkeypatch.setattr(DiscoveryService, "start_acquire", _start)
        monkeypatch.setattr(DiscoveryService, "get_job",
                            lambda self, job_id: {"status": "completed", "datasetId": landed})
        h = _a_libraries_card(client, user, token, monkeypatch)
        picked = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": f"{CHICAGO}/{LIBRARIES}"}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert [(a["source"], a["resource"]) for a in asked] == [(CHICAGO, LIBRARIES)], asked
        assert asked[0].get("title") == LIBRARIES_NAME, asked
        assert landed in _held_by_the_dataflow(h), _held_by_the_dataflow(h)
        assert [p.get("installed") for p in picked.get_json()["picks"]] == [True], picked.get_json()

    def test_a_download_that_lands_after_the_pick_joins_the_dataflow(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.app.datasets.repositories import user_store

        user, token = user_and_token
        _the_portals(monkeypatch)
        _downloads(monkeypatch)
        h = _a_libraries_card(client, user, token, monkeypatch)
        picked = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": f"{CHICAGO}/{LIBRARIES}"}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert (picked.get_json().get("delegated") or {}).get("status") == "acquiring", picked.get_json()
        landed = _a_dataset(user, LIBRARIES_NAME)
        monkeypatch.setattr(user_store.UserDatasetRepository, "discovery_resource_index",
                            lambda self: {(CHICAGO, LIBRARIES): landed})
        with monkeypatch.context() as patched:
            patched.setattr(spec_reads, "_acting_user", lambda: user)
            acquire._settle_discovery_acquisitions(h.ukey, h.pid)
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        assert landed in _held_by_the_dataflow(h), _held_by_the_dataflow(h)


# ── 6. A sentence never changes the case of a name it starts with ────────────


class TestASentenceKeepsANamesCase:
    """On dev the editor's pick read "X8fc-8rcq.geojson (Chicago Public
    Library locations) waits for ...": a sentence made of a reason capitalized
    its first letter, the dataset's name. A pick's reasons start with Curio's
    own words; ``test_the_pick_says_the_plan_goes_on_once_it_is_added_and_names_no_control``
    checks the owner's review, this one an add the Data Catalog refuses."""

    def test_an_add_that_fails_says_so_in_the_names_own_case(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
        from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

        user, token = user_and_token
        dataset_id = _a_dataset(user, LOWER_NAME)
        h = _Harness(client, user, token, monkeypatch,
                     discover_replies=[_catalog_reply((dataset_id, LOWER_NAME, 90, "the branches"))])
        h.simulate("auto")

        def _refused(self, *args, **kwargs):
            raise DatasetCatalogError("the store is full")

        monkeypatch.setattr(DatasetCatalogService, "install_dataset", _refused)
        picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        reason = (picked.get_json().get("delegated") or {}).get("reason") or ""
        assert "could not be added" in reason and "the store is full" in reason, reason
        said = [dr.source_record(h.spec(), h.load).get("next") or "",
                *[h.session_turns(chat)[-1].get("text") or "" for chat in (h.finder_attachment_id(), h.att)]]
        for text in said:
            assert LOWER_NAME in text and LOWER_NAME[0].upper() + LOWER_NAME[1:] not in text, text


# ── 8. A card says what the dataflow holds now ───────────────────────────────


def _catalog_rows_of(h, attachment_id: str, *, node_id: str) -> list[dict]:
    """The Data Catalog rows the cards of the chat of *attachment_id* offer
    for the loader *node_id*: its Dataset Finder's own cards, and the copies
    in a chat that asked (``sourcePick``)."""
    return [
        row for turn in h.session_turns(attachment_id) for part in turn.get("content") or []
        if part.get("type") == "datasetCandidates"
        or (part.get("type") == "sourcePick" and part.get("nodeId") == node_id)
        for row in (part.get("lanes") or {}).get("catalog") or []
    ]


class TestACardSaysWhatTheDataflowHoldsNow:
    """On dev, in dataflow B, the 10-year loader's pick added the shipped
    peak depths to the dataflow, and the 50-year loader's card still said
    Not installed for the same dataset: a row's ``installed`` was kept as the
    Data Catalog listing said it when the card was minted, never read again.
    Every card that offers a dataset says it is installed once the dataflow
    holds it, however it got there."""

    def test_the_other_loaders_card_says_installed_once_a_pick_added_the_dataset(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Peak depths")
        plan = {
            "goal": "chart the peak depths of two storms",
            "nodes": [
                {"ref": "load_10", "nodeType": "curio.builtin/data-loading", "title": "10-year storm",
                 "intent": "load the 10-year storm's peaks"},
                {"ref": "load_50", "nodeType": "curio.builtin/data-loading", "title": "50-year storm",
                 "intent": "load the 50-year storm's peaks"},
                {"ref": "both", "nodeType": "curio.builtin/python-computation", "title": "Both storms",
                 "intent": "stack the two storms' peaks"},
            ],
            "edges": [{"from": "load_10", "to": "both"}, {"from": "load_50", "to": "both"}],
        }
        h = _Harness(client, user, token, monkeypatch, plan=plan,
                     discover_replies=[_catalog_reply((dataset_id, "Peak depths", 97, "the storms' peaks"))],
                     dl_replies=[_reads(dataset_id)])
        done = h.simulate("auto")[-1][1]
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
        first, second = h.loaders
        assert [row["installed"] for row in _catalog_rows_of(h, h.finder_attachment_id(second), node_id=second)] \
            == [False], "the premise: the dataflow does not hold it yet"
        picked = _select(h, h.finder_attachment_id(first), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert dataset_id in _held_by_the_dataflow(h)
        for chat in (h.finder_attachment_id(second), h.att):
            rows = [row for row in _catalog_rows_of(h, chat, node_id=second) if row.get("datasetId") == dataset_id]
            assert rows and all(row.get("installed") is True for row in rows), (chat, rows)


# ── 7. A link to a page reads Web page, whatever its portal's metadata says ──


#: An ArcGIS Hub item with one layer, as the dev check's second row named it.
HUB_ITEM = "9f031888499b4eee9b3713f238e22dcd_0"


def _resolver(host: str):
    def _resolve(name):
        if name == host:
            return ["93.184.216.34"]
        raise OSError(f"unknown host {name}")

    return _resolve


def _a_portal_that_answers(metadata_marker: str, metadata: dict, page_title: str):
    """A portal whose metadata endpoint (any URL holding *metadata_marker*)
    answers *metadata* as JSON, and whose every other URL answers an HTML
    page titled *page_title*. Records each URL asked."""
    asked: list[str] = []

    def _fn(method, url, headers=None):
        asked.append(url)
        if metadata_marker in url:
            return 200, {"Content-Type": "application/json"}, json.dumps(metadata).encode(), None
        page = f"<html><head><title>{page_title}</title></head><body>app</body></html>"
        return 200, {"Content-Type": "text/html; charset=utf-8"}, page.encode(), None

    return _fn, asked


class TestAPageLinkReadsWebPage:
    """DISCOVERY-CATALOG.md part 6: each external row says what its link
    answered, Verified for data, Web page for a page about the data. A link
    a provider recognizes was read through the provider's metadata of its
    dataset alone, so a link to the dataset's page read Verified, and its row
    was one code could fetch."""

    def test_a_hub_link_to_its_about_page_reads_web_page(self):
        url = f"https://hub.arcgis.com/datasets/{HUB_ITEM}/about"
        request_fn, asked = _a_portal_that_answers(
            "/api/v3/datasets/", {"data": {"attributes": {"name": "Library Location", "fields": []}}},
            "Library Location",
        )
        outcome = verify.verify_external_source(url, request_fn=request_fn, resolver=_resolver("hub.arcgis.com"))
        assert url in asked, asked
        assert (outcome.get("status"), outcome.get("webPage")) == ("verified", True), outcome
        assert (outcome.get("provider"), outcome.get("datasetId")) == ("arcgis", HUB_ITEM), outcome
        assert verify.classify_access(outcome, url)["access"] == verify.ACCESS_MANUAL, outcome

    def test_a_socrata_landing_page_link_reads_web_page(self):
        url = f"https://data.cityofchicago.org/d/{LIBRARIES}"
        request_fn, asked = _a_portal_that_answers(
            f"/api/views/{LIBRARIES}.json", {"name": LIBRARIES_NAME, "columns": [{"fieldName": "branch_"}]},
            "Libraries | City of Chicago | Data Portal",
        )
        outcome = verify.verify_external_source(
            url, request_fn=request_fn, resolver=_resolver("data.cityofchicago.org"),
        )
        assert url in asked, asked
        assert (outcome.get("status"), outcome.get("webPage")) == ("verified", True), outcome
        assert (outcome.get("provider"), outcome.get("datasetId")) == ("socrata", LIBRARIES), outcome
        assert outcome.get("datasetName") == LIBRARIES_NAME, outcome

    def test_a_page_link_of_a_dataset_its_portal_does_not_have_still_answers_its_error(self):
        """A guard: the page of a made-up id may answer 200, as a Hub page
        does for any path; its portal's metadata answers 404, and so does
        the row."""
        url = f"https://hub.arcgis.com/datasets/{'0' * 32}_0/about"

        def _fn(method, url, headers=None):
            if "/api/v3/datasets/" in url:
                return 404, {"Content-Type": "application/json"}, b"{}", None
            return 200, {"Content-Type": "text/html"}, b"<html><title>Hub</title></html>", None

        outcome = verify.verify_external_source(url, request_fn=_fn, resolver=_resolver("hub.arcgis.com"))
        assert (outcome.get("status"), outcome.get("httpStatus")) == (verify.HTTP_ERROR, 404), outcome
