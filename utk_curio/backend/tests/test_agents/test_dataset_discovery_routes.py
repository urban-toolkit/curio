"""dev/126: resolving a data-loading node INITIATES discovery.

The end-to-end shape the owner asked for: a plan is applied, each data-loading
node carries its own Dataset Finder, and Solve asks that agent for candidates
instead of letting the content builder guess a filename or decline into a dead
end. The node then WAITS for the user's selection — pending, with the remedy
naming the attachment to open — and a second Solve spends no model call.

Build & validate and a plan row's Solve wait for the source too: the run
pauses once at the loader and its row needs a source, until the pick puts the
row back and the next run builds it, once. The Finder's chat says who asked and
why, the listing says who waits for a pick, and only an agent the server lets
Solve a node says it can.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections import Counter

import pytest

from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application.solve import budgets
from utk_curio.backend.app.agents.application.turns import titles as services_mod
from utk_curio.backend.app.agents.domain.manifest import AgentManifestError
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.repositories import storage as agents_storage
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents.test_verified_rounds import TEMPLATES

DFB = "agent.curio.dataflow-builder@1"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/python-computation"

CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {
    "external": [{
        "name": "Chicago community areas", "sourceType": "portal",
        "url": "https://data.example.org/areas.geojson",
        "format": "geojson",
        "fit": {"score": 90, "rationale": "the boundaries the goal asks for"},
    }],
    "catalog": [],
}}})

#: The external row the Finder proposes, which a pick names by its url.
URL = "https://data.example.org/areas.geojson"

#: The probe's answer for a URL that serves data code can fetch and that Curio
#: does not download itself: a body read as JSON, with no content type a
#: Discovery Catalog source takes (``verify.classify_access``,
#: ``acquire._acquirable``). A pick of such a row starts the node's own builder.
FETCHABLE = {"status": "verified", "detail": "200 OK", "httpStatus": 200, "sampleKeys": ["type", "features"]}

#: Two loaders, neither reading from the other, a join of both, and a count of
#: the join.
TWO_LOADERS = {
    "goal": "compare parks and schools",
    "nodes": [
        {"ref": "parks", "nodeType": DL, "title": "Load parks", "intent": "load the city's parks"},
        {"ref": "schools", "nodeType": DL, "title": "Load schools", "intent": "load the city's schools"},
        {"ref": "join", "nodeType": CA, "title": "Join", "intent": "join the parks and the schools by area"},
        {"ref": "count", "nodeType": CA, "title": "Count", "intent": "count the schools near each park"},
    ],
    "edges": [{"from": "parks", "to": "join"}, {"from": "schools", "to": "join"}, {"from": "join", "to": "count"}],
}


def _sse_events(response) -> list[tuple[str, dict]]:
    """A streamed route's events, in order, as ``(event, data)``."""
    events = []
    for block in response.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class _Harness:
    """A project with an applied plan whose loader has NO grounded source.

    ``parent`` is the agent that plans and solves, the Dataflow Builder unless
    a test names another; ``prepare`` runs on the new project before it is
    installed. ``plan`` replaces the plan of one loader feeding one node: every
    loader of it is answered from ``dl_replies``. ``message`` is what the user
    asks the parent for, in its chat, before the plan lands."""

    def __init__(self, client, user, token, monkeypatch, *, goal=None,
                 discover_replies=None, dl_replies=None, parent=DFB, prepare=None, plan=None,
                 message="plan it"):
        self.client, self.user, self.token = client, user, token
        self.ukey = _user_dir_key(user)
        routes_proposals.TestNodeCreate()._write_builtin_package(self.ukey, templates=TEMPLATES)
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                "outputs": []}
        self.pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        if prepare is not None:
            prepare(self)
        client.post(f"/api/agents/projects/{self.pid}/install", json={"coord": parent},
                    headers=_auth(token))
        self.att = client.post(
            f"/api/agents/projects/{self.pid}/attachments",
            json={"coord": parent, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()["attachmentId"]
        self.discover_calls: list = []
        self.dl_calls: list = []
        # Every model call, whatever asked it, in order.
        self.model_calls: list = []
        plan = plan or {
            "goal": "compare community areas",
            "nodes": [
                {"ref": "load", "nodeType": DL, "title": "Load boundaries",
                 "intent": goal or "load the community area boundaries"},
                {"ref": "stats", "nodeType": CA, "title": "Stats", "intent": "compute density"},
            ],
            "edges": [{"from": "load", "to": "stats"}],
        }
        plan_reply = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"
        discover_script = list(discover_replies or [CANDIDATES])
        dl_script = list(dl_replies or ['import pandas as pd\nreturn pd.read_csv("areas.csv")'])

        def _fake_run(config, messages, **kwargs):
            self.model_calls.append(messages[-1].get("content") if messages else "")
            if messages and messages[0].get("content") == services_mod.title_prompt():
                return "Title"
            frame = messages[-1].get("content") or ""
            if "[delegated task" not in frame:
                return plan_reply
            if "discoveryReplyContract" in frame:
                self.discover_calls.append(frame)
                return discover_script[min(len(self.discover_calls) - 1, len(discover_script) - 1)]
            # A loader's OWN content call: nodeContext carries its nodeId
            # (an upstream row would carry it under "id" instead).
            if any(f'"nodeId": "{node_id}"' in frame for node_id in getattr(self, "loaders", ())):
                self.dl_calls.append(frame)
                return dl_script[min(len(self.dl_calls) - 1, len(dl_script) - 1)]
            return "df = input_0[0]\nreturn df.describe()"

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run
        )
        self.exec_payloads: list = []

        def _exec(endpoint, payload):
            self.exec_payloads.append(payload)
            return {"stdout": [], "stderr": "",
                    "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: {"status": "verified", "detail": "200 OK"},
        )
        r = client.post(f"/api/agents/projects/{self.pid}/attachments/{self.att}/run",
                        json={"message": message}, headers=_auth(token))
        # The plan landed with the reply; its nodes are what the reply hands a
        # canvas no doc binds.
        graph = routes_proposals._landed_plan(r.get_json())["canvas"]
        self.loaders = [n["id"] for n in graph["nodes"] if str(n["type"]).startswith(DL)]
        self.load = self.loaders[0]
        self.stats = next(n["id"] for n in graph["nodes"] if str(n["type"]).startswith(CA))

    def solve(self, node_ids=None):
        payload = {"nodeIds": node_ids} if node_ids else {}
        return self.client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/solve",
            json=payload, headers=_auth(self.token),
        ).get_json()

    def spec(self):
        return projects_storage.read_spec(self.ukey, self.pid)

    def finder_attachment_id(self, node_id=None):
        record = dr.finder_attachment(self.spec(), node_id or self.load)
        return (record or {}).get("attachmentId")

    def node_content(self, node_id):
        node = next(
            n for n in (self.spec().get("dataflow") or {}).get("nodes") or []
            if n.get("id") == node_id
        )
        return node.get("content") or ""

    def session_turns(self, attachment_id):
        return self.client.get(
            f"/api/agents/projects/{self.pid}/attachments/{attachment_id}/session",
            headers=_auth(self.token),
        ).get_json()["turns"]

    def record_selection(self, url):
        """Record the user's pick of the external row *url* the way the
        selection endpoint does (commit 6)."""
        finder_id = self.finder_attachment_id()
        spec = self.spec()
        part = next(
            p for t in self.session_turns(finder_id) for p in (t.get("content") or [])
            if p.get("type") == "datasetCandidates"
        )
        rows = dr.resolve_picks(part, [{"lane": "external", "key": url}])
        dr.record_selection(spec, finder_id, rows)
        projects_storage.write_spec(self.ukey, self.pid, spec)

    def recorded_urls(self):
        """The node's recorded source state and the URLs of its picks."""
        record = dr.source_record(self.spec(), self.load) or {}
        return record.get("status"), [p.get("url") for p in record.get("picks") or []]

    def node_builder_attachment_id(self, node_id=None):
        """A loader's own Node Builder: the agent on it that writes its code."""
        record = spec_reads._node_attachment_declaring(self.spec(), "node.content.generate", node_id or self.load)
        return (record or {}).get("attachmentId")

    def ref_ids(self):
        """Each plan ref's node, as the plan's agent keeps them."""
        record = attachments.get_attachment(self.spec(), self.att) or {}
        return dict((record.get("builderSession") or {}).get("nodeIds") or {})

    def _stream(self, path, body):
        r = self.client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/{path}",
            json=body, headers=_auth(self.token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        return _sse_events(r)

    def simulate(self, mode="auto"):
        """Build & validate over the landed plan, as the strip's button and
        Resume ask for it: its events, the done payload last."""
        return self._stream("simulate", {"mode": mode})

    def validate(self, ref):
        """A plan row's Solve: its events, the done payload last."""
        return self._stream("validate-node", {"ref": ref})

    def select(self, url, node_id=None):
        """The user's pick of the external row *url* on the card in a
        loader's Dataset Finder chat, through the route the card posts to."""
        r = self.client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.finder_attachment_id(node_id)}/dataset-selection",
            json={"picks": [{"lane": "external", "key": url}]}, headers=_auth(self.token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        return r.get_json()

    def cards(self):
        """The dataflow's agents as the canvas lists them, by attachment id."""
        r = self.client.get(f"/api/agents/projects/{self.pid}/attachments", headers=_auth(self.token))
        assert r.status_code == 200, r.get_data(as_text=True)
        return {card["attachmentId"]: card for card in r.get_json()["attachments"]}


#: How long a test waits for a request it runs on another thread: far longer
#: than any of these requests takes, so only one that hangs ends the test.
WAIT_S = 60


def _picks(h, url, node_id=None):
    """The user's pick of the external row *url* on the card of the Dataset
    Finder of *node_id* (the loader by default), as a request another tab
    makes: run it later, and it answers ``{"status", "body"}``."""
    finder = h.finder_attachment_id(node_id)

    def _pick():
        r = h.client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder}/dataset-selection",
            json={"picks": [{"lane": "external", "key": url}]}, headers=_auth(h.token),
        )
        return {"status": r.status_code, "body": r.get_json()}

    return _pick


def _clears(h, attachment_id):
    """Clearing the chat of *attachment_id*, as a request another tab makes."""

    def _clear():
        r = h.client.delete(
            f"/api/agents/projects/{h.pid}/attachments/{attachment_id}/session", headers=_auth(h.token),
        )
        return {"status": r.status_code, "body": r.get_json()}

    return _clear


def _start_on_a_thread(request, answer: dict, ended: threading.Event) -> threading.Thread:
    """Run *request* on a thread of its own, as another tab's request runs:
    its answer goes into *answer*, and *ended* is set when it ends, however it
    ends."""

    def _run():
        try:
            answer.update(request())
        finally:
            answer["ended"] = True
            ended.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def _during_the_discovery_of(h, monkeypatch, node_id, request) -> dict:
    """Run *request* while the Dataset Finder of *node_id* is asked for
    candidates: in the middle of a Build & validate pass, between two of its
    writes. It runs on a thread of its own while the pass waits for it, so
    one thread runs at a time. Returns its answer, filled once it ran."""
    ask = providers.run_chat_turn
    answer: dict = {}

    def _asked(config, messages, **kwargs):
        frame = (messages[-1].get("content") or "") if messages else ""
        if not answer and "discoveryReplyContract" in frame and f'"nodeId": "{node_id}"' in frame:
            ended = threading.Event()
            _start_on_a_thread(request, answer, ended)
            assert ended.wait(WAIT_S), "the request on the other thread never ended"
        return ask(config, messages, **kwargs)

    monkeypatch.setattr(providers, "run_chat_turn", _asked)
    return answer


class _InsideAWrite:
    """Run *request* inside the next write of the dataflow that the test's
    own thread makes and *when* accepts: after that writer read the dataflow
    and before its write lands, as a request of another tab can.

    One thread runs at a time. When the writer holds the dataflow's spec lock
    there, the request runs until it asks for that lock, the write lands, and
    the request ends once the writer lets the lock go, before the writer goes
    on. When the writer does not hold it, the whole request ends before the
    write lands."""

    def __init__(self, monkeypatch, request, when=lambda spec: True):
        self.request, self.when = request, when
        self.main = threading.current_thread()
        self.thread: threading.Thread | None = None
        self.asked, self.ended = threading.Event(), threading.Event()
        self.answer: dict = {}
        self.armed = False
        self.waits_for_the_lock = False
        write, lock = dataflow_docs.write, projects_storage.spec_write_lock

        def _write(user_key, project_id, spec, actor, **kwargs):
            if self.armed and threading.current_thread() is self.main and self.when(spec):
                self.armed = False
                self._run(held=projects_storage.holds_spec_lock(user_key, project_id))
            return write(user_key, project_id, spec, actor, **kwargs)

        @contextlib.contextmanager
        def _lock(user_key, project_id):
            if self.thread is not None and threading.current_thread() is self.thread:
                self.asked.set()
            with lock(user_key, project_id):
                yield
            if self.waits_for_the_lock and threading.current_thread() is self.main:
                self.waits_for_the_lock = False
                assert self.ended.wait(WAIT_S), "the request inside the write never ended"

        monkeypatch.setattr(dataflow_docs, "write", _write)
        monkeypatch.setattr(projects_storage, "spec_write_lock", _lock)

    def arm(self):
        """Run the request inside the next write *when* accepts."""
        self.armed = True

    def _run(self, *, held: bool) -> None:
        def _request():
            # Known as the request's thread before it asks for any lock.
            self.thread = threading.current_thread()
            try:
                return self.request()
            finally:
                # A request that never asks for the lock does not keep the
                # writer waiting for its ask.
                self.asked.set()

        _start_on_a_thread(_request, self.answer, self.ended)
        if held:
            assert self.asked.wait(WAIT_S), "the request never asked for the spec lock"
            self.waits_for_the_lock = True
        else:
            assert self.ended.wait(WAIT_S), "the request never ended"


def _pausing_for_a_source(attachment_id):
    """Whether a spec being written pauses the plan of *attachment_id* for a
    loader's source."""

    def _when(spec):
        session = (attachments.get_attachment(spec, attachment_id) or {}).get("builderSession") or {}
        return (session.get("pauseReason") or {}).get("kind") == "awaiting-source"

    return _when


def _validating(attachment_id):
    """Whether a spec being written marks a validation of a node of the plan
    of *attachment_id* as running."""

    def _when(spec):
        session = (attachments.get_attachment(spec, attachment_id) or {}).get("builderSession") or {}
        return bool(session.get("validatingSince"))

    return _when


class TestDiscoveryIsInitiated:
    def test_a_loader_the_project_cannot_ground_ends_awaiting_the_selection(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The end of the old dead end. Nothing names the loader's source: its
        own Dataset Finder is asked before its builder writes anything, and
        the node ends PENDING with candidates awaiting the user and the remedy
        naming the chat to open. A loader whose rounds were refused for their
        source first keeps their trail
        (``test_a_loader_with_no_finder_of_its_own_tries_before_a_finder_is_asked``)."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        body = h.solve()
        load = body["results"][h.load]
        # PENDING, never failed: nothing was generated, run or written.
        assert load["status"] == "pending"
        assert load["reason"].startswith("awaiting your dataset selection")
        assert load["remedy"]["kind"] == "dataset-selection"
        assert load["remedy"]["nodeId"] == h.load
        assert load["attempts"] == []
        assert h.dl_calls == []  # its builder was never asked
        assert h.exec_payloads == []  # nothing ungrounded ever ran
        assert h.node_content(h.load) == ""
        # The candidates live in the node's OWN Dataset Finder chat.
        finder_id = h.finder_attachment_id()
        assert finder_id and load["remedy"]["attachmentId"] == finder_id
        parts = [
            p for t in h.session_turns(finder_id) for p in (t.get("content") or [])
            if p.get("type") == "datasetCandidates"
        ]
        assert len(parts) == 1
        row = parts[0]["lanes"]["external"][0]
        assert row["name"] == "Chicago community areas"
        assert row["verification"]["status"] == "verified"
        # And the state is recorded on that attachment.
        record = dr.source_record(h.spec(), h.load)
        assert record["status"] == dr.STATE_CANDIDATES_PENDING
        assert record["candidates"] == 1
        # The dependent waits for the loader rather than running on nothing.
        assert body["results"][h.stats]["status"] == "pending"

    def test_a_second_solve_spends_no_model_call(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        assert len(h.discover_calls) == 1
        content_calls = len(h.dl_calls)
        again = h.solve()
        assert again["results"][h.load]["status"] == "pending"
        assert again["results"][h.load]["attempts"] == []  # nothing was attempted
        assert len(h.discover_calls) == 1  # no second delegation, no duplicate card
        assert len(h.dl_calls) == content_calls  # and no second generation
        parts = [
            p for t in h.session_turns(h.finder_attachment_id())
            for p in (t.get("content") or []) if p.get("type") == "datasetCandidates"
        ]
        assert len(parts) == 1

    def test_the_finders_mission_joins_its_parts_with_plain_punctuation(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The mission the Dataset Finder is handed is the node's goal, then
        the dataflow's goal, joined with "; ". On main they were joined with an
        em dash, which the Finder's chat now shows."""
        from utk_curio.backend.app.collaboration import dataflow_docs

        def with_a_goal(h):
            spec = dataflow_docs.live(h.ukey, h.pid)
            spec["dataflow"]["task"] = "Compare community areas"
            dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "edit"))

        missions: list = []
        initiate = dr.initiate
        monkeypatch.setattr(dr, "initiate", lambda *a, **k: (missions.append(k.get("mission") or ""), initiate(*a, **k))[1])
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, prepare=with_a_goal)
        h.solve()
        dataflow = h.spec()["dataflow"]
        goal = next(n for n in dataflow["nodes"] if n.get("id") == h.load).get("goal")
        task = dataflow.get("task")
        assert goal and task, (goal, task)
        assert missions == [f"{goal}; {task}"], missions

    def test_clearing_the_finders_chat_while_its_candidates_wait_asks_for_them_again(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Clearing the Dataset Finder's chat takes its candidates card away,
        so nothing is left to pick from: the node is unresolved again, and the
        next Solve asks the Finder for candidates again. On main the node kept
        waiting for a pick with no card left to answer, and no Solve asked the
        Finder again."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        finder = h.finder_attachment_id()
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_CANDIDATES_PENDING
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert dr.node_source_state(h.spec(), h.load)["state"] == dr.STATE_UNRESOLVED
        again = h.solve()
        assert len(h.discover_calls) == 2
        assert again["results"][h.load]["status"] == "pending"
        parts = [
            p for t in h.session_turns(finder)
            for p in (t.get("content") or []) if p.get("type") == "datasetCandidates"
        ]
        assert len(parts) == 1

    def test_a_goal_that_names_a_path_skips_discovery_and_records_why(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch,
            goal="load /data/community_areas.csv from disk",
            dl_replies=['import pandas as pd\nreturn pd.read_csv("/data/community_areas.csv")'],
        )
        body = h.solve()
        assert h.discover_calls == []
        assert body["results"][h.load]["status"] == "solved"
        record = dr.source_record(h.spec(), h.load)
        assert record["status"] == dr.STATE_NOT_NEEDED
        assert record["skippedBecause"] == "/data/community_areas.csv"

    def test_discovery_that_finds_nothing_keeps_the_nodes_own_failure(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """"Awaiting your selection" would be a lie when there is nothing to
        select: the node keeps its own honest outcome and the discovery attempt
        rides along as the reason. The Finder, asked before the rounds, is not
        asked again after them: each of the session's two passes asks it once,
        before its 3 rounds."""
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch,
            discover_replies=["No source covers that."],
            dl_replies=['import pandas as pd\nreturn pd.read_csv("invented.csv")'],
        )
        body = h.solve()
        load = body["results"][h.load]
        assert load["status"] == "failed"
        assert "ungrounded-source" in load["error"]
        assert "invented.csv" in load["error"]
        assert all(a["kind"] == "ungrounded-source" for a in load["attempts"])
        assert len(h.discover_calls) * 3 == len(h.dl_calls), (len(h.discover_calls), len(h.dl_calls))
        assert len(h.discover_calls) >= 1

    def test_the_finders_task_names_the_builder_and_its_mission(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Dataset Finder's chat says who asked it for a source and why:
        the task the runtime records there names the agent whose Solve asked,
        as its manifest names it, and the mission the candidates are for. On
        main it named the agent's id and the capability alone."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.solve()
        asked = [t.get("text") or "" for t in h.session_turns(h.finder_attachment_id()) if t.get("role") == "user"]
        assert len(asked) == 1, asked
        assert asked[0].startswith("[Delegated by Dataflow Builder] dataset.discover"), asked[0]
        # The mission starts with the loader's goal: its title, then its intent.
        assert "mission: Load boundaries" in asked[0], asked[0]
        assert "load the community area boundaries" in asked[0], asked[0]

    def test_the_candidates_reach_the_chat_that_asked(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The candidates the Dataset Finder found reach the chat whose Solve
        or Build & validate asked for them, here the Dataflow Builder's, by its
        plan row's Solve: one line that names the node and its Finder, and the
        card, whose pick posts on the Finder's own route. The line is in the
        Builder's model context, so the Builder knows candidates wait; the card
        is not. The Finder's chat still holds its one card, and the loader's
        Node Builder, which asked nothing, holds none. On main the candidates
        reached the Finder's chat alone."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder = h.finder_attachment_id()
        cards = [
            p for t in h.session_turns(finder) for p in (t.get("content") or [])
            if p.get("type") == "datasetCandidates"
        ]
        assert len(cards) == 1, cards
        builder_turns = h.session_turns(h.att)
        asked = [
            (t, p) for t in builder_turns for p in (t.get("content") or [])
            if p.get("type") == "sourcePick"
        ]
        assert len(asked) == 1, [t.get("text") for t in builder_turns]
        turn, part = asked[0]
        assert (part["finderAttachmentId"], part["nodeId"], part["nodeLabel"]) == (
            finder, h.load, "Load boundaries",
        ), part
        assert part["lanes"] == cards[0]["lanes"]
        assert "Load boundaries" in turn["text"] and "Dataset Finder" in turn["text"], turn["text"]
        assert "Use this source" in turn["text"], turn["text"]
        # The line reaches the Builder's model; the card does not.
        context = "\n".join(m["content"] for m in sessions.context_messages(builder_turns))
        assert turn["text"] in context, context
        assert URL not in context and "sourcePick" not in context, context
        assert not [
            p for t in h.session_turns(h.node_builder_attachment_id()) for p in (t.get("content") or [])
            if p.get("type") in ("sourcePick", "datasetCandidates")
        ], "the loader's Node Builder asked for no candidates"

    @pytest.mark.parametrize("found, words", [(1, "1 candidate"), (3, "3 candidates")])
    def test_the_finders_chat_counts_its_candidates_and_names_the_node(
        self, client, user_and_token, tmp_curio, monkeypatch, found, words
    ):
        """The Dataset Finder's chat says in plain words how many candidates
        it found, for which node, and how to pick one, and the loader's row
        counts them the same way. On 7430c0d5a4 the Finder's chat said "1
        dataset candidate(s) for this node: pick the source to use with Use
        this source; external rows carry the runtime's verification verdict.",
        which never counted, named no node and spoke of the runtime, and the
        row's reason said "1 candidate(s)". The line in the chat that asked
        already counted and named the node: it is a guard here."""
        rows = [{
            "name": f"Chicago community areas {i}", "sourceType": "portal",
            "url": f"https://data.example.org/areas-{i}.geojson", "format": "geojson",
            "fit": {"score": 90, "rationale": "the boundaries the goal asks for"},
        } for i in range(found)]
        candidates = json.dumps({"datasetCandidates": {"lanes": {"external": rows, "catalog": []}}})
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=[candidates])
        body = h.solve()
        said = {
            "the Finder's chat": [
                t.get("text") for t in h.session_turns(h.finder_attachment_id())
                if any(p.get("type") == "datasetCandidates" for p in t.get("content") or [])
            ],
            "the chat that asked": [
                t.get("text") for t in h.session_turns(h.att)
                if any(p.get("type") == "sourcePick" for p in t.get("content") or [])
            ],
            "the loader's row": body["results"][h.load]["reason"],
        }
        # One comparison, so a failure shows every place that reads wrong.
        assert said == {
            "the Finder's chat": [f"I found {words} for Load boundaries. Pick one with Use this source."],
            "the chat that asked": [
                f"**Load boundaries** needs a source. Its Dataset Finder found {words}: pick one with Use this source."
            ],
            "the loader's row": f"awaiting your dataset selection: {words} awaiting your selection",
        }


class TestConfirmedSourceReachesTheBuilder:
    def test_a_recorded_selection_resolves_the_node_and_is_handed_over(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        # Nothing names the source, so the Finder is asked before any round
        # and candidates land; then the code that loads the confirmed URL.
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[
                ("import pandas as pd\nreturn pd.read_json"
                 '("https://data.example.org/areas.geojson")'),
            ],
        )
        assert h.solve()["results"][h.load]["status"] == "pending"
        assert h.dl_calls == []  # no round before the pick
        h.record_selection("https://data.example.org/areas.geojson")
        body = h.solve(node_ids=[h.load])
        load = body["results"][h.load]
        assert load["status"] == "solved", load
        assert len(h.dl_calls) == 1  # built from its first round
        # The confirmed source was HANDED to the content child.
        frame = h.dl_calls[-1]
        assert "confirmedSource" in frame
        assert "https://data.example.org/areas.geojson" in frame
        assert len(h.discover_calls) == 1  # resolved: no second discovery
        # And the selection is still the node's source after the Solve that used it.
        assert h.recorded_urls() == (
            dr.STATE_RESOLVED, ["https://data.example.org/areas.geojson"]
        )

    def test_rounds_that_miss_the_confirmed_source_keep_the_selection(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Solve after the selection starts with rounds whose code does not
        load the confirmed source: on a loaded runner the old one-second session
        cut the first Solve short, so the second read an ungrounded reply. Those
        rounds fail at the gate, the node keeps its selection instead of being
        sent back to discovery, and the session's next pass builds the loader
        from the same source."""
        user, token = user_and_token
        url = "https://data.example.org/areas.geojson"
        invented = 'import pandas as pd\nreturn pd.read_csv("invented.csv")'
        # No round in the first Solve, which asks the Finder first; three
        # ungrounded attempts in the first pass after the selection, then the
        # code that loads the confirmed URL.
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[invented] * 3 + [f'import pandas as pd\nreturn pd.read_json("{url}")'],
        )
        assert h.solve()["results"][h.load]["status"] == "pending"
        assert h.dl_calls == []
        h.record_selection(url)
        body = h.solve(node_ids=[h.load])
        load = body["results"][h.load]
        assert load["status"] == "solved", load
        assert [a["kind"] for a in load["attempts"][:3]] == ["ungrounded-source"] * 3
        # Every round, all after the selection, was handed the confirmed source.
        assert len(h.dl_calls) > 3
        for frame in h.dl_calls:
            assert "confirmedSource" in frame
            assert url in frame
        assert len(h.discover_calls) == 1  # no second discovery, no second card
        assert h.recorded_urls() == (dr.STATE_RESOLVED, [url])


class TestSelectionEndpoint:
    """dev/126: the client sends KEYS; the server resolves them against the
    candidates it proposed itself."""

    def _await_candidates(self, client, user, token, monkeypatch, **kw):
        h = _Harness(client, user, token, monkeypatch, **kw)
        h.solve()
        return h, h.finder_attachment_id()

    def _select(self, h, finder_id, picks):
        return h.client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder_id}/dataset-selection",
            json={"picks": picks}, headers=_auth(h.token),
        )

    def test_a_confirmed_external_row_is_recorded_and_re_probed(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = self._await_candidates(client, user, token, monkeypatch)
        probed: list = []
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: (probed.append(url), {"status": "verified", "detail": "200"})[1],
        )
        r = self._select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ])
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body["status"] == dr.STATE_RESOLVED
        assert body["nodeId"] == h.load
        assert probed == ["https://data.example.org/areas.geojson"]  # re-probed NOW
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        turn = next(
            t for t in reversed(h.session_turns(finder_id))
            if (t.get("text") or "").startswith("Source recorded")
        )
        assert "Chicago community areas" in turn["text"]

    def test_a_key_the_runtime_never_proposed_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = self._await_candidates(client, user, token, monkeypatch)
        r = self._select(h, finder_id, [
            {"lane": "external", "key": "https://evil.example.net/steal.json"},
        ])
        assert r.status_code == 422
        assert "not a external candidate" in r.get_json()["error"]
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_CANDIDATES_PENDING

    def test_an_unreachable_pick_does_not_resolve_the_node(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = self._await_candidates(client, user, token, monkeypatch)
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: {"status": "unreachable", "detail": "404"},
        )
        body = self._select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["status"] == dr.STATE_CANDIDATES_PENDING
        assert body["picks"][0]["verification"]["status"] == "unreachable"

    def test_a_selection_on_the_wrong_attachment_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, _finder_id = self._await_candidates(client, user, token, monkeypatch)
        r = self._select(h, h.att, [{"lane": "external", "key": "x"}])
        assert r.status_code == 400
        assert "Dataset Finder attachment" in r.get_json()["error"]
        assert self._select(h, "ghost", [{"lane": "external", "key": "x"}]).status_code == 404

    def test_the_body_must_carry_picks(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = self._await_candidates(client, user, token, monkeypatch)
        r = h.client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder_id}/dataset-selection",
            json={}, headers=_auth(h.token),
        )
        assert r.status_code == 400
        assert "picks" in r.get_json()["error"]


class TestAttemptTrailInTheTranscript:
    """dev/127: the owner's requirement — every attempt to fix a node is IN the
    chat transcript, with the code it ran, and it is still there after a reload.
    """

    def _turn_parts(self, h, attachment_id, part_type):
        return [
            p for t in h.session_turns(attachment_id)
            for p in (t.get("content") or []) if p.get("type") == part_type
        ]

    def test_a_failed_node_leaves_its_whole_trail_on_the_solve_turn(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        # A loader whose code the gate refuses three times: three attempts,
        # each with its own code. Discovery finds nothing, so the node keeps
        # its own failure (dev/126) and the trail is what explains it.
        h = _Harness(
            client, user, token, monkeypatch,
            goal="load /data/areas.csv from disk",
            discover_replies=["no source covers that"],
            dl_replies=[
                'import pandas as pd\nreturn pd.read_csv("guess1.csv")',
                'import pandas as pd\nreturn pd.read_csv("guess2.csv")',
                'import pandas as pd\nreturn pd.read_csv("guess3.csv")',
            ],
        )
        body = h.solve()
        assert body["results"][h.load]["status"] == "failed"
        parts = self._turn_parts(h, h.att, "solveAttempts")
        trail = next(p for p in parts if p["nodeId"] == h.load)
        assert trail["verdict"] == "fail"
        assert trail["stoppedBy"] in ("rounds", "budget", "repeat")
        # dev/131: the session's trail spans passes; the part carries the most
        # recent rows and counts the rest (``elided``), and every row it does
        # carry has its round, its error and its CODE.
        recorded = body["results"][h.load]["attempts"]
        assert len(trail["attempts"]) == min(len(recorded), content.SOLVE_ATTEMPTS_MAX_ROWS)
        assert trail.get("elided", 0) == max(len(recorded) - content.SOLVE_ATTEMPTS_MAX_ROWS, 0)
        for row in trail["attempts"]:
            assert row["code"] and "guess" in row["code"]
            assert row["error"]
            assert row["kind"] == "ungrounded-source"
        # And the node's own agent is one click away.
        assert trail["attachmentId"]
        assert trail["label"].startswith("Load boundaries")

    def test_the_trail_survives_a_reload(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch,
            goal="load /data/areas.csv from disk",
            dl_replies=['import pandas as pd\nreturn pd.read_csv("nope.csv")'],
        )
        h.solve()
        # Re-read the session the way the panel does on open.
        parts = self._turn_parts(h, h.att, "solveAttempts")
        assert parts and parts[0]["attempts"][0]["code"]

    def test_a_solved_node_leaves_no_trail_part(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch,
            goal="load /data/community_areas.csv from disk",
            dl_replies=['import pandas as pd\nreturn pd.read_csv("/data/community_areas.csv")'],
        )
        body = h.solve()
        assert body["results"][h.load]["status"] == "solved"
        trails = [p for p in self._turn_parts(h, h.att, "solveAttempts")
                  if p["nodeId"] == h.load]
        assert trails == []

    def test_an_awaiting_source_node_shows_what_it_tried(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        # dev/126's lane: the goal names a path, so the rounds run first, and
        # the builder misses it. The rounds that were refused before discovery
        # ran are attempts too, and the owner asked for ALL of them.
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, goal="load /data/areas.csv from disk")
        h.solve()
        trail = next(
            p for p in self._turn_parts(h, h.att, "solveAttempts") if p["nodeId"] == h.load
        )
        assert trail["stoppedBy"] == "source"
        assert trail["attempts"] and all(r.get("code") for r in trail["attempts"])


class TestBuildAndValidateWaitsForTheSource:
    """Build & validate and a plan row's Solve stop at a loader that waits for
    the user to pick its source in its Dataset Finder's chat.

    The run goes on past such a loader to every node that does not read from
    it, so each loader's Finder is asked in the same pass, and pauses once,
    when no node can go on, naming every loader that waits; their rows need a
    source. A Resume while the candidates still wait asks no model and adds no
    turn to any chat. The pick puts the row back and starts nothing beside the
    plan, and the next Build & validate builds the loader from that source,
    once. On main the run validated the first loader again and again, each
    pass a turn in its Node Builder chat, until its action cap (500 in Curio,
    six here)."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_auto_pauses_once_on_a_loader_awaiting_its_source(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        events = h.simulate("auto")
        done = events[-1][1]
        reason = done.get("reason") or {}
        assert (done.get("status"), reason.get("kind")) == ("paused", "awaiting-source"), done
        assert reason.get("nodes") == [
            {"ref": "load", "nodeId": h.load, "attachmentId": h.finder_attachment_id()},
        ], reason
        # It names the node; the strip ends it with how to go on.
        assert "Load boundaries" in reason["message"], reason
        assert not reason["message"].rstrip(" .").endswith("Resume"), reason
        # One validation of the loader, one discovery, nothing downstream.
        assert [p["ref"] for kind, p in events if kind == "action_result"] == ["load"]
        assert len(h.discover_calls) == 1
        session = done["builderSession"]
        assert session["nodeStates"] == {"load": "awaiting-source", "stats": "created"}
        assert session["pauseReason"] == reason
        # The Finder was asked before the loader's builder, which nothing
        # asked: no Solve was handed to it.
        asked = [
            t.get("text") for t in h.session_turns(h.node_builder_attachment_id())
            if (t.get("text") or "").startswith("[Delegated by")
        ]
        assert asked == [], asked
        assert h.dl_calls == []
        assert h.node_content(h.load) == h.node_content(h.stats) == ""

    def test_a_rows_solve_leaves_the_row_needing_a_source(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "awaiting-source", done
        assert done["builderSession"]["nodeStates"].get("load") == "awaiting-source"
        # What the row reads once its chat lists the agents again.
        assert h.cards()[h.att]["builderSession"]["nodeStates"].get("load") == "awaiting-source"

    def test_resume_while_the_source_is_pending_pauses_again_with_no_model_call(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        first = h.simulate("auto")[-1][1]
        assert (first.get("reason") or {}).get("kind") == "awaiting-source", first
        chats = (h.att, h.node_builder_attachment_id(), h.finder_attachment_id())
        turns = {chat: len(h.session_turns(chat)) for chat in chats}
        calls = len(h.model_calls)
        events = h.simulate("auto")
        done = events[-1][1]
        reason = done.get("reason") or {}
        assert (done.get("status"), reason.get("kind"), [n.get("ref") for n in reason.get("nodes") or []]) == (
            "paused", "awaiting-source", ["load"],
        ), done
        assert h.model_calls[calls:] == []
        # No chat gained a turn: the loader was not handed to its Node Builder
        # again.
        assert {chat: len(h.session_turns(chat)) for chat in chats} == turns
        assert done["builderSession"]["nodeStates"]["load"] == "awaiting-source"
        assert len(h.discover_calls) == 1

    def test_the_pick_puts_the_row_back_and_resume_builds_it_from_the_source(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The picked row serves data code can fetch, so on main the pick
        started the loader's own builder on it beside the plan, which the next
        Build & validate then built again."""
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[f'import pandas as pd\nreturn pd.read_json("{URL}")'],
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(FETCHABLE),
        )
        started: list = []
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.solve.node_solve.solve_node_stream",
            lambda *a, **k: started.append(k.get("node_id")),
        )
        h.simulate("auto")
        assert h.recorded_urls()[0] == dr.STATE_CANDIDATES_PENDING
        tried = len(h.dl_calls)
        assert tried == 0, "the loader's builder was asked before its Finder"
        picked = h.select(URL)
        assert picked["status"] == dr.STATE_RESOLVED, picked
        delegated = picked.get("delegated") or {}
        assert delegated.get("status") == "plan-waiting", picked
        assert started == [], "the pick started the loader's builder beside the plan"
        assert (delegated.get("attachmentId"), delegated.get("nodeId")) == (h.att, h.load)
        assert "Dataflow Builder" in delegated["reason"], delegated
        # The row is back, nothing pauses at it, and nothing was built.
        session = h.cards()[h.att]["builderSession"]
        assert session["nodeStates"]["load"] == "created"
        assert "pauseReason" not in session
        assert len(h.dl_calls) == tried
        assert h.node_content(h.load) == ""
        # The next Build & validate builds it from the source, once, and goes
        # on with the plan.
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "completed", done
        assert set(done["builderSession"]["nodeStates"].values()) == {"approved"}
        assert len(h.dl_calls) == tried + 1
        assert "confirmedSource" in h.dl_calls[-1] and URL in h.dl_calls[-1]
        assert URL in h.node_content(h.load)
        assert started == []

    def test_auto_goes_on_past_a_waiting_loader_and_pauses_once_for_both(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Two loaders, neither reading from the other: the run asks each
        one's Dataset Finder in the same pass, then pauses once, naming both,
        while the nodes that read from them wait. On main it asked the first
        loader again and again and never reached the second."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        ids = h.ref_ids()
        calls = len(h.model_calls)
        events = h.simulate("auto")
        done = events[-1][1]
        reason = done.get("reason") or {}
        assert [p["ref"] for kind, p in events if kind == "action_result"] == ["parks", "schools"], done
        assert (done.get("status"), reason.get("kind")) == ("paused", "awaiting-source"), done
        assert reason.get("nodes") == [
            {"ref": ref, "nodeId": ids[ref], "attachmentId": h.finder_attachment_id(ids[ref])}
            for ref in ("parks", "schools")
        ], reason
        assert "Load parks" in reason["message"] and "Load schools" in reason["message"], reason
        assert len(h.discover_calls) == 2
        # One pass of models: each loader's Finder, asked before its builder,
        # and nothing asked for the loaders' builders or the nodes that read
        # from them.
        assert h.dl_calls == []
        assert len(h.model_calls) - calls == len(h.discover_calls)
        session = done["builderSession"]
        assert session["nodeStates"] == {
            "parks": "awaiting-source", "schools": "awaiting-source", "join": "created", "count": "created",
        }
        assert session["pauseReason"] == reason
        assert [h.node_content(ids[ref]) for ref in ("parks", "schools", "join", "count")] == [""] * 4

    def test_step_goes_on_past_a_waiting_loader(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Step does one action at a time, and passes over a loader that
        already waits for its source without asking anyone: the second step
        asks the second loader's Finder, then pauses naming both, and a third
        only pauses again."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        first = h.simulate("step")[-1][1]
        assert (first.get("status"), first.get("nextAction")) == (
            "stepped", {"action": "validate", "ref": "schools"},
        ), first
        assert first["builderSession"]["nodeStates"]["parks"] == "awaiting-source"
        events = h.simulate("step")
        second = events[-1][1]
        assert [p["ref"] for kind, p in events if kind == "action_result"] == ["parks", "schools"]
        assert (second.get("status"), [n.get("ref") for n in (second.get("reason") or {}).get("nodes") or []]) == (
            "paused", ["parks", "schools"],
        ), second
        assert len(h.discover_calls) == 2
        calls = len(h.model_calls)
        third = h.simulate("step")[-1][1]
        assert (third.get("status"), [n.get("ref") for n in (third.get("reason") or {}).get("nodes") or []]) == (
            "paused", ["parks", "schools"],
        ), third
        assert h.model_calls[calls:] == []

    def test_a_pick_for_one_of_two_waiting_loaders_leaves_the_other_waiting(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        ids = h.ref_ids()
        h.simulate("auto")
        picked = h.select(URL, ids["parks"])
        delegated = picked.get("delegated") or {}
        assert (delegated.get("status"), delegated.get("nodeId")) == ("plan-waiting", ids["parks"]), picked
        session = h.cards()[h.att]["builderSession"]
        assert (session["nodeStates"]["parks"], session["nodeStates"]["schools"]) == ("created", "awaiting-source")
        reason = session.get("pauseReason") or {}
        assert [n.get("ref") for n in reason.get("nodes") or []] == ["schools"], reason
        assert "Load schools" in reason["message"] and "Load parks" not in reason["message"], reason

    def test_a_pick_while_auto_runs_is_built_by_the_same_run(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The user picks the source of a loader the running pass already
        found waiting, while the pass asks the other loader's Dataset Finder.
        The same pass builds the picked loader from its source, then pauses
        naming only the loader still waiting, and the pick's card says the
        running Build & validate builds it. On main the pass held the picked
        loader to its end and paused naming it: its row read Placed while the
        strip said it needed a source, and the card named Build & validate
        plan while the strip's button read Resume."""
        user, token = user_and_token
        h = _Harness(
            client, user, token, monkeypatch, plan=TWO_LOADERS,
            dl_replies=[f'import pandas as pd\nreturn pd.read_json("{URL}")'],
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(FETCHABLE),
        )
        started: list = []
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.solve.node_solve.solve_node_stream",
            lambda *a, **k: started.append(k.get("node_id")),
        )
        ids = h.ref_ids()
        picked = _during_the_discovery_of(h, monkeypatch, ids["schools"], _picks(h, URL, ids["parks"]))
        events = h.simulate("auto")
        done = events[-1][1]
        assert picked.get("status") == 200, picked
        delegated = (picked.get("body") or {}).get("delegated") or {}
        assert delegated.get("status") == "plan-waiting", picked
        assert "Build & validate, running now, builds the loader" in delegated.get("reason", ""), delegated
        # The running pass builds it: nothing more is to start after the pick.
        assert (delegated.get("running"), delegated.get("continueWith")) == ("auto", None), delegated
        assert [(p["action"], p["ref"]) for kind, p in events if kind == "action_result"] == [
            ("validate", "parks"), ("validate", "schools"), ("validate", "parks"), ("approve", "parks"),
        ], done
        reason = done.get("reason") or {}
        assert (done.get("status"), [n.get("ref") for n in reason.get("nodes") or []]) == (
            "paused", ["schools"],
        ), done
        assert "Load schools" in reason["message"] and "Load parks" not in reason["message"], reason
        assert done["builderSession"]["nodeStates"] == {
            "parks": "approved", "schools": "awaiting-source", "join": "created", "count": "created",
        }
        # Built from its first round: no loader's builder was asked before its pick.
        assert len(h.dl_calls) == 1, len(h.dl_calls)
        assert "confirmedSource" in h.dl_calls[-1] and URL in h.dl_calls[-1]
        assert URL in h.node_content(ids["parks"])
        assert started == [], "the pick started the loader's builder beside the plan"

    def test_a_finders_chat_cleared_while_auto_runs_is_asked_again_by_the_same_run(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The user clears the chat of a loader's Dataset Finder, whose card
        the running pass left waiting, while the pass asks the other loader's
        Finder. No card is left to answer, so the same pass asks that Finder
        again, and the pause it ends on names both loaders, each with a card in
        its Finder's chat. On main the pass held the loader to its end and
        paused saying its Finder's chat asked for it, a chat that held no card
        any more."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        ids = h.ref_ids()
        parks_finder = h.finder_attachment_id(ids["parks"])
        cleared = _during_the_discovery_of(h, monkeypatch, ids["schools"], _clears(h, parks_finder))
        done = h.simulate("auto")[-1][1]
        assert cleared.get("status") == 200, cleared
        reason = done.get("reason") or {}
        assert (done.get("status"), sorted(n.get("ref") for n in reason.get("nodes") or [])) == (
            "paused", ["parks", "schools"],
        ), done
        assert len(h.discover_calls) == 3
        cards = [
            p for t in h.session_turns(parks_finder)
            for p in (t.get("content") or []) if p.get("type") == "datasetCandidates"
        ]
        assert len(cards) == 1, "the cleared Finder's chat holds no card to answer"

    def test_clearing_a_waiting_loaders_finder_chat_ends_the_plans_wait(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Clearing the chat of the Dataset Finder a paused plan waits on takes
        its card away: the plan waits for it no more, its row is placed again
        and the pause that named it ends. The next pass asks the Finder again.
        On main the row still needed a source and the pause still said the
        cleared chat asked for it."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.simulate("auto")
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        cards = h.cards()
        session = cards[h.att]["builderSession"]
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session
        assert (cards[h.att]["waitsForYou"], cards[finder]["waitsForYou"]) == ([], [])
        done = h.simulate("auto")[-1][1]
        assert [n.get("ref") for n in (done.get("reason") or {}).get("nodes") or []] == ["load"], done
        assert len(h.discover_calls) == 2

    def test_a_step_whose_recheck_asks_the_finder_again_does_nothing_else(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Step does one action. Checking a waiting loader again is free while
        its Dataset Finder's card still waits for a pick, so it is no action.
        Once that Finder is taken off, no card is left: the check asks a
        Finder for candidates anew, a model call and a new card, which is
        Step's one action. On main it counted as free, and the same Step went
        on to validate the other loader too."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        ids = h.ref_ids()
        first = h.simulate("step")[-1][1]
        assert first.get("nextAction") == {"action": "validate", "ref": "schools"}, first
        finder = h.finder_attachment_id(ids["parks"])
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        events = h.simulate("step")
        second = events[-1][1]
        assert [(p["action"], p["ref"]) for kind, p in events if kind == "action_result"] == [
            ("validate", "parks"),
        ], second
        assert (second.get("status"), second.get("nextAction")) == (
            "stepped", {"action": "validate", "ref": "schools"},
        ), second
        assert len(h.discover_calls) == 2


class TestTheChatThatAskedGoesOn:
    """After the user's pick, the chat that asked for the candidates says the
    source is recorded too, and the plan that waited for the loader goes on
    from that chat by itself: the pick's answer says how. Build & validate
    paused on the loader goes on with Build & validate, a plan row's Solve
    that left it waiting goes on with that row's Solve, and a Build & validate
    running now builds it with nothing more to start. On main the Source
    recorded turn was in the Finder's chat alone, and the answer told the user
    to continue in the Dataflow Builder's chat."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_a_pick_says_the_source_is_recorded_in_both_chats(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        h.select(URL)
        finder_said = [t.get("text") or "" for t in h.session_turns(h.finder_attachment_id())]
        # The Finder's chat names the node too, as the chat that asked does.
        assert finder_said[-1].startswith("Source recorded for Load boundaries: Chicago community areas."), finder_said[-1]
        builder_turns = h.session_turns(h.att)
        recorded = [t for t in builder_turns if (t.get("text") or "").startswith("Source recorded for Load boundaries")]
        assert len(recorded) == 1, [t.get("text") for t in builder_turns]
        assert "Chicago community areas" in recorded[0]["text"], recorded[0]["text"]
        card = next(p for p in recorded[0].get("content") or [] if p.get("type") == "card")
        assert card["title"] == "Dataset selection recorded", card
        assert any("Chicago community areas" in line for line in card["lines"]), card

    def test_a_pick_for_a_loader_build_and_validate_paused_on_goes_on_with_build_and_validate(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.simulate("auto")
        delegated = h.select(URL).get("delegated") or {}
        assert (delegated.get("status"), delegated.get("continueWith"), delegated.get("ref"), delegated.get("running")) == (
            "plan-waiting", "build", "load", None,
        ), delegated
        assert "continue in" not in delegated["reason"], delegated
        assert "Dataflow Builder goes on with its plan" in delegated["reason"], delegated

    def test_a_pick_for_a_loader_a_rows_solve_left_waiting_goes_on_with_that_rows_solve(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        delegated = h.select(URL).get("delegated") or {}
        assert (delegated.get("status"), delegated.get("continueWith"), delegated.get("ref"), delegated.get("running")) == (
            "plan-waiting", "node", "load", None,
        ), delegated
        assert "continue in" not in delegated["reason"], delegated


class TestAPickIsNeverLost:
    """A pick on a Dataset Finder's card writes the dataflow, and so does each
    step of Build & validate, a row's Solve and a cleared chat. Each of those
    reads the dataflow and writes it back under its spec lock, so a pick that
    lands between that read and that write is kept. Here the pick runs on a
    thread of its own inside that window, one thread at a time. On main those
    writers read without the lock, and their write put back the record the
    pick had changed: the agents' attachments are merged record by record."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_a_pick_that_lands_as_auto_pauses_is_kept(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        inside = _InsideAWrite(monkeypatch, _picks(h, URL), when=_pausing_for_a_source(h.att))
        inside.arm()
        done = h.simulate("auto")[-1][1]
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
        assert inside.answer.get("status") == 200, inside.answer
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        session = h.cards()[h.att]["builderSession"]
        # The pick put the row back and ended the pause that named it alone.
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session

    def test_a_pick_that_lands_as_a_rows_solve_starts_is_kept(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        ids = h.ref_ids()
        h.simulate("auto")
        inside = _InsideAWrite(monkeypatch, _picks(h, URL, ids["parks"]), when=_validating(h.att))
        inside.arm()
        done = h.validate("schools")[-1][1]
        assert done.get("verdict") == "awaiting-source", done
        assert inside.answer.get("status") == 200, inside.answer
        delegated = (inside.answer.get("body") or {}).get("delegated") or {}
        assert delegated.get("status") == "plan-waiting", inside.answer
        session = h.cards()[h.att]["builderSession"]
        assert (session["nodeStates"]["parks"], session["nodeStates"]["schools"]) == (
            "created", "awaiting-source",
        ), session
        assert [n.get("ref") for n in (session.get("pauseReason") or {}).get("nodes") or []] == ["schools"], session

    def test_a_pick_that_lands_as_the_asking_chat_is_cleared_is_kept(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Clearing the chat that asked for a loader's candidates changes the
        loader's Dataset Finder record: it asked no more. A pick an editor
        makes on that Finder's card at the same moment is kept."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        inside = _InsideAWrite(monkeypatch, _picks(h, URL))
        inside.arm()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{h.att}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert inside.answer.get("status") == 200, inside.answer
        record = dr.source_record(h.spec(), h.load) or {}
        assert record.get("status") == dr.STATE_RESOLVED, record
        # And the plan's row, which waited for it, is placed again.
        assert h.cards()[h.att]["builderSession"]["nodeStates"]["load"] == "created"


class TestWhoWaitsForYou:
    """The listing says which agents wait for the user to pick a node's
    source: the node's Dataset Finder, whose chat holds the candidates, and
    the agent whose chat asked for them, which the Finder's record keeps
    (``askedBy``, on its card's ``sourceRecord``). A pick, a skip, the node's
    removal or its Finder taken off ends both; clearing the asking chat ends
    its own wait only."""

    def test_the_listing_says_who_waits_and_the_pick_ends_it(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder, builder = h.finder_attachment_id(), h.node_builder_attachment_id()
        cards = h.cards()
        assert {a: cards[a].get("waitsForYou") for a in (finder, h.att, builder)} == {
            finder: [h.load], h.att: [h.load], builder: [],
        }
        record = cards[finder].get("sourceRecord") or {}
        assert (record.get("status"), record.get("askedBy")) == (dr.STATE_CANDIDATES_PENDING, h.att)
        assert cards[h.att].get("sourceRecord") is None
        h.select(URL)
        cards = h.cards()
        assert {a: cards[a].get("waitsForYou") for a in (finder, h.att, builder)} == {
            finder: [], h.att: [], builder: [],
        }
        record = cards[finder]["sourceRecord"]
        # The pick keeps who asked.
        assert (record["status"], record.get("askedBy")) == (dr.STATE_RESOLVED, h.att)

    def test_a_cleared_chat_stops_its_wait_and_the_finder_still_waits(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{h.att}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        cards = h.cards()
        assert (cards[h.att].get("waitsForYou"), cards[finder].get("waitsForYou")) == ([], [h.load])
        assert "askedBy" not in (cards[finder].get("sourceRecord") or {})

    def test_a_finder_taken_off_the_node_ends_the_wait(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        cards = h.cards()
        assert finder not in cards
        assert cards[h.att].get("waitsForYou") == []

    def test_a_skip_or_the_nodes_removal_ends_the_wait(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder = h.finder_attachment_id()
        assert dr.waiting_on_user(h.spec()) == {finder: [h.load], h.att: [h.load]}
        # The node came to name its source: discovery is skipped.
        skipped = h.spec()
        dr.mark_skipped(skipped, finder, literal="/data/areas.csv")
        assert dr.waiting_on_user(skipped) == {}
        # The node is removed, and its agents with it.
        removed = h.spec()
        removed["dataflow"]["nodes"] = [n for n in removed["dataflow"]["nodes"] if n.get("id") != h.load]
        attachments.prune_orphaned_attachments(removed)
        assert dr.waiting_on_user(removed) == {}


class TestWhichAgentsSolveANode:
    def test_solve_this_node_from_a_finders_chat_is_refused_and_the_listing_says_so(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Every node agent's chat shows Solve this node, but the server Solves
        a node only from an agent that writes node content, or hands that on:
        it refuses the Finder's. The listing says so, from the same check."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        finder, builder = h.finder_attachment_id(), h.node_builder_attachment_id()
        assert finder and builder, "the plan gave its loader no Dataset Finder or no Node Builder"
        r = client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder}/solve-node",
            json={"nodeId": h.load}, headers=_auth(token),
        )
        assert r.status_code == 409, r.get_data(as_text=True)
        assert "no installed agent declares node.content.generate" in r.get_json()["error"]
        cards = h.cards()
        assert {a: cards[a].get("solvesNodes") for a in (finder, builder, h.att)} == {
            finder: False, builder: True, h.att: True,
        }

    def test_an_installed_agent_whose_manifest_no_longer_parses_fails_no_listing(
        self, client, user_and_token, tmp_curio, monkeypatch, caplog
    ):
        """An agent installed in the dataflow whose copy in the account's store
        no longer parses makes the answer of each agent that reads it no, and
        the reason is logged. The listing still answers. On main it answered
        500: a Dataset Finder's answer reads every installed agent."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        broken = "agent.acme.broken@1"
        folder = agents_storage.agent_definition_dir(h.ukey, broken)
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{ no longer json", encoding="utf-8")
        spec = dataflow_docs.live(h.ukey, h.pid)
        spec["dataflow"]["agents"] = [*(spec["dataflow"].get("agents") or []), broken]
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "edit"))
        caplog.set_level(logging.WARNING)
        cards = h.cards()
        finder, builder = h.finder_attachment_id(), h.node_builder_attachment_id()
        assert (cards[finder]["solvesNodes"], cards[builder]["solvesNodes"]) == (False, True)
        assert any(
            isinstance((record.exc_info or (None, None))[1], AgentManifestError) for record in caplog.records
        ), [record.getMessage() for record in caplog.records]

    def test_the_listing_reads_each_agents_answer_once(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Several cards share an agent: the listing asks whether that agent
        Solves a node once, and who waits for the user once. On main it asked
        both for every card, and a Dataset Finder's answer reads every agent
        installed in the dataflow."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, plan=TWO_LOADERS)
        asked: Counter = Counter()
        waits: list = []
        resolve_among, waiting_on_user = delegation.resolve_among, dr.waiting_on_user

        def _resolve_among(user_key, installed, parent, capability):
            if capability == "node.content.generate":
                asked[parent.dir_name] += 1
            return resolve_among(user_key, installed, parent, capability)

        def _waiting_on_user(spec):
            waits.append(spec)
            return waiting_on_user(spec)

        monkeypatch.setattr(delegation, "resolve_among", _resolve_among)
        monkeypatch.setattr(dr, "waiting_on_user", _waiting_on_user)
        cards = h.cards()
        coords = {card["coord"] for card in cards.values()}
        assert len(cards) > len(coords), "no two cards share an agent"
        assert dict(asked) == {coord: 1 for coord in coords}, asked
        assert len(waits) == 1

    def test_an_agent_whose_solve_installs_its_required_agents_first_says_it_solves(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A node's Solve from an agent's chat installs the agents that agent
        requires before it checks for one that writes node content
        (``node_solve.py``). The listing answers as that Solve will, and
        installs nothing itself. On main it answered from the lockfile as it
        was: the Dataflow Builder, whose Node Builder was taken out of the
        lockfile, said no where its Solve goes ahead."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        spec = dataflow_docs.live(h.ukey, h.pid)
        spec["dataflow"]["agents"] = [
            coord for coord in spec["dataflow"].get("agents") or []
            if not coord.startswith("agent.curio.node-builder@")
        ]
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "edit"))
        assert h.cards()[h.att]["solvesNodes"] is True
        assert not [
            coord for coord in project_agents.project_agents(h.spec())
            if coord.startswith("agent.curio.node-builder@")
        ], "the listing installed an agent"


def _source_picks(h, attachment_id) -> list[dict]:
    """The candidates cards the chat of *attachment_id* holds for a node's
    Dataset Finder (``sourcePick`` parts), in order."""
    return [
        part for turn in h.session_turns(attachment_id) for part in (turn.get("content") or [])
        if part.get("type") == "sourcePick"
    ]


def _pick_on(h, finder, card_id, picks):
    """The user's *picks* on the candidates card *card_id*, posted as the card
    posts them: on the route of the node's Dataset Finder *finder*, naming the
    card they were made on."""
    return h.client.post(
        f"/api/agents/projects/{h.pid}/attachments/{finder}/dataset-selection",
        json={"picks": picks, "discoveryId": card_id}, headers=_auth(h.token),
    )


def _builder_session(h) -> dict:
    """The plan's ledger and its build, as the Dataflow Builder's record holds
    them."""
    return dict((attachments.get_attachment(h.spec(), h.att) or {}).get("builderSession") or {})


def _left_on_the_plan(h, *, drop=(), **fields) -> None:
    """Write *fields* into the plan's record of the Dataflow Builder, and take
    *drop* off it, as a backend process that is gone left them there, under
    the dataflow's spec lock."""
    with projects_storage.spec_write_lock(h.ukey, h.pid):
        spec = dataflow_docs.live(h.ukey, h.pid)
        record = attachments.get_attachment(spec, h.att)
        session = dict(record.get("builderSession") or {})
        for key in drop:
            session.pop(key, None)
        session.update(fields)
        record["builderSession"] = session
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "edit"))


def _answered(response) -> tuple[int, str]:
    """A request's status, and its error when it was refused. A stream that
    was answered (200) is not read: what it would run is not the test's."""
    status = response.status_code
    error = "" if status == 200 else str((response.get_json(silent=True) or {}).get("error") or "")
    response.close()
    return status, error


class _NoJob:
    """A Solve this node job that was not started."""

    job_id = "not-started"
    kind = "solve-node"


def _no_solve_job(monkeypatch) -> list:
    """Start no Solve this node job: a request that passes its checks answers
    an empty stream. Returns the kinds of the jobs asked for."""
    started: list = []
    monkeypatch.setattr(agent_jobs, "start_job", lambda **kw: started.append(kw.get("kind")) or _NoJob())
    monkeypatch.setattr(agent_jobs, "subscribe", lambda job: iter(()))
    return started


def _solve_this_node(h, attachment_id) -> dict:
    """Solve this node on the loader, from the chat of *attachment_id*, to its
    end: its done payload."""
    r = h.client.post(
        f"/api/agents/projects/{h.pid}/attachments/{attachment_id}/solve-node",
        json={"nodeId": h.load}, headers=_auth(h.token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return _sse_events(r)[-1][1]


class TestACardFollowsItsFindersRecord:
    """Every candidates card a node's Dataset Finder mints carries an id of
    its own (``discoveryId``), the same in the Finder's chat and in the chat
    that asked, and the Finder's record names the card whose pick it asks
    for. A pick names the card it was made on: a pick on a card the record
    no longer asks about is refused, so it is never read against another
    card's rows and starts no build beside the plan. Review of #1635, B1."""

    def test_a_pick_on_a_card_newer_candidates_replaced_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The loader's Dataset Finder is asked twice: a row's Solve asks it,
        its chat is cleared, and the row's Solve asks it again. The Dataflow
        Builder's chat holds both cards, each with its own id, and the
        Finder's record names the newer. A pick on the older card is refused,
        and one on the newer is recorded with the card it came from. On
        04d7e8c03f the cards carried no id, and the pick on the older card was
        recorded, read against the newer card's rows."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        h.validate("load")
        assert len(h.discover_calls) == 2
        cards = _source_picks(h, h.att)
        assert len(cards) == 2, [t.get("text") for t in h.session_turns(h.att)]
        older, newer = (card.get("discoveryId") for card in cards)
        stale = _pick_on(h, finder, older, [{"lane": "external", "key": URL}])
        assert stale.status_code == 409, (stale.status_code, stale.get_json())
        assert "newer candidates replaced these" in stale.get_json()["error"], stale.get_json()
        assert older and newer and older != newer, (older, newer)
        record = dr.source_record(h.spec(), h.load) or {}
        assert record.get("discoveryId") == newer, record
        fresh = _pick_on(h, finder, newer, [{"lane": "external", "key": URL}])
        assert fresh.status_code == 200, fresh.get_data(as_text=True)
        assert (dr.source_record(h.spec(), h.load) or {}).get("pickedFrom") == newer

    def test_a_pick_on_a_card_whose_finders_chat_was_cleared_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A row's Solve asks the loader's Dataset Finder, and its card comes
        to the Dataflow Builder's chat. The Finder's chat is cleared, which
        takes its card and its record away: the Builder's card asks for
        nothing any more. A pick on it, of a dataset the Data Catalog holds,
        is refused, and no Node Builder starts on the loader. On 04d7e8c03f
        the pick went through the Data Catalog fallback of resolve_picks, was
        recorded with no card to check it against and nobody who asked, and
        started the loader's Node Builder beside the plan."""
        from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns

        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        cards = _source_picks(h, h.att)
        assert len(cards) == 1, [t.get("text") for t in h.session_turns(h.att)]
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        # A dataset comes into the Data Catalog: the fallback that lets a
        # dataset just imported from a card be picked finds it.
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        started: list = []
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.solve.node_solve.solve_node_stream",
            lambda *a, **k: started.append(k.get("node_id")),
        )
        r = _pick_on(h, finder, cards[0].get("discoveryId"), [{"lane": "catalog", "key": dataset_id}])
        assert r.status_code == 409, (r.status_code, r.get_json(), started)
        assert "no longer" in r.get_json()["error"], r.get_json()
        assert started == [], "the pick started the loader's Node Builder beside the plan"


class TestABuildNoProcessRuns:
    """A Build & validate is a stream its backend process drives. One that a
    process left behind, when it stopped or a restart ended it, runs no more:
    the server takes it for gone by the start its record names
    (``simulateBootId``), and says so in the listing (``buildRunning``). It
    holds no Build & validate and no Solve, Stop clears one no driver holds,
    and a pick is never told that it builds the loader. Review of #1635, B2."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_a_build_an_earlier_start_left_holds_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The plan's record still names a build that a start which is gone
        began a minute ago. The listing says no build runs, and Build &
        validate runs. On 04d7e8c03f the listing gave no verdict, so a tab
        took the build for running by its own clock, and Build & validate was
        refused for 15 minutes: a simulation is already running."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        _left_on_the_plan(
            h, simulatingSince=time.time() - 60, simulateMode="auto",
            simulateExecutionId="a-build-of-an-earlier-start", simulateBootId="an-earlier-start",
        )
        listed = h.cards()[h.att].get("buildRunning", "not said")
        r = client.post(
            f"/api/agents/projects/{h.pid}/attachments/{h.att}/simulate",
            json={"mode": "auto"}, headers=_auth(token),
        )
        refused = r.get_json(silent=True) if r.status_code != 200 else None
        assert (r.status_code, listed) == (200, None), (refused, listed)
        done = _sse_events(r)[-1][1]
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done

    def test_stop_clears_a_build_no_driver_holds(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The plan's record names a build of this start that no driver
        holds: the stream that drove it is gone. Its Stop clears it at once,
        the listing says no build runs, and Build & validate runs. On
        04d7e8c03f the Stop only asked a driver that was not there to stop:
        the build stayed in the record, and Build & validate was refused until
        it went stale."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        _left_on_the_plan(
            h, simulatingSince=time.time() - 60, simulateMode="auto",
            simulateExecutionId="a-build-no-driver-holds", simulateBootId=shared_budgets.BOOT_ID,
        )
        # A build of this start, which the server takes for one that runs. A
        # listing that gives no verdict reads that way too.
        assert h.cards()[h.att].get("buildRunning", "auto") == "auto"
        r = client.post(f"/api/agents/projects/{h.pid}/attachments/{h.att}/simulate/cancel", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        session = _builder_session(h)
        assert not session.get("simulatingSince") and not session.get("simulateExecutionId"), session
        assert h.cards()[h.att].get("buildRunning") is None
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "paused", done

    def test_a_pick_while_a_dead_build_holds_the_plan_goes_on_by_itself(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Build & validate paused on the loader, and its Resume began a build
        that an earlier start left behind. The user's pick is answered as no
        build runs: the Dataflow Builder goes on with Build & validate, and
        the answer never says a build running now builds the loader. On
        04d7e8c03f the answer said the Build & validate running now built it,
        with nothing more to start, and nothing built it."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "paused", done
        # The Resume's start, as a start that is gone left it: no pause, and
        # its build in flight.
        _left_on_the_plan(
            h, drop=("pauseReason",), simulatingSince=time.time() - 60, simulateMode="auto",
            simulateExecutionId="a-resume-of-an-earlier-start", simulateBootId="an-earlier-start",
        )
        delegated = h.select(URL).get("delegated") or {}
        assert (delegated.get("status"), delegated.get("running"), delegated.get("continueWith")) == (
            "plan-waiting", None, "build",
        ), delegated
        assert "running now" not in delegated.get("reason", ""), delegated


class TestARowsSolveIsWorkOnItsNode:
    """A plan row's Solve, among them the one a pick starts by itself, is
    work on its node: while it runs, no Solve this node of that node and no
    Build & validate of its plan starts, and the listing names it
    (``validating``), so every tab shows its row running. While a build runs
    on the plan, no row's Solve and no Solve this node of its nodes starts.
    The server refuses each with 409 and says why. Review of #1635, B4."""

    def test_while_a_rows_solve_runs_its_node_takes_no_other_solve_and_its_plan_no_build(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """While the loader's row Solve asks its Dataset Finder, the loader's
        Node Builder is asked to Solve this node, and the Dataflow Builder to
        Build & validate its plan. Both are refused with 409, and the listing
        names the row's Solve. On 04d7e8c03f both started over it (each
        answered 200), and the listing named nothing."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        node_builder = h.node_builder_attachment_id()
        started = _no_solve_job(monkeypatch)

        def _meanwhile():
            solve = h.client.post(
                f"/api/agents/projects/{h.pid}/attachments/{node_builder}/solve-node",
                json={"nodeId": h.load}, headers=_auth(h.token),
            )
            build = h.client.post(
                f"/api/agents/projects/{h.pid}/attachments/{h.att}/simulate",
                json={"mode": "auto"}, headers=_auth(h.token),
            )
            return {"solve": _answered(solve), "build": _answered(build),
                    "listed": h.cards()[h.att].get("validating", "not said")}

        meanwhile = _during_the_discovery_of(h, monkeypatch, h.load, _meanwhile)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "awaiting-source", done
        solve = meanwhile.get("solve") or (None, "")
        assert solve[0] == 409 and "this node is being solved" in solve[1], (solve, started)
        build = meanwhile.get("build") or (None, "")
        assert build[0] == 409 and "a node of this plan is being solved" in build[1], build
        assert meanwhile.get("listed") == {"ref": "load", "nodeId": h.load}, meanwhile
        assert started == [], started

    def test_while_the_plan_is_built_no_rows_solve_and_no_solve_this_node_starts(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A Build & validate of this start runs on the plan, between two of
        its validations. A row's Solve of the loader and Solve this node from
        the loader's Node Builder are both refused with 409: the plan is being
        built. On 04d7e8c03f the server refused neither (each answered 200):
        only a tab held them back."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        node_builder = h.node_builder_attachment_id()
        started = _no_solve_job(monkeypatch)
        _left_on_the_plan(
            h, simulatingSince=time.time(), simulateMode="auto",
            simulateExecutionId="a-build-of-this-start", simulateBootId=shared_budgets.BOOT_ID,
        )
        row = _answered(client.post(
            f"/api/agents/projects/{h.pid}/attachments/{h.att}/validate-node",
            json={"ref": "load"}, headers=_auth(token),
        ))
        solve = _answered(client.post(
            f"/api/agents/projects/{h.pid}/attachments/{node_builder}/solve-node",
            json={"nodeId": h.load}, headers=_auth(token),
        ))
        assert row[0] == 409 and "the plan is being built" in row[1], row
        assert solve[0] == 409 and "the plan is being built" in solve[1], (solve, started)
        assert started == [], started


class TestAPickGoesOnAsTheUserWasGoing:
    """After the user's pick, the plan goes on as the user was going: one
    Step after a Step, Build & validate after Build & validate, and the
    row's Solve after a row's Solve. Review of #1635, B5."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_after_a_step_paused_on_the_loader_the_pick_goes_on_with_one_step(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The user steps through the plan: a Step finds the loader waiting
        for its source and pauses there, since nothing else can go on. The
        pick's answer goes on with one Step. On 04d7e8c03f it went on with
        Build & validate (continueWith build), which built the rest of the
        plan by itself while the user was stepping."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        done = h.simulate("step")[-1][1]
        assert (done.get("status"), [n.get("ref") for n in (done.get("reason") or {}).get("nodes") or []]) == (
            "paused", ["load"],
        ), done
        delegated = h.select(URL).get("delegated") or {}
        assert (delegated.get("status"), delegated.get("running"), delegated.get("continueWith")) == (
            "plan-waiting", None, "step",
        ), delegated
        assert "by one Step" in delegated.get("reason", ""), delegated


class TestTheChatThatAsksLaterGetsTheCardToo:
    """A loader's candidates already wait for a pick when another agent's
    Solve or Build & validate reaches the loader: that agent's chat gets the
    same card, with the same id, and waits for the pick too. Review of
    #1635, B6."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_build_and_validate_on_a_loader_solve_this_node_asked_about_puts_the_card_in_its_chat(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Solve this node, from the loader's Node Builder, asks the loader's
        Dataset Finder first. Then the Dataflow Builder's Build & validate
        pauses on the loader. The Builder's chat holds the card, with the id
        the Finder's record names, and the listing says the Builder waits for
        the pick, as the Node Builder still does. No second discovery runs. On
        04d7e8c03f the Builder's chat held no card and the listing said the
        Builder waited for nothing, while its plan paused on the loader."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        node_builder = h.node_builder_attachment_id()
        first = _solve_this_node(h, node_builder)
        assert first.get("verdict") == "awaiting-source", first
        done = h.simulate("auto")[-1][1]
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
        cards = _source_picks(h, h.att)
        assert len(cards) == 1, [t.get("text") for t in h.session_turns(h.att)]
        record = dr.source_record(h.spec(), h.load) or {}
        assert cards[0].get("discoveryId") and cards[0]["discoveryId"] == record.get("discoveryId"), (
            cards[0], record,
        )
        assert (cards[0].get("nodeId"), cards[0].get("finderAttachmentId")) == (h.load, h.finder_attachment_id())
        listed = h.cards()
        assert (listed[h.att]["waitsForYou"], listed[node_builder]["waitsForYou"]) == ([h.load], [h.load]), listed
        assert len(h.discover_calls) == 1


class _Asked:
    """The model calls the dataflow of a harness makes from now on: the
    loader's Node Builder's, its Dataset Finder's, and all of them."""

    def __init__(self, h):
        self.h = h
        self.before = (len(h.dl_calls), len(h.discover_calls), len(h.model_calls))

    def counts(self) -> dict:
        builder, finder, every = self.before
        return {
            "the loader's Node Builder": len(self.h.dl_calls) - builder,
            "its Dataset Finder": len(self.h.discover_calls) - finder,
            "in all": len(self.h.model_calls) - every,
        }

    def of_the_loader(self) -> dict:
        """The calls of the loader's own agents alone. A Solve of the plan
        also asks the builder of the node that reads the loader, once a pass,
        which finds its input empty (``batch.py``'s ``upstreamEmpty``): two
        calls here, on main as with this change."""
        counts = self.counts()
        return {who: counts[who] for who in ("the loader's Node Builder", "its Dataset Finder")}


#: What a loader with no source costs when its Dataset Finder is asked first:
#: the Finder's one call, and none of its Node Builder.
FINDER_ALONE = {"the loader's Node Builder": 0, "its Dataset Finder": 1, "in all": 1}
#: What a loader with a source costs: its Node Builder's first round, which
#: builds it, and no Finder.
BUILT_AT_ONCE = {"the loader's Node Builder": 1, "its Dataset Finder": 0, "in all": 1}


def _delegated_solves(h) -> list[str]:
    """The Solve turns another agent handed the loader's Node Builder: one
    each time the loader goes to its builder."""
    return [
        t.get("text") or "" for t in h.session_turns(h.node_builder_attachment_id())
        if (t.get("text") or "").startswith("[Delegated by")
    ]


def _a_dataset(user, title: str) -> str:
    """A dataset the account imported into its Data Catalog, titled *title*,
    in no dataflow: its id."""
    from utk_curio.backend.app.datasets.install.installer import install_imported_file

    return install_imported_file(_user_dir_key(user), b"a,b\n1,2\n", "rows.csv", "csv", title=title).manifest.id


def _reads(dataset_id: str) -> str:
    """A loader's code that reads *dataset_id* from the Data Catalog."""
    return f'data = curio_load_data("{dataset_id}")\nreturn data'


def _in_the_dataflow(h, dataset_id: str) -> None:
    """Add *dataset_id* to the dataflow, as Add to project does."""
    r = h.client.post(f"/api/dataflows/{h.pid}/datasets/install", json={"datasetId": dataset_id},
                      headers=_auth(h.token))
    assert r.status_code == 200, r.get_data(as_text=True)


def _the_loader_holds(h, *, content: str | None = None, datasets: dict | None = None) -> None:
    """The loader as the user left it: *content* as its code, and each of its
    dataset widgets named in *datasets* holding the id given."""
    with projects_storage.spec_write_lock(h.ukey, h.pid):
        spec = dataflow_docs.live(h.ukey, h.pid)
        node = next(n for n in spec["dataflow"]["nodes"] if n.get("id") == h.load)
        if content is not None:
            node["content"] = content
        widgets = node.setdefault("metadata", {}).setdefault("widgets", [])
        for name, dataset_id in (datasets or {}).items():
            widget = next((w for w in widgets if w.get("name") == name), None)
            if widget is None:
                widgets.append({"name": name, "type": "dataset", "default": "", "value": dataset_id})
            else:
                widget["value"] = dataset_id
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "edit"))


#: The file the user names in the Dataflow Builder's chat for the branches.
BRANCHES_FILE = "/data/cpl_branches.csv"
#: The URL a candidates card of the Builder's own chat verified for the branches.
BRANCHES_URL = "https://data.example.org/cpl_branches.csv"


def _branches_and_crimes(branches_intent: str) -> dict:
    """A plan of two loaders, the library branches, whose intent is
    *branches_intent*, and the crimes, and a node that reads both."""
    return {
        "goal": "compare library branches with crimes",
        "nodes": [
            {"ref": "branches", "nodeType": DL, "title": "CPL branches", "intent": branches_intent},
            {"ref": "crimes", "nodeType": DL, "title": "Crimes", "intent": "load the crimes by community area"},
            {"ref": "join", "nodeType": CA, "title": "Join", "intent": "count the crimes near each branch"},
        ],
        "edges": [{"from": "branches", "to": "join"}, {"from": "crimes", "to": "join"}],
    }


def _the_builder_offered(h, url: str) -> None:
    """A candidates card the Dataflow Builder's own chat offered, as when the
    user asked it for data before the plan: one external row, *url*,
    verified, for no node."""
    session_id = (attachments.get_attachment(h.spec(), h.att) or {}).get("sessionId")
    card = {"type": "datasetCandidates", "discoveryId": "the-builders-own", "lanes": {"catalog": [], "external": [{
        "name": "CPL branches", "sourceType": "portal", "url": url, "format": "csv",
        "verification": {"status": "verified", "detail": "200 OK", "httpStatus": 200},
    }]}}
    sessions.append_turns(h.ukey, h.pid, session_id, h.att,
                          [sessions.make_turn("agent", "I found 1 candidate.", content=[card])])


class TestALoaderWithNoSourceAsksItsFinderFirst:
    """A data-loading node with a Dataset Finder of its own, and nothing that
    names its source: Solve, Build & validate plan, a plan row's Solve and
    Solve this node each ask its Finder before any round, and the loader
    waits for the pick with no call of its Node Builder. Step 5.3 of the agent
    chat plan, found by the dev check of steps 4 and 5 (11-26). On main a Data
    Catalog that held any dataset, a shipped one among them, grounded a first
    attempt: the Node Builder wrote the loader round after round, each one
    refused for its source, and the Finder was asked only once the rounds
    ended (on dev 8 rounds and 48 s, here the 3 rounds the suite allows).

    A loader that has a source it can load from is built as before, from its
    first round: a dataset of its dataflow, a dataset of the Data Catalog its
    goal names by title, one its dataset widget holds, its own code that
    reads one, or a URL its goal names. So is a loader with no Dataset Finder
    of its own: the Data Catalog grounds its first attempt, and discovery
    starts once the rounds are refused for its source. Those guards pass on
    main too."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_solve_asks_the_finder_before_the_loaders_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        asked = _Asked(h)
        load = h.solve()["results"][h.load]
        assert asked.of_the_loader() == {"the loader's Node Builder": 0, "its Dataset Finder": 1}, (
            asked.counts(), [a.get("kind") for a in load.get("attempts") or []],
        )
        assert load["status"] == "pending", load
        assert load["reason"].startswith("awaiting your dataset selection"), load
        assert load["attempts"] == [], load["attempts"]
        assert h.node_content(h.load) == ""

    def test_build_and_validate_plan_asks_the_finder_before_the_loaders_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        asked = _Asked(h)
        done = h.simulate("auto")[-1][1]
        assert asked.counts() == FINDER_ALONE, asked.counts()
        assert (done.get("status"), (done.get("reason") or {}).get("kind")) == ("paused", "awaiting-source"), done
        assert done["builderSession"]["nodeStates"]["load"] == "awaiting-source", done["builderSession"]
        # The loader was never handed to its Node Builder.
        assert _delegated_solves(h) == []
        assert h.node_content(h.load) == ""

    def test_a_rows_solve_asks_the_finder_before_the_loaders_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert asked.counts() == FINDER_ALONE, asked.counts()
        assert done.get("verdict") == "awaiting-source", done
        assert done.get("attempts") == [], done.get("attempts")
        assert _delegated_solves(h) == []
        assert h.node_content(h.load) == ""

    def test_solve_this_node_asks_the_finder_before_the_loaders_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        asked = _Asked(h)
        done = _solve_this_node(h, h.node_builder_attachment_id())
        assert asked.counts() == FINDER_ALONE, asked.counts()
        assert done.get("verdict") == "awaiting-source", done
        assert h.node_content(h.load) == ""

    def test_a_loader_its_dataflow_holds_a_dataset_for_is_built_from_its_first_round(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The dataflow holds a dataset its goal does not name: its builder is
        handed the dataflow's datasets and loads it."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch, dl_replies=[_reads(dataset_id)])
        _in_the_dataflow(h, dataset_id)
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "pass", done
        assert asked.counts() == BUILT_AT_ONCE, asked.counts()
        assert dataset_id in h.node_content(h.load)

    def test_a_loader_whose_goal_names_a_dataset_by_its_title_is_built_from_its_first_round(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The goal names a dataset of the Data Catalog by its title, in no
        dataflow."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch, goal="load the city's ward offices",
                     dl_replies=[_reads(dataset_id)])
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "pass", done
        assert asked.counts() == BUILT_AT_ONCE, asked.counts()
        assert dataset_id in h.node_content(h.load)

    def test_a_loader_whose_dataset_widget_holds_a_dataset_is_built_from_its_first_round(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The loader's Data widget holds a dataset of the Data Catalog, which
        its code reads through the widget."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch, dl_replies=["data = curio_load_data([!! data !!])\nreturn data"])
        _the_loader_holds(h, datasets={"data": dataset_id})
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "pass", done
        assert asked.counts() == BUILT_AT_ONCE, asked.counts()

    def test_solve_this_node_runs_the_code_a_loader_holds_that_reads_a_dataset(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The loader's own code reads a dataset of the Data Catalog: Solve
        this node runs it as it is, and asks no one."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch)
        _the_loader_holds(h, content=_reads(dataset_id))
        asked = _Asked(h)
        done = _solve_this_node(h, h.node_builder_attachment_id())
        assert done.get("verdict") == "pass", done
        assert asked.counts() == {"the loader's Node Builder": 0, "its Dataset Finder": 0, "in all": 0}, asked.counts()
        assert h.node_content(h.load) == _reads(dataset_id)

    def test_a_loader_whose_goal_names_a_url_is_built_from_its_first_round(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, goal=f"load the boundaries at {URL}",
                     dl_replies=[f'import pandas as pd\nreturn pd.read_json("{URL}")'])
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert done.get("verdict") == "pass", done
        assert asked.counts() == BUILT_AT_ONCE, asked.counts()
        assert URL in h.node_content(h.load)

    def test_a_loader_with_no_finder_of_its_own_tries_before_a_finder_is_asked(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The loader's Dataset Finder was taken off it: the Data Catalog
        grounds a first attempt, the rounds are refused for its source, and
        only then does discovery start, which gives the loader a Finder. The
        node waits for the pick with the trail of what was tried."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        asked = _Asked(h)
        load = h.solve()["results"][h.load]
        assert asked.of_the_loader() == {"the loader's Node Builder": 3, "its Dataset Finder": 1}, asked.counts()
        assert load["status"] == "pending", load
        assert load["reason"].startswith("awaiting your dataset selection"), load
        assert [a["kind"] for a in load["attempts"]] == ["ungrounded-source"] * 3
        assert "areas.csv" in load["attempts"][0]["detail"]
        assert h.exec_payloads == []  # nothing ungrounded ever ran
        assert h.node_content(h.load) == ""
        # The Finder the discovery gave the loader holds its candidates.
        assert load["remedy"]["attachmentId"] == h.finder_attachment_id() != finder
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_CANDIDATES_PENDING

    @pytest.mark.parametrize("message, goal, code", [
        ("My branches are in /data/cpl_branches.csv", "load the locations of the CPL branches",
         'import pandas as pd\nreturn pd.read_csv("/data/cpl_branches.csv")'),
        ("Make a demo with synthetic data of parks", "load the daily visits of each park",
         'import numpy as np\nimport pandas as pd\nreturn pd.DataFrame({"visits": np.random.randint(0, 500, 30)})'),
        ("Rents: Loop 2450, Pilsen 1500", "load the rents, Loop 2450 and Pilsen 1500",
         'import pandas as pd\nreturn pd.DataFrame({"Rents": [2450, 1500]}, index=["Loop", "Pilsen"])'),
    ], ids=["path", "synthetic", "values"])
    def test_a_source_the_user_gave_in_the_chat_that_asked_is_built_from_its_first_round(
        self, client, user_and_token, tmp_curio, monkeypatch, message, goal, code,
    ):
        """The user gave the loader's source in the Dataflow Builder's chat,
        and the plan's goal says it in other words: a path, a request for
        synthetic data, values typed with their labels. The round's source
        check reads that chat, so Build & validate builds the loader from its
        first round and waits for no pick. On 271aec86a4 the step before the
        rounds read the goal alone, so the Finder was asked for the path and
        for the synthetic data, and the build paused for a pick the user did
        not need. The typed values are a guard: the goal gives them. Found by
        the review of #1642."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, message=message, goal=goal, dl_replies=[code])
        asked = _Asked(h)
        done = h.simulate("auto")[-1][1]
        assert asked.of_the_loader() == {"the loader's Node Builder": 1, "its Dataset Finder": 0}, asked.counts()
        assert done.get("status") == "completed", done
        assert h.node_content(h.load) == code

    def test_a_year_the_chat_and_the_goal_share_is_no_source(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A year the user wrote and the goal repeats says when the data is
        from, and is no data: the loader's Finder is asked before its builder,
        as for any loader with no source. On 271aec86a4 any number both wrote
        counted as values the user typed, so the builder wrote the loader round
        after round, each refused for its source, before the Finder was asked.
        Found by the review of #1642."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, message="Compare the 2023 crimes by community area.",
                     goal="load the 2023 crimes")
        asked = _Asked(h)
        done = h.validate("load")[-1][1]
        assert asked.counts() == FINDER_ALONE, asked.counts()
        assert done.get("verdict") == "awaiting-source", done

    @pytest.mark.parametrize("message, branches_intent, code, offered", [
        (f"My branches are in {BRANCHES_FILE}", "load the CPL branches",
         f'import pandas as pd\nreturn pd.read_csv("{BRANCHES_FILE}")', None),
        ("Make a demo with synthetic data.", "generate synthetic CPL branches",
         'import numpy as np\nimport pandas as pd\nreturn pd.DataFrame({"visits": np.random.randint(0, 500, 30)})', None),
        ("plan it", f"load the CPL branches from {BRANCHES_URL}",
         f'import pandas as pd\nreturn pd.read_csv("{BRANCHES_URL}")', BRANCHES_URL),
    ], ids=["path", "synthetic", "url"])
    def test_what_the_chat_said_grounds_only_the_loader_it_names(
        self, client, user_and_token, tmp_curio, monkeypatch, message, branches_intent, code, offered,
    ):
        """A plan of two loaders, the library branches and the crimes, and in
        the Dataflow Builder's chat a path, a request for synthetic data, or a
        candidates card of its own with a verified URL. The branches loader,
        whose goal names that source, is built from its first round; the
        crimes loader's Finder is asked before its builder. On 6031770487
        what the chat said grounded every loader of the plan, so the crimes
        loader was built from the branches' file, URL or made-up rows. Found
        by the second review of #1642."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, message=message, plan=_branches_and_crimes(branches_intent),
                     dl_replies=[code])
        if offered:
            _the_builder_offered(h, offered)
        asked = _Asked(h)
        crimes = h.validate("crimes")[-1][1]
        assert asked.counts() == FINDER_ALONE, (asked.counts(), crimes.get("verdict"))
        assert crimes.get("verdict") == "awaiting-source", crimes
        asked = _Asked(h)
        branches = h.validate("branches")[-1][1]
        assert branches.get("verdict") == "pass", branches
        assert asked.counts() == BUILT_AT_ONCE, asked.counts()
        assert h.node_content(h.ref_ids()["branches"]) == code

    def test_a_card_its_finder_no_longer_offers_grounds_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The chat that asked holds the loader's candidates card, with a URL
        it verified, and the Finder's chat was cleared, so its record offers
        that card no more. Build & validate asks the Finder again before any
        round: the card's URL was a candidate the user never picked. While a
        card stands, the node waits for its pick, which outranks anything the
        chat says."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.simulate("auto")
        assert [p.get("nodeId") for p in _source_picks(h, h.att)] == [h.load]
        finder = h.finder_attachment_id()
        r = client.delete(f"/api/agents/projects/{h.pid}/attachments/{finder}/session", headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        asked = _Asked(h)
        done = h.simulate("auto")[-1][1]
        assert asked.counts() == FINDER_ALONE, asked.counts()
        assert (done.get("reason") or {}).get("kind") == "awaiting-source", done


def _the_finders_first_run_fails(monkeypatch) -> list:
    """The first run of a Dataset Finder fails, as when its model's endpoint
    is down: the run ends in an error and offers nothing. Returns the tasks of
    the runs that failed, filled as they fail."""
    ask = providers.run_chat_turn
    failed: list = []

    def _asked(config, messages, **kwargs):
        frame = (messages[-1].get("content") or "") if messages else ""
        if not failed and "discoveryReplyContract" in frame:
            failed.append(frame)
            raise RuntimeError("the model endpoint is down")
        return ask(config, messages, **kwargs)

    monkeypatch.setattr(providers, "run_chat_turn", _asked)
    return failed


def _during_the_loaders_first_round(h, monkeypatch, act) -> list:
    """Run *act* while the loader's Node Builder writes its first round, as
    another chat acts while the rounds run. Returns a list that holds one
    entry once *act* ran."""
    ask = providers.run_chat_turn
    ran: list = []

    def _asked(config, messages, **kwargs):
        frame = (messages[-1].get("content") or "") if messages else ""
        if (not ran and "[delegated task" in frame and "discoveryReplyContract" not in frame
                and f'"nodeId": "{h.load}"' in frame):
            act()
            ran.append(True)
        return ask(config, messages, **kwargs)

    monkeypatch.setattr(providers, "run_chat_turn", _asked)
    return ran


def _a_card(card_id: str) -> dict:
    """A candidates card of a Dataset Finder, *card_id*, with the one row of
    CANDIDATES."""
    return {"type": "datasetCandidates", "discoveryId": card_id, **json.loads(CANDIDATES)["datasetCandidates"]}


def _candidates_another_ask_left(h, card_id: str) -> None:
    """Candidates the loader's Finder found on another chat's ask: its card
    *card_id* in the Finder's chat, and its record waiting for the pick."""
    node = next(n for n in h.spec()["dataflow"]["nodes"] if n.get("id") == h.load)
    finder = h.finder_attachment_id()
    dr._append_candidates_turn(h.ukey, h.pid, finder, node, _a_card(card_id), 1)
    with projects_storage.spec_write_lock(h.ukey, h.pid):
        spec = dataflow_docs.live(h.ukey, h.pid)
        dr.mark_candidates_pending(spec, finder, count=1, discovery_id=card_id)
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.by_curio(h.ukey, "dataset"))


def _offered_while_nothing_waits(h, card: dict) -> None:
    """The loader's Finder offered *card* in its own chat while the loader
    waited for nothing: the card is in the Finder's chat, and its record
    names it as the card on offer."""
    node = next(n for n in h.spec()["dataflow"]["nodes"] if n.get("id") == h.load)
    finder = h.finder_attachment_id()
    dr._append_candidates_turn(h.ukey, h.pid, finder, node, card, 1)
    dr.offer_from_chat(h.ukey, h.pid, finder, card)


def _a_pick_that_waits_for_its_install(h, card_id: str, dataset_id: str) -> None:
    """The user's pick, on the card *card_id* of the loader's Finder, of
    *dataset_id*, a dataset of the Data Catalog that the dataflow does not
    hold: the pick waits for its reviewed install."""
    row = {"lane": "catalog", "datasetId": dataset_id, "name": "Ward offices", "sourceType": "catalog",
           "installed": False}
    finder = h.finder_attachment_id()
    with projects_storage.spec_write_lock(h.ukey, h.pid):
        spec = dataflow_docs.live(h.ukey, h.pid)
        dr.record_selection(spec, finder, [row], picked_from=card_id)
        dataflow_docs.write(h.ukey, h.pid, spec, dataflow_docs.person(h.ukey, "dataset"))


class TestTheFinderAfterTheRounds:
    """A loader with no source whose Dataset Finder, asked before the first
    round, had nothing to offer: its rounds run, and when they are refused for
    their source the loader keeps its own failure, with why, and the Finder is
    not asked a second time. Unless that ask never ran, or a card came since:
    then the Finder is asked again, or the loader waits for the card's pick,
    as on main. Found by the review of #1642."""

    def test_a_finder_that_could_not_run_before_the_rounds_is_asked_again_after_them(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Finder's run failed before the first round. On 271aec86a4 the
        loader then failed with that error, and the Finder was not asked
        again."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        failed = _the_finders_first_run_fails(monkeypatch)
        done = h.validate("load")[-1][1]
        assert (len(failed), len(h.discover_calls)) == (1, 1), (done.get("verdict"), done.get("evidence"))
        assert done.get("verdict") == "awaiting-source", done
        # The rounds that ran before are kept, each refused for its source.
        assert done.get("attempts"), done
        assert {a.get("kind") for a in done["attempts"]} == {"ungrounded-source"}, done["attempts"]
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_CANDIDATES_PENDING

    def test_a_card_the_finders_own_chat_offers_during_the_rounds_has_it_asked_again(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Finder found nothing before the first round, and while the
        rounds ran it offered a card in its own chat, where the user asked it.
        On 271aec86a4 the loader failed, and the Finder was not asked again."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=["No source covers that.", CANDIDATES])
        offered = _during_the_loaders_first_round(
            h, monkeypatch, lambda: dr.offer_from_chat(h.ukey, h.pid, h.finder_attachment_id(), _a_card("its-own")),
        )
        done = h.validate("load")[-1][1]
        assert offered == [True]
        assert len(h.discover_calls) == 2, (done.get("verdict"), done.get("evidence"))
        assert done.get("verdict") == "awaiting-source", done
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_CANDIDATES_PENDING

    def test_candidates_another_ask_left_during_the_rounds_are_waited_on(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Finder found nothing before the first round, and while the
        rounds ran another chat's ask left candidates waiting for the pick:
        the loader waits for that pick, its card in the chat that asked too,
        and the Finder is not asked again. On 271aec86a4 the loader failed
        beside the waiting card."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=["No source covers that."])
        left = _during_the_loaders_first_round(h, monkeypatch, lambda: _candidates_another_ask_left(h, "another-ask"))
        done = h.validate("load")[-1][1]
        assert left == [True]
        assert done.get("verdict") == "awaiting-source", done
        assert len(h.discover_calls) == 1
        assert [p.get("discoveryId") for p in _source_picks(h, h.att)] == ["another-ask"]

    def test_a_finder_that_found_nothing_is_named_in_the_loaders_failure(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Nothing came since the Finder found nothing: the loader keeps its
        own failure, whose evidence says why discovery found nothing
        (``discovery``), and the Finder was asked once."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=["No source covers that."])
        done = h.validate("load")[-1][1]
        evidence = done.get("evidence") or {}
        assert (done.get("verdict"), evidence.get("kind")) == ("fail", "ungrounded-source"), done
        assert "no recognizable datasetCandidates block" in str(evidence.get("discovery")), evidence
        assert len(h.discover_calls) == 1

    @pytest.mark.parametrize("since", ["another-card", "a-pick-that-waits"])
    def test_each_half_of_what_came_since_the_finders_ask_is_read(
        self, client, user_and_token, tmp_curio, monkeypatch, since,
    ):
        """Before the rounds the Finder's record named a card it had offered
        while nothing waited, and the Finder, asked again, found nothing. What
        comes during the rounds is read by one half of ``_offered_since``
        each, so each case fails with its own half removed. Another card
        offered in the Finder's own chat, which no one waits on, has the
        Finder asked again after the rounds. A pick on the card from before
        that waits for its install leaves that card on offer, and the loader
        waits for the install."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch, discover_replies=["No source covers that.", CANDIDATES])
        _offered_while_nothing_waits(h, {**_a_card("before"), "lanes": {"external": [], "catalog": [
            {"datasetId": dataset_id, "name": "Ward offices", "sourceType": "catalog", "installed": False},
        ]}})
        def _another_card():
            dr.offer_from_chat(h.ukey, h.pid, h.finder_attachment_id(), _a_card("another"))

        def _a_pick_on_the_card_from_before():
            _a_pick_that_waits_for_its_install(h, "before", dataset_id)

        acted = _during_the_loaders_first_round(
            h, monkeypatch, _another_card if since == "another-card" else _a_pick_on_the_card_from_before,
        )
        done = h.validate("load")[-1][1]
        assert acted == [True]
        evidence = done.get("evidence") or {}
        assert done.get("verdict") == "awaiting-source", (done.get("verdict"), evidence)
        waits = {"another-card": ("pick", 2), "a-pick-that-waits": ("install", 1)}[since]
        assert (evidence.get("sourceWait"), len(h.discover_calls)) == waits, evidence

    def test_the_resolver_that_asks_no_one_writes_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """``ask=False``, with which the loop reads whether a card came since
        the Finder's first ask (``_offered_since``), asks no model and writes
        nothing, whatever the loader's source: none, for which a resolve that
        asks has its Finder asked; a path its goal names, which such a resolve
        records as a skip; or candidates another chat's ask left waiting,
        which such a resolve puts in its own chat too."""
        from utk_curio.backend.app.agents.application import source_grounding as sg
        from utk_curio.backend.app.agents.application.turns import grounding
        from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig

        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        resolve = grounding._source_resolver(
            h.ukey, h.pid, coord=DFB, attachment_id=h.att, execution_id="e-ask-no-one",
            config=ProviderConfig(api_key="k", api_type="openai_compatible", base_url="http://x", model="m"),
        )
        writes: list = []
        turns: list = []
        write, append = dataflow_docs.write, sessions.append_turns
        monkeypatch.setattr(dataflow_docs, "write", lambda *a, **k: (writes.append(a), write(*a, **k))[1])
        monkeypatch.setattr(sessions, "append_turns", lambda *a, **k: (turns.append(a), append(*a, **k))[1])

        def _state_asking_no_one(node, stage):
            before = (len(writes), len(turns), len(h.model_calls), json.dumps(h.spec(), sort_keys=True))
            answer = resolve(node, sg.GroundingContext(), stage=stage, ask=False)
            after = (len(writes), len(turns), len(h.model_calls), json.dumps(h.spec(), sort_keys=True))
            assert after == before, (stage, answer, after[:3], before[:3])
            return answer.get("state")

        node = next(n for n in h.spec()["dataflow"]["nodes"] if n.get("id") == h.load)
        assert _state_asking_no_one(node, "pre") == "unresolved"
        assert _state_asking_no_one({**node, "goal": "load /data/areas.csv"}, "pre") == "resolved"
        _candidates_another_ask_left(h, "another-ask")
        assert _state_asking_no_one(node, "post") == "awaiting"


class TestTheUsersOwnSourceEndsTheWait:
    """A loader waits for the pick on its Finder's card, and the user answers
    by giving the loader its source on the node itself: a dataset on its Data
    widget, or code that reads one. That ends the wait, and Resume builds the
    loader from it. On 271aec86a4 the card outranked the node's own source,
    so Resume paused again, awaiting the dataset selection. Found by the
    review of #1642."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    @pytest.mark.parametrize("given", ["widget", "code"])
    def test_a_source_given_on_the_loader_ends_its_wait_and_resume_builds_it(
        self, client, user_and_token, tmp_curio, monkeypatch, given,
    ):
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        built = "data = curio_load_data([!! data !!])\nreturn data" if given == "widget" else _reads(dataset_id)
        h = _Harness(client, user, token, monkeypatch, dl_replies=[built])
        paused = h.simulate("auto")[-1][1]
        assert (paused.get("reason") or {}).get("kind") == "awaiting-source", paused
        if given == "widget":
            _the_loader_holds(h, datasets={"data": dataset_id})
        else:
            _the_loader_holds(h, content=_reads(dataset_id))
        asked = _Asked(h)
        done = h.simulate("auto")[-1][1]
        assert asked.of_the_loader() == {"the loader's Node Builder": 1, "its Dataset Finder": 0}, asked.counts()
        assert done.get("status") == "completed", done
        assert h.node_content(h.load) == built
        # Nobody waits for the pick any more.
        assert dr.waiting_on_user(h.spec()) == {}

    @pytest.mark.parametrize("held", ["widget", "code"])
    def test_what_the_loader_held_before_its_card_does_not_end_the_wait(
        self, client, user_and_token, tmp_curio, monkeypatch, held,
    ):
        """The loader held a dataset before its Finder's card was offered, on
        its Data widget or in its code, and its goal is about other data: its
        rounds were refused for their source, and its Finder was asked. Resume
        then waits on the card and asks no one. On 6031770487 what the loader
        held before the card outranked it: every Resume closed the card, ran
        the rounds again and had the Finder offer a new card. Found by the
        second review of #1642."""
        user, token = user_and_token
        dataset_id = _a_dataset(user, "Ward offices")
        h = _Harness(client, user, token, monkeypatch)
        if held == "widget":
            _the_loader_holds(h, datasets={"data": dataset_id})
        else:
            _the_loader_holds(h, content=_reads(dataset_id))
        paused = h.simulate("auto")[-1][1]
        assert (paused.get("reason") or {}).get("kind") == "awaiting-source", paused
        offered = dr.source_record(h.spec(), h.load).get("discoveryId")
        asked = _Asked(h)
        again = h.simulate("auto")[-1][1]
        assert asked.counts() == {"the loader's Node Builder": 0, "its Dataset Finder": 0, "in all": 0}, asked.counts()
        assert (again.get("reason") or {}).get("kind") == "awaiting-source", again
        record = dr.source_record(h.spec(), h.load)
        assert (record.get("status"), record.get("discoveryId")) == (dr.STATE_CANDIDATES_PENDING, offered), record
