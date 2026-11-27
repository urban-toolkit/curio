"""Step 5.4 of the agent chat plan: the Dataset Finder's candidates can be used as offered.

On dev (11-26) a plan's loader asked its Dataset Finder for the Chicago Public
Library branches. The best row named the right dataset but offered only the
portal's home page, read Verified, with an id no tool confirmed. The Overpass
row read Unreachable for an answer of 406, and two Data Catalog rows the Finder
itself rated as map context were offered as sources. No row could be picked
and built from without a manual step (ci-reports/finder-candidates-1126/REPORT.md).

- F1: the runtime searches the Discovery Catalog for the delegated Finder,
  which holds no tools, and the rows it copies from that search are
  Downloadable. Found on the way: discovery.search named each source by its
  manifest id, without the major the roster keys sources by, so a row copied
  from it never kept its coordinate.
- F2: a pick that waits for its install ends once the dataflow holds the
  dataset, however it got there.
- F2b (the owner's "Pick adds it", 11-26): the owner's pick of a Data Catalog
  row the dataflow does not hold adds it at once; an invited editor's pick
  asks the owner, through the editor requests.
- F3: a portal link that holds its dataset's id gets its portal's coordinate,
  a web page is never read as verified data, and the card ranks its rows by
  what can be done with them.
- F4: an error answer is named for what it was, never Unreachable, and the
  probe says it is Curio and what it accepts.
- F5: rows the Finder itself rates as not the data are not offered.

Names main lacks are read inside each test, so the module imports on main and
each test fails at its own check.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.application.proposals import acquire
from utk_curio.backend.app.agents.application.turns import delegates
from utk_curio.backend.app.agents.application.turns import grounding
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.discovery.service import DiscoveryService
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import (
    _a_dataset,
    _a_pick_that_waits_for_its_install,
    _Harness,
    _in_the_dataflow,
    _reads,
    _solve_this_node,
)
from utk_curio.backend.tests.test_agents.test_editors_drive_agents import BOB_TOKEN, _account
from utk_curio.backend.tests.test_agents.test_fetch_delegation import _plan_session, _select

#: The City of Chicago Data Portal, by the id the roster keys it by, and by its manifest's own id.
CHICAGO = "source.cityofchicago.data-portal@1"
CHICAGO_ID = "source.cityofchicago.data-portal"
#: The dataset the dev check's loader needed, as the portal's search finds it first.
LIBRARIES = "x8fc-8rcq"
LIBRARIES_NAME = "Libraries - Locations, Contact Information, and Usual Hours of Operation"

#: The portal as the Discovery Catalog's roster lists it.
CHICAGO_SOURCE = {
    "sourceId": CHICAGO_ID, "dirName": CHICAGO, "name": "City of Chicago Data Portal",
    "provider": "socrata", "baseUrl": "https://data.cityofchicago.org", "kind": "portal",
    "publisher": "City of Chicago", "description": "", "auth": {"required": False, "present": False},
    "capabilities": {"search": True, "describe": True, "download": True, "formats": ["csv", "geojson", "json"]},
}
#: The portal's search result for the library branches, as ``DiscoveryService.search_all`` answers it.
LIBRARIES_ROW = {
    "sourceId": CHICAGO_ID, "sourceName": "City of Chicago Data Portal", "resourceId": LIBRARIES,
    "name": LIBRARIES_NAME, "publisher": "City of Chicago",
    "description": "Chicago Public Library locations, contact information and usual hours",
    "formats": ["csv", "geojson", "json"], "updatedAt": "2026-11-01T00:00:00Z",
    "alreadyHeldDatasetId": None, "landingUrl": f"https://data.cityofchicago.org/d/{LIBRARIES}",
}
#: The Finder's reply that copies that row's coordinate, as the reply contract asks.
LIBRARIES_CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {"external": [{
    "name": LIBRARIES_NAME, "sourceType": "discovery", "sourceId": CHICAGO, "resourceId": LIBRARIES,
    "format": "csv", "fit": {"score": 90, "rationale": "the branch locations the loader asks for"},
}], "catalog": []}}})


def _the_portals(monkeypatch, *, fails: bool = False) -> list[dict]:
    """The Discovery Catalog with one portal, Chicago's, whose search answers
    the library branches and which describes that dataset alone; its downloads
    start and keep running. Returns each search asked of it: its text and the
    account it was asked as. With *fails*, a search raises."""
    from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

    searched: list[dict] = []

    def _search_all(self, *, q="", fmt=None, limit=None, provider=None, auth=None, include_storage=True):
        searched.append({"q": q, "user": getattr(self.user, "id", None)})
        if fails:
            raise RuntimeError("the portals did not answer")
        return {"resources": [dict(LIBRARIES_ROW)],
                "sources": [{"sourceId": CHICAGO_ID, "status": "ok", "count": 1}]}

    def _list_catalog(self, **kwargs):
        return {"sources": [dict(CHICAGO_SOURCE)], "facets": {}}

    def _describe(self, dir_name, resource_id):
        if (dir_name, resource_id) != (CHICAGO, LIBRARIES):
            raise DiscoveryError(f"{resource_id} is not on {dir_name}")
        return {"resourceId": resource_id, "name": LIBRARIES_NAME, "formats": ["csv", "geojson", "json"]}

    monkeypatch.setattr(DiscoveryService, "search_all", _search_all)
    monkeypatch.setattr(DiscoveryService, "list_catalog", _list_catalog)
    monkeypatch.setattr(DiscoveryService, "describe_resource", _describe)
    return searched


def _downloads(monkeypatch) -> list[tuple]:
    """Downloads into the Data Catalog that start and keep running: each
    start, by its coordinate."""
    started: list[tuple] = []

    def _start(self, dir_name, resource_id, **kwargs):
        started.append((dir_name, resource_id))
        return {"jobId": "job-1", "status": "queued"}

    monkeypatch.setattr(DiscoveryService, "start_acquire", _start)
    monkeypatch.setattr(DiscoveryService, "get_job", lambda self, job_id: {"status": "running"})
    monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0.2)
    return started


def _cards(h, attachment_id) -> list[dict]:
    """The candidates cards the chat of *attachment_id* holds, in order."""
    return [
        part for turn in h.session_turns(attachment_id) for part in (turn.get("content") or [])
        if part.get("type") == "datasetCandidates"
    ]


def _goal(h) -> str:
    """The loader's goal, as the dataflow holds it."""
    return next(n for n in h.spec()["dataflow"]["nodes"] if n.get("id") == h.load).get("goal") or ""


def _held_by_the_dataflow(h) -> list[str]:
    """The ids of the datasets the dataflow holds (Add to project's refs)."""
    return [str(ref.get("datasetId") or ref.get("id")) for ref in (h.spec()["dataflow"].get("datasets") or [])
            if isinstance(ref, dict)]


def _catalog_candidates(*rows) -> str:
    """The Finder's reply holding *rows* in its Data Catalog lane, each
    ``(dataset id, name, fit)``."""
    return json.dumps({"datasetCandidates": {"lanes": {"external": [], "catalog": [
        {"name": name, "sourceType": "catalog", "datasetId": dataset_id,
         "fit": {"score": fit, "rationale": f"rated {fit}"}}
        for dataset_id, name, fit in rows
    ]}}})


# ── F1: the runtime searches the Discovery Catalog for the delegated Finder ────


class TestTheFinderSearchesTheDiscoveryCatalog:
    @pytest.mark.parametrize("entry", ["row-solve", "solve"])
    def test_a_loaders_finder_is_handed_the_portals_search_for_its_goal_and_its_row_downloads(
        self, client, user_and_token, tmp_curio, monkeypatch, entry
    ):
        """The Finder runs as a delegate with no tools, so on main it saw only
        the Data Catalog listing, never the Discovery Catalog: the right
        dataset reached its card only as a guess from the model's memory. Now
        the runtime searches the portals for the loader's goal, as the account
        that asked (a Solve's thread holds no request), and hands the Finder
        the rows; a row it copies the coordinate of is Downloadable, and its
        pick downloads it."""
        user, token = user_and_token
        searched = _the_portals(monkeypatch)
        started = _downloads(monkeypatch)
        h = _Harness(client, user, token, monkeypatch, discover_replies=[LIBRARIES_CANDIDATES])
        if entry == "solve":
            h.solve()
        else:
            h.validate("load")
        assert [(s["q"], s["user"]) for s in searched] == [(_goal(h), user.id)], searched
        assert len(h.discover_calls) == 1, len(h.discover_calls)
        frame = h.discover_calls[0]
        assert LIBRARIES in frame and LIBRARIES_NAME in frame, frame
        # Named by the roster's id, the one a candidates row must carry.
        assert f'"sourceId": "{CHICAGO}"' in frame, frame
        finder = h.finder_attachment_id()
        row = _cards(h, finder)[-1]["lanes"]["external"][0]
        assert (row.get("sourceId"), row.get("resourceId"), row.get("acquirable")) == (CHICAGO, LIBRARIES, True), row
        picked = _select(h, finder, [{"lane": "external", "key": f"{CHICAGO}/{LIBRARIES}"}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert started == [(CHICAGO, LIBRARIES)], started

    def test_a_search_that_fails_is_a_note_and_the_finder_is_still_asked(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A portal search that raises never fails discovery: the Finder is
        asked as before, and its input says the Discovery Catalog could not be
        searched, so it can say so."""
        user, token = user_and_token
        searched = _the_portals(monkeypatch, fails=True)
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        assert len(searched) == 1, searched
        assert len(h.discover_calls) == 1, len(h.discover_calls)
        frame = h.discover_calls[0]
        assert '"discovery": {' in frame, frame
        assert LIBRARIES not in frame, frame
        assert len(_cards(h, h.finder_attachment_id())) == 1

    def test_the_finders_reply_contract_teaches_the_portal_coordinate(self):
        """The delegate answers to a contract it can see: it now holds the
        portals' rows, so it is told how a row carries their coordinate."""
        contract = delegates._discovery_reply_contract()
        assert agent_text.section(builtin.PROTOCOL_FILE, "dataset-candidates-from-portals") in contract, contract

    def test_a_discovery_search_names_each_source_as_the_roster_does(self, app, monkeypatch):
        """Found on the way, on main: discovery.search answered each row's
        source by its manifest's id, with no major, while the roster, the
        describe and the download key a source by its id with its major, as
        discovery.sources names it. A candidates row that copied the coordinate
        from a search lost it, and so never was Downloadable."""
        _the_portals(monkeypatch)
        with app.app_context():
            status, text = tools.execute_read_tool(
                "discovery.search", user_key="1", project_id="p", target=None, params={"q": "libraries"},
            )
        assert status == "ok", text
        found = json.loads(text)["resources"][0]
        assert (found["sourceId"], found["resourceId"]) == (CHICAGO, LIBRARIES), found
        copied = {"name": found["name"], "sourceType": "discovery",
                  "sourceId": found["sourceId"], "resourceId": found["resourceId"]}
        with app.app_context():
            acquire._mint_row_acquirable(copied, agents_roster._LazyRoster(), None)
        assert (copied.get("sourceId"), copied.get("acquirable")) == (CHICAGO, True), copied


# ── F2: a pick waiting for its install ends once the dataflow holds it ────────


class TestAnInstallWaitEndsOnceTheDataflowHoldsTheDataset:
    @pytest.mark.parametrize("entry", ["resume", "solve-this-node"])
    def test_a_pick_waiting_for_its_install_is_built_once_the_dataset_was_added(
        self, client, user_and_token, tmp_curio, monkeypatch, entry
    ):
        """A pick of a Data Catalog dataset the dataflow does not hold waits
        for its install. On main only an applied dataset.install card of the
        Finder's ended the wait: Add to project from the Data Catalog left the
        loader waiting for good, and Resume and Solve this node kept saying to
        install it. Now each reads what the dataflow holds before it starts."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Library branches")
        h = _Harness(client, user, token, monkeypatch, dl_replies=[_reads(dataset_id)])
        h.simulate("auto")
        card = dr.source_record(h.spec(), h.load)["discoveryId"]
        _a_pick_that_waits_for_its_install(h, card, dataset_id)
        _in_the_dataflow(h, dataset_id)
        if entry == "resume":
            h.simulate("auto")
        else:
            _solve_this_node(h, h.node_builder_attachment_id())
        record = dr.source_record(h.spec(), h.load)
        assert record["status"] == dr.STATE_RESOLVED, record
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load), h.node_content(h.load)


# ── F2b: a pick adds a Data Catalog dataset (owner, 11-26, "Pick adds it") ────


class TestAPickAddsACatalogDataset:
    def test_the_owners_pick_adds_it_to_the_dataflow_and_the_plan_goes_on(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Use this source on a Data Catalog row the dataflow does not hold
        adds it to the dataflow at once, as a pick downloads a Downloadable
        row, and the plan goes on: the next Build & validate builds the loader
        from it. On main the pick waited for a separate install."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Library branches")
        h = _Harness(client, user, token, monkeypatch,
                     discover_replies=[_catalog_candidates((dataset_id, "Library branches", 90))],
                     dl_replies=[_reads(dataset_id)])
        h.simulate("auto")
        picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        body = picked.get_json()
        assert body["status"] == dr.STATE_RESOLVED, body
        assert dataset_id in _held_by_the_dataflow(h), _held_by_the_dataflow(h)
        assert body["picks"][0]["installed"] is True, body["picks"]
        assert _plan_session(h)["nodeStates"]["load"] == "created", _plan_session(h)
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "completed", done
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load)

    def test_an_add_that_fails_keeps_the_pick_waiting_and_says_why(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """An add the Data Catalog refuses leaves the pick waiting for its
        install, with the reason in the pick's answer: never a server error,
        and never a pick that claims the dataflow holds the dataset."""
        from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
        from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

        user, token = user_and_token
        dataset_id = _a_dataset(user, "Library branches")
        h = _Harness(client, user, token, monkeypatch,
                     discover_replies=[_catalog_candidates((dataset_id, "Library branches", 90))])
        h.simulate("auto")

        def _refused(self, *args, **kwargs):
            raise DatasetCatalogError("the store is full")

        monkeypatch.setattr(DatasetCatalogService, "install_dataset", _refused)
        picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        body = picked.get_json()
        assert body["status"] == dr.STATE_AWAITING_INSTALL, body
        reason = (body.get("delegated") or {}).get("reason") or ""
        assert "could not be added" in reason and "the store is full" in reason, body
        assert dataset_id not in _held_by_the_dataflow(h)

    def test_an_editors_pick_asks_the_owner_whose_apply_lets_the_plan_go_on(
        self, client, db, user_and_token, tmp_curio, monkeypatch
    ):
        """An invited editor's pick of his own dataset changes no account but
        his, so it asks the owner, as his Add to project does: the pick waits
        for her review, which the Data Catalog's requests hold, naming the
        loader. Once she applies it, Resume builds the loader from it. On main
        the pick waited for an install nobody was asked for."""
        from utk_curio.backend.app.projects import access

        alice, alice_token = user_and_token
        bob = _account(db, "bob", "Bob", BOB_TOKEN)
        dataset_id = _a_dataset(bob, "Library branches")
        h = _Harness(client, alice, alice_token, monkeypatch,
                     discover_replies=[_catalog_candidates((dataset_id, "Library branches", 90))],
                     dl_replies=[_reads(dataset_id)])
        access.add_editor(alice, h.pid, "bob")
        h.token = BOB_TOKEN
        h.simulate("auto")
        assert [r["datasetId"] for r in _cards(h, h.finder_attachment_id())[-1]["lanes"]["catalog"]] == [dataset_id]
        picked = _select(h, h.finder_attachment_id(), [{"lane": "catalog", "key": dataset_id}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert picked.get_json()["status"] == dr.STATE_AWAITING_INSTALL, picked.get_json()
        assert dataset_id not in _held_by_the_dataflow(h)
        listed = client.get(f"/api/dataflows/{h.pid}/datasets/requests", headers=_auth(alice_token))
        assert listed.status_code == 200, listed.get_data(as_text=True)
        requests = listed.get_json()["requests"]
        assert [(r["datasetId"], r["nodeIds"]) for r in requests] == [(dataset_id, [h.load])], requests
        assert "Alice" in ((picked.get_json().get("delegated") or {}).get("reason") or ""), picked.get_json()
        applied = client.post(f"/api/dataflows/{h.pid}/datasets/requests/{requests[0]['proposalId']}/apply",
                              headers=_auth(alice_token))
        assert applied.status_code == 200, applied.get_data(as_text=True)
        h.token = alice_token
        h.simulate("auto")
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        assert f'curio_load_data("{dataset_id}")' in h.node_content(h.load)


# ── F3: a portal link's coordinate, no web page read as data, the card's order ─


#: What the probe saw of each link of the ranking test's rows.
_VERDICTS = {
    "https://data.example.org/rows.xml": {
        "status": "verified", "httpStatus": 200, "contentType": "application/xml", "checkedAt": "now"},
    "https://data.example.org/portal": {
        "status": "verified", "httpStatus": 200, "contentType": "text/html", "pageTitle": "Open data",
        "checkedAt": "now"},
    "https://overpass.example.org/api/interpreter": {
        "status": "http-error", "httpStatus": 406, "contentType": "text/html",
        "detail": "the endpoint answered 406", "checkedAt": "now"},
}


def _external(name: str, fit: int, **row) -> dict:
    return {"name": name, "sourceType": "portal", "fit": {"score": fit, "rationale": f"rated {fit}"}, **row}


def _minted(app, monkeypatch, reply: dict, listing: list) -> dict:
    """The card a delegated Finder's *reply* becomes, checked against the
    Data Catalog *listing*, its links probed as :data:`_VERDICTS` says and
    Chicago's portal describing its libraries."""
    _the_portals(monkeypatch)
    monkeypatch.setattr(verify, "verify_external_source", lambda url, **kwargs: dict(
        _VERDICTS.get(url) or {"status": "unverified", "detail": "no probeable URL", "checkedAt": "now"}))
    with app.app_context():
        part, text, outcome = delegates._mint_candidates_from_delegate(
            {}, json.dumps({"datasetCandidates": {"lanes": reply}}), listing,
        )
    assert outcome == "ok" and part is not None, text
    return part


class TestTheCardOffersWhatCanBeDone:
    def test_a_portal_link_that_holds_its_dataset_id_gets_the_portals_coordinate(self, app, monkeypatch):
        """A link on a portal of the Discovery Catalog that holds the portal's
        dataset id is that dataset of that portal: Curio downloads it through
        the portal, with the portal's own export. On main it got the Direct
        URL coordinate, which downloads the link as it is (a Socrata export
        link answers its first 1,000 rows)."""
        _the_portals(monkeypatch)
        direct = "source.curio.direct-url@1"
        sources = {
            CHICAGO: dict(CHICAGO_SOURCE),
            direct: {"dirName": direct, "provider": "direct", "kind": "portal", "baseUrl": "",
                     "capabilities": {"download": True, "formats": ["csv", "geojson", "json"]}},
        }
        row = {
            "name": LIBRARIES_NAME, "sourceType": "portal",
            "url": f"https://data.cityofchicago.org/resource/{LIBRARIES}.json",
            "verification": {"status": "verified", "httpStatus": 200, "contentType": "application/json",
                             "sampleKeys": ["name"]},
            "access": verify.ACCESS_FETCHABLE,
        }
        with app.app_context():
            acquire._mint_row_acquirable(row, agents_roster._LazyRoster(sources), None)
        assert (row.get("sourceId"), row.get("resourceId"), row.get("acquirable")) == (CHICAGO, LIBRARIES, True), row

    def test_a_web_page_answer_is_named_a_web_page(self):
        """A link that answers a web page answered, but it is no data: the
        probe's outcome says it was a page, so no card reads it as verified
        data. On main it read Verified."""

        def _page(method, url, **kwargs):
            return 200, {"Content-Type": "text/html; charset=utf-8"}, b"<html><title>Open data</title></html>", None

        outcome = verify.verify_endpoint("https://data.example.org/", request_fn=_page,
                                         resolver=lambda host: ["93.184.216.34"])
        assert outcome.get("webPage") is True, outcome

    def test_the_rows_rank_by_what_can_be_done_then_fit_and_the_best_lane_comes_first(self, app, monkeypatch):
        """Downloadable rows first, then rows code can fetch, then the Data
        Catalog's rows the dataflow holds, then its others, then portal
        downloads, then the rest; by fit within each. Each lane keeps its rows
        in that order, and the lane that holds the best row comes first. On
        main the rows kept the reply's order and the external lane always came
        first."""
        installed = {"id": "imported.held@1", "name": "Held", "installed": True}
        other = {"id": "imported.other@1", "name": "Other", "installed": False}
        part = _minted(app, monkeypatch, {
            "external": [
                _external("Portal page", 95, url="https://data.example.org/portal"),
                _external("Error answer", 92, url="https://overpass.example.org/api/interpreter"),
                _external("Fetchable", 60, url="https://data.example.org/rows.xml"),
                _external("Downloadable", 55, sourceType="discovery", sourceId=CHICAGO, resourceId=LIBRARIES),
            ],
            "catalog": [
                {"name": "Other", "sourceType": "catalog", "datasetId": other["id"],
                 "fit": {"score": 99, "rationale": "rated 99"}},
                {"name": "Held", "sourceType": "catalog", "datasetId": installed["id"],
                 "fit": {"score": 70, "rationale": "rated 70"}},
            ],
        }, [installed, other])
        order = {lane: [row["name"] for row in part["lanes"][lane]] for lane in ("external", "catalog")}
        assert order == {
            "external": ["Downloadable", "Fetchable", "Portal page", "Error answer"],
            "catalog": ["Held", "Other"],
        }, order
        assert part.get("laneOrder") == ["external", "catalog"], part.get("laneOrder")

    def test_with_nothing_external_to_download_or_fetch_the_data_catalog_comes_first(self, app, monkeypatch):
        held = {"id": "imported.held@1", "name": "Held", "installed": True}
        part = _minted(app, monkeypatch, {
            "external": [_external("Portal page", 95, url="https://data.example.org/portal")],
            "catalog": [{"name": "Held", "sourceType": "catalog", "datasetId": held["id"],
                         "fit": {"score": 70, "rationale": "rated 70"}}],
        }, [held])
        assert part.get("laneOrder") == ["catalog", "external"], part.get("laneOrder")


# ── F4: honest probe verdicts ──────────────────────────────────────────────────


def _answers(status: int, content_type: str = "text/html", body: bytes = b"<html><title>No</title></html>"):
    seen: list[dict] = []

    def _fn(method, url, headers=None):
        seen.append(dict(headers or {}))
        return status, {"Content-Type": content_type}, body, None

    return _fn, seen


class TestTheProbeSaysWhatHappened:
    def test_an_error_answer_is_named_for_what_it_was(self):
        """Overpass answered 406 to the dev check's probe. On main every error
        answer read Unreachable, as a link that never answered does."""
        request_fn, _seen = _answers(406)
        outcome = verify.verify_endpoint("https://overpass.example.org/api/interpreter", request_fn=request_fn,
                                         resolver=lambda host: ["93.184.216.34"])
        assert (outcome["status"], outcome.get("httpStatus")) == ("http-error", 406), outcome
        assert outcome["detail"] == "the endpoint answered 406", outcome

    def test_a_link_that_never_answered_is_still_unreachable(self):
        def _down(method, url, headers=None):
            raise ConnectionError("timed out")

        outcome = verify.verify_endpoint("https://data.example.org/x", request_fn=_down,
                                         resolver=lambda host: ["93.184.216.34"])
        assert outcome["status"] == "unreachable" and "httpStatus" not in outcome, outcome

    def test_the_probe_says_it_is_curio_and_what_it_accepts(self):
        """Overpass's policy, like most portals', asks a client to say who it
        is. On main the probe sent no User-Agent and no Accept."""
        request_fn, seen = _answers(200, "application/json", b"[]")
        verify.verify_external_source("https://data.example.org/rows.json", request_fn=request_fn,
                                      resolver=lambda host: ["93.184.216.34"])
        assert seen and "curio.urbantk.org" in seen[0].get("User-Agent", ""), seen
        assert seen[0].get("Accept"), seen

    def test_a_gated_answer_still_teaches_the_portal_download(self):
        request_fn, _seen = _answers(403)
        outcome = verify.verify_endpoint("https://data.example.org/data.csv", request_fn=request_fn,
                                         resolver=lambda host: ["93.184.216.34"])
        assert verify.classify_access(outcome, "https://data.example.org/data.csv")["access"] == verify.ACCESS_MANUAL

    def test_a_pick_whose_link_answered_an_error_does_not_resolve_the_node(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """An error answer is no source, as an unreachable link is not: the
        node keeps waiting for a pick."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        monkeypatch.setattr(verify, "verify_external_source", lambda url, **kwargs: {
            "status": "http-error", "httpStatus": 406, "detail": "the endpoint answered 406", "checkedAt": "now",
        })
        picked = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": "https://data.example.org/areas.geojson"}])
        assert picked.status_code == 200, picked.get_data(as_text=True)
        assert picked.get_json()["status"] == dr.STATE_CANDIDATES_PENDING, picked.get_json()


# ── F5: no context rows offered ────────────────────────────────────────────────


class TestOnlyTheDataIsOffered:
    def test_rows_the_finder_rates_as_not_the_data_are_not_offered(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """On dev the Finder offered two Data Catalog rows it rated 25 and 15,
        "not branch data": the map's context, which the check then loaded as
        the branches. A row rated under the floor is no candidate."""
        user, token = user_and_token
        # Titles the loader's goal does not name, so its Finder is asked.
        districts = _a_dataset(user, "Police districts")
        offices = _a_dataset(user, "Ward offices")
        reply = json.dumps({"datasetCandidates": {"lanes": {
            "external": [{"name": "CPL branches", "sourceType": "portal", "url": "https://data.example.org/areas.geojson",
                          "fit": {"score": 85, "rationale": "the branches"}}],
            "catalog": [
                {"name": "Police districts", "sourceType": "catalog", "datasetId": districts,
                 "fit": {"score": 25, "rationale": "not branch data"}},
                {"name": "Ward offices", "sourceType": "catalog", "datasetId": offices,
                 "fit": {"score": 15, "rationale": "not branch data"}},
            ],
        }}})
        h = _Harness(client, user, token, monkeypatch, discover_replies=[reply])
        h.validate("load")
        card = _cards(h, h.finder_attachment_id())[-1]
        assert {lane: [row["name"] for row in rows] for lane, rows in card["lanes"].items()} == {
            "external": ["CPL branches"], "catalog": [],
        }, card["lanes"]

    def test_a_card_the_floor_empties_leaves_the_loader_its_rounds_and_its_finder_asked_once_a_pass(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """When every row is rated under the floor there is nothing to pick:
        no card, and the loader keeps its own rounds and failure, as when the
        Finder found nothing. Its Finder is asked once each Solve pass, before
        the rounds, never after each of them."""
        user, token = user_and_token
        districts = _a_dataset(user, "Police districts")
        h = _Harness(client, user, token, monkeypatch,
                     discover_replies=[_catalog_candidates((districts, "Police districts", 20))],
                     dl_replies=['import pandas as pd\nreturn pd.read_csv("invented.csv")'])
        body = h.solve()
        assert _cards(h, h.finder_attachment_id()) == []
        load = body["results"][h.load]
        assert load["status"] == "failed" and "ungrounded-source" in load["error"], load
        assert len(h.discover_calls) >= 1
        assert len(h.discover_calls) * 3 == len(h.dl_calls), (len(h.discover_calls), len(h.dl_calls))

    def test_a_row_with_no_fit_is_still_offered(self, app, monkeypatch):
        """The floor is the Finder's own rating: a row it gave none is kept."""
        part = _minted(app, monkeypatch, {
            "external": [{"name": "Fetchable", "sourceType": "portal", "url": "https://data.example.org/rows.xml"}],
            "catalog": [],
        }, [])
        assert [row["name"] for row in part["lanes"]["external"]] == ["Fetchable"]

    def test_a_chats_own_card_drops_the_rows_rated_under_the_floor(self):
        """The Finder's own chat writes its card itself, checked as a delegated
        card is: a row rated under the floor goes, and a card it empties says
        why, not that the Data Catalog lacks the datasets."""
        kept = {"type": "datasetCandidates", "lanes": {"catalog": [], "external": [
            _external("Context", 30, url="https://data.example.org/portal"),
            _external("The data", 80, url="https://data.example.org/rows.xml"),
        ]}}
        emptied = {"type": "datasetCandidates", "lanes": {"catalog": [], "external": [
            _external("Context", 30, url="https://data.example.org/portal"),
        ]}}
        parts = [kept, emptied]
        grounding._ground_catalog_lanes(parts, lambda: [])
        assert [row["name"] for row in parts[0]["lanes"]["external"]] == ["The data"], parts[0]
        assert parts[1].get("type") == "card", parts[1]
        assert "Data Catalog" not in " ".join(parts[1].get("lines") or []), parts[1]
