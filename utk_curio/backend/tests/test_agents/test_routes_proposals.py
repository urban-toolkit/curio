"""Integration tests for the /api/agents proposal routes (routes/proposals.py).

Applying and dismissing what a run proposed. TestNodeCreate,
TestDataflowPlanMint and TestDestructiveReplan also serve the run and
solve tests as helpers."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    _drop_from_lockfile,
)


class TestReviewProposals:
    """Review-before-apply (memo dev/41, DEC-006/REQ-REVIEW-001): the model
    proposes, only the authenticated endpoint applies, digest-checked."""

    COORD = "agent.node-content-builder@1.0.0"

    def _mutate_tail(self, node_id="n1", new_content="print(2)"):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "node.content.write", '
            f'"params": {{"nodeId": "{node_id}", "content": "{new_content}"}}}}}}\n```'
        )

    def _setup(self, client, token, project_id, monkeypatch, replies=None):
        """Save a node, attach the builder, and mock a mint-then-answer run."""
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "node", "targetId": "n1"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []
        script = replies or [self._mutate_tail(), "Proposed — review it above."]

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return script[min(len(calls) - 1, len(script) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="write it"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _turns(self, client, token, project_id, att_id):
        return client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]

    def _spec_node_content(self, user, project_id, node_id="n1"):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), project_id)
        node = next(n for n in spec["dataflow"]["nodes"] if n["id"] == node_id)
        return node.get("content")

    def _proposal_from_run(self, response):
        body = response.get_json()
        return next(p for p in body["content"] if p["type"] == "proposal")

    def test_mutate_request_mints_a_pending_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, token, alice_project, monkeypatch)
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        proposal = self._proposal_from_run(r)
        assert proposal["status"] == "pending"
        assert proposal["pins"]["nodeId"] == "n1"
        assert proposal["preview"] == "print(2)"
        # Nothing mutated; the model was told it awaits review.
        assert self._spec_node_content(user, alice_project) == "print(1)"
        assert "awaits the user's explicit review" in calls[1][-1]["content"]
        # The proposal part persisted with the turn; the mirror is pending.
        turns = self._turns(client, token, alice_project, att_id)
        persisted = next(p for p in turns[1]["content"] if p["type"] == "proposal")
        assert persisted["proposalId"] == proposal["proposalId"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "pending"

    def test_stream_emits_review_required_before_done(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        script = [self._mutate_tail(), "Proposed."]
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            yield script[min(len(calls) - 1, 1)]

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "write it"}, headers=_auth(token),
        )
        events = []
        for block in r.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            events.append((lines["event"], json.loads(lines["data"])))
        kinds = [k for k, _ in events]
        assert kinds.index("tool_result") < kinds.index("review_required") < kinds.index("done")
        review = next(p for k, p in events if k == "review_required")
        assert review["tool"] == "node.content.write"
        assert review["proposalId"]
        done = events[-1][1]
        assert any(p["type"] == "proposal" for p in done["content"])

    def test_the_card_and_its_result_name_the_node_not_its_id(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # #506: both read "node 'n1'", an id the user sees nowhere else, while
        # the chat header names the node by its kind.
        _, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        node = {"id": "n1", "type": "curio.builtin/computation-analysis",
                "title": "Word counts", "content": "print(1)"}
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [node], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        assert proposal["summary"] == "Replace the content of the Python Computation node · Word counts"
        assert proposal["pins"]["nodeId"] == "n1"  # the id stays where the apply checks it

        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r.status_code == 200
        result = self._turns(client, token, alice_project, att_id)[-1]
        text = json.dumps(result, ensure_ascii=False)
        assert "Applied: Python Computation node · Word counts content updated." in text
        assert "node n1" not in text and "(n1)" not in text

    def test_apply_executes_the_write_and_logs_a_result_turn(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        runs_before = ledger.aggregates(_user_dir_key(user))["runs"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["mutationApplied"] is True
        assert self._spec_node_content(user, alice_project) == "print(2)"
        # Apply is deterministic: no quota consumed (dev/41 §4.6).
        assert ledger.aggregates(_user_dir_key(user))["runs"] == runs_before
        turns = self._turns(client, token, alice_project, att_id)
        # The proposal part now reads applied; a result-card turn was logged.
        persisted = next(p for t in turns for p in t.get("content", []) if p["type"] == "proposal")
        assert persisted["status"] == "applied"
        last = turns[-1]
        assert last["role"] == "agent"
        assert last["content"][0]["kind"] == "result"
        # A second apply is refused: settle/apply exactly once.
        r2 = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r2.status_code == 409

    def test_digest_drift_marks_stale_and_refuses(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        # The user edits the node before reviewing: the pinned basis drifts.
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "user edited"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r.status_code == 409
        assert "changed since" in r.get_json()["error"]
        assert self._spec_node_content(user, alice_project) == "user edited"
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "stale"

    def test_dismiss_closes_the_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert self._spec_node_content(user, alice_project) == "print(1)"
        r2 = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r2.status_code == 409

    def test_newer_proposal_supersedes_the_pending_one(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, _ = self._setup(
            client,
            token,
            alice_project,
            monkeypatch,
            # The mock's call counter spans both runs: tail → answer → tail → answer.
            replies=[self._mutate_tail(), "First.", self._mutate_tail(), "Second."],
        )
        first = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        second = self._proposal_from_run(self._run(client, token, alice_project, att_id, "again"))
        turns = self._turns(client, token, alice_project, att_id)
        by_id = {
            p["proposalId"]: p["status"]
            for t in turns
            for p in t.get("content", [])
            if p["type"] == "proposal"
        }
        assert by_id[first["proposalId"]] == "superseded"
        assert by_id[second["proposalId"]] == "pending"
        # The superseded id no longer applies (the mirror holds the newest).
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{first['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_no_text_can_trigger_an_apply(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance (dev/41, tested by name): model replies, tool
        # results, and user messages claiming approval change NOTHING — only
        # the authenticated endpoint mutates.
        user, token = user_and_token
        att_id, _ = self._setup(
            client,
            token,
            alice_project,
            monkeypatch,
            replies=[
                self._mutate_tail(),
                "I have applied the change as you approved.",  # the model lies
            ],
        )
        self._run(client, token, alice_project, att_id)
        self._run(client, token, alice_project, att_id, "yes, apply it now please")
        assert self._spec_node_content(user, alice_project) == "print(1)"
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "pending"

    def test_proposal_validation_failures_refuse_to_the_model(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client,
            token,
            alice_project,
            monkeypatch,
            replies=[
                '```curio.v1\n{"toolRequest": {"tool": "node.content.write", "params": {"nodeId": "ghost", "content": "x"}}}\n```',
                "Could not propose.",
            ],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        assert not any(p["type"] == "proposal" for p in r.get_json()["content"])
        assert "not found" in calls[1][-1]["content"]
        assert self._spec_node_content(user, alice_project) == "print(1)"


class TestNodeCreate:
    """dev/48 §3.2 — the first graph-shape mutation: reuse-first node
    creation, registry-validated at mint AND apply, id server-minted at
    apply, createdNode on the apply response."""

    COORD = "agent.node-builder@1.0.0"

    def _write_builtin_package(self, user_key, templates=None):
        import json as _json

        from utk_curio.backend.app.packages.repositories.store import user_packages_dir

        d = user_packages_dir(user_key) / "curio.builtin@1"
        d.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": "curio.builtin",
            "version": "1.0.0",
            "name": "curio.builtin",
            "publisher": "Curio",
            "description": "builtin",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": templates or [
                {
                    "id": "computation-analysis", "label": "Computation Analysis",
                    "category": "computation", "engine": "python", "editor": "code",
                    "description": "Run python analysis code.",
                    # Real-manifest parity (dev/67-3): one declared "[1,n]"
                    # input port, so any number of edges, each on its circle.
                    "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                },
                {
                    "id": "data-summary", "label": "Data Summary",
                    "category": "computation", "engine": "python", "editor": "code",
                    "description": "Summarize a table.",
                    # Real-manifest parity: one input, one edge.
                    "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                },
                {
                    "id": "data-pool", "label": "Data Pool",
                    "category": "data", "engine": "python", "editor": "none",
                    "hasCode": False, "description": "Holds data.",
                    "inputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                },
                {
                    "id": "merge-flow", "label": "Merge Flow",
                    "category": "data", "engine": "python", "editor": "none",
                    "hasCode": False, "description": "Merges multiple flows.",
                    "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                },
            ],
            "createdAt": "2026-06-01T12:00:00Z",
        }
        (d / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")

    def _create_tail(self, node_type="curio.builtin/computation-analysis", content="print('new')", extra=""):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "node.create", '
            f'"params": {{"nodeType": "{node_type}", "content": "{content}"{extra}}}}}}}\n```'
        )

    def _create_tail_json(self, **params):
        """The same block built with json.dumps (#245) — ``_create_tail`` is an
        f-string and cannot express a multi-line source body."""
        import json as _json

        params.setdefault("nodeType", "curio.builtin/computation-analysis")
        return (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "node.create", "params": params}})
            + "\n```"
        )

    def _setup(self, client, user, token, project_id, monkeypatch, replies=None):
        from utk_curio.backend.app.projects.services import _user_dir_key

        self._write_builtin_package(_user_dir_key(user))
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)", "x": 100, "y": 60}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []
        script = replies or [self._create_tail(), "Proposed — review it above."]

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return script[min(len(calls) - 1, len(script) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="build it"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _proposal_from_run(self, response):
        body = response.get_json()
        return next(p for p in body["content"] if p["type"] == "proposal")

    def _spec_nodes(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), project_id)
        return spec["dataflow"]["nodes"]

    def test_tail_lists_available_templates_for_granted_run(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch, replies=["ok"])
        self._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]
        assert "Available node templates" in system
        assert "- curio.builtin/computation-analysis — Computation Analysis" in system
        # Non-authorable templates are not offered.
        assert "data-pool" not in system

    def test_mint_refuses_unknown_and_non_authorable_types(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(node_type="curio.builtin/not-a-thing"), "done"],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        assert all(p["type"] != "proposal" for p in r.get_json()["content"])
        assert "not an available template" in calls[1][-1]["content"]
        assert len(self._spec_nodes(user, alice_project)) == 1

        att2, calls2 = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(node_type="curio.builtin/data-pool"), "done"],
        )
        self._run(client, token, alice_project, att2)
        assert "does not hold authored content" in calls2[1][-1]["content"]

    def test_mint_then_apply_inserts_node_and_returns_created_node(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch)
        r = self._run(client, token, alice_project, att_id)
        proposal = self._proposal_from_run(r)
        assert proposal["status"] == "pending"
        # dev/119 (DEC-076): the roster's executability rides the card as display.
        assert proposal["pins"] == {"nodeType": "curio.builtin/computation-analysis", "executable": True}
        assert "contentSha256" not in proposal["pins"]  # no digest for a creation
        assert len(self._spec_nodes(user, alice_project)) == 1  # nothing mutated yet

        runs_before = ledger.aggregates(_user_dir_key(user))["runs"]
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["mutationApplied"] is True
        created = body["createdNode"]
        assert created["type"] == "curio.builtin/computation-analysis"
        assert created["content"] == "print('new')"
        # Placement: a gutter right of the existing node's right edge (x 100 plus
        # the default 525 width), on its row, so the two never overlap (#499).
        assert created["x"] == 100 + 525 + 120 and created["y"] == 60.0
        nodes = self._spec_nodes(user, alice_project)
        assert len(nodes) == 2
        inserted = next(n for n in nodes if n["id"] == created["id"])
        assert inserted["content"] == "print('new')"
        # Apply is deterministic — no quota consumed.
        assert ledger.aggregates(_user_dir_key(user))["runs"] == runs_before

    def test_large_content_node_create_mints_and_applies(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """Issue #245 — the reported bug, end to end.

        A node body past the old 1KB params cap was refused by the tail parser
        and the whole reply failed open, so the raw request JSON became the
        chat message and no node ever reached the canvas. The mints have always
        accepted content up to PROPOSAL_CONTENT_MAX_CHARS; only the parser
        disagreed.
        """
        user, token = user_and_token
        source = (
            "import pandas as pd\n\n\n"
            "def summarise(path, column):\n"
            '    """Load a CSV and return the mean of one numeric column."""\n'
            "    df = pd.read_csv(path)\n"
            "    if column not in df.columns:\n"
            '        raise ValueError(f"column {column} missing")\n'
            '    series = pd.to_numeric(df[column], errors="coerce").dropna()\n'
            '    return {"mean": float(series.mean()), "count": int(series.size)}\n'
        ) * 40  # ~14KB: a realistic node, far past the old cap
        assert len(source) > 4096
        # extract_node_content trims the boundary, as it has always done.
        stored = source.strip()
        tail = self._create_tail_json(content=source, title="CSV mean", goal="summarise a column")
        att_id, _ = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[tail, "Proposed a CSV summariser — review it above."],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()

        proposal = self._proposal_from_run(r)
        assert proposal["tool"] == "node.create"
        assert proposal["status"] == "pending"
        # The leak: none of the machine block may survive as chat prose.
        assert "curio.v1" not in body["reply"]
        assert "toolRequest" not in body["reply"]
        assert "nodeType" not in body["reply"]
        assert "import pandas" not in body["reply"]

        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        created = resp.get_json()["createdNode"]
        assert created["content"] == stored  # whole body, not truncated
        nodes = self._spec_nodes(user, alice_project)
        assert len(nodes) == 2
        assert next(n for n in nodes if n["id"] == created["id"])["content"] == stored

        # The transcript logged the result card.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert any("node created" in (t.get("text") or "") for t in turns)

    # ── dev/90 A16: same-run proposal sequences ──────────────────────────────
    # Field regression: one Researcher reply proposed a question note then an
    # answer note; the second mint superseded the first while its transcript
    # part (not yet persisted) stayed "pending" — a live Apply button pointing
    # at a dead proposal. Same-run mints now queue as ONE jointly-pending
    # sequence; a LATER run still supersedes the whole sequence (dev/41).

    def _two_note_run(self, client, user, token, project_id, monkeypatch, extra_replies=()):
        att_id, calls = self._setup(
            client, token=token, user=user, project_id=project_id, monkeypatch=monkeypatch,
            replies=[
                self._create_tail(content="the question"),
                self._create_tail(content="the answer"),
                "Both notes proposed.",
                *extra_replies,
            ],
        )
        r = self._run(client, token, project_id, att_id)
        assert r.status_code == 200
        proposals = [p for p in r.get_json()["content"] if p["type"] == "proposal"]
        assert len(proposals) == 2
        return att_id, proposals, calls

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def test_same_run_sequence_stays_jointly_pending_and_both_apply(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_note_run(client, user, token, alice_project, monkeypatch)
        assert [p["status"] for p in proposals] == ["pending", "pending"]

        first = self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"])
        assert first.status_code == 200
        # The queued sibling is still surfaced as the pending review.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(a for a in cards if a["attachmentId"] == att_id)["activeProposal"]
        assert active["proposalId"] == proposals[1]["proposalId"]
        assert active["status"] == "pending"

        second = self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"])
        assert second.status_code == 200
        contents = [n["content"] for n in self._spec_nodes(user, alice_project)]
        assert "the question" in contents and "the answer" in contents

    def test_same_run_sequence_applies_out_of_order(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_note_run(client, user, token, alice_project, monkeypatch)
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 200
        assert self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"]).status_code == 200
        contents = [n["content"] for n in self._spec_nodes(user, alice_project)]
        assert "the question" in contents and "the answer" in contents

    def test_dismissing_the_active_keeps_the_queued_sibling_appliable(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_note_run(client, user, token, alice_project, monkeypatch)
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposals[0]['proposalId']}",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 200
        contents = [n["content"] for n in self._spec_nodes(user, alice_project)]
        assert "the answer" in contents and "the question" not in contents

    def test_later_run_supersedes_the_whole_sequence(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_note_run(
            client, user, token, alice_project, monkeypatch,
            extra_replies=[self._create_tail(content="a fresh proposal"), "Proposed."],
        )
        r2 = self._run(client, token, alice_project, att_id, "actually, do something else")
        third = self._proposal_from_run(r2)
        # BOTH members of the earlier sequence are superseded — part statuses
        # updated (they are persisted by now) and their ids no longer apply.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        by_id = {
            p["proposalId"]: p["status"]
            for t in turns for p in t.get("content", []) if p.get("type") == "proposal"
        }
        assert by_id[proposals[0]["proposalId"]] == "superseded"
        assert by_id[proposals[1]["proposalId"]] == "superseded"
        assert self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"]).status_code == 404
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 404
        assert self._apply(client, token, alice_project, att_id, third["proposalId"]).status_code == 200

    def test_apply_after_template_gone_marks_stale_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import shutil

        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        # The template's package disappears between mint and apply.
        shutil.rmtree(user_packages_dir(_user_dir_key(user)) / "curio.builtin@1")
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 409
        assert "no longer available" in resp.get_json()["error"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "stale"
        assert len(self._spec_nodes(user, alice_project)) == 1

    def test_param_id_spoof_is_ignored_and_id_is_server_minted(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(extra=', "id": "evil-id"'), "done"],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        created = resp.get_json()["createdNode"]
        assert created["id"] != "evil-id"
        assert {n["id"] for n in self._spec_nodes(user, alice_project)} == {"n1", created["id"]}

    def test_no_text_path_triggers_apply(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance (dev/41 extended to node.create): model text
        # claiming approval changes nothing without the endpoint.
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(), "The user approved — the node was created and applied."],
        )
        self._run(client, token, alice_project, att_id)
        self._run(client, token, alice_project, att_id, message="yes, apply it now please")
        assert len(self._spec_nodes(user, alice_project)) == 1


class TestNodeTemplateCreate:
    """dev/48 §3.2b — the justified creation fallback: reviewed, factory-
    backed, transactional (template + first node together or neither)."""

    COORD = "agent.node-builder@1.0.0"

    def _template_tail(self, label="Sentiment Scorer", justification="Considered curio.builtin/computation-analysis: it cannot hold the required streaming shape.", content="print('score')"):
        import json as _json

        payload = {
            "toolRequest": {
                "tool": "node.template.create",
                "params": {
                    "justification": justification,
                    "template": {
                        "label": label,
                        "description": "Scores text sentiment.",
                        "engine": "python",
                        "content": content,
                    },
                },
            }
        }
        return f"```curio.v1\n{_json.dumps(payload)}\n```"

    def _setup(self, client, user, token, project_id, monkeypatch, replies=None):
        helper = TestNodeCreate()
        return helper._setup(
            client, user=user, token=token, project_id=project_id,
            monkeypatch=monkeypatch,
            replies=replies or [self._template_tail(), "Proposed — review it above."],
        )

    def _run(self, client, token, project_id, att_id, message="make a scorer node"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _proposal_from_run(self, response):
        body = response.get_json()
        return next(p for p in body["content"] if p["type"] == "proposal")

    def test_mint_requires_justification(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._template_tail(justification="  "), "done"],
        )
        r = self._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in r.get_json()["content"])
        assert "the review needs your reasoning" in calls[1][-1]["content"]

    def test_mint_refuses_reuse_territory_collision(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._template_tail(label="Computation Analysis"), "done"],
        )
        self._run(client, token, alice_project, att_id)
        assert "reuse territory" in calls[1][-1]["content"]

    def test_proposal_carries_justification_for_the_review_card(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        assert proposal["tool"] == "node.template.create"
        assert "cannot hold the required streaming shape" in proposal["justification"]
        assert proposal["template"]["label"] == "Sentiment Scorer"
        assert proposal["pins"] == {"templateSlug": "sentiment-scorer"}

    def test_apply_registers_template_installs_and_inserts_node(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["createdTemplate"]["id"] == "curio.agent.sentiment-scorer/sentiment-scorer"
        assert body["createdNode"]["type"] == "curio.agent.sentiment-scorer/sentiment-scorer"
        # Both effects landed: store package + project lockfile + spec node.
        assert (user_packages_dir(key) / "curio.agent.sentiment-scorer@1").is_dir()
        assert "curio.agent.sentiment-scorer@1" in project_packages.get_project_lockfile(key, alice_project)
        nodes = TestNodeCreate()._spec_nodes(user, alice_project)
        assert any(n.get("type") == "curio.agent.sentiment-scorer/sentiment-scorer" for n in nodes)
        # Round-trip (dev/48): the created type is instantiable by plain
        # node.create in a later run — it is now an available template.
        available = {t["id"] for t in packages_templates.available_templates(key, alice_project)}
        assert "curio.agent.sentiment-scorer/sentiment-scorer" in available

    def test_factory_failure_at_apply_is_transactional_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch)
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        # A colliding store package appears between mint and apply → the
        # installer's collision handling surfaces verbatim.
        (user_packages_dir(key) / "curio.agent.sentiment-scorer@1").mkdir(parents=True)
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 409
        # Nothing half-applied: proposal stale, no node inserted.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "stale"
        nodes = TestNodeCreate()._spec_nodes(user, alice_project)
        assert all(n.get("type") != "curio.agent.sentiment-scorer/sentiment-scorer" for n in nodes)

    # #565: the template's own imports are its declared libraries, and the
    # apply is the only install the package ever gets.

    def _apply_importing(self, client, user, token, project_id, monkeypatch, *, pip, imports):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        asked: list[dict] = []

        def _install(deps, on_line=None):
            asked.append(dict(deps))
            return pip(deps)

        monkeypatch.setattr(pip_runner, "install_python_deps", _install)
        monkeypatch.setattr(pip_runner, "import_failures", lambda deps: imports)
        att_id, _ = self._setup(
            client, user, token, project_id, monkeypatch,
            replies=[self._template_tail(content="import shapely\nreturn arg\n"),
                     "Proposed - review it above."],
        )
        proposal = self._proposal_from_run(self._run(client, token, project_id, att_id))
        resp = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        turns = client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        applied = [t.get("text") or "" for t in turns
                   if "node type registered" in (t.get("text") or "")]
        return resp, asked, applied

    def test_apply_installs_the_libraries_the_template_imports(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        user, token = user_and_token
        resp, asked, applied = self._apply_importing(
            client, user, token, alice_project, monkeypatch,
            pip=lambda deps: pip_runner.InstallReport(installed=sorted(deps), skipped=[]),
            imports={},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert asked == [{"shapely": "*"}]
        assert resp.get_json()["createdTemplate"]["importErrors"] == {}
        assert applied and "cannot be imported" not in applied[-1]

    def test_a_library_that_cannot_be_imported_is_reported_on_the_applied_turn(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        user, token = user_and_token
        resp, _, applied = self._apply_importing(
            client, user, token, alice_project, monkeypatch,
            pip=lambda deps: pip_runner.InstallReport(installed=[], skipped=sorted(deps)),
            imports={"shapely": "ImportError: GEOS"},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["createdTemplate"]["importErrors"] == {"shapely": "ImportError: GEOS"}
        assert applied and "shapely cannot be imported (ImportError: GEOS)" in applied[-1]

    def test_a_pip_failure_is_reported_and_the_node_type_stays(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """Reported, not undone: the other file-first installs keep the package
        when pip fails, and the user's fix is a reachable index."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir

        def _fail(deps):
            raise pip_runner.PipInstallError("ERROR: No matching distribution found")

        user, token = user_and_token
        resp, _, applied = self._apply_importing(
            client, user, token, alice_project, monkeypatch, pip=_fail, imports={},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert "No matching distribution" in resp.get_json()["createdTemplate"]["dependencyError"]
        assert applied and "could not be installed" in applied[-1]
        assert (user_packages_dir(_user_dir_key(user)) / "curio.agent.sentiment-scorer@1").is_dir()

    def test_a_hosted_guest_is_refused_before_anything_lands(
        self, client, db, tmp_curio, monkeypatch,
    ):
        """#451's rule on the one store write it did not reach.

        The shared guest is every anonymous visitor, so a package in its store
        is in every visitor's palette, and its libraries would be one pip run
        away. The refusal has to come before the files, not after them.
        """
        from utk_curio.backend import config
        from utk_curio.backend.app.packages.infrastructure import backend_runtime
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.users.models import User, UserSession

        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: True)
        # A hosted guest runs on the deployment's GUEST_LLM_* endpoint, not the
        # DEFAULT_LLM_* one the conftest configures.
        monkeypatch.setattr(config, "GUEST_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(config, "GUEST_LLM_BASE_URL", "http://127.0.0.1:9/v1")
        monkeypatch.setattr(config, "GUEST_LLM_MODEL", "test-model")
        monkeypatch.setattr(config, "GUEST_LLM_API_KEY", "test-key")
        guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                     email="guest@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="guest-token"))
        db.session.commit()
        project = client.post(
            "/api/projects",
            json={"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                  "outputs": []},
            headers=_auth("guest-token"),
        ).get_json()["id"]

        resp, asked, _ = self._apply_importing(
            client, guest, "guest-token", project, monkeypatch,
            pip=lambda deps: None, imports={},
        )

        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert "guest" in resp.get_json()["error"].lower()
        assert asked == []
        assert not (user_packages_dir(_user_dir_key(guest)) / "curio.agent.sentiment-scorer@1").exists()


class TestDataflowPlanMint:
    """dev/52 — a validated dataflowPlan tail on the final reply mints the
    reviewed plan proposal in one step (runtime-minted, never model-requested)."""

    COORD = "agent.dataflow-builder@1.0.0"

    def _plan_tail(self, nodes=None, edges=None):
        import json as _json

        plan = {
            "goal": "heat analysis",
            "nodes": nodes or [
                {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
                 "title": "Load", "intent": "load the data"},
                {"ref": "b", "nodeType": "curio.builtin/computation-analysis",
                 "title": "Analyze", "intent": "compute stats"},
            ],
            "edges": edges if edges is not None else [{"from": "a", "to": "b"}],
        }
        return f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def _setup(self, client, user, token, project_id, monkeypatch, replies=None, coord=None):
        helper = TestNodeCreate()
        helper._write_builtin_package(self._ukey(user))
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)", "x": 10, "y": 20}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        use = coord or self.COORD
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": use}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": use, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []
        script = replies or ["Here is the plan.\n" + self._plan_tail()]

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return script[min(len(calls) - 1, len(script) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _ukey(self, user):
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(user)

    def _run(self, client, token, project_id, att_id, message="plan it"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def test_plan_tail_mints_reviewed_proposal_and_sets_phase(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch)
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "dataflow.plan.write"
        assert proposal["summary"] == "Apply plan · 2 nodes, 1 edge"
        assert "baseGraphDigest" in proposal["pins"]
        assert [n["title"] for n in proposal["plan"]["nodes"]] == ["Load", "Analyze"]
        # The raw plan part was consumed by the mint — no duplicate part.
        assert all(p["type"] != "dataflowPlan" for p in body["content"])
        # The templates roster rode the system turn (plan grants get it too).
        assert "Available node templates" in calls[0][0]["content"]
        # Builder session: plan_review phase persisted on the attachment.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "pending"

    # ── dev/126 (DEC-080): the closure repaired at the point of use ──────

    def test_a_legacy_lockfile_is_repaired_before_the_run_delegates(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The regression test for the owner's session 7c300d0d: a Dataflow
        Builder conversation must never spend a turn on an install proposal for
        one of its OWN required agents. The delegation is scripted so the run
        actually asks for dataset.discover in a project whose lockfile lost the
        Dataset Finder."""
        user, token = user_and_token
        # The candidate row below carries a URL, and the Dataset Finder gate
        # probes one for real; the suite's netguard refuses that. Stubbed as
        # the verification tests in this file stub it.
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"},
        )
        att_id, calls = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                '```curio.v1\n{"delegateRequest": {"capability": "dataset.discover", '
                '"inputs": {"mission": "chicago population density"}}}\n```',
                '{"datasetCandidates": {"lanes": {"external": [{"name": "Chicago portal", '
                '"sourceType": "api", "url": "https://example.org/d.json"}], "catalog": []}}}',
                "Here are the candidates.",
            ],
        )
        _drop_from_lockfile(user, alice_project, "agent.dataset-finder@1.0.0")
        body = self._run(client, token, alice_project, att_id).get_json()
        # No install proposal for a required agent, anywhere in the reply.
        assert all(
            p.get("tool") != "project.install" for p in body["content"] if p["type"] == "proposal"
        )
        # The Dataset Finder is back in the lockfile, and the repair says so.
        installed = client.get(
            f"/api/agents/projects/{alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        assert "agent.dataset-finder@1.0.0" in {a["dirName"] for a in installed}
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        disclosure = next(
            t for t in turns if (t.get("text") or "").startswith("Added Dataset Finder")
        )
        assert "required by Dataflow Builder" in disclosure["text"]

    def test_a_preferred_delegate_keeps_the_reviewed_install_lane(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """`REQ-ORCH-001` is untouched: only requiresAgents members are
        repaired. A merely PREFERRED delegate still reaches the user as a
        reviewed install proposal."""
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                '```curio.v1\n{"delegateRequest": {"capability": "connection.propose", '
                '"inputs": {"subtask": "connect these"}}}\n```',
                "I asked for an install.",
            ],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "project.install"
        assert proposal["pins"]["coord"] == "agent.connection-builder@1.0.0"
        installed = {
            a["dirName"] for a in client.get(
                f"/api/agents/projects/{alice_project}", headers=_auth(token)
            ).get_json()["agents"]
        }
        assert "agent.connection-builder@1.0.0" not in installed

    def test_unavailable_template_yields_error_card_not_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + self._plan_tail(nodes=[
                {"ref": "a", "nodeType": "curio.builtin/not-a-thing",
                 "title": "Load", "intent": "load"},
            ], edges=[])],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        assert all(p["type"] != "proposal" for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Plan not proposable"
        assert "not-a-thing" in card["lines"][0]

    def test_ungranted_plan_part_passes_through_without_mutation_path(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A non-builder agent emitting a plan tail: informational part only.
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.chat-agent@1.0.0",
            replies=["idea!\n" + self._plan_tail()],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        assert all(p["type"] != "proposal" for p in body["content"])
        assert any(p["type"] == "dataflowPlan" for p in body["content"])


class TestPlanTemplateSpellings:
    """dev/93 D3 — the reported loop, and the regression that had never been
    written: no test had ever fed a VERSIONED nodeType into a dataflowPlan.

    The live failure: the Dataflow Builder quoted curio.builtin/data-loading@1
    from the "Installed node templates" list its own run context supplied, was
    refused, fell back to the legacy enum name DATA_LOADING, was refused
    again, and burned 33.1k tokens over four correction rounds. Both spellings
    are ones the system itself produces — the client registry keys descriptors
    versioned, and the runtime prints versioned ids in its own proposal
    previews — so refusing them manufactured an unfixable-looking error.
    """

    def _mint(self, client, user_and_token, alice_project, monkeypatch, nodes, edges=None):
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + helper._plan_tail(nodes=nodes, edges=edges or [])],
        )
        return helper._run(client, token, alice_project, att_id).get_json(), att_id, token

    def test_versioned_node_types_are_proposable(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/computation-analysis@1",
                    "title": "Load", "intent": "load"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        # Proposed, AND the stored plan pins the canonical unversioned id
        # rather than whatever spelling the model happened to send.
        assert proposal["plan"]["nodes"][0]["nodeType"] == (
            "curio.builtin/computation-analysis"
        )

    def test_legacy_enum_node_types_are_proposable(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "COMPUTATION_ANALYSIS",
                    "title": "Load", "intent": "load"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["plan"]["nodes"][0]["nodeType"] == (
            "curio.builtin/computation-analysis"
        )

    def test_mixed_spellings_in_one_plan_all_canonicalise(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A confused model mixes spellings across nodes — likely, given it was
        told three different things. Each canonicalises independently."""
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[
                {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
                 "title": "One", "intent": "i"},
                {"ref": "b", "nodeType": "curio.builtin/computation-analysis@1",
                 "title": "Two", "intent": "i"},
                {"ref": "c", "nodeType": "COMPUTATION_ANALYSIS",
                 "title": "Three", "intent": "i"},
            ],
            edges=[{"from": "a", "to": "b"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert {n["nodeType"] for n in proposal["plan"]["nodes"]} == {
            "curio.builtin/computation-analysis"
        }

    def test_a_plan_may_use_a_non_authorable_template(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The one intended difference from node.create: a plan places a typed
        PLACEHOLDER and its content arrives later from Solve, so a template
        that holds no authored content is legal here and refused there."""
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/data-pool@1",
                    "title": "Pool", "intent": "hold data"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["plan"]["nodes"][0]["nodeType"] == "curio.builtin/data-pool"

    def test_unknown_type_still_refuses_and_names_the_spellings(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/not-a-thing@1",
                    "title": "Load", "intent": "load"}],
        )
        assert all(p["type"] != "proposal" for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Plan not proposable"
        line = " ".join(card["lines"])
        assert "not-a-thing" in line
        # The refusal must name the accepted spellings so a weak local model
        # can self-correct from the message alone.
        assert "@<major>" in line

    def test_bare_slug_stays_ambiguous(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """'data-loading' names no package. Resolving it by guessing a package
        would be worse than refusing, so the refusal stays."""
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "computation-analysis",
                    "title": "Load", "intent": "load"}],
        )
        assert all(p["type"] != "proposal" for p in body["content"])

    def test_versioned_plan_applies_end_to_end(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Nothing may be proposable-but-unappliable: the whole-plan apply
        re-check used to exact-match the same way the mint did."""
        body, att_id, token = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/computation-analysis@1",
                    "title": "Load", "intent": "load"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        applied = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert applied.status_code == 200, applied.get_json()
        user, _ = user_and_token
        nodes = TestNodeCreate()._spec_nodes(user, alice_project)
        created = [n for n in nodes if n.get("id") != "n1"]
        assert created, "the plan's node must exist on the canvas"

    def test_apply_tolerates_a_pre_change_proposal_holding_a_raw_versioned_id(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Edge case 18: a proposal minted BEFORE parse-boundary
        canonicalisation stores a raw versioned nodeType, and its shape digest
        was computed over exactly that string. The apply must canonicalise the
        COMPARISON, not the stored value, or an in-flight proposal goes stale
        on deploy day."""
        from utk_curio.backend.app.agents.application import attachments
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        body, att_id, token = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/computation-analysis@1",
                    "title": "Load", "intent": "load"}],
        )
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        user, _ = user_and_token
        key = _user_dir_key(user)

        # Rewind the stored proposal to what an older build would have written.
        spec = projects_storage.read_spec(key, alice_project)
        stored = attachments.find_proposal(spec, att_id, proposal["proposalId"])
        stored["plan"]["nodes"][0]["nodeType"] = "curio.builtin/computation-analysis@1"
        projects_storage.write_spec(key, alice_project, spec)

        applied = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert applied.status_code == 200, applied.get_json()

    def test_removal_only_plan_still_applies(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The one plan path that always worked — it carries zero nodes, so the
        availability loop never ran, which is why "clear nodes" succeeded at
        12:08 while every node-bearing plan failed. The refactor must not
        break it."""
        import json as _json

        helper = TestDataflowPlanMint()
        user, token = user_and_token
        plan = {"goal": "clear the canvas", "removeNodes": ["n1"]}
        tail = f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch, replies=["clearing.\n" + tail],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        applied = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert applied.status_code == 200, applied.get_json()
        assert TestNodeCreate()._spec_nodes(user, alice_project) == []


class TestDataflowPlanApply:
    """dev/52 — the atomic, ADDITIVE plan apply: whole-graph digest safety,
    server ids, topological placement, builder-session phases."""

    def _mint(self, client, user, token, project_id, monkeypatch, **kw):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, project_id, monkeypatch, **kw)
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    # ── dev/126: a whole-plan apply attaches the plan-node agents ────────

    def _data_loading_plan(self):
        helper = TestDataflowPlanMint()
        return helper._plan_tail(
            nodes=[
                {"ref": "a", "nodeType": "curio.builtin/data-loading",
                 "title": "Load boundaries", "intent": "load the community areas"},
                {"ref": "b", "nodeType": "curio.builtin/computation-analysis",
                 "title": "Analyze", "intent": "compute density"},
            ],
            edges=[{"from": "a", "to": "b"}],
        )

    def _add_data_loading_template(self, user):
        """The fixture package ships no data-loading template; the plan-node
        agents key on that type, so add one to the installed manifest."""
        import json as _json

        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        path = (
            user_packages_dir(_user_dir_key(user)) / "curio.builtin@1" / "manifest.json"
        )
        manifest = _json.loads(path.read_text(encoding="utf-8"))
        if not any(t["id"] == "data-loading" for t in manifest["templates"]):
            manifest["templates"].append({
                "id": "data-loading", "label": "Data Loading",
                "category": "data", "engine": "python", "editor": "code",
                "description": "Load a dataset.",
                "inputPorts": [],
                "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            })
            path.write_text(_json.dumps(manifest), encoding="utf-8")

    def _mint_data_loading_plan(self, client, user, token, project_id, monkeypatch):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, project_id, monkeypatch,
            replies=["Plan.\n" + self._data_loading_plan()],
        )
        self._add_data_loading_template(user)
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def test_whole_plan_apply_attaches_both_agents_per_node_kind(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal = self._mint_data_loading_plan(
            client, user, token, alice_project, monkeypatch
        )
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        ids = {n["goal"].split(" —")[0]: n["id"] for n in body["appliedGraph"]["nodes"]}
        by_node: dict[str, set] = {}
        for row in body["attachedAgents"]:
            by_node.setdefault(row["nodeId"], set()).add(row["agentId"])
        assert by_node[ids["Load boundaries"]] == {
            "agent.node-builder", "agent.dataset-finder",
        }
        assert by_node[ids["Analyze"]] == {"agent.node-builder"}
        assert body["skippedAgents"] == [] or all(
            r["agentId"] == "agent.dataset-finder" for r in body["skippedAgents"]
        )
        # The spec carries them, targeted at those nodes.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        finder = [
            c for c in cards if c["coord"].startswith("agent.dataset-finder@")
        ]
        assert [c["target"] for c in finder] == [
            {"kind": "node", "targetId": ids["Load boundaries"]}
        ]
        # And the applied card says what it attached.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        card = next(
            p for t in reversed(turns) for p in (t.get("content") or [])
            if p.get("title") == "Applied: dataflow plan"
        )
        line = next(l for l in card["lines"] if l.startswith("agents attached:"))
        assert "Node Builder ×2" in line and "Dataset Finder" in line

    def test_both_apply_paths_produce_the_same_attachments(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """dev/126: the per-node apply and the whole-plan apply are two ways to
        apply ONE plan; the attachment set they produce must be identical."""
        user, token = user_and_token
        att_id, proposal = self._mint_data_loading_plan(
            client, user, token, alice_project, monkeypatch
        )
        per_node = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/"
            f"{proposal['proposalId']}/apply-node",
            json={"ref": "a"}, headers=_auth(token),
        ).get_json()
        assert {r["agentId"] for r in per_node["attachedAgents"]} == {
            "agent.node-builder", "agent.dataset-finder",
        }
        assert per_node["attachedAgentId"] == next(
            r["attachmentId"] for r in per_node["attachedAgents"]
            if r["agentId"] == "agent.node-builder"
        )
        # Finishing the same proposal as a whole covers the remaining ref only.
        rest = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert {r["agentId"] for r in rest["attachedAgents"]} == {"agent.node-builder"}
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        node_attachments = sorted(
            (c["coord"].split("@")[0], c["target"]["targetId"])
            for c in cards if c["target"]["kind"] == "node"
        )
        loader = per_node["createdNode"]["id"]
        other = rest["appliedGraph"]["nodes"][0]["id"]
        assert node_attachments == sorted([
            ("agent.dataset-finder", loader),
            ("agent.node-builder", loader),
            ("agent.node-builder", other),
        ])

    def test_apply_inserts_graph_additively_with_server_ids(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200
        body = resp.get_json()
        applied = body["appliedGraph"]
        assert len(applied["nodes"]) == 2 and len(applied["edges"]) == 1
        spec = self._spec(user, alice_project)
        nodes = spec["dataflow"]["nodes"]
        edges = spec["dataflow"]["edges"]
        # Additive: the pre-existing node is untouched, in place.
        assert nodes[0] == {"id": "n1", "content": "print(1)", "x": 10, "y": 20}
        assert len(nodes) == 3 and len(edges) == 1
        load = next(n for n in nodes if n.get("goal", "").startswith("Load"))
        analyze = next(n for n in nodes if n.get("goal", "").startswith("Analyze"))
        # Server-minted ids wired through the ref map; topological columns.
        assert edges[0]["source"] == load["id"] and edges[0]["target"] == analyze["id"]
        # One node's width and a gutter apart, and the first column clear of the
        # existing node (x 10, default width 525), so nothing overlaps (#410).
        assert load["x"] == 10 + 525 + 120
        assert analyze["x"] == load["x"] + 525 + 120
        assert load["content"] == "" and load["goal"] == "Load — load the data"
        # Builder session: applied phase, both nodes pending for Solve.
        session = body["builderSession"]
        assert session["phase"] == "applied"
        assert set(session["nodeRuns"]) == {load["id"], analyze["id"]}
        assert set(session["nodeRuns"].values()) == {"pending"}
        # The session is visible on the attachment card (panel wiring).
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["builderSession"]["phase"] == "applied"

    def test_graph_shape_drift_marks_stale_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        # A node appears between mint and apply → shape digest drift.
        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        spec["dataflow"]["nodes"].append({"id": "user-added", "content": ""})
        projects_storage.write_spec(key, alice_project, spec)
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 409
        assert "replan" in resp.get_json()["error"]
        assert len(self._spec(user, alice_project)["dataflow"]["nodes"]) == 2  # nothing inserted

    def test_content_only_edits_do_not_invalidate_the_plan(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        spec["dataflow"]["nodes"][0]["content"] = "print(999)"  # content edit only
        projects_storage.write_spec(key, alice_project, spec)
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200  # deliberate: additive plans survive content edits

    def test_plan_carried_content_is_refused_at_mint(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # dev/67-5 supersedes dev/52's "trivial code" allowance (67-0: no
        # shortcut) — plans describe intent; content is generated and
        # validated per node after creation. The refusal is corrective.
        user, token = user_and_token
        nodes = [{"ref": "a", "nodeType": "curio.builtin/computation-analysis",
                  "title": "Done", "intent": "already coded", "content": "print('x')"}]
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + helper._plan_tail(nodes=nodes, edges=[]),
                     "fixed.\n" + helper._plan_tail()],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"  # the content-less replan minted
        feedback = calls[1][-1]["content"]
        assert "must not carry content" in feedback
        assert "'a'" in feedback

    def test_dismissed_plan_returns_the_session_to_idle(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        resp = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["builderSession"]["phase"] == "idle"


class TestDestructiveReplan:
    """dev/59 (DEC-049) — reviewed removals and rewires: per-victim digest
    pins, cascade, attachment pruning, nodeRuns hygiene, existing-id wiring."""

    COORD = "agent.dataflow-builder@1.0.0"

    def _revision_tail(self, remove=("old-loader",), nodes=None, edges=None, remove_edges=None):
        import json as _json

        plan = {"goal": "replace the loader"}
        if nodes is not None:
            plan["nodes"] = nodes
        if edges is not None:
            plan["edges"] = edges
        if remove:
            plan["removeNodes"] = list(remove)
        if remove_edges:
            plan["removeEdges"] = list(remove_edges)
        return f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def _new_node(self, ref="a", title="API Fetch"):
        return {"ref": ref, "nodeType": "curio.builtin/computation-analysis",
                "title": title, "intent": "fetch from the api"}

    def _setup(self, client, user, token, project_id, monkeypatch, replies,
               cleaner_type="curio.builtin/computation-analysis"):
        from utk_curio.backend.app.projects.services import _user_dir_key

        TestNodeCreate()._write_builtin_package(_user_dir_key(user))
        spec = {"dataflow": {"nodes": [
            {"id": "old-loader", "type": "curio.builtin/computation-analysis",
             "content": "load_csv()", "goal": "Load CSV", "x": 10, "y": 20},
            {"id": "cleaner", "type": cleaner_type,
             "content": "clean()", "goal": "Clean", "x": 430, "y": 20},
        ], "edges": [
            {"id": "edge-1", "source": "old-loader", "target": "cleaner"},
        ], "packages": []}}
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": spec, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="replace the loader"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _proposal(self, response):
        return next(p for p in response.get_json()["content"] if p["type"] == "proposal")

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def test_replace_flow_end_to_end(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(
                nodes=[self._new_node()],
                edges=[{"from": "a", "to": "cleaner"}],  # wire to an EXISTING node
            )],
        )
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        # DEC-049: victim pinned by content; the card data names it.
        assert "old-loader" in proposal["pins"]["removeContentSha256"]
        (removal,) = proposal["plan"]["removals"]
        assert removal == {"id": "old-loader", "label": "Load CSV",
                           "nodeType": "curio.builtin/computation-analysis",
                           "contentChars": len("load_csv()")}
        assert proposal["plan"]["cascadeCount"] == 1  # edge-1 dies with it
        assert "removes 1 node" in proposal["summary"]
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        applied = body["appliedGraph"]
        assert applied["removedNodeIds"] == ["old-loader"]
        assert applied["removedEdgeIds"] == ["edge-1"]
        spec = self._spec(user, alice_project)
        ids = {n["id"] for n in spec["dataflow"]["nodes"]}
        assert "old-loader" not in ids and "cleaner" in ids
        # The preserved node is byte-identical (the session's contract).
        cleaner = next(n for n in spec["dataflow"]["nodes"] if n["id"] == "cleaner")
        assert cleaner["content"] == "clean()" and cleaner["x"] == 430
        # The new edge wires the created node to the EXISTING cleaner.
        (edge,) = spec["dataflow"]["edges"]
        assert edge["target"] == "cleaner"
        assert edge["source"] == applied["nodes"][0]["id"]

    def test_editing_a_victim_after_mint_makes_apply_stale(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(nodes=[self._new_node()])],
        )
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        # The user edits the doomed node's content (shape digest unchanged!).
        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        next(n for n in spec["dataflow"]["nodes"] if n["id"] == "old-loader")["content"] = "precious_new_work()"
        projects_storage.write_spec(key, alice_project, spec)
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 409
        assert "about to remove changed" in resp.get_json()["error"]
        # Nothing died: the edited node and its edge survive.
        spec = self._spec(user, alice_project)
        assert any(n["id"] == "old-loader" for n in spec["dataflow"]["nodes"])
        assert any(e["id"] == "edge-1" for e in spec["dataflow"]["edges"])

    def test_removal_prunes_attachments_and_node_runs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(nodes=[self._new_node()])],
        )
        # A node-target attachment on the victim (dies with it, dev/32) …
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.node-content-builder@1.0.0"}, headers=_auth(token))
        victim_att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.node-content-builder@1.0.0", "target": {"kind": "node", "targetId": "old-loader"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        # … and a stale nodeRuns entry for it in the builder session.
        from utk_curio.backend.app.agents.application import attachments as attachments_mod
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        record = attachments_mod.get_attachment(spec, att_id)
        record["builderSession"] = {"phase": "applied", "appliedPlanId": "prev",
                                    "nodeRuns": {"old-loader": "pending", "cleaner": "solved"}}
        projects_storage.write_spec(key, alice_project, spec)
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        # The victim's attachment is gone; the builder's survives.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        card_ids = {c["attachmentId"] for c in cards}
        assert victim_att not in card_ids and att_id in card_ids
        # nodeRuns: victim dropped, survivor kept, new pending node joined.
        runs = body["builderSession"]["nodeRuns"]
        assert "old-loader" not in runs
        assert runs["cleaner"] == "solved"
        assert "pending" in runs.values().__iter__().__next__() or any(
            s == "pending" for s in runs.values()
        )

    def test_remove_only_plan_applies(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Cleanup.\n" + self._revision_tail(remove=("old-loader", "cleaner"))],
        )
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert sorted(body["appliedGraph"]["removedNodeIds"]) == ["cleaner", "old-loader"]
        assert self._spec(user, alice_project)["dataflow"]["nodes"] == []
        assert body["builderSession"]["phase"] == "ready"

    def test_unknown_removal_targets_feed_correction_rounds(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                "Revising.\n" + self._revision_tail(remove=("ghost-node",), nodes=[self._new_node()]),
                "Fixed.\n" + self._revision_tail(nodes=[self._new_node()]),
            ],
        )
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        assert proposal["status"] == "pending"
        feedback = calls[1][-1]["content"]
        assert "'ghost-node' is not a node in the saved dataflow" in feedback

    def test_additive_plans_carry_no_removal_pins(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Adding.\n" + self._revision_tail(remove=(), nodes=[self._new_node()])],
        )
        proposal = self._proposal(self._run(client, token, alice_project, att_id))
        assert "removeContentSha256" not in proposal["pins"]
        assert "removals" not in proposal["plan"]
        assert proposal["summary"] == "Apply plan · 1 node, 0 edges"


class TestPerNodePlanApply:
    """dev/67-5 — Simulation Mode: create. Per-node Apply narrows the plan
    proposal (which stays pending), editable goals overlay creation, and
    sequential per-node application reproduces the whole-plan nodes."""

    def _mint(self, client, user, token, project_id, monkeypatch, plan=None):
        import json as _json

        helper = TestDataflowPlanMint()
        if plan is None:
            reply = None  # helper default: 2 nodes a→b
            att_id, _ = helper._setup(client, user, token, project_id, monkeypatch)
        else:
            reply = f"Plan.\n```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"
            att_id, _ = helper._setup(
                client, user, token, project_id, monkeypatch, replies=[reply],
            )
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def _apply_node(self, client, token, project_id, att_id, proposal_id, ref):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        )

    def _spec_nodes(self, user, project_id):
        # The helper's seeded spec carries a baseline node "n1" — the plan's
        # creations are everything else.
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        nodes = projects_storage.read_spec(_user_dir_key(user), project_id)["dataflow"]["nodes"]
        return [n for n in nodes if n.get("id") != "n1"]

    def test_apply_node_creates_one_node_and_keeps_the_proposal_pending(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        body = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref).get_json()
        assert body["status"] == "pending"  # more refs remain
        created = body["createdNode"]
        assert created["content"] == ""  # never a knowingly-unresolved shortcut
        nodes = self._spec_nodes(user, alice_project)
        assert [n["id"] for n in nodes] == [created["id"]]  # exactly ONE node
        session = body["builderSession"]
        assert session["phase"] == "simulating"
        assert session["nodeStates"][ref] == "created"
        assert session["nodeRuns"][created["id"]] == "pending"
        # The second ref is still planned; the mirror survives reloads.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
        assert active["status"] == "pending"
        assert active["appliedRefs"] == [ref]

    def test_apply_node_is_idempotent_per_ref(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        first = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref).get_json()
        second = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref).get_json()
        assert second["status"] == "already-applied"
        assert second["nodeId"] == first["createdNode"]["id"]
        assert len(self._spec_nodes(user, alice_project)) == 1

    def test_edited_goal_overlays_creation(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        r = client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/plan-goals",
            json={"ref": ref, "goal": "Load ONLY the 2024 heat data"},
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["editedGoals"] == {ref: "Load ONLY the 2024 heat data"}
        body = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref).get_json()
        assert body["createdNode"]["goal"] == "Load ONLY the 2024 heat data"

    def test_goal_edit_guards(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        base = f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/plan-goals"
        assert client.patch(base, json={"ref": "ghost", "goal": "x"}, headers=_auth(token)).status_code == 404
        assert client.patch(
            base, json={"ref": proposal["plan"]["nodes"][0]["ref"], "goal": "  "},
            headers=_auth(token),
        ).status_code == 422

    def test_sequential_application_reproduces_the_whole_plan_nodes(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        for node in proposal["plan"]["nodes"]:
            r = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], node["ref"])
            assert r.status_code == 200
        created = self._spec_nodes(user, alice_project)
        assert len(created) == len(proposal["plan"]["nodes"])
        # Positions come from the ONE mint-time layout — distinct columns for
        # the a→b chain, exactly where the whole-plan apply places them.
        assert created[0]["x"] != created[1]["x"]
        assert {n["goal"].split(" — ")[0] for n in created} == {
            n["title"] for n in proposal["plan"]["nodes"]
        }
        # dev/71: the LAST apply progressively connected the edge and
        # completed the structure — the graph never waits for a connect stage.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
        assert active["status"] == "applied"
        assert active["edgeStates"] == {"0": "applied"}
        assert sorted(active["appliedRefs"]) == sorted(
            n["ref"] for n in proposal["plan"]["nodes"]
        )

    def test_whole_plan_apply_after_partial_wires_edges_to_real_ids(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        first_ref = proposal["plan"]["nodes"][0]["ref"]
        first = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], first_ref).get_json()
        body = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        # The already-created ref is NOT duplicated; the edge wires to it.
        assert len(self._spec_nodes(user, alice_project)) == len(proposal["plan"]["nodes"])
        (edge,) = [e for e in body["appliedGraph"]["edges"]]
        assert edge["source"] == first["createdNode"]["id"]

    def test_dismiss_after_partial_keeps_created_nodes(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref)
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}",
            headers=_auth(token),
        )
        assert r.status_code == 200
        # The created node is a real reviewed node — it survives the dismissal.
        assert len(self._spec_nodes(user, alice_project)) == 1
        # Remaining refs died with the proposal.
        assert self._apply_node(
            client, token, alice_project, att_id, proposal["proposalId"],
            proposal["plan"]["nodes"][1]["ref"],
        ).status_code == 409

    def test_expects_rides_the_plan_card(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "g", "nodes": [
            {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
             "title": "Load", "intent": "load it",
             "expects": "in: none · out: dataframe"},
        ], "edges": []}
        _, proposal = self._mint(client, user, token, alice_project, monkeypatch, plan=plan)
        assert proposal["plan"]["nodes"][0]["expects"] == "in: none · out: dataframe"


class TestPlanFanInValidation:
    """dev/67-3 (DEC-051) — invalid multi-input topology is unmintable: fan-in
    validates against the rendered template capacity BEFORE anything
    materializes, the corrective error names the Merge resolution, and apply
    assigns real merge slot handles so plan-created merges work WITHOUT a
    reload."""

    def _plan_reply(self, plan):
        import json as _json

        return f"Plan.\n```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def _node(self, ref, node_type="curio.builtin/computation-analysis"):
        return {"ref": ref, "nodeType": node_type, "title": ref.upper(),
                "intent": f"do {ref}"}

    def test_fanin_into_single_input_node_refuses_then_merge_replan_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        single = "curio.builtin/data-summary"
        bad = {"goal": "g", "nodes": [self._node("a"), self._node("b"), self._node("c", single)],
               "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}]}
        good = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"),
                          self._node("m", "curio.builtin/merge-flow"), self._node("c", single)],
                "edges": [{"from": "a", "to": "m"}, {"from": "b", "to": "m"},
                          {"from": "m", "to": "c"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad), self._plan_reply(good)],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"  # the merge replan minted
        feedback = calls[1][-1]["content"]
        assert "accepts 1 input" in feedback
        assert "curio.builtin/merge-flow" in feedback  # the named resolution

    def test_existing_target_counts_surviving_edges(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDestructiveReplan()  # seeds old-loader → cleaner
        bad = "Add.\n" + helper._revision_tail(
            remove=(), nodes=[helper._new_node()], edges=[{"from": "a", "to": "cleaner"}],
        )
        good = "Fixed.\n" + helper._revision_tail(
            remove=("old-loader",), nodes=[helper._new_node()],
            edges=[{"from": "a", "to": "cleaner"}],
        )
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch, replies=[bad, good],
            cleaner_type="curio.builtin/data-summary",
        )
        proposal = helper._proposal(helper._run(client, token, alice_project, att_id))
        # Removing old-loader frees cleaner's single input — the replan mints.
        assert proposal["status"] == "pending"
        feedback = calls[1][-1]["content"]
        assert "plus 1 existing connection" in feedback

    def test_merge_apply_assigns_real_slot_handles(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        plan = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"),
                          self._node("m", "curio.builtin/merge-flow")],
                "edges": [{"from": "a", "to": "m", "toHandle": "in_3"},
                          {"from": "b", "to": "m"}]}
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(plan)],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        body = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        applied = body["appliedGraph"]["edges"]
        # The named slot is honored; the unnamed edge takes the lowest free.
        assert sorted(e["targetHandle"] for e in applied) == ["in_0", "in_3"]
        assert all(e["sourceHandle"] == "out" for e in applied)
        # Persisted, not just reported — the reload-heals era is over.
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        spec_handles = sorted(
            e.get("targetHandle") for e in spec["dataflow"]["edges"]
        )
        assert spec_handles == ["in_0", "in_3"]

    def test_fanin_into_a_growing_node_mints_and_takes_a_circle_per_edge(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        # The computation template declares one "[1,n]" port: no Merge needed.
        plan = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"), self._node("c"), self._node("t")],
                "edges": [{"from": "a", "to": "t"}, {"from": "b", "to": "t", "toHandle": "in_2"},
                          {"from": "c", "to": "t"}]}
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(plan)],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        body = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        # A named free circle is honored; the others take the first free ones.
        assert sorted(e["targetHandle"] for e in body["appliedGraph"]["edges"]) == ["in", "in_1", "in_2"]
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert sorted(e.get("targetHandle") for e in spec["dataflow"]["edges"]) == ["in", "in_1", "in_2"]

    def test_bad_merge_slot_name_feeds_correction(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        bad = {"goal": "g",
               "nodes": [self._node("a"), self._node("m", "curio.builtin/merge-flow")],
               "edges": [{"from": "a", "to": "m", "toHandle": "in_9"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad),
                     "Fixed.\n" + helper._plan_tail()],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        assert "merge inputs are in_0..in_4" in calls[1][-1]["content"]


class TestPlanEdgeApply:
    """dev/67-8 — the connection review stage: per-edge apply over the pinned
    plan, validated against the CURRENT spec, partial success honest and
    named; completion flips the proposal to applied."""

    def _mint(self, client, user, token, project_id, monkeypatch):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, project_id, monkeypatch)
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def _apply_node(self, client, token, project_id, att_id, proposal_id, ref):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()

    def _apply_edges(self, client, token, project_id, att_id, proposal_id, body=None):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply-edges",
            json=body or {}, headers=_auth(token),
        )

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def test_edges_render_by_name_on_the_plan_part(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        _, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        (edge_row,) = proposal["plan"]["edges"]
        assert edge_row["fromLabel"] == "Load" and edge_row["toLabel"] == "Analyze"

    def test_edges_refuse_until_created_then_connect_progressively(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        # Explicit connect before creation → the edge refuses BY NAME.
        body = self._apply_edges(client, token, alice_project, att_id, pid).get_json()
        assert body["results"]["0"]["status"] == "refused"
        assert "create 'Load' first" in body["results"]["0"]["reason"]
        assert body["edgeStates"] == {"0": "refused"}
        # dev/71: applying the nodes connects PROGRESSIVELY — the second
        # apply draws the edge (real handles) and completes the structure.
        first = self._apply_node(client, token, alice_project, att_id, pid, refs[0])
        assert first["createdEdges"] == []  # the other endpoint is missing
        created_b = self._apply_node(client, token, alice_project, att_id, pid, refs[1])
        (created_edge,) = created_b["createdEdges"]
        assert created_edge["target"] == created_b["createdNode"]["id"]
        assert created_edge["sourceHandle"] == "out" and created_edge["targetHandle"] == "in"
        spec_edges = self._spec(user, alice_project)["dataflow"]["edges"]
        assert any(e.get("id") == created_edge["id"] for e in spec_edges)
        assert created_b["status"] == "applied"  # structure complete
        assert created_b["builderSession"]["phase"] == "applied"  # nodes pend Solve
        # The connect stage is a no-op remainder now.
        r = self._apply_edges(client, token, alice_project, att_id, pid)
        assert r.status_code == 409  # the proposal is applied — no longer pending

    def test_manual_edge_applies_as_noop_and_fanin_refuses_by_name(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        created_a = self._apply_node(client, token, alice_project, att_id, pid, refs[0])
        # The user manually pre-wires the planned connection: they create the
        # target node themselves? No — they draw source → (future b) later;
        # here: create b's node id is unknown, so wire after creating b is
        # impossible to pre-empt. Instead: the sweep's no-op path is exercised
        # by wiring source → an EXISTING node the plan also targets. Simplest
        # faithful shape: apply b, delete the auto edge, draw it manually,
        # then retry the explicit connect stage → no-op, no duplicate.
        created_b = self._apply_node(client, token, alice_project, att_id, pid, refs[1])
        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        auto_edge = next(
            e for e in spec["dataflow"]["edges"]
            if e.get("target") == created_b["createdNode"]["id"]
        )
        spec["dataflow"]["edges"] = [
            e for e in spec["dataflow"]["edges"] if e is not auto_edge
        ]
        spec["dataflow"]["edges"].append({
            "id": "manual-1",
            "source": created_a["createdNode"]["id"],
            "target": created_b["createdNode"]["id"],
        })
        # Un-mark the edge so the stage retries it (simulating a user redo).
        record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
        record["activeProposal"]["edgeStates"] = {}
        record["activeProposal"]["status"] = "pending"
        projects_storage.write_spec(key, alice_project, spec)
        body = self._apply_edges(client, token, alice_project, att_id, pid).get_json()
        assert body["results"]["0"]["status"] == "applied"
        assert body["results"]["0"]["note"] == "already connected"
        assert body["createdEdges"] == []
        edges = self._spec(user, alice_project)["dataflow"]["edges"]
        assert len([e for e in edges if e.get("target") == created_b["createdNode"]["id"]]) == 1

    def test_fanin_refusal_names_the_merge_resolution(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        self._apply_node(client, token, alice_project, att_id, pid, refs[0])
        # dev/71: the conflicting feed exists BEFORE the target is created —
        # the progressive sweep must refuse (fan-in) yet still create the node.
        key = _user_dir_key(user)
        # Pre-wire the baseline node into... the target doesn't exist yet, so
        # seed the conflict right after creation via the sweep ordering: the
        # sweep runs inside apply-node, so instead the conflict targets the
        # FIRST node — plan edge Load→Analyze; feed Analyze from n1 by
        # applying b, whose sweep sees n1→b? n1→b must pre-exist b. Simplest
        # honest setup: refuse at the EXPLICIT stage after a manual conflict.
        created_b = self._apply_node(client, token, alice_project, att_id, pid, refs[1])
        # The sweep already connected Load→Analyze; a SECOND feed would now
        # be refused by onConnect/mint — assert the stage-level refusal shape
        # by resetting the edge and adding the conflict.
        spec = projects_storage.read_spec(key, alice_project)
        auto_edge = next(
            e for e in spec["dataflow"]["edges"]
            if e.get("target") == created_b["createdNode"]["id"]
        )
        spec["dataflow"]["edges"] = [
            e for e in spec["dataflow"]["edges"] if e is not auto_edge
        ]
        spec["dataflow"]["edges"].append({
            "id": "manual-feed",
            "source": "n1",  # the helper's seeded baseline node
            "target": created_b["createdNode"]["id"],
        })
        record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
        record["activeProposal"]["edgeStates"] = {}
        record["activeProposal"]["status"] = "pending"
        projects_storage.write_spec(key, alice_project, spec)
        body = self._apply_edges(client, token, alice_project, att_id, pid).get_json()
        assert body["results"]["0"]["status"] == "refused"
        assert "merge-flow" in body["results"]["0"]["reason"]
        assert body["status"] == "pending"  # a refused edge never completes


class TestPackageBuilderTools:
    """dev/89 commit 8 — package.draft.apply: the Package Builder's ONE
    authoring mutate contract. Mint runs the isolated build service and
    persists bounded provenance; Apply promotes the exact reviewed artifact
    digest, inserts the requested nodes server-side (normalized appearance at
    metadata.appearance), and tells the frontend to refresh registries before
    painting (registry-before-canvas)."""

    COORD = "agent.package-builder@1.0.0"
    TARGET = "ai.agent.notes@1"

    def _draft_params(self, *, color="pink", template_id="note-kind"):
        return {
            "mode": "create",
            "target": self.TARGET,
            "manifest": {
                "id": "ai.agent.notes",
                "version": "1.0.0",
                "name": "Agent Notes",
                "publisher": "Agent",
                "description": "Post-it style notes",
                "license": "MIT",
                "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
                "permissions": [],
                "dependencies": {"packages": {}, "python": {}, "js": {}},
                "templates": [{
                    "id": template_id, "label": "Research note",
                    "category": "visualization", "engine": "python",
                    "editor": "code", "hasCode": True, "hasWidgets": False,
                    "hasGrammar": False, "inputPorts": [], "outputPorts": [],
                    "templateDir": f"starters/{template_id}",
                    "defaultTemplate": f"starters/{template_id}/Default.py",
                }],
            },
            "files": {
                f"starters/{template_id}/Default.py": {"text": "return arg\n"},
            },
            "nodes": [{
                "templateId": template_id,
                "title": "Research note",
                "content": "# Findings\nweb-search results here",
                "appearance": {"backgroundColor": color},
            }],
        }

    def _draft_tail(self, params):
        import json as _json

        return (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.draft.apply",
                                           "params": params}})
            + "\n```"
        )

    def _setup(self, client, token, project_id, monkeypatch, replies):
        client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": self.COORD}, headers=_auth(token),
        )
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="build a notes package"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    @pytest.fixture(autouse=True)
    def _fresh_build_jobs(self):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        yield
        build_jobs.reset_registry()

    def test_mint_and_apply_full_flow(self, client, user_and_token, tmp_curio,
                                      alice_project, monkeypatch):
        from utk_curio.backend.app.packages.application.project_packages import get_project_lockfile
        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._draft_tail(self._draft_params()), "Proposed — review above."],
        )
        run = self._run(client, token, alice_project, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == self.TARGET
        artifact_digest = proposal["pins"]["artifactDigest"]
        assert len(artifact_digest) == 64

        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["mutationApplied"] is True
        assert body["requiresRegistryRefresh"] is True
        assert body["installedPackage"]["dirName"] == self.TARGET

        with client.application.app_context():
            user_key = _user_dir_key(user)
        # Installed in the store, locked in the project.
        assert (package_dir(user_key, self.TARGET) / "manifest.json").is_file()
        with client.application.app_context():
            assert self.TARGET in get_project_lockfile(user_key, alice_project)
        # The created node persisted with the canonical appearance shape and
        # the normalized palette hex (never the raw name).
        created = body["createdNodes"][0]
        assert created["type"] == "ai.agent.notes/note-kind@1"
        assert created["metadata"]["appearance"]["backgroundColor"] == "#fbd3e0"
        assert created["title"] == "Research note"
        spec = projects_storage.read_spec(user_key, alice_project)
        node = next(n for n in spec["dataflow"]["nodes"] if n["id"] == created["id"])
        assert node["metadata"]["appearance"]["backgroundColor"] == "#fbd3e0"

    def test_invalid_draft_refuses_at_mint(self, client, user_and_token, tmp_curio,
                                           alice_project, monkeypatch):
        _, token = user_and_token
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._draft_tail(self._draft_params(color="rgb(1,2,3)")), "ok"],
        )
        run = self._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        # The refusal reached the model as a tool result it can revise from.
        assert "invalid build request" in calls[1][-1]["content"]

    def test_apply_refuses_expired_artifact_as_stale(self, client, user_and_token,
                                                     tmp_curio, alice_project,
                                                     monkeypatch):
        from utk_curio.backend.app.packages.repositories import staging as build_staging
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._draft_tail(self._draft_params()), "Proposed."],
        )
        run = self._run(client, token, alice_project, att_id)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        with client.application.app_context():
            user_key = _user_dir_key(user)
        build_staging.discard_artifact(user_key, proposal["pins"]["artifactDigest"])
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 409
        assert "no longer be applied" in resp.get_json()["error"]

    def test_insert_node_appearance_round_trip_unit(self):
        # dev/89 typed round-trip: _insert_node persists the canonical
        # metadata.appearance shape; omitting it stays byte-identical.
        from utk_curio.backend.app.agents.application.proposals.apply import _insert_node

        spec = {"dataflow": {"nodes": [], "edges": []}}
        plain = _insert_node(spec, "a.b/kind@1", "content", None)
        assert "metadata" not in plain and "title" not in plain
        colored = _insert_node(
            spec, "a.b/kind@1", "content", None,
            appearance={"backgroundColor": "#fef3c0"}, title="Note")
        assert colored["metadata"] == {"appearance": {"backgroundColor": "#fef3c0"}}
        assert colored["title"] == "Note"


class TestPackageBuilderTargetErgonomics:
    """dev/90 A4 — the live-transcript regression: a create draft WITHOUT
    target mints (identity = manifest.id@major), and a single-segment id gets
    a refusal naming the reverse-DNS grammar so the agent can self-correct
    instead of concluding the service is broken."""

    def test_create_without_target_mints(self, client, user_and_token, tmp_curio,
                                         alice_project, monkeypatch):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        params = helper._draft_params()
        params.pop("target")
        att_id, _ = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(params), "Proposed."],
        )
        run = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        assert proposal["pins"]["target"] == "ai.agent.notes@1"  # derived
        build_jobs.reset_registry()

    def test_single_segment_id_refusal_is_diagnosable(self, client, user_and_token,
                                                      tmp_curio, alice_project,
                                                      monkeypatch):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        params = helper._draft_params()
        params.pop("target")
        params["manifest"] = dict(params["manifest"], id="curio-notes")
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(params), "ok"],
        )
        run = helper._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        refusal = calls[1][-1]["content"]
        assert "reverse-DNS" in refusal
        assert "curio.notes" in refusal  # the fix is IN the refusal


class TestBackendDraftEndToEnd:
    """dev/91 commit 4 — a backend-bearing draft through the WHOLE lane:
    mint (build + policy scan + real-worker probe) → the card states the
    trust edge → Apply promotes + pins the entry digest → the new
    /api/packages/<dir>/backend/<handler> route computes through a sandboxed
    worker → tampering refuses with reinstall guidance."""

    TARGET = "ai.agent.wordcount@1"

    def _backend_draft_params(self):
        return {
            "mode": "create",
            "manifest": {
                "id": "ai.agent.wordcount",
                "version": "1.0.0",
                "name": "Word Count",
                "publisher": "Agent",
                "description": "Server-side word counting",
                "license": "MIT",
                "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
                "permissions": ["server-code"],
                "dependencies": {"packages": {}, "python": {}, "js": {}},
                "backend": {
                    "entry": "backend/handler.py",
                    "handlers": [{"name": "word-count", "timeoutClass": "quick"}],
                },
                "templates": [{
                    "id": "word-count-kind", "label": "Word count",
                    "category": "computation", "engine": "python",
                    "editor": "none", "hasCode": False, "hasWidgets": False,
                    "hasGrammar": False, "inputPorts": [],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                    "backendHandler": "word-count",
                }],
            },
            "files": {
                "backend/handler.py": {
                    "text": "def handle(payload):\n"
                            "    return {'words': len(str(payload.get('text', '')).split())}\n",
                },
            },
        }

    @pytest.fixture(autouse=True)
    def _fresh_build_jobs(self):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        yield
        build_jobs.reset_registry()

    def test_full_lane_mint_apply_invoke_tamper(self, client, user_and_token,
                                                tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.infrastructure import backend_runtime
        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestPackageBuilderTools()
        att_id, _ = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(self._backend_draft_params()),
                     "Proposed — review above."],
        )
        run = helper._run(client, token, alice_project, att_id,
                          message="build a word counter with a backend")
        assert run.status_code == 200, run.get_data(as_text=True)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        # dev/91 §5: the trust edge is ON the card before Apply.
        assert proposal["backend"] == {
            "handlers": [{"name": "word-count", "timeoutClass": "quick"}],
            "permissions": ["server-code"],
            "network": False,
        }
        assert "server-side code" in proposal["preview"]
        assert "word-count" in proposal["preview"]

        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)

        with client.application.app_context():
            user_key = _user_dir_key(user)
        # The install authority pinned the entry digest.
        pinned = backend_runtime.pinned_entry_digest(user_key, self.TARGET)
        assert pinned is not None and len(pinned) == 64

        # The route computes through a sandboxed worker.
        invoke = client.post(
            f"/api/packages/{self.TARGET}/backend/word-count",
            json={"payload": {"text": "one two three"}},
            headers=_auth(token),
        )
        assert invoke.status_code == 200, invoke.get_data(as_text=True)
        body = invoke.get_json()
        assert body["reply"] == {"contract": "curio.pkgbackend.v1", "ok": True,
                                 "result": {"words": 3}}
        assert body["entryDigest"] == pinned

        # Post-install tampering refuses with reinstall guidance (§6.1).
        entry = package_dir(user_key, self.TARGET) / "backend" / "handler.py"
        entry.chmod(0o644)
        entry.write_text("def handle(payload):\n    return {'tampered': True}\n",
                         encoding="utf-8")
        tampered = client.post(
            f"/api/packages/{self.TARGET}/backend/word-count",
            json={"payload": {}}, headers=_auth(token),
        )
        assert tampered.status_code == 409
        assert "reinstall" in tampered.get_json()["error"]


class TestRestartHonestyOnApply:
    """dev/92 B-2: an Apply whose pip step ACTUALLY changed shared libraries
    says so — on the apply payload and in the result turn's text; idempotent
    (skipped-only) installs stay silent."""

    @pytest.fixture(autouse=True)
    def _fresh_build_jobs(self):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        yield
        build_jobs.reset_registry()

    def _apply_draft_with_pip(self, client, token, alice_project, monkeypatch,
                              *, installed, skipped, import_errors=None):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "install_python_deps",
            lambda deps, on_line=None: pip_runner.InstallReport(
                installed=list(installed), skipped=list(skipped)),
        )
        # The probe spawns a real interpreter, so it is always stubbed here.
        monkeypatch.setattr(
            pip_runner, "import_failures", lambda deps: dict(import_errors or {}),
        )
        helper = TestPackageBuilderTools()
        params = helper._draft_params()
        # The packager derives manifest deps from the SBOM report — declared
        # python deps ride the REQUEST-level dependencies field.
        params["dependencies"] = {"python": {"weather-sdk": "1.2.0"}}
        att_id, _ = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(params), "Proposed."],
        )
        run = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        return resp.get_json(), turns

    def test_installed_libs_surface_on_payload_and_result_turn(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        body, turns = self._apply_draft_with_pip(
            client, token, alice_project, monkeypatch,
            installed=["weather-sdk"], skipped=[])
        assert body["restartRecommended"] == {"libs": ["weather-sdk"]}
        applied_text = next(t["text"] for t in turns
                            if "Applied: package" in (t.get("text") or ""))
        assert "Restart Curio to pick up weather-sdk" in applied_text
        assert "previously loaded versions" in applied_text

    def test_a_library_that_cannot_be_imported_is_reported_on_the_applied_turn(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """The turn that claims the package installed must not overclaim.

        pip counts metadata as satisfaction, so a wheel whose native extension
        cannot load promotes "successfully". This turn is the last place the
        failure is still connectable to the package that introduced it - after
        it, the user meets a node's ImportError with nothing linking the two.
        """
        _, token = user_and_token
        body, turns = self._apply_draft_with_pip(
            client, token, alice_project, monkeypatch,
            installed=["weather-sdk"], skipped=[],
            import_errors={"weather-sdk": "ImportError: DLL load failed"})

        applied_text = next(t["text"] for t in turns
                            if "Applied: package" in (t.get("text") or ""))
        assert "cannot be imported" in applied_text
        assert "DLL load failed" in applied_text
        # The package itself still installed - this is a warning, not a rollback.
        assert body["status"] == "applied"

    def test_working_libraries_add_no_warning(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        _, turns = self._apply_draft_with_pip(
            client, token, alice_project, monkeypatch,
            installed=["weather-sdk"], skipped=[])
        applied_text = next(t["text"] for t in turns
                            if "Applied: package" in (t.get("text") or ""))
        assert "cannot be imported" not in applied_text

    def test_skipped_only_apply_stays_silent(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        body, turns = self._apply_draft_with_pip(
            client, token, alice_project, monkeypatch,
            installed=[], skipped=["weather-sdk"])
        assert "restartRecommended" not in body
        applied_text = next(t["text"] for t in turns
                            if "Applied: package" in (t.get("text") or ""))
        assert "Restart Curio" not in applied_text


class TestPlanTopologyMint:
    """dev/112 (DEC-070) — the owner's 2026-08-25 session, made unmintable:
    a plan data edge that closes a cycle is refused with the path named; an
    interaction edge is kept as such (visualization ↔ data-pool only);
    edge-only plans mint; removed connections are reviewed by name."""

    COORD = "agent.dataflow-builder@1.0.0"
    TEMPLATES = [
        {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
         "engine": "python", "editor": "code", "description": "d",
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python",
         "editor": "none", "hasCode": False, "description": "d", "bidirectional": True,
         "inputPorts": [{"types": ["JSON"], "cardinality": "1"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "merge-flow", "label": "Merge Flow", "category": "data", "engine": "python",
         "editor": "none", "hasCode": False, "description": "d",
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "vis-vega", "label": "Vega", "category": "visualization", "engine": "javascript",
         "editor": "grammar", "description": "d", "bidirectional": True,
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    ]
    # The owner's canvas: Load → Transform → Merge → Pool → Vis.
    NODES = [
        {"id": "load", "type": "curio.builtin/computation-analysis", "content": "", "goal": "Fabricate", "x": 0, "y": 0},
        {"id": "xform", "type": "curio.builtin/computation-analysis", "content": "", "goal": "Transform", "x": 400, "y": 0},
        {"id": "merge", "type": "curio.builtin/merge-flow", "content": "", "goal": "Pool Input Merge", "x": 800, "y": 0},
        {"id": "pool", "type": "curio.builtin/data-pool", "content": "", "goal": "Time Data Pool", "x": 1200, "y": 0},
        {"id": "vis", "type": "curio.builtin/vis-vega", "content": "", "goal": "Metric Distribution", "x": 1600, "y": 0},
    ]
    EDGES = [
        {"id": "e1", "source": "load", "target": "xform", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e2", "source": "xform", "target": "merge", "sourceHandle": "out", "targetHandle": "in_0"},
        {"id": "e3", "source": "merge", "target": "pool", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e4", "source": "pool", "target": "vis", "sourceHandle": "out", "targetHandle": "in"},
    ]

    def _tail(self, plan):
        import json as _json
        return f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def _setup(self, client, user, token, project_id, monkeypatch, replies, edges=None):
        from utk_curio.backend.app.projects.services import _user_dir_key

        TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=self.TEMPLATES)
        spec = {"dataflow": {"nodes": self.NODES, "edges": edges if edges is not None else self.EDGES, "packages": []}}
        r = client.put(f"/api/projects/{project_id}", json={"name": "p", "spec": spec, "outputs": []}, headers=_auth(token))
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="fix the cycle"):
        return client.post(f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
                           json={"message": message}, headers=_auth(token))

    @staticmethod
    def _proposal(body):
        return next((p for p in body["content"] if p["type"] == "proposal"), None)

    def test_the_owners_plan_is_refused_with_the_cycle_named(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Round one of the 2026-08-25 session: vis → merge as a data edge.
        user, token = user_and_token
        owner_plan = {"goal": "interaction loop", "nodes": [], "edges": [{"from": "vis", "to": "merge"}]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(owner_plan), "I give up."])
        body = self._run(client, token, alice_project, att_id).get_json()
        assert self._proposal(body) is None
        feedback = calls[1][-1]["content"]
        assert "creates a cycle" in feedback
        assert "Metric Distribution" in feedback and "Pool Input Merge" in feedback
        assert '"kind": "interaction"' in feedback
        # The saved graph is untouched — nothing materialized (DEC-051 discipline).
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        assert len(projects_storage.read_spec(_user_dir_key(user), alice_project)["dataflow"]["edges"]) == 4

    def test_interaction_edge_to_the_pool_mints_edge_only_and_keeps_its_kind(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "interaction", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch, replies=["Fix.\n" + self._tail(plan)])
        proposal = self._proposal(self._run(client, token, alice_project, att_id).get_json())
        assert proposal is not None, "an edge-only plan must mint (no filler nodes needed)"
        assert proposal["summary"] == "Apply plan · 0 nodes, 1 edge"
        assert proposal["plan"]["edges"] == [{
            "from": "vis", "to": "pool", "kind": "interaction",
            "fromLabel": "Metric Distribution", "toLabel": "Time Data Pool",
        }]

    def test_interaction_edge_into_a_merge_is_refused_naming_the_fix(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "interaction", "edges": [{"from": "vis", "to": "merge", "kind": "interaction"}]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(plan), "ok"])
        body = self._run(client, token, alice_project, att_id).get_json()
        assert self._proposal(body) is None
        feedback = calls[1][-1]["content"]
        assert "invalid interaction edges" in feedback
        assert "'merge' is merge-flow" in feedback and "target the data-pool" in feedback

    def test_removal_only_plan_that_breaks_a_user_cycle_mints_and_names_the_connection(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "merge", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "break", "removeEdges": ["e5"]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Fix.\n" + self._tail(plan)], edges=cyclic)
        proposal = self._proposal(self._run(client, token, alice_project, att_id).get_json())
        assert proposal is not None
        assert proposal["summary"] == "Apply plan · 0 nodes, 0 edges, removes 1 connection"
        assert proposal["plan"]["removals"] == []
        assert proposal["plan"]["removedEdges"] == [
            {"id": "e5", "fromLabel": "Metric Distribution", "toLabel": "Pool Input Merge"},
        ]

    def test_remove_and_readd_as_data_is_still_refused(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Rounds two to five of the session: removeEdges the loop edge, add it back as data.
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "merge", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "convert", "nodes": [], "edges": [{"from": "vis", "to": "merge"}], "removeEdges": ["e5"]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(plan), "ok"], edges=cyclic)
        assert self._proposal(self._run(client, token, alice_project, att_id).get_json()) is None
        assert "creates a cycle" in calls[1][-1]["content"]

    def test_a_plan_that_leaves_a_user_cycle_alone_is_not_blamed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "merge", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "note", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                          "title": "Side", "intent": "unrelated"}], "edges": []}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + self._tail(plan)], edges=cyclic)
        assert self._proposal(self._run(client, token, alice_project, att_id).get_json()) is not None

    def test_existing_interaction_edges_do_not_count_toward_fan_in_or_cycles(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        with_feedback = self.EDGES + [{"id": "e5", "source": "vis", "target": "pool", "type": "Interaction",
                                       "sourceHandle": "in/out", "targetHandle": "in/out"}]
        plan = {"goal": "extend", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                            "title": "Post", "intent": "downstream"}],
                "edges": [{"from": "vis", "to": "n"}]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + self._tail(plan)], edges=with_feedback)
        assert self._proposal(self._run(client, token, alice_project, att_id).get_json()) is not None


class TestPlanTopologyApply:
    """dev/112 (DEC-070) — the apply paths: interaction edges materialize as
    the Trill's Interaction shape, removed connections are counted, the applied
    turn carries the topology verdict, and drift that would close a cycle is
    refused (whole-plan → 409 + stale; per-edge → refused row, named)."""

    def _base(self):
        return TestPlanTopologyMint()

    def _cyclic_edges(self):
        return TestPlanTopologyMint.EDGES + [
            {"id": "e5", "source": "vis", "target": "merge", "sourceHandle": "out", "targetHandle": "in_1"},
        ]

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _apply_edges(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply-edges",
            json={}, headers=_auth(token),
        )

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def _write_spec(self, user, project_id, spec):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        projects_storage.write_spec(_user_dir_key(user), project_id, spec)

    def _drift_but_keep_digest(self, user, project_id, att_id, new_edge):
        """The user draws an edge AND the digest is re-pinned (as the per-node
        applies do), so the topology re-check — not the digest — must catch it."""
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        spec = self._spec(user, project_id)
        spec["dataflow"]["edges"].append(new_edge)
        record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
        record["activeProposal"]["baseGraphDigest"] = spec_reads._graph_shape_digest(spec)
        self._write_spec(user, project_id, spec)

    def _turn_texts(self, client, token, project_id, att_id):
        body = client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session", headers=_auth(token)
        ).get_json()
        return [t.get("text") or "" for t in body.get("turns", [])]

    def test_the_repair_applies_as_an_interaction_edge_and_reports_acyclic(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        plan = {"goal": "convert", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}], "removeEdges": ["e5"]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Fix.\n" + base._tail(plan)], edges=self._cyclic_edges())
        proposal = base._proposal(base._run(client, token, alice_project, att_id).get_json())
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        (created,) = body["appliedGraph"]["edges"]
        assert created["type"] == "Interaction"
        assert created["sourceHandle"] == "in/out" and created["targetHandle"] == "in/out"
        assert body["appliedGraph"]["removedEdgeIds"] == ["e5"]
        edges = self._spec(user, alice_project)["dataflow"]["edges"]
        assert all(e["id"] != "e5" for e in edges)
        assert any(e.get("type") == "Interaction" and e["source"] == "vis" and e["target"] == "pool" for e in edges)
        applied = next(t for t in self._turn_texts(client, token, alice_project, att_id) if t.startswith("Applied: plan"))
        assert applied == "Applied: plan added 0 nodes and 1 connection, removed 1 connection. Topology: acyclic."

    def test_applied_turn_reports_a_user_cycle_the_plan_left_alone(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        plan = {"goal": "side", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                          "title": "Side", "intent": "unrelated"}], "edges": []}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + base._tail(plan)], edges=self._cyclic_edges())
        proposal = base._proposal(base._run(client, token, alice_project, att_id).get_json())
        self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        applied = next(t for t in self._turn_texts(client, token, alice_project, att_id) if t.startswith("Applied: plan"))
        assert "Topology: cycle through" in applied
        assert "Metric Distribution" in applied and "Pool Input Merge" in applied

    def test_whole_plan_apply_refuses_drift_that_would_close_a_cycle(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        # Acyclic at mint: load → merge (merge accepts many inputs).
        plan = {"goal": "wire", "edges": [{"from": "load", "to": "merge"}]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch, replies=["Wire.\n" + base._tail(plan)])
        proposal = base._proposal(base._run(client, token, alice_project, att_id).get_json())
        # The user then draws merge → load; the plan edge load → merge would close it.
        self._drift_but_keep_digest(user, alice_project, att_id,
                                    {"id": "u1", "source": "merge", "target": "load", "sourceHandle": "out", "targetHandle": "in"})
        r = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert r.status_code == 409
        assert "close a cycle" in r.get_json()["error"]
        # Nothing mutated: the drawn edge is there, the plan edge is not.
        edges = self._spec(user, alice_project)["dataflow"]["edges"]
        assert any(e["id"] == "u1" for e in edges) and not any(e["source"] == "load" and e["target"] == "merge" for e in edges)

    def test_per_edge_apply_refuses_a_closing_edge_by_name_and_applies_interaction_edges(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        plan = {"goal": "wire", "edges": [
            {"from": "load", "to": "merge"},
            {"from": "vis", "to": "pool", "kind": "interaction"},
        ]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch, replies=["Wire.\n" + base._tail(plan)])
        proposal = base._proposal(base._run(client, token, alice_project, att_id).get_json())
        self._drift_but_keep_digest(user, alice_project, att_id,
                                    {"id": "u1", "source": "merge", "target": "load", "sourceHandle": "out", "targetHandle": "in"})
        body = self._apply_edges(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert body["results"]["0"]["status"] == "refused"
        assert body["results"]["0"]["reason"].startswith("closes a cycle: ")
        assert body["results"]["1"]["status"] == "applied" and body["results"]["1"]["kind"] == "interaction"
        (created,) = body["createdEdges"]
        assert created["type"] == "Interaction" and created["sourceHandle"] == "in/out"
