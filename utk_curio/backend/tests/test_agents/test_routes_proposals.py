"""Integration tests for what a run changes and proposes (routes/proposals.py).

An agent's change (a node's code, a new node, a plan) lands with the turn, as
the agent's, after the same checks; an install waits, and the routes apply or
dismiss it. TestNodeCreate, TestDataflowPlanMint and TestDestructiveReplan
also serve the run and solve tests as helpers."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    _drop_from_lockfile,
)


def _changes(body) -> list[dict]:
    """The turn's change cards: what its agent changed, landed."""
    return [p for p in body["content"] if p["type"] == "change"]


def _landed_plan(body) -> dict:
    """The plan that landed with the turn: its change card, with ``canvas``,
    the nodes and connections a tab no doc binds puts on its canvas."""
    assert not [p for p in body["content"] if p["type"] == "proposal"], "a plan waited for review"
    [card] = [p for p in _changes(body) if p.get("kind") == "plan"]
    [landed] = [c for c in body.get("changes") or [] if c["changeId"] == card["changeId"]]
    return {**card, "canvas": landed["canvas"]}


class TestReviewProposals:
    """What a run changes and what it asks for (memo dev/41, DEC-006): an
    agent's code write lands at once, after its checks, as the agent's change,
    which only the authenticated Undo takes back; an install waits for review,
    and only the authenticated endpoint applies or dismisses it."""

    COORD = "agent.curio.node-builder@1"

    def _mutate_tail(self, node_id="n1", new_content="print(2)"):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "node.content.write", '
            f'"params": {{"nodeId": "{node_id}", "content": "{new_content}"}}}}}}\n```'
        )

    def _install_tail(self, dir_name="curio.notes@1"):
        return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": "package.install", "params": {
            "dirName": dir_name, "reason": "the notes need it",
        }}}) + "\n```"

    def _setup(self, client, token, project_id, monkeypatch, replies=None, target=None):
        """Save a node, attach the builder, and mock a write-then-answer run."""
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": target or {"kind": "node", "targetId": "n1"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []
        script = replies or [self._mutate_tail(), "Written."]

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application.turns import titles

            if messages and messages[0].get("content") == titles.title_prompt():
                return "Title"
            calls.append(messages)
            return script[min(len(calls) - 1, len(script) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _install_setup(self, client, user, token, project_id, monkeypatch, replies):
        """The Node Builder on the canvas, with two packages in the account's
        store that a run may ask to install."""
        from utk_curio.backend.tests.test_agents.test_routes_turns import TestReuseLadder

        store = TestReuseLadder()
        store._write_store_package(_user_dir_key(user), "curio.notes@1", "curio.notes", "note-surface", "Note")
        store._write_store_package(_user_dir_key(user), "curio.marks@1", "curio.marks", "mark-surface", "Mark")
        return self._setup(client, token, project_id, monkeypatch, replies=replies, target={"kind": "canvas"})

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

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _active(self, client, token, project_id, att_id) -> dict:
        cards = client.get(
            f"/api/agents/projects/{project_id}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        return next(c for c in cards if c["attachmentId"] == att_id).get("activeProposal") or {}

    def _part_statuses(self, client, token, project_id, att_id) -> dict:
        return {
            p["proposalId"]: p["status"]
            for t in self._turns(client, token, project_id, att_id)
            for p in t.get("content", [])
            if p["type"] == "proposal"
        }

    # ── an agent's change ────────────────────────────────────────────────────

    def test_a_code_write_lands_at_once_as_the_agents_change(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        att_id, calls = self._setup(client, token, alice_project, monkeypatch)
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        [card] = _changes(body)
        assert (card["status"], card["nodeId"], card["preview"]) == ("applied", "n1", "print(2)")
        # The node holds it at once, and the model was told so, with the Undo.
        assert self._spec_node_content(user, alice_project) == "print(2)"
        assert "now holds your code" in calls[1][-1]["content"]
        assert "the user can undo it from this chat" in calls[1][-1]["content"]
        # The card persisted with the turn, and no review waits.
        turns = self._turns(client, token, alice_project, att_id)
        persisted = next(p for p in turns[1]["content"] if p["type"] == "change")
        assert persisted["changeId"] == card["changeId"]
        assert self._active(client, token, alice_project, att_id).get("status") != "pending"
        # The attachment keeps the change, with the code before it, for its Undo.
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        [record] = [a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id]
        [kept] = record["changes"]
        assert (kept["changeId"], kept["before"], kept["content"], kept["status"]) == (
            card["changeId"], "print(1)", "print(2)", "applied",
        )

    def test_the_stream_carries_the_change_before_done(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        script = [self._mutate_tail(), "Written."]
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
        assert "review_required" not in kinds
        assert kinds.index("tool_result") < kinds.index("change") < kinds.index("done")
        change = next(p for k, p in events if k == "change")
        assert (change["tool"], change["attachmentId"]) == ("node.content.write", att_id)
        assert change["changeId"]
        # What a tab no doc binds puts on its canvas.
        assert (change["canvas"]["kind"], change["canvas"]["nodeId"], change["canvas"]["content"]) == (
            "node-content-applied", "n1", "print(2)",
        )
        done = events[-1][1]
        assert any(p["type"] == "change" and p["changeId"] == change["changeId"] for p in done["content"])

    def test_the_card_names_the_node_not_its_id(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # #506: the card read "node 'n1'", an id the user sees nowhere else,
        # while the chat header names the node by its kind.
        _, token = user_and_token
        att_id, _ = self._setup(client, token, alice_project, monkeypatch)
        node = {"id": "n1", "type": "curio.builtin/computation-analysis",
                "title": "Word counts", "content": "print(1)"}
        client.put(
            f"/api/projects/{alice_project}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [node], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        [card] = _changes(self._run(client, token, alice_project, att_id).get_json())
        assert card["summary"] == "Replaced the content of the Python Computation node · Word counts"
        assert card["lines"] == ["Python Computation node · Word counts"]
        assert card["nodeId"] == "n1"  # the id stays where the Undo finds the node
        persisted = next(p for t in self._turns(client, token, alice_project, att_id)
                         for p in t.get("content") or [] if p.get("type") == "change")
        shown = json.dumps({k: v for k, v in persisted.items() if k != "nodeId"}, ensure_ascii=False)
        assert "Word counts" in shown
        assert "node n1" not in shown and "(n1)" not in shown and "'n1'" not in shown

    def test_undo_puts_the_code_back_once_and_runs_no_model(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, token, alice_project, monkeypatch)
        [card] = _changes(self._run(client, token, alice_project, att_id).get_json())
        runs_before = ledger.aggregates(_user_dir_key(user))["runs"]
        model_calls = len(calls)
        undo = f"/api/agents/projects/{alice_project}/attachments/{att_id}/changes/{card['changeId']}/undo"
        r = client.post(undo, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        assert self._spec_node_content(user, alice_project) == "print(1)"
        # Undo is deterministic: no model ran and no quota went (dev/41 §4.6).
        assert len(calls) == model_calls
        assert ledger.aggregates(_user_dir_key(user))["runs"] == runs_before
        persisted = next(p for t in self._turns(client, token, alice_project, att_id)
                         for p in t.get("content", []) if p["type"] == "change")
        assert persisted["status"] == "undone"
        # A second Undo is refused: a change is undone exactly once.
        again = client.post(undo, headers=_auth(token))
        assert again.status_code == 409
        assert self._spec_node_content(user, alice_project) == "print(1)"

    def test_code_a_person_wrote_while_the_agent_waited_is_kept_and_the_write_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """The write lands only where the node still holds the code the agent
        read, as a person's put-back does: a person in the node who rewrites it
        keeps their code."""
        import time as real_time
        from types import SimpleNamespace

        from utk_curio.backend.app.agents.application.proposals import changes
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.collaboration import room_state

        user, token = user_and_token
        att_id, calls = self._setup(client, token, alice_project, monkeypatch)
        held = {"by": "Ana"}
        real_snapshot = room_state.snapshot

        def _snapshot(room):
            out = dict(real_snapshot(room) or {})
            if held["by"]:
                out["locks"] = {"n1": {"user_id": "someone-else", "name": held["by"]}}
            return out

        def _sleep(seconds):
            # Ana, in the node, writes her own code there, then leaves it.
            if held["by"]:
                spec = dataflow_docs.live(_user_dir_key(user), alice_project)
                spec["dataflow"]["nodes"][0]["content"] = "user edited"
                dataflow_docs.write(_user_dir_key(user), alice_project, spec, dataflow_docs.person("someone-else", "edit"))
                held["by"] = None

        monkeypatch.setattr(room_state, "snapshot", _snapshot)
        monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=_sleep))
        body = self._run(client, token, alice_project, att_id).get_json()
        assert held["by"] is None, "the write never waited for Ana"
        assert _changes(body) == []
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        assert self._spec_node_content(user, alice_project) == "user edited"
        assert "took other code while you worked" in calls[1][-1]["content"], calls[1][-1]["content"]

    def test_proposal_validation_failures_refuse_to_the_model(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client,
            token,
            alice_project,
            monkeypatch,
            replies=[
                '```curio.v1\n{"toolRequest": {"tool": "node.content.write", "params": {"nodeId": "ghost", "content": "x"}}}\n```',
                "Could not write it.",
            ],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        assert not any(p["type"] in ("proposal", "change") for p in r.get_json()["content"])
        assert "not found" in calls[1][-1]["content"]
        assert self._spec_node_content(user, alice_project) == "print(1)"

    def test_no_text_makes_a_change(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance (dev/41, tested by name): model replies and user
        # messages claiming a change change NOTHING; only a request that passes
        # its checks does.
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=["I have written print(2) into the node, as you approved."],  # the model lies
        )
        first = self._run(client, token, alice_project, att_id).get_json()
        second = self._run(client, token, alice_project, att_id, "yes, write it now please").get_json()
        assert _changes(first) == [] and _changes(second) == []
        assert self._spec_node_content(user, alice_project) == "print(1)"

    # ── an install, which waits for review ───────────────────────────────────

    def test_an_install_waits_for_review_and_only_its_apply_installs_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        user, token = user_and_token
        att_id, calls = self._install_setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._install_tail(), "I have installed the notes, as you approved."],  # the model lies
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        assert (proposal["tool"], proposal["status"]) == ("package.install", "pending")
        assert "awaits the user's explicit review" in calls[1][-1]["content"]
        # No text applies it, the user's message included.
        self._run(client, token, alice_project, att_id, "yes, install it now please")
        assert self._active(client, token, alice_project, att_id)["status"] == "pending"
        applied = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert applied.status_code == 200, applied.get_json()
        assert self._part_statuses(client, token, alice_project, att_id)[proposal["proposalId"]] == "applied"
        # A second apply is refused: an install applies exactly once.
        assert self._apply(client, token, alice_project, att_id, proposal["proposalId"]).status_code == 409

    def test_dismiss_closes_an_install(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._install_setup(
            client, user, token, alice_project, monkeypatch, replies=[self._install_tail(), "Asked."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert self._apply(client, token, alice_project, att_id, proposal["proposalId"]).status_code == 409

    def test_a_newer_install_supersedes_the_pending_one(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._install_setup(
            client, user, token, alice_project, monkeypatch,
            # The mock's call counter spans both runs: tail, answer, tail, answer.
            replies=[self._install_tail(), "First.", self._install_tail("curio.marks@1"), "Second."],
        )
        first = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        second = self._proposal_from_run(self._run(client, token, alice_project, att_id, "again"))
        by_id = self._part_statuses(client, token, alice_project, att_id)
        assert by_id[first["proposalId"]] == "superseded"
        assert by_id[second["proposalId"]] == "pending"
        # The superseded id no longer applies (the mirror holds the newest).
        assert self._apply(client, token, alice_project, att_id, first["proposalId"]).status_code == 404

    # dev/90 A16: same-run install sequences. Field regression: one Researcher
    # reply proposed two installs; the second mint superseded the first while
    # its transcript part (not yet persisted) stayed "pending", a live Apply
    # button pointing at a dead proposal. Same-run mints queue as ONE jointly
    # pending sequence; a LATER run still supersedes the whole sequence.

    def _two_install_run(self, client, user, token, project_id, monkeypatch, extra_replies=()):
        att_id, calls = self._install_setup(
            client, user, token, project_id, monkeypatch,
            replies=[self._install_tail(), self._install_tail("curio.marks@1"), "Both asked.", *extra_replies],
        )
        r = self._run(client, token, project_id, att_id)
        assert r.status_code == 200
        proposals = [p for p in r.get_json()["content"] if p["type"] == "proposal"]
        assert len(proposals) == 2
        return att_id, proposals, calls

    def test_same_run_installs_stay_jointly_pending_and_both_apply(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_install_run(client, user, token, alice_project, monkeypatch)
        assert [p["status"] for p in proposals] == ["pending", "pending"]
        assert self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"]).status_code == 200
        # The queued sibling is still surfaced as the pending review.
        active = self._active(client, token, alice_project, att_id)
        assert (active["proposalId"], active["status"]) == (proposals[1]["proposalId"], "pending")
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 200

    def test_same_run_installs_apply_out_of_order(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_install_run(client, user, token, alice_project, monkeypatch)
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 200
        assert self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"]).status_code == 200

    def test_dismissing_the_active_install_keeps_the_queued_sibling_appliable(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_install_run(client, user, token, alice_project, monkeypatch)
        r = client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposals[0]['proposalId']}",
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 200
        statuses = self._part_statuses(client, token, alice_project, att_id)
        assert (statuses[proposals[0]["proposalId"]], statuses[proposals[1]["proposalId"]]) == ("dismissed", "applied")

    def test_a_later_run_supersedes_the_whole_install_sequence(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposals, _ = self._two_install_run(
            client, user, token, alice_project, monkeypatch,
            extra_replies=[self._install_tail(), "Asked again."],
        )
        third = self._proposal_from_run(self._run(client, token, alice_project, att_id, "actually, just the notes"))
        # BOTH members of the earlier sequence are superseded: part statuses
        # updated (they are persisted by now) and their ids no longer apply.
        by_id = self._part_statuses(client, token, alice_project, att_id)
        assert by_id[proposals[0]["proposalId"]] == "superseded"
        assert by_id[proposals[1]["proposalId"]] == "superseded"
        assert self._apply(client, token, alice_project, att_id, proposals[0]["proposalId"]).status_code == 404
        assert self._apply(client, token, alice_project, att_id, proposals[1]["proposalId"]).status_code == 404
        assert self._apply(client, token, alice_project, att_id, third["proposalId"]).status_code == 200


class TestNodeCreate:
    """dev/48 §3.2, the first graph-shape mutation: reuse-first node
    creation, registry-validated at mint, landed at once as the agent's change
    with a server-minted id, and the new node on the turn's ``changes`` for a
    canvas no doc binds."""

    COORD = "agent.curio.node-builder@1"

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
        script = replies or [self._create_tail(), "Added it."]

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.title_prompt():
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

    def _created(self, body) -> dict:
        """The node the turn's one node.create landed, as a tab no doc binds
        takes it."""
        assert not [p for p in body["content"] if p["type"] == "proposal"], "a new node waited for review"
        [landed] = [c for c in body.get("changes") or [] if c["tool"] == "node.create"]
        assert landed["canvas"]["kind"] == "node-created"
        return landed["canvas"]["node"]

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
        assert all(p["type"] not in ("proposal", "change") for p in r.get_json()["content"])
        assert "not an available template" in calls[1][-1]["content"]
        assert len(self._spec_nodes(user, alice_project)) == 1

        att2, calls2 = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(node_type="curio.builtin/data-pool"), "done"],
        )
        self._run(client, token, alice_project, att2)
        assert "does not hold authored content" in calls2[1][-1]["content"]
        assert len(self._spec_nodes(user, alice_project)) == 1

    def test_a_new_node_lands_at_once_placed_beside_the_others(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch)
        body = self._run(client, token, alice_project, att_id).get_json()
        [card] = _changes(body)
        assert (card["kind"], card["status"]) == ("node", "applied")
        # dev/119 (DEC-076): the roster's executability rides the card as display.
        assert (card["nodeType"], card["executable"]) == ("curio.builtin/computation-analysis", True)
        assert "contentSha256" not in card  # no digest for a creation
        created = self._created(body)
        assert created["type"] == "curio.builtin/computation-analysis"
        assert created["content"] == "print('new')"
        # Placement: a gutter right of the existing node's right edge (x 100 plus
        # the default 525 width), on its row, so the two never overlap (#499).
        assert created["x"] == 100 + 525 + 120 and created["y"] == 60.0
        nodes = self._spec_nodes(user, alice_project)
        assert len(nodes) == 2
        inserted = next(n for n in nodes if n["id"] == created["id"])
        assert inserted["content"] == "print('new')"
        assert "is on the canvas" in calls[1][-1]["content"], calls[1][-1]["content"]

    def test_the_created_node_names_the_agent_that_added_it(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """The canvas starts the node's history with an entry named after the
        agent, as it names an agent's change to a node's code: the landing
        names the agent on the node it hands the canvas, never on the saved
        node."""
        from utk_curio.backend.app.agents.domain import builtin

        user, token = user_and_token
        att_id, _ = self._setup(client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch)
        created = self._created(self._run(client, token, alice_project, att_id).get_json())
        assert created["agent"] == builtin.get_builtin_manifest(self.COORD).name
        saved = next(n for n in self._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert "agent" not in saved

    def test_large_content_node_create_lands_whole(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """Issue #245, the reported bug, end to end.

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
            replies=[tail, "Added a CSV summariser."],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()
        # The leak: none of the machine block may survive as chat prose.
        assert "curio.v1" not in body["reply"]
        assert "toolRequest" not in body["reply"]
        assert "nodeType" not in body["reply"]
        assert "import pandas" not in body["reply"]

        created = self._created(body)
        assert created["content"] == stored  # whole body, not truncated
        nodes = self._spec_nodes(user, alice_project)
        assert len(nodes) == 2
        assert next(n for n in nodes if n["id"] == created["id"])["content"] == stored

        # The transcript holds the change's card.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert any(p.get("type") == "change" and p.get("kind") == "node"
                   for t in turns for p in t.get("content") or [])

    # ── two nodes one reply asks for ─────────────────────────────────────────
    # Field regression (dev/90 A16): one Researcher reply asked for a question
    # note then an answer note. Each lands as its own change, so each has its
    # own Undo, in any order.

    def _two_note_run(self, client, user, token, project_id, monkeypatch):
        att_id, calls = self._setup(
            client, token=token, user=user, project_id=project_id, monkeypatch=monkeypatch,
            replies=[
                self._create_tail(content="the question"),
                self._create_tail(content="the answer"),
                "Both notes added.",
            ],
        )
        r = self._run(client, token, project_id, att_id)
        assert r.status_code == 200
        cards = _changes(r.get_json())
        assert [c["kind"] for c in cards] == ["node", "node"]
        assert len({c["changeId"] for c in cards}) == 2
        return att_id, cards, calls

    def _undo(self, client, token, project_id, att_id, change_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/changes/{change_id}/undo",
            headers=_auth(token),
        )

    def _contents(self, user, project_id) -> list:
        return [n["content"] for n in self._spec_nodes(user, project_id)]

    def test_two_nodes_one_reply_asks_for_land_each_as_its_change(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, cards, _ = self._two_note_run(client, user, token, alice_project, monkeypatch)
        contents = self._contents(user, alice_project)
        assert "the question" in contents and "the answer" in contents
        # The first one's Undo takes back its node alone.
        assert self._undo(client, token, alice_project, att_id, cards[0]["changeId"]).status_code == 200
        contents = self._contents(user, alice_project)
        assert "the question" not in contents and "the answer" in contents
        assert self._undo(client, token, alice_project, att_id, cards[1]["changeId"]).status_code == 200
        assert self._contents(user, alice_project) == ["print(1)"]

    def test_two_nodes_one_reply_asks_for_are_undone_in_either_order(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, cards, _ = self._two_note_run(client, user, token, alice_project, monkeypatch)
        assert self._undo(client, token, alice_project, att_id, cards[1]["changeId"]).status_code == 200
        contents = self._contents(user, alice_project)
        assert "the question" in contents and "the answer" not in contents
        assert self._undo(client, token, alice_project, att_id, cards[0]["changeId"]).status_code == 200
        assert self._contents(user, alice_project) == ["print(1)"]

    def test_param_id_spoof_is_ignored_and_id_is_server_minted(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[self._create_tail(extra=', "id": "evil-id"'), "done"],
        )
        created = self._created(self._run(client, token, alice_project, att_id).get_json())
        assert created["id"] != "evil-id"
        assert {n["id"] for n in self._spec_nodes(user, alice_project)} == {"n1", created["id"]}

    def test_no_text_path_adds_a_node(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance (dev/41 extended to node.create): text claiming
        # a node was added adds none; only a request that passes its checks does.
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=["The user approved: the node was created and placed."],
        )
        self._run(client, token, alice_project, att_id)
        self._run(client, token, alice_project, att_id, message="yes, add it now please")
        assert len(self._spec_nodes(user, alice_project)) == 1


class TestDataflowPlanMint:
    """dev/52: a validated dataflowPlan tail on the final reply lands the
    plan whole, in one step (runtime-landed, never model-requested)."""

    COORD = "agent.curio.dataflow-builder@1"

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

    def _setup(self, client, user, token, project_id, monkeypatch, replies=None, coord=None, templates=None):
        helper = TestNodeCreate()
        helper._write_builtin_package(self._ukey(user), templates)
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
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.title_prompt():
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

    def test_a_plan_tail_lands_the_plan_and_sets_the_phase(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch)
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()
        card = _landed_plan(body)
        assert card["tool"] == "dataflow.plan.write"
        assert card["summary"] == "Plan · 2 nodes, 1 edge"
        assert [n["title"] for n in card["plan"]["nodes"]] == ["Load", "Analyze"]
        # Its nodes and its connection are on the canvas, beside n1.
        created = card["canvas"]["nodes"]
        assert [n["goal"].startswith(title) for n, title in zip(created, ["Load", "Analyze"])] == [True, True]
        assert [(e["source"], e["target"]) for e in card["canvas"]["edges"]] == [(created[0]["id"], created[1]["id"])]
        nodes = TestNodeCreate()._spec_nodes(user, alice_project)
        assert {n["id"] for n in nodes} == {"n1", created[0]["id"], created[1]["id"]}
        # The raw plan part was consumed by the mint: no duplicate part.
        assert all(p["type"] != "dataflowPlan" for p in body["content"])
        # The templates roster rode the system turn (plan grants get it too).
        assert "Available node templates" in calls[0][0]["content"]
        # Builder session: the planner holds the plan that landed, for Build & validate.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        planner = next(c for c in cards if c["attachmentId"] == att_id)
        assert planner["builderSession"]["phase"] == "applied"
        assert (planner["planProposal"]["proposalId"], planner["planProposal"]["status"]) == (card["planId"], "applied")
        assert (planner.get("activeProposal") or {}).get("status") != "pending"

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
        # the verification tests in test_routes_turns.py stub it.
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
        _drop_from_lockfile(user, alice_project, "agent.curio.dataset-finder@1")
        body = self._run(client, token, alice_project, att_id).get_json()
        # No install proposal for a required agent, anywhere in the reply.
        assert all(
            p.get("tool") != "project.install" for p in body["content"] if p["type"] == "proposal"
        )
        # The Dataset Finder is back in the lockfile, and the repair says so.
        installed = client.get(
            f"/api/agents/projects/{alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        assert "agent.curio.dataset-finder@1" in {a["dirName"] for a in installed}
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
        repaired. A merely PREFERRED delegate (the Researcher, which the
        Dataflow Builder asks to check a fact) still reaches the user as a
        reviewed install proposal."""
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                '```curio.v1\n{"delegateRequest": {"capability": "research.verify", '
                '"inputs": {"intent": "check the dataset id"}}}\n```',
                "I asked for an install.",
            ],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "project.install"
        assert proposal["pins"]["coord"] == "agent.curio.researcher@1"
        installed = {
            a["dirName"] for a in client.get(
                f"/api/agents/projects/{alice_project}", headers=_auth(token)
            ).get_json()["agents"]
        }
        assert "agent.curio.researcher@1" not in installed

    def test_unavailable_template_yields_error_card_and_lands_nothing(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + self._plan_tail(nodes=[
                {"ref": "a", "nodeType": "curio.builtin/not-a-thing",
                 "title": "Load", "intent": "load"},
            ], edges=[])],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        assert all(p["type"] not in ("proposal", "change") for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Plan could not be made"
        assert "not-a-thing" in card["lines"][0]
        assert [n["id"] for n in TestNodeCreate()._spec_nodes(user, alice_project)] == ["n1"]

    def test_ungranted_plan_part_passes_through_without_mutation_path(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A non-builder agent emitting a plan tail: informational part only.
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.curio.researcher@1",
            replies=["idea!\n" + self._plan_tail()],
        )
        body = self._run(client, token, alice_project, att_id).get_json()
        assert all(p["type"] != "proposal" for p in body["content"])
        assert any(p["type"] == "dataflowPlan" for p in body["content"])


class TestPlanTemplateSpellings:
    """dev/93 D3: the reported loop, and the regression that had never been
    written: no test had ever fed a VERSIONED nodeType into a dataflowPlan.

    The live failure: the Dataflow Builder quoted curio.builtin/data-loading@1
    from the "Installed node templates" list its own run context supplied, was
    refused, fell back to the legacy enum name DATA_LOADING, was refused
    again, and burned 33.1k tokens over four correction rounds. Both spellings
    are ones the system itself produces (the client registry keys descriptors
    versioned, and the runtime prints versioned ids in its own plan previews),
    so refusing them manufactured an unfixable-looking error.
    """

    def _mint(self, client, user_and_token, alice_project, monkeypatch, nodes, edges=None):
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + helper._plan_tail(nodes=nodes, edges=edges or [])],
        )
        return helper._run(client, token, alice_project, att_id).get_json(), att_id, token

    def test_versioned_node_types_land_canonical(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/computation-analysis@1",
                    "title": "Load", "intent": "load"}],
        )
        # Landed, AND the stored plan pins the canonical unversioned id rather
        # than whatever spelling the model happened to send.
        assert _landed_plan(body)["plan"]["nodes"][0]["nodeType"] == (
            "curio.builtin/computation-analysis"
        )

    def test_legacy_enum_node_types_land_canonical(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "COMPUTATION_ANALYSIS",
                    "title": "Load", "intent": "load"}],
        )
        assert _landed_plan(body)["plan"]["nodes"][0]["nodeType"] == (
            "curio.builtin/computation-analysis"
        )

    def test_mixed_spellings_in_one_plan_all_canonicalise(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A confused model mixes spellings across nodes, likely given it was
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
        assert {n["nodeType"] for n in _landed_plan(body)["plan"]["nodes"]} == {
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
        assert _landed_plan(body)["plan"]["nodes"][0]["nodeType"] == "curio.builtin/data-pool"

    def test_unknown_type_still_refuses_and_names_the_spellings(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/not-a-thing@1",
                    "title": "Load", "intent": "load"}],
        )
        assert all(p["type"] not in ("proposal", "change") for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Plan could not be made"
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
        assert all(p["type"] not in ("proposal", "change") for p in body["content"])

    def test_a_versioned_plan_lands_end_to_end(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Nothing may be plannable but not placeable: the node a versioned
        spelling names is on the canvas."""
        body, _, _ = self._mint(
            client, user_and_token, alice_project, monkeypatch,
            nodes=[{"ref": "a", "nodeType": "curio.builtin/computation-analysis@1",
                    "title": "Load", "intent": "load"}],
        )
        [created] = _landed_plan(body)["canvas"]["nodes"]
        user, _ = user_and_token
        nodes = TestNodeCreate()._spec_nodes(user, alice_project)
        assert created["id"] in {n["id"] for n in nodes}, "the plan's node must exist on the canvas"

    def test_a_removal_only_plan_still_lands(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The one plan path that always worked: it carries zero nodes, so the
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
        card = _landed_plan(helper._run(client, token, alice_project, att_id).get_json())
        assert card["canvas"]["removedNodeIds"] == ["n1"]
        assert TestNodeCreate()._spec_nodes(user, alice_project) == []


class TestDataflowPlanApply:
    """dev/52: the atomic, ADDITIVE plan landing: server ids, topological
    placement, the agents of each node kind, the planner's session."""

    def _land(self, client, user, token, project_id, monkeypatch, **kw):
        """A plan the Dataflow Builder landed: its attachment and the plan's
        change card, with ``canvas``, what it put on the canvas."""
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, project_id, monkeypatch, **kw)
        r = helper._run(client, token, project_id, att_id)
        assert r.status_code == 200, r.get_json()
        return att_id, _landed_plan(r.get_json())

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def _planner(self, client, token, project_id, att_id) -> dict:
        cards = client.get(
            f"/api/agents/projects/{project_id}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        return next(c for c in cards if c["attachmentId"] == att_id)

    # ── dev/126: a landed plan attaches the plan-node agents ─────────────

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

    def _land_data_loading_plan(self, client, user, token, project_id, monkeypatch):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, project_id, monkeypatch,
            replies=["Plan.\n" + self._data_loading_plan()],
        )
        self._add_data_loading_template(user)
        r = helper._run(client, token, project_id, att_id)
        return att_id, _landed_plan(r.get_json())

    def test_a_landed_plan_attaches_the_agents_of_each_node_kind(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, card = self._land_data_loading_plan(
            client, user, token, alice_project, monkeypatch
        )
        ids = {
            title: next(n["id"] for n in card["canvas"]["nodes"] if n["goal"].startswith(title))
            for title in ("Load boundaries", "Analyze")
        }
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        by_node: dict[str, set] = {}
        for c in cards:
            if c["target"]["kind"] == "node":
                by_node.setdefault(c["target"]["targetId"], set()).add(c["coord"].split("@")[0])
        assert by_node[ids["Load boundaries"]] == {
            "agent.curio.node-builder", "agent.curio.dataset-finder",
        }
        assert by_node[ids["Analyze"]] == {"agent.curio.node-builder"}
        # The spec carries them, the Dataset Finder at the loader alone.
        finder = [
            c for c in cards if c["coord"].startswith("agent.curio.dataset-finder@")
        ]
        assert [c["target"] for c in finder] == [
            {"kind": "node", "targetId": ids["Load boundaries"]}
        ]
        # And the plan's card says what it attached.
        line = next(l for l in card["lines"] if l.startswith("agents attached:"))
        assert "Node Builder ×2" in line and "Dataset Finder" in line

    def test_a_plan_lands_additively_with_server_ids(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, card = self._land(client, user, token, alice_project, monkeypatch)
        assert len(card["canvas"]["nodes"]) == 2 and len(card["canvas"]["edges"]) == 1
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
        # The goal is the plan row's title and intent; no code yet.
        assert load["content"] == ""
        assert load["goal"].startswith("Load ") and load["goal"].endswith(" load the data")
        # Builder session: applied phase, both nodes pending for Build & validate or Solve.
        session = self._planner(client, token, alice_project, att_id)["builderSession"]
        assert session["phase"] == "applied"
        assert set(session["nodeRuns"]) == {load["id"], analyze["id"]}
        assert set(session["nodeRuns"].values()) == {"pending"}

    def test_plan_carried_content_is_refused_at_mint(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # dev/67-5 supersedes dev/52's "trivial code" allowance (67-0: no
        # shortcut): plans describe intent; content is generated and
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
        card = _landed_plan(r.get_json())  # the content-less replan landed
        assert [n["content"] for n in card["canvas"]["nodes"]] == ["", ""]
        feedback = calls[1][-1]["content"]
        assert "must not carry content" in feedback
        assert "'a'" in feedback

    def test_undo_of_the_only_plan_leaves_the_planner_nothing_to_build(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, card = self._land(client, user, token, alice_project, monkeypatch)
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/changes/{card['changeId']}/undo",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_json()
        planner = self._planner(client, token, alice_project, att_id)
        assert planner.get("planProposal") is None
        session = planner.get("builderSession") or {}
        assert not session.get("nodeIds") and not session.get("nodeRuns"), session
        assert [n["id"] for n in self._spec(user, alice_project)["dataflow"]["nodes"]] == ["n1"]


class TestDestructiveReplan:
    """dev/59 (DEC-049): the removals and rewires a plan lands: per-victim
    digest pins, cascade, attachment pruning, nodeRuns hygiene, existing-id
    wiring."""

    COORD = "agent.curio.dataflow-builder@1"

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
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.title_prompt():
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

    def _landed(self, response):
        """The plan that landed with the reply *response*: its change card,
        with ``canvas``, what it put on the canvas and took off it."""
        assert response.status_code == 200, response.get_json()
        return _landed_plan(response.get_json())

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def _planner(self, client, token, project_id, att_id) -> dict:
        cards = client.get(
            f"/api/agents/projects/{project_id}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        return next(c for c in cards if c["attachmentId"] == att_id)

    def _landing(self, user, project_id, att_id) -> dict:
        """The plan as the planner keeps it, its pins included."""
        from utk_curio.backend.app.agents.application import attachments as attachments_mod

        return attachments_mod.get_attachment(self._spec(user, project_id), att_id)["planProposal"]

    def test_replace_flow_end_to_end(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(
                nodes=[self._new_node()],
                edges=[{"from": "a", "to": "cleaner"}],  # wire to an EXISTING node
            )],
        )
        card = self._landed(self._run(client, token, alice_project, att_id))
        # DEC-049: the victim was held to the code the mint read; the card names it.
        assert "old-loader" in self._landing(user, alice_project, att_id)["removeContentSha256"]
        (removal,) = card["plan"]["removals"]
        assert removal == {"id": "old-loader", "label": "Load CSV",
                           "nodeType": "curio.builtin/computation-analysis",
                           "contentChars": len("load_csv()")}
        assert card["plan"]["cascadeCount"] == 1  # edge-1 dies with it
        assert "removes 1 node" in card["summary"]
        assert card["canvas"]["removedNodeIds"] == ["old-loader"]
        assert card["canvas"]["removedEdgeIds"] == ["edge-1"]
        spec = self._spec(user, alice_project)
        ids = {n["id"] for n in spec["dataflow"]["nodes"]}
        assert "old-loader" not in ids and "cleaner" in ids
        # The preserved node is byte-identical (the session's contract).
        cleaner = next(n for n in spec["dataflow"]["nodes"] if n["id"] == "cleaner")
        assert cleaner["content"] == "clean()" and cleaner["x"] == 430
        # The new edge wires the created node to the EXISTING cleaner.
        (edge,) = spec["dataflow"]["edges"]
        assert edge["target"] == "cleaner"
        assert edge["source"] == card["canvas"]["nodes"][0]["id"]

    def test_removal_prunes_attachments_and_node_runs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(nodes=[self._new_node()])],
        )
        # A node-target attachment on the victim (dies with it, dev/32) ...
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.curio.node-builder@1"}, headers=_auth(token))
        victim_att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.curio.node-builder@1", "target": {"kind": "node", "targetId": "old-loader"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        # ... and a stale nodeRuns entry for it in the builder session.
        from utk_curio.backend.app.agents.application import attachments as attachments_mod
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        record = attachments_mod.get_attachment(spec, att_id)
        record["builderSession"] = {"phase": "applied", "appliedPlanId": "prev",
                                    "nodeRuns": {"old-loader": "pending", "cleaner": "solved"}}
        projects_storage.write_spec(key, alice_project, spec)
        self._landed(self._run(client, token, alice_project, att_id))
        # The victim's attachment is gone; the builder's survives.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        card_ids = {c["attachmentId"] for c in cards}
        assert victim_att not in card_ids and att_id in card_ids
        # nodeRuns: victim dropped, survivor kept, new pending node joined.
        runs = next(c for c in cards if c["attachmentId"] == att_id)["builderSession"]["nodeRuns"]
        assert "old-loader" not in runs
        assert runs["cleaner"] == "solved"
        assert any(s == "pending" for s in runs.values())

    def test_a_plan_that_removes_a_node_deletes_the_transcript_of_the_agent_on_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """A transcript lives exactly as long as its attachment: the plan that
        removes a node takes the chat of the agent attached to it with it, as a
        detach and a save that deletes the node do."""
        from utk_curio.backend.app.agents.repositories import sessions

        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Revising.\n" + self._revision_tail(nodes=[self._new_node()])],
        )
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.curio.node-builder@1"},
                    headers=_auth(token))
        victim = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.curio.node-builder@1", "target": {"kind": "node", "targetId": "old-loader"}},
            headers=_auth(token),
        ).get_json()
        key = _user_dir_key(user)
        sessions.append_turns(key, alice_project, victim["sessionId"], victim["attachmentId"],
                              [sessions.make_turn("user", "What does this loader read?")])
        transcript = sessions._session_path(key, alice_project, victim["sessionId"])
        assert transcript.exists()
        card = self._landed(self._run(client, token, alice_project, att_id))
        assert card["canvas"]["removedNodeIds"] == ["old-loader"]
        assert not transcript.exists(), "the removed node's agent kept its transcript"

    def test_remove_only_plan_lands(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Cleanup.\n" + self._revision_tail(remove=("old-loader", "cleaner"))],
        )
        card = self._landed(self._run(client, token, alice_project, att_id))
        assert sorted(card["canvas"]["removedNodeIds"]) == ["cleaner", "old-loader"]
        assert self._spec(user, alice_project)["dataflow"]["nodes"] == []
        assert self._planner(client, token, alice_project, att_id)["builderSession"]["phase"] == "ready"

    def test_unknown_removal_targets_feed_correction_rounds(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, calls = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                "Revising.\n" + self._revision_tail(remove=("ghost-node",), nodes=[self._new_node()]),
                "Fixed.\n" + self._revision_tail(nodes=[self._new_node()]),
            ],
        )
        card = self._landed(self._run(client, token, alice_project, att_id))
        assert card["status"] == "applied"  # the corrected replan landed
        feedback = calls[1][-1]["content"]
        assert "'ghost-node' is not a node in the saved dataflow" in feedback

    def test_additive_plans_carry_no_removal_pins(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Adding.\n" + self._revision_tail(remove=(), nodes=[self._new_node()])],
        )
        card = self._landed(self._run(client, token, alice_project, att_id))
        assert "removeContentSha256" not in self._landing(user, alice_project, att_id)
        assert "removals" not in card["plan"]
        assert card["summary"] == "Plan · 1 node, 0 edges"


class TestThePlanCard:
    """What a landed plan's card carries for its rows."""

    def _land(self, client, user, token, project_id, monkeypatch, plan=None):
        import json as _json

        helper = TestDataflowPlanMint()
        replies = None if plan is None else [f"Plan.\n```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"]
        att_id, _ = helper._setup(client, user, token, project_id, monkeypatch, replies=replies)
        return att_id, _landed_plan(helper._run(client, token, project_id, att_id).get_json())

    def test_expects_rides_the_plan_card(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "g", "nodes": [
            {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
             "title": "Load", "intent": "load it",
             "expects": "in: none · out: dataframe"},
        ], "edges": []}
        _, card = self._land(client, user, token, alice_project, monkeypatch, plan=plan)
        assert card["plan"]["nodes"][0]["expects"] == "in: none · out: dataframe"

    def test_edges_render_by_name_on_the_plan_card(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        _, card = self._land(client, user, token, alice_project, monkeypatch)
        (edge_row,) = card["plan"]["edges"]
        assert edge_row["fromLabel"] == "Load" and edge_row["toLabel"] == "Analyze"

    def test_the_connection_lands_on_its_nodes_handles(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        _, card = self._land(client, user, token, alice_project, monkeypatch)
        load, analyze = card["canvas"]["nodes"]
        (edge,) = card["canvas"]["edges"]
        assert (edge["source"], edge["target"]) == (load["id"], analyze["id"])
        assert edge["sourceHandle"] == "out" and edge["targetHandle"] == "in"
        spec_edges = TestDestructiveReplan()._spec(user, alice_project)["dataflow"]["edges"]
        assert [e["id"] for e in spec_edges] == [edge["id"]]

    def test_a_connection_the_dataflow_already_holds_is_not_drawn_again(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A plan edge between two nodes the dataflow already connects, on the
        same circle, lands as the connection there is: no node is fed twice
        by one plan edge."""
        user, token = user_and_token
        base = TestDestructiveReplan()  # seeds Load CSV feeding Clean over edge-1
        att_id, _ = base._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Adding.\n" + base._revision_tail(
                remove=(), nodes=[base._new_node()],
                edges=[{"from": "old-loader", "to": "cleaner"}, {"from": "a", "to": "cleaner"}],
            )],
        )
        card = base._landed(base._run(client, token, alice_project, att_id))
        new_id = card["canvas"]["nodes"][0]["id"]
        assert [(e["source"], e["target"]) for e in card["canvas"]["edges"]] == [(new_id, "cleaner")]
        pairs = [(e["source"], e["target"]) for e in base._spec(user, alice_project)["dataflow"]["edges"]]
        assert sorted(pairs) == sorted([("old-loader", "cleaner"), (new_id, "cleaner")])


class TestPlanFanInValidation:
    """dev/67-3 (DEC-051): invalid multi-input topology never lands: fan-in
    validates against the template capacity BEFORE anything materializes, the
    corrective error says how to rewire (one node that takes several inputs),
    and the landing puts each edge into a growing node on a circle of its own,
    so plan-created fan-in works WITHOUT a reload. The Merge Flow and its slots
    left with #662."""

    #: The default roster plus a node whose one input port takes at most two
    #: edges ("[1,2]"): two circles, "in" and "in_1".
    BOUNDED_TEMPLATES = [
        {"id": "computation-analysis", "label": "Computation Analysis",
         "category": "computation", "engine": "python", "editor": "code",
         "description": "Run python analysis code.",
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "compare-two", "label": "Compare Two",
         "category": "computation", "engine": "python", "editor": "code",
         "description": "Compare two tables.",
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,2]"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    ]

    #: A computation node plus the Spatial Join's shape: two input ports, one
    #: edge each, on the circles "in" (input_0) and "in_1" (input_1).
    TWO_PORT_TEMPLATES = BOUNDED_TEMPLATES[:1] + [
        {"id": "spatial-join", "label": "Spatial Join",
         "category": "data", "engine": "python", "editor": "none", "hasCode": False,
         "description": "Pair the rows of two inputs whose shapes meet.",
         "inputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"},
                        {"types": ["GEODATAFRAME"], "cardinality": "1"}],
         "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}]},
    ]

    def _plan_reply(self, plan):
        import json as _json

        return f"Plan.\n```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def _node(self, ref, node_type="curio.builtin/computation-analysis"):
        return {"ref": ref, "nodeType": node_type, "title": ref.upper(),
                "intent": f"do {ref}"}

    def test_fanin_into_single_input_node_refuses_then_a_combining_step_replan_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        single = "curio.builtin/data-summary"
        bad = {"goal": "g", "nodes": [self._node("a"), self._node("b"), self._node("c", single)],
               "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}]}
        # What the refusal asks for: both flows into one code step that takes
        # several inputs (one circle each), and that step into the target.
        good = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"),
                          self._node("m"), self._node("c", single)],
                "edges": [{"from": "a", "to": "m"}, {"from": "b", "to": "m"},
                          {"from": "m", "to": "c"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad), self._plan_reply(good)],
        )
        r = helper._run(client, token, alice_project, att_id)
        assert _landed_plan(r.get_json())["status"] == "applied"  # the combining replan landed
        feedback = calls[1][-1]["content"]
        assert (
            "target 'C' (curio.builtin/data-summary) accepts 1 input but the plan wires 2: "
            "wire 'a', 'b' into one node that takes several inputs (a code step that "
            "combines them), and connect that node to the target"
        ) in feedback
        assert "curio.builtin/merge-flow" not in feedback

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
        card = helper._landed(helper._run(client, token, alice_project, att_id))
        # Removing old-loader frees cleaner's single input: the replan lands.
        assert card["status"] == "applied"
        feedback = calls[1][-1]["content"]
        assert "plus 1 existing connection" in feedback

    def test_fanin_apply_honors_a_named_circle_and_fills_the_lowest_free(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Successor of the Merge apply (#662): A and B wired straight into a
        # node that takes several inputs, each edge on a circle of its own.
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        plan = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"), self._node("m")],
                "edges": [{"from": "a", "to": "m", "toHandle": "in_3"},
                          {"from": "b", "to": "m"}]}
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(plan)],
        )
        r = helper._run(client, token, alice_project, att_id)
        applied = _landed_plan(r.get_json())["canvas"]["edges"]
        # The named circle is honored; the unnamed edge takes the lowest free,
        # circle 0, whose handle is the plain "in".
        assert sorted(e["targetHandle"] for e in applied) == ["in", "in_3"]
        assert all(e["sourceHandle"] == "out" for e in applied)
        # Persisted, not just reported — the reload-heals era is over.
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        spec_handles = sorted(
            e.get("targetHandle") for e in spec["dataflow"]["edges"]
        )
        assert spec_handles == ["in", "in_3"]

    def test_fanin_into_a_growing_node_mints_and_takes_a_circle_per_edge(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        # The computation template declares one "[1,n]" port: one circle per edge.
        plan = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"), self._node("c"), self._node("t")],
                "edges": [{"from": "a", "to": "t"}, {"from": "b", "to": "t", "toHandle": "in_2"},
                          {"from": "c", "to": "t"}]}
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(plan)],
        )
        r = helper._run(client, token, alice_project, att_id)
        card = _landed_plan(r.get_json())
        assert card["status"] == "applied"
        # A named free circle is honored; the others take the first free ones.
        assert sorted(e["targetHandle"] for e in card["canvas"]["edges"]) == ["in", "in_1", "in_2"]
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert sorted(e.get("targetHandle") for e in spec["dataflow"]["edges"]) == ["in", "in_1", "in_2"]

    def test_a_circle_past_a_bounded_nodes_limit_feeds_correction(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Successor of the Merge slot-name check (#662): a node whose one port
        # takes at most two edges has circles "in" and "in_1" only, and a plan
        # that wires more than two is told to reduce the fan-in.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        bounded = "curio.builtin/compare-two"
        bad = {"goal": "g",
               "nodes": [self._node("a"), self._node("b"), self._node("c"), self._node("p", bounded)],
               "edges": [{"from": "a", "to": "p", "toHandle": "in_1"},
                         {"from": "b", "to": "p", "toHandle": "in_2"},
                         {"from": "c", "to": "p"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad),
                     "Fixed.\n" + helper._plan_tail()],
            templates=self.BOUNDED_TEMPLATES,
        )
        r = helper._run(client, token, alice_project, att_id)
        assert _landed_plan(r.get_json())["status"] == "applied"
        feedback = calls[1][-1]["content"]
        assert "edges[1].toHandle 'in_2': this node's inputs are \"in\", \"in_1\"" in feedback
        assert "edges[0].toHandle" not in feedback  # "in_1" is within the limit
        assert (
            "target 'P' (curio.builtin/compare-two) accepts at most 2 inputs but the "
            "plan wires 3: reduce the fan-in"
        ) in feedback

    def test_a_handle_that_names_no_circle_feeds_correction(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A growing node's first circle is "in", never the Merge's old "in_0";
        # with no limit the refusal lists the first circles and an ellipsis.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        bad = {"goal": "g",
               "nodes": [self._node("a"), self._node("b"), self._node("m")],
               "edges": [{"from": "a", "to": "m", "toHandle": "in_0"},
                         {"from": "b", "to": "m", "toHandle": "in_1"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad),
                     "Fixed.\n" + helper._plan_tail()],
        )
        r = helper._run(client, token, alice_project, att_id)
        assert _landed_plan(r.get_json())["status"] == "applied"
        feedback = calls[1][-1]["content"]
        assert (
            "edges[0].toHandle 'in_0': this node's inputs are \"in\", \"in_1\", \"in_2\", ..."
        ) in feedback
        assert "edges[1].toHandle" not in feedback

    def test_two_edges_into_a_two_port_node_take_its_two_circles(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # #576: the Spatial Join's inputs follow its circles, "in" for input_0
        # and "in_1" for input_1. A plan that names no circle put both of its
        # edges on "in", so the join had input_0 twice and no input_1.
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        join = "curio.builtin/spatial-join"
        plan = {"goal": "g",
                "nodes": [self._node("a"), self._node("b"), self._node("j", join)],
                "edges": [{"from": "a", "to": "j"}, {"from": "b", "to": "j"}]}
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(plan)], templates=self.TWO_PORT_TEMPLATES,
        )
        r = helper._run(client, token, alice_project, att_id)
        card = _landed_plan(r.get_json())
        assert card["status"] == "applied"
        applied = card["canvas"]["edges"]
        assert sorted(e["targetHandle"] for e in applied) == ["in", "in_1"]
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert sorted(e.get("targetHandle") for e in spec["dataflow"]["edges"]) == ["in", "in_1"]

    def test_a_handle_past_a_two_port_nodes_circles_feeds_correction(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # #576: a two-port node's circles are "in" and "in_1", as a bounded
        # growing node's are; "in_2" names no input of it.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        join = "curio.builtin/spatial-join"
        bad = {"goal": "g",
               "nodes": [self._node("a"), self._node("b"), self._node("j", join)],
               "edges": [{"from": "a", "to": "j"}, {"from": "b", "to": "j", "toHandle": "in_2"}]}
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._plan_reply(bad), "Fixed.\n" + helper._plan_tail()],
            templates=self.TWO_PORT_TEMPLATES,
        )
        helper._run(client, token, alice_project, att_id)
        feedback = calls[1][-1]["content"]
        assert "edges[1].toHandle 'in_2': this node's inputs are \"in\", \"in_1\"" in feedback


class TestALandedPlansResult:
    """A plan lands whole: it removes what it removes, checked as it lands,
    hands the live canvas the removed ids, and its card names what changed
    and ends with the Topology verdict. A plan with no nodes lands on its
    connections."""

    def _replan(self, client, user, token, project_id, monkeypatch, runs=None, **setup):
        """TestDestructiveReplan's canvas (Load CSV feeds Clean over edge-1)
        and its plan: API Fetch replaces Load CSV and feeds Clean. *runs* are
        the builder session's node runs before the plan."""
        from utk_curio.backend.app.agents.application import attachments as attachments_mod
        from utk_curio.backend.app.projects import storage as projects_storage

        base = TestDestructiveReplan()
        att_id, _ = base._setup(
            client, user, token, project_id, monkeypatch,
            replies=["Revising.\n" + base._revision_tail(
                nodes=[base._new_node()], edges=[{"from": "a", "to": "cleaner"}],
            )],
            **setup,
        )
        if runs is not None:
            key = _user_dir_key(user)
            spec = projects_storage.read_spec(key, project_id)
            attachments_mod.get_attachment(spec, att_id)["builderSession"] = {
                "phase": "applied", "appliedPlanId": "prev", "nodeRuns": dict(runs),
            }
            projects_storage.write_spec(key, project_id, spec)
        return att_id, base._landed(base._run(client, token, project_id, att_id))

    def test_a_landed_plan_removes_what_it_removes_and_ends_with_the_topology(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, card = self._replan(
            client, user, token, alice_project, monkeypatch,
            runs={"old-loader": "pending", "cleaner": "solved"},
        )
        assert card["status"] == "applied"
        # The live canvas is handed what left the saved one.
        assert card["canvas"]["removedNodeIds"] == ["old-loader"]
        assert card["canvas"]["removedEdgeIds"] == ["edge-1"]
        spec = TestDestructiveReplan()._spec(user, alice_project)
        ids = {n["id"] for n in spec["dataflow"]["nodes"]}
        assert "old-loader" not in ids and "cleaner" in ids
        cleaner = next(n for n in spec["dataflow"]["nodes"] if n["id"] == "cleaner")
        assert cleaner["content"] == "clean()" and cleaner["x"] == 430
        # The new node feeds Clean on its first circle.
        new_id = card["canvas"]["nodes"][0]["id"]
        (edge,) = spec["dataflow"]["edges"]
        assert (edge["source"], edge["target"], edge["targetHandle"]) == (new_id, "cleaner", "in")
        # Its card names what changed and ends with the verdict.
        assert card["lines"][0].startswith("+1 node · +1 connection · ")
        assert card["lines"][-1] == "Topology: acyclic."
        # The removed node leaves the runs, the kept one keeps its state, and
        # the new one awaits Build & validate or Solve.
        session = TestDestructiveReplan()._planner(client, token, alice_project, att_id)["builderSession"]
        assert session["nodeRuns"] == {"cleaner": "solved", new_id: "pending"}
        assert session["phase"] == "applied"

    def test_a_node_that_takes_one_input_takes_the_feed_of_the_node_it_loses(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Clean takes one input, which Load CSV fills until the plan removes
        it. The mint counted the dataflow the plan leaves, and so does the
        landing: the new feed is not refused for the edge that goes with Load
        CSV."""
        user, token = user_and_token
        _att_id, card = self._replan(
            client, user, token, alice_project, monkeypatch, cleaner_type="curio.builtin/data-summary",
        )
        assert card["status"] == "applied"
        assert card["canvas"]["removedEdgeIds"] == ["edge-1"]
        (edge,) = TestDestructiveReplan()._spec(user, alice_project)["dataflow"]["edges"]
        assert (edge["source"], edge["target"]) == (card["canvas"]["nodes"][0]["id"], "cleaner")

    def test_a_plan_of_connections_lands_and_removes_what_it_names(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """TestPlanTopologyApply's repair: an interaction edge in, the loop's
        connection out, and nothing else."""
        user, token = user_and_token
        base = TestPlanTopologyMint()
        plan = {"goal": "convert", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}], "removeEdges": ["e5"]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Fix.\n" + base._tail(plan)], edges=TestPlanTopologyApply()._cyclic_edges())
        card = base._landed(base._run(client, token, alice_project, att_id).get_json())
        assert (card["canvas"]["removedNodeIds"], card["canvas"]["removedEdgeIds"]) == ([], ["e5"])
        edges = TestDestructiveReplan()._spec(user, alice_project)["dataflow"]["edges"]
        assert all(e["id"] != "e5" for e in edges)
        assert any(e.get("type") == "Interaction" and e["source"] == "vis" and e["target"] == "pool" for e in edges)
        assert card["lines"][-1] == "Topology: acyclic."

    def test_a_plan_of_connections_only_lands(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        base = TestPlanTopologyMint()
        plan = {"goal": "link", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch, replies=["Link.\n" + base._tail(plan)])
        card = base._landed(base._run(client, token, alice_project, att_id).get_json())
        assert card["status"] == "applied"
        assert (card["canvas"]["removedNodeIds"], card["canvas"]["removedEdgeIds"]) == ([], [])
        assert card["lines"][0] == "+0 nodes · +1 connection"
        assert card["lines"][-1] == "Topology: acyclic."


#: Why a test draft's node type is new. A draft that adds a template carries
#: one: the closest existing templates and why each is inadequate.
DRAFT_JUSTIFICATION = (
    "Considered curio.builtin/data-summary and curio.builtin/vis-simple: "
    "neither keeps a research note with its own title and color."
)


class TestPackageBuilderTools:
    """dev/89 commit 8, package.draft.apply: the ONE package-writing mutate
    contract, which the Node Builder's chat holds. Mint runs the isolated
    build service and persists bounded provenance; Apply promotes the exact
    reviewed artifact digest, inserts the requested nodes server-side
    (normalized appearance at metadata.appearance), and tells the frontend to
    refresh registries before painting (registry-before-canvas)."""

    COORD = "agent.curio.node-builder@1"
    TARGET = "ai.agent.notes@1"

    def _draft_params(self, *, color="pink", template_id="note-kind"):
        return {
            "mode": "create",
            "target": self.TARGET,
            "justification": DRAFT_JUSTIFICATION,
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
                f"starters/{template_id}/Default.py": {"text": "return input_0\n"},
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
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.title_prompt():
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

    def test_the_created_nodes_name_the_agent_that_drafted_them(self, client, user_and_token, tmp_curio,
                                                                 alice_project, monkeypatch):
        """Each node the draft adds starts its history on the canvas with an
        entry named after the agent, as a node.create apply's does; the saved
        nodes carry no name."""
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._draft_tail(self._draft_params()), "Proposed for your review."],
        )
        run = self._run(client, token, alice_project, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        created = resp.get_json()["createdNodes"]
        name = builtin.get_builtin_manifest(self.COORD).name
        assert created and [node["agent"] for node in created] == [name] * len(created)
        with client.application.app_context():
            user_key = _user_dir_key(user)
        ids = {node["id"] for node in created}
        saved = [n for n in projects_storage.read_spec(user_key, alice_project)["dataflow"]["nodes"] if n["id"] in ids]
        assert len(saved) == len(created) and all("agent" not in n for n in saved)

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


class TestNewNodeTypesInADraft:
    """A package draft is the one way an agent makes a node type. Before the
    build, every template a draft adds (all of a create's, the new ones of an
    extend) passes the three checks the retired one-template tool had: a
    justification the user judges on the card, a label no available template
    has (reuse territory), and code that reads only grounded sources. Each
    refusal says what to change."""

    @pytest.fixture(autouse=True)
    def _fresh_build_jobs(self):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        yield
        build_jobs.reset_registry()

    def _mint(self, client, token, project_id, monkeypatch, params):
        """One Node Builder chat whose model asks for the draft *params*:
        the attachment, the run's parts, and what the model was handed back."""
        helper = TestPackageBuilderTools()
        att_id, calls = helper._setup(
            client, token, project_id, monkeypatch,
            replies=[helper._draft_tail(params), "Done."],
        )
        run = helper._run(client, token, project_id, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        return att_id, run.get_json()["content"], calls[1][-1]["content"]

    def _refusal(self, client, token, project_id, monkeypatch, params):
        _, parts, handed_back = self._mint(client, token, project_id, monkeypatch, params)
        assert all(p["type"] != "proposal" for p in parts), parts
        assert "package.draft.apply: refused" in handed_back, handed_back
        return handed_back

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}"
            f"/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    @pytest.mark.parametrize("justification", [None, "   "])
    def test_a_draft_that_adds_a_node_type_needs_its_justification(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch, justification):
        _, token = user_and_token
        params = TestPackageBuilderTools()._draft_params()
        if justification is None:
            del params["justification"]
        else:
            params["justification"] = justification
        refusal = self._refusal(client, token, alice_project, monkeypatch, params)
        assert "the review needs your reasoning" in refusal
        assert "note-kind" in refusal  # the node type the draft adds
        assert '"justification"' in refusal
        assert "closest existing templates" in refusal
        assert "why each is inadequate" in refusal

    def test_an_overlong_justification_is_refused(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application.proposals import mint

        _, token = user_and_token
        params = TestPackageBuilderTools()._draft_params()
        params["justification"] = "x" * (mint._JUSTIFICATION_MAX_CHARS + 1)
        refusal = self._refusal(client, token, alice_project, monkeypatch, params)
        assert f"at most {mint._JUSTIFICATION_MAX_CHARS}" in refusal

    @pytest.mark.parametrize("label", [
        "Computation Analysis",  # its slug is the built-in's template id
        "python computation",    # the built-in's label, in another case
    ])
    def test_a_new_template_like_an_existing_one_is_reuse_territory(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch, label):
        _, token = user_and_token
        params = TestPackageBuilderTools()._draft_params()
        params["manifest"]["templates"][0]["label"] = label
        refusal = self._refusal(client, token, alice_project, monkeypatch, params)
        assert "reuse territory" in refusal
        assert "curio.builtin/computation-analysis" in refusal  # the template to use
        assert "note-kind" in refusal
        assert "a label no existing template has" in refusal

    @pytest.mark.parametrize("where", [
        "its source file sources/note_kind.py",
        "nodes[0].content",
    ])
    def test_the_code_of_a_new_template_reads_only_grounded_sources(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch, where):
        # Issue #298's shape: a file nobody gave and no catalog dataset holds.
        code = 'import pandas as pd\nreturn pd.read_csv("bras_ibge_data.csv")\n'
        _, token = user_and_token
        params = TestPackageBuilderTools()._draft_params()
        if where.startswith("its source file"):
            params["manifest"]["templates"][0]["source"] = "sources/note_kind.py"
            params["files"]["sources/note_kind.py"] = {"text": code}
        else:
            params["nodes"][0]["content"] = code
        refusal = self._refusal(client, token, alice_project, monkeypatch, params)
        assert "source grounding refused" in refusal
        assert "bras_ibge_data.csv" in refusal
        assert f"'note-kind', {where}" in refusal

    def test_a_justified_draft_mints_with_its_reasoning_and_its_type_is_reusable(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import attachments
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, parts, handed_back = self._mint(
            client, token, alice_project, monkeypatch, TestPackageBuilderTools()._draft_params(),
        )
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert "awaits the user's explicit review" in handed_back
        # The reasoning is what the user judges: on the card's part, on the
        # part a reload renders, and on the stored proposal.
        assert proposal["justification"] == DRAFT_JUSTIFICATION
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        persisted = next(p for t in turns for p in t.get("content", [])
                         if p.get("type") == "proposal")
        assert persisted["justification"] == DRAFT_JUSTIFICATION
        stored = attachments.find_proposal(
            projects_storage.read_spec(key, alice_project), att_id, proposal["proposalId"])
        assert stored["justification"] == DRAFT_JUSTIFICATION
        # Applied, the new type is one node.create can use in a later run.
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        available = {t["id"] for t in packages_templates.available_templates(key, alice_project)}
        assert "ai.agent.notes/note-kind" in available

    def test_an_extend_justifies_only_the_templates_it_adds(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.builder.extension import installed_package_digest

        user, token = user_and_token
        key = _user_dir_key(user)
        helper = TestPackageBuilderTools()
        created = helper._draft_params()
        att_id, parts, _ = self._mint(client, token, alice_project, monkeypatch, created)
        proposal = next(p for p in parts if p["type"] == "proposal")
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        kept = created["manifest"]["templates"][0]

        def extend(templates, **extra):
            return {
                "mode": "extend",
                "baseDigest": installed_package_digest(key, helper.TARGET),
                "manifest": {**created["manifest"], "version": "1.1.0", "templates": templates},
                **extra,
            }

        added = {**kept, "id": "summary-kind", "label": "Research summary"}
        refusal = self._refusal(client, token, alice_project, monkeypatch, extend([kept, added]))
        assert "the review needs your reasoning" in refusal
        assert "summary-kind" in refusal and "note-kind" not in refusal
        _, parts, _ = self._mint(client, token, alice_project, monkeypatch,
                                 extend([kept, added], justification=DRAFT_JUSTIFICATION))
        assert next(p for p in parts if p["type"] == "proposal")["justification"] == DRAFT_JUSTIFICATION
        # A change to a template the package has adds no node type.
        revised = {**kept, "description": "A research note, revised."}
        _, parts, _ = self._mint(client, token, alice_project, monkeypatch, extend([revised]))
        assert "justification" not in next(p for p in parts if p["type"] == "proposal")

    def test_a_library_a_new_template_imports_is_installed_at_apply(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """#565 on the draft path: the libraries a new template's code imports
        are its dependencies, installed by the Apply that installs the type."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        asked: list = []
        monkeypatch.setattr(
            pip_runner, "install_python_deps",
            lambda deps, on_line=None: asked.append(dict(deps))
            or pip_runner.InstallReport(installed=sorted(deps), skipped=[]),
        )
        monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
        _, token = user_and_token
        params = TestPackageBuilderTools()._draft_params()
        params["manifest"]["templates"][0]["source"] = "sources/note_kind.py"
        params["files"]["sources/note_kind.py"] = {"text": "import shapely\nreturn input_0\n"}
        att_id, parts, _ = self._mint(client, token, alice_project, monkeypatch, params)
        proposal = next(p for p in parts if p["type"] == "proposal")
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert asked == [{"shapely": "*"}]

    def test_a_hosted_guests_draft_is_refused_at_apply_before_anything_lands(
            self, client, db, tmp_curio, monkeypatch):
        """#451's rule on the agent apply path. The shared guest is every
        anonymous visitor, so a package in its store is in every visitor's
        palette, with its libraries one pip run away: the refusal comes
        before the files, not after them."""
        from utk_curio.backend import config
        from utk_curio.backend.app.packages.infrastructure import backend_runtime
        from utk_curio.backend.app.packages.infrastructure import pip_runner
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
        asked: list = []
        monkeypatch.setattr(pip_runner, "install_python_deps",
                            lambda deps, on_line=None: asked.append(dict(deps)))
        guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                     email="guest@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="guest-token"))
        db.session.commit()
        # A hosted guest saves no dataflow: on a deployed Curio its dataflows
        # are the examples the server seeds. This one is saved as the local
        # guest saves one, with sign-in off, before the hosted guest's turn.
        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        project = client.post(
            "/api/projects",
            json={"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                  "outputs": []},
            headers=_auth("guest-token"),
        ).get_json()["id"]
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        params = TestPackageBuilderTools()._draft_params()
        params["dependencies"] = {"python": {"weather-sdk": "1.2.0"}}
        att_id, parts, _ = self._mint(client, "guest-token", project, monkeypatch, params)
        proposal = next(p for p in parts if p["type"] == "proposal")

        resp = self._apply(client, "guest-token", project, att_id, proposal["proposalId"])

        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert "guest" in resp.get_json()["error"].lower()
        assert asked == []
        assert not (user_packages_dir(_user_dir_key(guest)) / TestPackageBuilderTools.TARGET).exists()


class TestTheOneTemplateToolIsRetired:
    """node.template.create is retired: a package draft is the one way an
    agent makes a node type. No agent is offered the tool, a request for it
    mints nothing, and a proposal of it saved before no longer applies."""

    RETIRED = "node.template.create"
    COORD = "agent.curio.node-builder@1"

    def test_no_agent_is_offered_it(self):
        from utk_curio.backend.app.agents.application import tools
        from utk_curio.backend.app.agents.domain import builtin

        assert self.RETIRED not in tools.REGISTRY
        for m in builtin.list_builtin_manifests():
            assert self.RETIRED not in [t.id for t in m.tools], m.agent_id
        granted = tools.resolve_grants(builtin.get_builtin_manifest(self.COORD).tools)
        offered = [t["name"] for t in tools.native_tools(granted)]
        assert tools.wire_name(self.RETIRED) not in offered
        for key in ("instruction", "package.build"):
            assert self.RETIRED not in builtin.read_prompt_text(self.COORD, key), key

    def test_a_request_for_it_mints_nothing(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir

        user, token = user_and_token
        request = {"toolRequest": {"tool": self.RETIRED, "params": {
            "justification": "Considered curio.builtin/computation-analysis: it cannot score.",
            "template": {"label": "Sentiment Scorer", "engine": "python",
                         "content": "print('score')"},
        }}}
        helper = TestPackageBuilderTools()
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=["```curio.v1\n" + json.dumps(request) + "\n```", "No node type."],
        )
        run = helper._run(client, token, alice_project, att_id, message="make a scorer node")
        assert run.status_code == 200, run.get_data(as_text=True)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        assert f"tool {self.RETIRED!r} is not granted" in calls[1][-1]["content"]
        assert not list(user_packages_dir(_user_dir_key(user)).glob("curio.agent.*"))

    def test_a_saved_proposal_of_it_no_longer_applies(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import attachments
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, _ = TestPackageBuilderTools()._setup(
            client, token, alice_project, monkeypatch, replies=["Hello."])
        spec = projects_storage.read_spec(key, alice_project)
        attachments.get_attachment(spec, att_id)["activeProposal"] = {
            "proposalId": "saved-before",
            "tool": self.RETIRED,
            "justification": "Considered curio.builtin/computation-analysis: it cannot score.",
            "template": {"label": "Sentiment Scorer", "engine": "python",
                         "description": "", "content": "print('score')"},
            "summary": "Create a new custom node type: Sentiment Scorer",
            "status": "pending",
        }
        projects_storage.write_spec(key, alice_project, spec)

        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            "/proposals/saved-before/apply",
            headers=_auth(token),
        )

        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert f"no apply flow exists for tool {self.RETIRED!r}" in resp.get_json()["error"]
        assert not list(user_packages_dir(key).glob("curio.agent.*"))
        nodes = (projects_storage.read_spec(key, alice_project).get("dataflow") or {}).get("nodes") or []
        assert nodes == []


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
            "justification": (
                "Considered curio.builtin/computation-analysis: it runs in the shared "
                "sandbox, and this count runs in its own package backend."
            ),
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
    """dev/112 (DEC-070): the owner's 2026-08-25 session, made unlandable: a
    plan data edge that closes a cycle is refused with the path named; an
    interaction edge is kept as such, and refused where neither end shows the
    selection it receives; edge-only plans land; removed connections are named
    on the plan's card."""

    COORD = "agent.curio.dataflow-builder@1"
    TEMPLATES = [
        {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
         "engine": "python", "editor": "code", "description": "d",
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python",
         "editor": "none", "hasCode": False, "description": "d", "bidirectional": True,
         "inputPorts": [{"types": ["JSON"], "cardinality": "1"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
        {"id": "vis-vega", "label": "Vega", "category": "visualization", "engine": "javascript",
         "editor": "grammar", "description": "d", "bidirectional": True,
         "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
         "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    ]
    # The owner's canvas, its Merge Flow now the code step that combines
    # (#662): Load, Transform, Combine, Pool, Vis, each feeding the next.
    NODES = [
        {"id": "load", "type": "curio.builtin/computation-analysis", "content": "", "goal": "Fabricate", "x": 0, "y": 0},
        {"id": "xform", "type": "curio.builtin/computation-analysis", "content": "", "goal": "Transform", "x": 400, "y": 0},
        {"id": "combine", "type": "curio.builtin/computation-analysis", "content": "", "goal": "Pool Input Combine", "x": 800, "y": 0},
        {"id": "pool", "type": "curio.builtin/data-pool", "content": "", "goal": "Time Data Pool", "x": 1200, "y": 0},
        {"id": "vis", "type": "curio.builtin/vis-vega", "content": "", "goal": "Metric Distribution", "x": 1600, "y": 0},
    ]
    EDGES = [
        {"id": "e1", "source": "load", "target": "xform", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e2", "source": "xform", "target": "combine", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e3", "source": "combine", "target": "pool", "sourceHandle": "out", "targetHandle": "in"},
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
            from utk_curio.backend.app.agents.application.turns import titles
            if messages and messages[0].get("content") == titles.title_prompt():
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="fix the cycle"):
        return client.post(f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
                           json={"message": message}, headers=_auth(token))

    @staticmethod
    def _landed(body):
        """The plan that landed with the turn, or None when none did."""
        assert not [p for p in body["content"] if p["type"] == "proposal"], "a plan waited for review"
        if not any(p.get("kind") == "plan" for p in _changes(body)):
            return None
        return _landed_plan(body)

    def test_the_owners_plan_is_refused_with_the_cycle_named(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Round one of the 2026-08-25 session: vis to combine as a data edge.
        user, token = user_and_token
        owner_plan = {"goal": "interaction loop", "nodes": [], "edges": [{"from": "vis", "to": "combine"}]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(owner_plan), "I give up."])
        body = self._run(client, token, alice_project, att_id).get_json()
        assert self._landed(body) is None
        feedback = calls[1][-1]["content"]
        assert "creates a cycle" in feedback
        assert "Metric Distribution" in feedback and "Pool Input Combine" in feedback
        assert '"kind": "interaction"' in feedback
        # The saved graph is untouched: nothing materialized (DEC-051 discipline).
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        assert len(projects_storage.read_spec(_user_dir_key(user), alice_project)["dataflow"]["edges"]) == 4

    def test_interaction_edge_to_the_pool_lands_edge_only_and_keeps_its_kind(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "interaction", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch, replies=["Fix.\n" + self._tail(plan)])
        card = self._landed(self._run(client, token, alice_project, att_id).get_json())
        assert card is not None, "an edge-only plan must land (no filler nodes needed)"
        assert card["summary"] == "Plan · 0 nodes, 1 edge"
        assert card["plan"]["edges"] == [{
            "from": "vis", "to": "pool", "kind": "interaction",
            "fromLabel": "Metric Distribution", "toLabel": "Time Data Pool",
        }]

    def test_interaction_edge_into_a_code_step_is_refused_naming_the_fix(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        plan = {"goal": "interaction", "edges": [{"from": "vis", "to": "combine", "kind": "interaction"}]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(plan), "ok"])
        body = self._run(client, token, alice_project, att_id).get_json()
        assert self._landed(body) is None
        feedback = calls[1][-1]["content"]
        assert "invalid interaction edges" in feedback
        assert "'combine' is computation-analysis" in feedback
        assert "end the interaction edge at a view that highlights or at a data-pool" in feedback

    def test_removal_only_plan_that_breaks_a_user_cycle_lands_and_names_the_connection(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "combine", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "break", "removeEdges": ["e5"]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Fix.\n" + self._tail(plan)], edges=cyclic)
        card = self._landed(self._run(client, token, alice_project, att_id).get_json())
        assert card is not None
        assert card["summary"] == "Plan · 0 nodes, 0 edges, removes 1 connection"
        assert card["plan"]["removals"] == []
        assert card["plan"]["removedEdges"] == [
            {"id": "e5", "fromLabel": "Metric Distribution", "toLabel": "Pool Input Combine"},
        ]
        assert card["canvas"]["removedEdgeIds"] == ["e5"]

    def test_remove_and_readd_as_data_is_still_refused(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Rounds two to five of the session: removeEdges the loop edge, add it back as data.
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "combine", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "convert", "nodes": [], "edges": [{"from": "vis", "to": "combine"}], "removeEdges": ["e5"]}
        att_id, calls = self._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Fix.\n" + self._tail(plan), "ok"], edges=cyclic)
        assert self._landed(self._run(client, token, alice_project, att_id).get_json()) is None
        assert "creates a cycle" in calls[1][-1]["content"]

    def test_a_plan_that_leaves_a_user_cycle_alone_is_not_blamed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        cyclic = self.EDGES + [{"id": "e5", "source": "vis", "target": "combine", "sourceHandle": "out", "targetHandle": "in_1"}]
        plan = {"goal": "note", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                          "title": "Side", "intent": "unrelated"}], "edges": []}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + self._tail(plan)], edges=cyclic)
        assert self._landed(self._run(client, token, alice_project, att_id).get_json()) is not None

    def test_existing_interaction_edges_do_not_count_toward_fan_in_or_cycles(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        with_feedback = self.EDGES + [{"id": "e5", "source": "vis", "target": "pool", "type": "Interaction",
                                       "sourceHandle": "in/out", "targetHandle": "in/out"}]
        plan = {"goal": "extend", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                            "title": "Post", "intent": "downstream"}],
                "edges": [{"from": "vis", "to": "n"}]}
        att_id, _ = self._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + self._tail(plan)], edges=with_feedback)
        assert self._landed(self._run(client, token, alice_project, att_id).get_json()) is not None


class TestPlanTopologyApply:
    """dev/112 (DEC-070), a plan as it lands: interaction edges materialize as
    the Trill's Interaction shape, removed connections are counted, its card
    ends with the topology verdict, and a connection drawn while it waited
    that it would close into a cycle refuses it."""

    def _base(self):
        return TestPlanTopologyMint()

    def _cyclic_edges(self):
        return TestPlanTopologyMint.EDGES + [
            {"id": "e5", "source": "vis", "target": "combine", "sourceHandle": "out", "targetHandle": "in_1"},
        ]

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def test_the_repair_lands_as_an_interaction_edge_and_reports_acyclic(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        plan = {"goal": "convert", "edges": [{"from": "vis", "to": "pool", "kind": "interaction"}], "removeEdges": ["e5"]}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Fix.\n" + base._tail(plan)], edges=self._cyclic_edges())
        card = base._landed(base._run(client, token, alice_project, att_id).get_json())
        (created,) = card["canvas"]["edges"]
        assert created["type"] == "Interaction"
        assert created["sourceHandle"] == "in/out" and created["targetHandle"] == "in/out"
        assert (card["canvas"]["removedNodeIds"], card["canvas"]["removedEdgeIds"]) == ([], ["e5"])
        edges = self._spec(user, alice_project)["dataflow"]["edges"]
        assert all(e["id"] != "e5" for e in edges)
        assert any(e.get("type") == "Interaction" and e["source"] == "vis" and e["target"] == "pool" for e in edges)
        # Its card says what changed and ends with the verdict.
        assert card["lines"][0].startswith("+0 nodes · +1 connection · ")
        assert card["lines"][-1] == "Topology: acyclic."

    def test_its_card_reports_a_user_cycle_the_plan_left_alone(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        base = self._base()
        plan = {"goal": "side", "nodes": [{"ref": "n", "nodeType": "curio.builtin/computation-analysis",
                                          "title": "Side", "intent": "unrelated"}], "edges": []}
        att_id, _ = base._setup(client, user, token, alice_project, monkeypatch,
                                replies=["Add.\n" + base._tail(plan)], edges=self._cyclic_edges())
        card = base._landed(base._run(client, token, alice_project, att_id).get_json())
        verdict = card["lines"][-1]
        assert verdict.startswith("Topology: cycle through")
        assert "Metric Distribution" in verdict and "Pool Input Combine" in verdict

    def test_a_connection_drawn_while_the_plan_waited_that_it_would_close_into_a_cycle_refuses_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """Acyclic at mint: Fabricate feeds Pool Input Combine (a code step
        takes many inputs, one circle each), and the plan waits for Ana, in the
        view it removes. She draws Combine into Fabricate meanwhile, which the
        plan's edge would close into a cycle: nothing lands."""
        import time as real_time
        from types import SimpleNamespace

        from utk_curio.backend.app.agents.application.proposals import changes
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.collaboration import room_state

        user, token = user_and_token
        base = self._base()
        plan = {"goal": "wire", "edges": [{"from": "load", "to": "combine"}], "removeNodes": ["vis"]}
        att_id, calls = base._setup(client, user, token, alice_project, monkeypatch,
                                    replies=["Wire.\n" + base._tail(plan), "It would loop."])
        held = {"by": "Ana"}
        real_snapshot = room_state.snapshot

        def _snapshot(room):
            out = dict(real_snapshot(room) or {})
            if held["by"]:
                out["locks"] = {"vis": {"user_id": "someone-else", "name": held["by"]}}
            return out

        def _sleep(seconds):
            if held["by"]:
                spec = dataflow_docs.live(_user_dir_key(user), alice_project)
                spec["dataflow"]["edges"].append(
                    {"id": "u1", "source": "combine", "target": "load", "sourceHandle": "out", "targetHandle": "in"})
                dataflow_docs.write(_user_dir_key(user), alice_project, spec, dataflow_docs.person("someone-else", "edit"))
                held["by"] = None

        monkeypatch.setattr(room_state, "snapshot", _snapshot)
        monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=_sleep))
        body = base._run(client, token, alice_project, att_id).get_json()
        assert held["by"] is None, "the plan never waited for Ana"
        assert base._landed(body) is None
        assert "would now close a cycle" in calls[-1][-1]["content"], calls[-1][-1]["content"]
        # Nothing mutated: her edge is there, the plan's is not, and the view stays.
        spec = self._spec(user, alice_project)
        edges = spec["dataflow"]["edges"]
        assert any(e["id"] == "u1" for e in edges)
        assert not any(e["source"] == "load" and e["target"] == "combine" for e in edges)
        assert any(n["id"] == "vis" for n in spec["dataflow"]["nodes"])
