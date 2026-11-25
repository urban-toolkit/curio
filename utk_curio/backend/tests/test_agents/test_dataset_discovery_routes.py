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
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import storage as agents_storage
from utk_curio.backend.app.collaboration import dataflow_docs
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
    loader of it is answered from ``dl_replies``."""

    def __init__(self, client, user, token, monkeypatch, *, goal=None,
                 discover_replies=None, dl_replies=None, parent=DFB, prepare=None, plan=None):
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
                        json={"message": "plan it"}, headers=_auth(token))
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
        """The end of the old dead end. The project's Data Catalog grounds a
        first attempt (the child is handed its rows), the gate refuses the
        filename the child invented anyway — and THAT is where discovery is
        initiated: the node ends PENDING with candidates awaiting the user, the
        trail of what was tried, and the remedy naming the chat to open."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        body = h.solve()
        load = body["results"][h.load]
        # PENDING, never failed: nothing was written, and the trail is kept.
        assert load["status"] == "pending"
        assert load["reason"].startswith("awaiting your dataset selection")
        assert load["remedy"]["kind"] == "dataset-selection"
        assert load["remedy"]["nodeId"] == h.load
        assert [a["kind"] for a in load["attempts"]] == ["ungrounded-source"] * 3
        assert "areas.csv" in load["attempts"][0]["detail"]
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
        rides along as the reason."""
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


class TestConfirmedSourceReachesTheBuilder:
    def test_a_recorded_selection_resolves_the_node_and_is_handed_over(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        # Three ungrounded attempts (so discovery fires and candidates land),
        # then the code that loads the confirmed URL.
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                ("import pandas as pd\nreturn pd.read_json"
                 '("https://data.example.org/areas.geojson")'),
            ],
        )
        assert h.solve()["results"][h.load]["status"] == "pending"
        h.record_selection("https://data.example.org/areas.geojson")
        body = h.solve(node_ids=[h.load])
        load = body["results"][h.load]
        assert load["status"] == "solved", load
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
        # Three ungrounded attempts in the first Solve, three more in the first
        # pass after the selection, then the code that loads the confirmed URL.
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[invented] * 6 + [f'import pandas as pd\nreturn pd.read_json("{url}")'],
        )
        assert h.solve()["results"][h.load]["status"] == "pending"
        h.record_selection(url)
        body = h.solve(node_ids=[h.load])
        load = body["results"][h.load]
        assert load["status"] == "solved", load
        assert [a["kind"] for a in load["attempts"][:3]] == ["ungrounded-source"] * 3
        # Every round after the selection was handed the confirmed source.
        assert len(h.dl_calls) > 3
        for frame in h.dl_calls[3:]:
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
        # dev/126's lane: the rounds that were refused before discovery ran are
        # attempts too, and the owner asked for ALL of them.
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
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
        asked = [
            t.get("text") for t in h.session_turns(h.node_builder_attachment_id())
            if (t.get("text") or "").startswith("[Delegated by")
        ]
        assert len(asked) == 1, asked
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
        invented = 'import pandas as pd\nreturn pd.read_csv("invented.csv")'
        h = _Harness(
            client, user, token, monkeypatch,
            dl_replies=[invented] * 3 + [f'import pandas as pd\nreturn pd.read_json("{URL}")'],
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
        # One pass of models: each loader's attempts and its Finder, nothing
        # asked for the nodes that read from them.
        assert len(h.dl_calls) == 6
        assert len(h.model_calls) - calls == len(h.dl_calls) + len(h.discover_calls)
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
        invented = 'import pandas as pd\nreturn pd.read_csv("invented.csv")'
        h = _Harness(
            client, user, token, monkeypatch, plan=TWO_LOADERS,
            dl_replies=[invented] * 6 + [f'import pandas as pd\nreturn pd.read_json("{URL}")'],
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
