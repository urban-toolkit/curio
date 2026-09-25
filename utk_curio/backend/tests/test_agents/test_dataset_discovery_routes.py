"""dev/126: resolving a data-loading node INITIATES discovery.

The end-to-end shape the owner asked for: a plan is applied, each data-loading
node carries its own Dataset Finder, and Solve asks that agent for candidates
instead of letting the content builder guess a filename or decline into a dead
end. The node then WAITS for the user's selection — pending, with the remedy
naming the attachment to open — and a second Solve spends no model call.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import content
from utk_curio.backend.app.agents import dataset_resolution as dr
from utk_curio.backend.app.agents import services as services_mod
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_agents import test_routes as _tr
from utk_curio.backend.tests.test_agents.test_verified_rounds import TEMPLATES

_auth = _tr._auth

DFB = "agent.dataflow-builder@1.0.0"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"

CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {
    "external": [{
        "name": "Chicago community areas", "sourceType": "portal",
        "url": "https://data.example.org/areas.geojson",
        "format": "geojson",
        "fit": {"score": 90, "rationale": "the boundaries the goal asks for"},
    }],
    "catalog": [],
}}})


class _Harness:
    """A project with an applied plan whose loader has NO grounded source."""

    def __init__(self, client, user, token, monkeypatch, *, goal=None,
                 discover_replies=None, dl_replies=None):
        self.client, self.user, self.token = client, user, token
        self.ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(self.ukey, templates=TEMPLATES)
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                "outputs": []}
        self.pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        client.post(f"/api/agents/projects/{self.pid}/install", json={"coord": DFB},
                    headers=_auth(token))
        self.att = client.post(
            f"/api/agents/projects/{self.pid}/attachments",
            json={"coord": DFB, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()["attachmentId"]
        self.discover_calls: list = []
        self.dl_calls: list = []
        plan = {
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
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            frame = messages[-1].get("content") or ""
            if "[delegated task" not in frame:
                return plan_reply
            if "discoveryReplyContract" in frame:
                self.discover_calls.append(frame)
                return discover_script[min(len(self.discover_calls) - 1, len(discover_script) - 1)]
            # The loader's OWN content call: nodeContext carries its nodeId
            # (an upstream row would carry it under "id" instead).
            if f'"nodeId": "{getattr(self, "load", "?")}"' in frame:
                self.dl_calls.append(frame)
                return dl_script[min(len(self.dl_calls) - 1, len(dl_script) - 1)]
            return "df = arg[0]\nreturn df.describe()"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )
        self.exec_payloads: list = []

        def _exec(endpoint, payload):
            self.exec_payloads.append(payload)
            return {"stdout": [], "stderr": "",
                    "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: {"status": "verified", "detail": "200 OK"},
        )
        r = client.post(f"/api/agents/projects/{self.pid}/attachments/{self.att}/run",
                        json={"message": "plan it"}, headers=_auth(token))
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        applied = client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/proposals/"
            f"{proposal['proposalId']}/apply", headers=_auth(token),
        ).get_json()
        self.applied = applied
        self.load = next(
            n["id"] for n in applied["appliedGraph"]["nodes"] if str(n["type"]).startswith(DL)
        )
        self.stats = next(
            n["id"] for n in applied["appliedGraph"]["nodes"] if str(n["type"]).startswith(CA)
        )

    def solve(self, node_ids=None):
        payload = {"nodeIds": node_ids} if node_ids else {}
        return self.client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/solve",
            json=payload, headers=_auth(self.token),
        ).get_json()

    def spec(self):
        return projects_storage.read_spec(self.ukey, self.pid)

    def finder_attachment_id(self):
        record = dr.finder_attachment(self.spec(), self.load)
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
                "import pandas as pd\nreturn pd.read_json"
                '("https://data.example.org/areas.geojson")',
            ],
        )
        assert h.solve()["results"][h.load]["status"] == "pending"
        finder_id = h.finder_attachment_id()
        # Record the selection the way the endpoint will (commit 6).
        spec = h.spec()
        part = next(
            p for t in h.session_turns(finder_id) for p in (t.get("content") or [])
            if p.get("type") == "datasetCandidates"
        )
        rows = dr.resolve_picks(part, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ])
        dr.record_selection(spec, finder_id, rows)
        projects_storage.write_spec(h.ukey, h.pid, spec)
        body = h.solve(node_ids=[h.load])
        assert body["results"][h.load]["status"] == "solved"
        # The confirmed source was HANDED to the content child.
        frame = h.dl_calls[-1]
        assert "confirmedSource" in frame
        assert "https://data.example.org/areas.geojson" in frame
        assert len(h.discover_calls) == 1  # resolved: no second discovery


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
            "utk_curio.backend.app.agents.verify.verify_external_source",
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
            "utk_curio.backend.app.agents.verify.verify_external_source",
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
