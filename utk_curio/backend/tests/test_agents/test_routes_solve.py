"""Integration tests for the /api/agents solve routes (routes/solve.py).

Solve, streamed Solve, Simulation Mode, run-node and validate-node."""

from __future__ import annotations

from utk_curio.backend.app.agents.repositories import ledger

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    _block_closure_repair,
    _drop_from_lockfile,
)

# Imported for their helpers. conftest.py runs each class only in the
# file that defines it, never again here.
from utk_curio.backend.tests.test_agents.test_routes_proposals import (
    TestDataflowPlanMint,
    TestNodeCreate,
)


class TestSolve:
    """dev/52 Solve (DEC-048): one authenticated batch, per-node digest
    guards, bounded children with all dev/48 guarantees, subset retry."""

    NCB = "agent.node-content-builder@1.0.0"

    def _applied_plan(self, client, user, token, project_id, monkeypatch, replies=None, install_ncb=True):
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(client, user, token, project_id, monkeypatch, replies=replies)
        # dev/118 (DEC-075): Solve now RUNS every executable node. These
        # plans are computation nodes; a fake sandbox that passes keeps the
        # tests about the batch's mechanics, not about the code they generate.
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {"stdout": [], "stderr": "",
                                       "output": {"path": "art-1", "dataType": "dataframe"}},
        )
        if install_ncb:
            client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.NCB}, headers=_auth(token))
        else:
            # dev/106: installing the Builder now brings the NCB along; the
            # missing-specialist state is a legacy/hand-edited lockfile.
            # dev/126: and DEC-080 repairs exactly that at the next action, so
            # a test about the reviewed install lane must also stand in for the
            # one case the repair cannot fix (see _block_closure_repair).
            _drop_from_lockfile(user, project_id, self.NCB)
            self._release_repair = _block_closure_repair(monkeypatch)
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        body = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        return att_id, body["appliedGraph"], calls

    def _solve(self, client, token, project_id, att_id, node_ids=None):
        payload = {"nodeIds": node_ids} if node_ids is not None else {}
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/solve",
            json=payload, headers=_auth(token),
        )

    def _spec_nodes(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)["dataflow"]["nodes"]

    def test_solve_fills_pending_nodes_and_reaches_ready(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        runs_before = ledger.aggregates(_user_dir_key(user))["runs"]
        resp = self._solve(client, token, alice_project, att_id)
        assert resp.status_code == 200
        body = resp.get_json()
        assert {r["status"] for r in body["results"].values()} == {"solved"}
        assert body["builderSession"]["phase"] == "ready"
        assert len(body["appliedContents"]) == 2
        # Children reserved individually (2 runs); the endpoint itself none.
        assert ledger.aggregates(_user_dir_key(user))["runs"] == runs_before + 2
        # Contents landed in the saved spec.
        nodes = {n["id"]: n for n in self._spec_nodes(user, alice_project)}
        for item in body["appliedContents"]:
            assert nodes[item["nodeId"]]["content"] == item["content"]
            assert item["content"]  # the child reply
        # The transcript logged the batch with its delegations.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        solve_turn = next(t for t in reversed(turns) if (t.get("text") or "").startswith("Solved"))
        assert len(solve_turn["execution"]["delegations"]) == 2
        assert all(
            d["parentExecutionId"] == body["executionId"]
            for d in solve_turn["execution"]["delegations"]
        )

    def _child_config(self, client, token, label="Child", model="child-model"):
        body = {"label": label, "apiType": "openai_compatible", "baseUrl": "https://llm.example.com/v1",
                "apiKey": "sk-child-key-0123456789", "model": model}
        return client.post("/api/agents/llm/configs", json=body, headers=_auth(token)).get_json()["config"]["id"]

    def _record_models(self, monkeypatch, on_call=None):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        inner = providers.run_chat_turn
        seen = []

        def _recording(config, messages, **kwargs):
            seen.append((config.model, config.source))
            if on_call is not None:
                on_call(len(seen))
            return inner(config, messages, **kwargs)

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _recording)
        return seen

    def test_each_child_runs_on_and_pins_its_own_configuration(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, _, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        child_config = self._child_config(client, token)
        client.put("/api/agents/llm/assignments", json={"agent.node-content-builder": child_config},
                   headers=_auth(token))
        seen = self._record_models(monkeypatch)
        resp = self._solve(client, token, alice_project, att_id)
        assert resp.status_code == 200, resp.get_json()
        assert seen and all(call == ("child-model", "assigned") for call in seen)
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        solve_turn = next(t for t in reversed(turns) if (t.get("text") or "").startswith("Solved"))
        # The summary pins the Builder's configuration, each child its own.
        assert solve_turn["execution"]["pins"]["llm"]["source"] == "deployment"
        for child in solve_turn["execution"]["delegations"]:
            assert child["pins"]["llm"]["configId"] == child_config
            assert child["pins"]["model"] == "child-model"

    def test_a_broken_delegate_choice_refuses_before_anything_is_written(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.agents.infrastructure import llm_configs
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        child_config = self._child_config(client, token)
        client.put("/api/agents/llm/assignments", json={"agent.node-content-builder": child_config},
                   headers=_auth(token))
        store = llm_configs.default_store()
        doc = store.read(_user_dir_key(user))
        del doc["configs"][child_config]  # the choice now names nothing
        store._write(_user_dir_key(user), doc)
        seen = self._record_models(monkeypatch)
        resp = self._solve(client, token, alice_project, att_id)
        assert resp.status_code == 400
        assert resp.get_json()["remedy"] == {"kind": "llm-config", "agentId": "agent.node-content-builder"}
        assert seen == []
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        session = next(c for c in cards if c["attachmentId"] == att_id)["builderSession"]
        assert session["phase"] != "solving" and not session.get("solveExecutionId")

    def test_a_choice_changed_mid_solve_reaches_the_later_children(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.agents.infrastructure import llm_configs
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, _, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        child_config = self._child_config(client, token)
        client.put("/api/agents/llm/assignments", json={"agent.node-content-builder": child_config},
                   headers=_auth(token))

        def _clear_after_first(n):
            if n == 1:  # the user clears the choice while the first node is generated
                llm_configs.default_store().set_choice(
                    _user_dir_key(user), "agent.node-content-builder", None
                )

        seen = self._record_models(monkeypatch, on_call=_clear_after_first)
        resp = self._solve(client, token, alice_project, att_id)
        assert resp.status_code == 200, resp.get_json()
        assert seen[0] == ("child-model", "assigned")
        # A delegate resolves when it starts: the next one inherits the Builder's.
        assert seen[-1] == ("test-model", "caller")

    def test_user_edited_node_is_skipped_never_overwritten(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        key = _user_dir_key(user)
        edited_id = applied["nodes"][0]["id"]
        spec = projects_storage.read_spec(key, alice_project)
        node = next(n for n in spec["dataflow"]["nodes"] if n["id"] == edited_id)
        node["content"] = "print('mine')"  # the user typed here
        projects_storage.write_spec(key, alice_project, spec)
        body = self._solve(client, token, alice_project, att_id).get_json()
        assert body["results"][edited_id]["status"] == "skipped"
        nodes = {n["id"]: n for n in self._spec_nodes(user, alice_project)}
        assert nodes[edited_id]["content"] == "print('mine')"

    def test_child_failure_isolates_and_retry_resolves_subset(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, applied, calls = self._applied_plan(client, user, token, alice_project, monkeypatch)
        # The next TWO child calls: first succeeds, second explodes.
        state = {"n": 0}

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
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("child provider down")
            return f"generated-{state['n']}"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        body = self._solve(client, token, alice_project, att_id).get_json()
        statuses = sorted(r["status"] for r in body["results"].values())
        # dev/131: a child failure still isolates — the sibling solved on the
        # same pass — and the SESSION now retries it instead of handing the
        # user a failure to click through: the second pass succeeds and the
        # session reaches ready by itself.
        assert statuses == ["solved", "solved"]
        assert body["passes"] > 1
        assert body["builderSession"]["phase"] == "ready"
        # Nothing is left to solve, so a re-run of the batch says so rather
        # than re-burning the same calls.
        again = self._solve(client, token, alice_project, att_id)
        assert again.status_code == 409

    def test_solve_without_applied_plan_409s(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch)
        assert self._solve(client, token, alice_project, att_id).status_code == 409

    def test_missing_specialist_fails_batch_with_one_install_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(
            client, user, token, alice_project, monkeypatch, install_ncb=False,
        )
        body = self._solve(client, token, alice_project, att_id).get_json()
        assert all(r["status"] == "failed" for r in body["results"].values())
        assert all("install proposal awaits review" in r["error"] for r in body["results"].values())
        # ONE reviewed install proposal (not per node) — the active mirror.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
        assert active["tool"] == "project.install"
        assert active["status"] == "pending"
        # dev/106 D1: the proposal RIDES THE SOLVE TURN — the assertion whose
        # absence let an invisible proposal ship. One reason line, not six.
        assert body["reason"].startswith("specialist not installed")
        assert "Node Content Builder" in body["reason"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        solve_turn = next(t for t in reversed(turns) if (t.get("text") or "").startswith("Solved"))
        kinds = [p["type"] for p in solve_turn["content"]]
        assert kinds == ["card", "proposal"]
        assert solve_turn["content"][1]["tool"] == "project.install"
        assert solve_turn["content"][1]["proposalId"] == active["proposalId"]
        reason_lines = [l for l in solve_turn["content"][0]["lines"] if l.startswith("reason:")]
        assert len(reason_lines) == 1
        assert "Apply it, then Retry" in reason_lines[0]

    def test_missing_specialist_apply_then_retry_solves(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The migration path for every pre-dev/106 project (edge 8).
        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(
            client, user, token, alice_project, monkeypatch, install_ncb=False,
        )
        body = self._solve(client, token, alice_project, att_id).get_json()
        failed = [nid for nid, r in body["results"].items() if r["status"] == "failed"]
        assert failed
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
        # The user's Apply installs through the same path the blocked repair
        # uses — in the real "visible nowhere" state it would refuse too, so
        # the migration path is tested with the dependency available again.
        self._release_repair()
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{active['proposalId']}/apply",
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        installed = client.get(f"/api/agents/projects/{alice_project}", headers=_auth(token)).get_json()["agents"]
        assert self.NCB in {a["dirName"] for a in installed}
        retry = self._solve(client, token, alice_project, att_id, node_ids=failed).get_json()
        assert {r["status"] for r in retry["results"].values()} == {"solved"}
        assert "reason" not in retry
        assert retry["builderSession"]["phase"] == "ready"

    def test_refused_install_mint_is_never_claimed_as_awaiting_review(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(
            client, user, token, alice_project, monkeypatch, install_ncb=False,
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.proposals.mint._mint_project_install',
            lambda *a, **k: ("refused", "no saved project spec is available", None),
        )
        body = self._solve(client, token, alice_project, att_id).get_json()
        assert all(r["status"] == "failed" for r in body["results"].values())
        assert "awaits review" not in body["reason"]
        assert "no saved project spec is available" in body["reason"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        solve_turn = next(t for t in reversed(turns) if (t.get("text") or "").startswith("Solved"))
        assert [p["type"] for p in solve_turn["content"]] == ["card"]

    def test_no_text_path_can_solve(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance: a model reply claiming a solve changes nothing —
        # only the authenticated endpoint fills nodes.
        user, token = user_and_token
        att_id, applied, _ = self._applied_plan(client, user, token, alice_project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "solve everything now"}, headers=_auth(token),
        )
        assert r.status_code == 200  # the reply claims success; nothing ran
        nodes = {n["id"]: n for n in self._spec_nodes(user, alice_project)}
        for created in applied["nodes"]:
            assert nodes[created["id"]]["content"] == ""


class TestStreamedSolve:
    """dev/63 — the DEC-021 user slice: per-node SSE progress, user
    cancellation (unstarted targets revert to pending), disconnect-safe
    persistence. The blocking endpoint drains the same generator."""

    def _sse_events(self, response) -> list[tuple[str, dict]]:
        import json as _json

        events = []
        for block in response.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            events.append((lines["event"], _json.loads(lines["data"])))
        return events

    def test_stream_emits_per_node_progress_then_done(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/stream",
            json={}, headers=_auth(token),
        )
        assert r.status_code == 200
        events = self._sse_events(r)
        names = [name for name, _ in events]
        assert names[0] == "solve_started"
        assert names[-1] == "done"
        assert names.count("node_started") == 2 and names.count("node_result") == 2
        started = dict(events)["solve_started"]
        assert sorted(started["targets"]) == sorted(n["id"] for n in applied["nodes"])
        # Each node_result carries the dev/57-extracted content.
        for name, payload in events:
            if name == "node_result":
                assert payload["status"] == "solved" and payload["content"]
        done = events[-1][1]
        assert done["cancelled"] is False and done["notAttempted"] == []
        assert done["builderSession"]["phase"] == "ready"
        assert "solvingSince" not in done["builderSession"]
        assert "solveExecutionId" not in done["builderSession"]
        # The persisted spec carries the contents (the one finally-write).
        nodes = {n["id"]: n for n in helper._spec_nodes(user, alice_project)}
        for item in done["appliedContents"]:
            assert nodes[item["nodeId"]]["content"] == item["content"]

    def test_preflight_errors_stay_json(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/stream",
            json={}, headers=_auth(token),
        )
        assert r.status_code == 409  # no applied plan — never a stream
        assert "apply a plan first" in r.get_json()["error"]

    def _solve_gen(self, user, project_id, att_id):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
        from utk_curio.backend.app.projects.services import _user_dir_key

        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="http://x", model="m")
        return packages_session.solve_attachment_stream(
            _user_dir_key(user), project_id, att_id, config
        )

    def test_cancel_reverts_unstarted_targets_to_pending(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json
        import threading

        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestSolve()
        # A 5-node plan: 3 dispatch immediately (the worker pool), 2 queue.
        plan = {"goal": "big", "nodes": [
            {"ref": f"n{i}", "nodeType": "curio.builtin/computation-analysis",
             "title": f"Step {i}", "intent": f"do step {i}"}
            for i in range(5)
        ], "edges": []}
        reply = f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"
        att_id, applied, _ = helper._applied_plan(
            client, user, token, alice_project, monkeypatch, replies=[reply],
        )
        gate = threading.Event()

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            gate.wait(timeout=10)  # children hold until the cancel lands
            return "generated"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        gen = self._solve_gen(user, alice_project, att_id)
        events: list = []
        done_evt = threading.Event()
        started_count = threading.Semaphore(0)

        def _drain():
            for kind, payload in gen:
                events.append((kind, payload))
                if kind == "node_started":
                    started_count.release()
            done_evt.set()

        t = threading.Thread(target=_drain)
        t.start()
        for _ in range(3):  # the full worker pool is busy
            assert started_count.acquire(timeout=10)
        packages_session.request_solve_cancel(_user_dir_key(user), alice_project, att_id)
        gate.set()  # in-flight children finish and are KEPT
        assert done_evt.wait(timeout=10)
        t.join(timeout=10)
        done = next(p for k, p in events if k == "done")
        assert done["cancelled"] is True
        assert len(done["notAttempted"]) == 2
        statuses = sorted(r["status"] for r in done["results"].values())
        assert statuses == ["solved", "solved", "solved"]
        # Unstarted victims stay pending; the phase honestly says applied.
        runs = done["builderSession"]["nodeRuns"]
        assert sorted(runs.values()) == ["pending", "pending", "solved", "solved", "solved"]
        assert done["builderSession"]["phase"] == "applied"
        assert "cancelRequested" not in done["builderSession"]

    def test_disconnect_persists_partials_and_exits_solving(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        gen = self._solve_gen(user, alice_project, att_id)
        seen = []
        for kind, payload in gen:
            seen.append(kind)
            if kind == "node_result":
                break
        gen.close()  # the client vanished mid-stream (GeneratorExit)
        # dev/115 (DEC-021 single-process slice): the client's disconnect only
        # UNSUBSCRIBES — the batch runs on as a detached job and finishes on
        # its own; the persisted session is the truth once it has.
        from utk_curio.backend.app.agents.infrastructure import agent_jobs

        job = agent_jobs.latest_job(_user_dir_key(user), att_id)
        assert job is not None
        job.thread.join(timeout=10)
        assert job.status == "done"
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        record = next(
            a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id
        )
        session = record["builderSession"]
        # Everything that completed persisted; the phase is never wedged.
        assert session["phase"] in ("ready", "applied")
        assert "solvingSince" not in session and "solveExecutionId" not in session
        assert "solved" in session["nodeRuns"].values()

    def test_cancel_endpoint_requires_a_running_solve(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/cancel",
            headers=_auth(token),
        )
        assert r.status_code == 409
        assert "no solve is running" in r.get_json()["error"]

    def test_cancel_endpoint_sets_the_durable_flag(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        import threading

        from utk_curio.backend.app.agents.infrastructure import agent_jobs

        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, alice_project)
        record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
        # dev/115: a "solving" session is live only while THIS process holds
        # its job (single-process lease); simulate the running batch with a
        # registered job that blocks until released.
        gate = threading.Event()

        def _events():
            gate.wait(timeout=10)
            yield "done", {}

        job = agent_jobs.start_job(
            user_key=key, project_id=alice_project, attachment_id=att_id,
            kind="solve-batch", job_id="live-solve", events=_events(),
        )
        record["builderSession"]["phase"] = "solving"
        record["builderSession"]["solvingSince"] = 1.0
        record["builderSession"]["solveExecutionId"] = "live-solve"
        projects_storage.write_spec(key, alice_project, spec)
        try:
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/cancel",
                headers=_auth(token),
            )
            assert r.status_code == 200 and r.get_json()["cancelRequested"] is True
            spec = projects_storage.read_spec(key, alice_project)
            record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
            assert record["builderSession"]["cancelRequested"] is True
            # Idempotent while "running".
            assert client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/cancel",
                headers=_auth(token),
            ).status_code == 200
        finally:
            gate.set()
            job.thread.join(timeout=5)


class TestGeneratedContentExtraction:
    """dev/57 — Solve and the node mints write only executable content."""

    def test_solve_strips_child_response_formatting(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        solve_helper = TestSolve()
        helper = TestDataflowPlanMint()
        att_id, _, _ = None, None, None
        att_id, applied, _ = solve_helper._applied_plan(client, user, token, alice_project, monkeypatch)
        wrapped = "Here is the code:\n```python\nprint('clean')\n```\nEnjoy!"
        state = {"n": 0}

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
            state["n"] += 1
            return wrapped

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        body = solve_helper._solve(client, token, alice_project, att_id).get_json()
        assert {r["status"] for r in body["results"].values()} == {"solved"}
        for item in body["appliedContents"]:
            assert item["content"] == "print('clean')"
        nodes = {n["id"]: n for n in solve_helper._spec_nodes(user, alice_project)}
        for created in applied["nodes"]:
            assert nodes[created["id"]]["content"] == "print('clean')"

    def test_node_create_mint_strips_wrapped_params(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestNodeCreate()
        wrapped_content = "Here you go:\\n```python\\nprint('tidy')\\n```"
        att_id, _ = helper._setup(
            client, token=token, user=user, project_id=alice_project, monkeypatch=monkeypatch,
            replies=[helper._create_tail(content=wrapped_content), "done"],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = helper._proposal_from_run(r)
        assert proposal["preview"] == "print('tidy')"
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.get_json()["createdNode"]["content"] == "print('tidy')"


class TestProposeModeSolve:
    """dev/67-6 — Simulation Mode: solve. Propose mode writes NOTHING: each
    solved child mints a reviewed node.content.write proposal; applying it
    writes the content and resolves the per-node ledger."""

    def test_propose_full_loop(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('generated')"],
        )
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": "agent.node-content-builder@1.0.0"}, headers=_auth(token),
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        ref = proposal["plan"]["nodes"][0]["ref"]
        created = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()["createdNode"]
        # dev/118 (DEC-075): propose mode now RUNS the computation node too and
        # mints an EXECUTED review; a fake sandbox that passes keeps this test
        # about the propose loop.
        exec_calls: list = []

        def _exec(endpoint, payload):
            exec_calls.append(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        # Propose-mode solve of exactly that node.
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/stream",
            json={"mode": "propose", "nodeIds": [created["id"]]}, headers=_auth(token),
        )
        events = TestStreamedSolve()._sse_events(resp)
        result = next(p for k, p in events if k == "node_result")
        assert result["status"] == "proposed"
        assert result["verdict"] == "pass" and result["rounds"] == 1  # dev/118: an executed review
        assert len(exec_calls) == 1 and "generated" in exec_calls[0]["code"]
        content_proposal_id = result["proposalId"]
        done = events[-1][1]
        assert done["mode"] == "propose"
        assert done["appliedContents"] == []  # nothing written
        session = done["builderSession"]
        assert session["phase"] == "simulating"  # restored, not applied/ready
        assert session["nodeRuns"][created["id"]] == "pending"
        assert session["nodeStates"][ref] == "solving"
        # The spec node is still empty; the content proposal is active.
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        node = next(n for n in spec["dataflow"]["nodes"] if n["id"] == created["id"])
        assert node["content"] == ""
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        # dev/126: the Node Builder is a required agent of the Dataflow Builder
        # now, so the applied plan node HAS its own agent and dev/73's rule
        # takes effect — the content review is minted at the NODE's agent, not
        # folded back into the orchestrator's chat. The event says where.
        mint_att_id = result["proposalAttachmentId"]
        minted_at = next(c for c in cards if c["attachmentId"] == mint_att_id)
        assert minted_at["coord"].startswith("agent.node-builder@")
        assert minted_at["target"] == {"kind": "node", "targetId": created["id"]}
        active = minted_at["activeProposal"]
        assert active["tool"] == "node.content.write"
        assert active["proposalId"] == content_proposal_id
        # Applying the content proposal writes + resolves the ledger.
        body = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{mint_att_id}/proposals/{content_proposal_id}/apply",
            headers=_auth(token),
        ).get_json()
        assert body["appliedContent"]["nodeId"] == created["id"]
        assert body["appliedContent"]["content"] == "print('generated')"
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        session = next(c for c in cards if c["attachmentId"] == att_id)["builderSession"]
        assert session["nodeRuns"][created["id"]] == "solved"
        assert session["nodeStates"][ref] == "approved"

    def test_classic_write_mode_is_untouched(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The blocking endpoint (always write mode) still writes directly.
        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        body = helper._solve(client, token, alice_project, att_id).get_json()
        assert {r["status"] for r in body["results"].values()} == {"solved"}
        assert "mode" not in body  # byte-compatible blocking payload
        assert body["builderSession"]["phase"] == "ready"

    def test_invalid_mode_is_refused(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestSolve()
        att_id, _, _ = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/stream",
            json={"mode": "bulk"}, headers=_auth(token),
        )
        assert r.status_code == 400


class TestProgressiveLifecycle:
    """dev/71 — Apply = create + attach + connect-what's-possible; per-node
    Run executes through the node and journals real results for the agents."""

    def _mint(self, client, user, token, project_id, monkeypatch, replies=None, install_nb=False):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, project_id, monkeypatch,
            **({"replies": replies} if replies else {}),
        )
        if install_nb:
            client.post(
                f"/api/agents/projects/{project_id}/install",
                json={"coord": "agent.node-builder@1.0.0"}, headers=_auth(token),
            )
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def _apply_node(self, client, token, project_id, att_id, proposal_id, ref):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()

    def test_apply_order_is_free_and_the_graph_grows_connected(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        # Apply B (the TARGET) first: the edge is ineligible, silently planned.
        first = self._apply_node(client, token, alice_project, att_id, pid, refs[1])
        assert first["createdEdges"] == []
        assert first["edgeStates"] == {}  # not refused — just not yet possible
        # Applying A makes the edge eligible → drawn in the SAME apply.
        second = self._apply_node(client, token, alice_project, att_id, pid, refs[0])
        (edge,) = second["createdEdges"]
        assert edge["source"] == second["createdNode"]["id"]
        assert edge["target"] == first["createdNode"]["id"]
        assert second["edgeStates"] == {"0": "applied"}
        assert second["status"] == "applied"  # structure complete

    def test_edges_to_existing_nodes_connect_on_first_apply(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json

        user, token = user_and_token
        plan = {"goal": "extend", "nodes": [
            {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
             "title": "Analyze", "intent": "crunch"},
        ], "edges": [{"from": "n1", "to": "a"}]}  # n1 = the seeded baseline node
        reply = f"Plan.\n```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"
        att_id, proposal = self._mint(
            client, user, token, alice_project, monkeypatch, replies=[reply],
        )
        body = self._apply_node(
            client, token, alice_project, att_id, proposal["proposalId"], "a"
        )
        (edge,) = body["createdEdges"]
        assert edge["source"] == "n1"  # the existing node, wired immediately
        assert edge["target"] == body["createdNode"]["id"]

    def test_apply_attaches_the_node_builder_when_installed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, proposal = self._mint(
            client, user, token, alice_project, monkeypatch, install_nb=True,
        )
        ref = proposal["plan"]["nodes"][0]["ref"]
        body = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref)
        assert body["attachedAgentId"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        attached = next(c for c in cards if c["attachmentId"] == body["attachedAgentId"])
        assert attached["coord"].startswith("agent.node-builder@")
        assert attached["target"] == {"kind": "node", "targetId": body["createdNode"]["id"]}
        # Idempotent: a re-apply reports the SAME attachment, no duplicate.
        again = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref)
        assert again["status"] == "already-applied"

    def test_apply_repairs_the_closure_and_attaches_the_node_builder(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # dev/126 (DEC-080): the Node Builder is a required agent of the
        # Dataflow Builder, so an apply in a project that lacks it completes
        # the closure and the created node carries its agent — the dev/71
        # behavior stops depending on what the user happened to install.
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        body = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref)
        assert body["attachedAgentId"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        attached = next(c for c in cards if c["attachmentId"] == body["attachedAgentId"])
        assert attached["coord"].startswith("agent.node-builder@")

    def test_apply_without_node_builder_installed_skips_quietly(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The remaining path to an agent-less node: the closure cannot be
        # completed (a required agent visible nowhere). Creation never fails
        # over its agent (dev/71), and the apply says so rather than pretending.
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        # The run's own repair already installed the Node Builder, so the
        # agent-less state has to be re-created the way a legacy lockfile has
        # it — and then held there by a repair that cannot complete.
        _drop_from_lockfile(user, alice_project, "agent.node-builder@1.0.0")
        _block_closure_repair(monkeypatch)
        ref = proposal["plan"]["nodes"][0]["ref"]
        body = self._apply_node(client, token, alice_project, att_id, proposal["proposalId"], ref)
        assert body["attachedAgentId"] is None
        assert body["createdNode"]  # creation never fails over the agent

    def test_run_node_executes_the_chain_and_journals_real_runs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.execution import runtime_journal
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {
                "stdout": ["ran"], "stderr": "",
                "output": {"path": "art-run", "dataType": "dataframe"},
            },
        )
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        self._apply_node(client, token, alice_project, att_id, pid, refs[0])
        created_b = self._apply_node(client, token, alice_project, att_id, pid, refs[1])
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
            json={"ref": refs[1]}, headers=_auth(token),
        )
        assert r.status_code == 200
        events = TestStreamedSolve()._sse_events(r)
        names = [k for k, _ in events]
        assert names[0] == "run_started" and "node_executed" in names
        done = events[-1][1]
        assert done["ok"] is True
        assert len(done["order"]) == 2  # the upstream chain ran too
        target = done["nodes"][created_b["createdNode"]["id"]]
        assert target["output"]["dataType"] == "dataframe"
        # A REAL run in the journal — agents read it via node.runtime.read.
        record = runtime_journal.read_record(
            _user_dir_key(user), alice_project, created_b["createdNode"]["id"]
        )
        assert record["validation"] is False and record["status"] == "ok"

    def test_run_node_failure_reports_honestly(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {
                "stdout": [], "stderr": "Traceback: NameError boom",
                "output": {"path": "", "dataType": "str"},
            },
        )
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        ref = proposal["plan"]["nodes"][0]["ref"]
        self._apply_node(client, token, alice_project, att_id, pid, ref)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
            json={"ref": ref}, headers=_auth(token),
        )
        done = TestStreamedSolve()._sse_events(r)[-1][1]
        assert done["ok"] is False and done["blocker"]
        # Guards: unknown ref / missing node.
        assert client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
            json={"ref": "ghost"}, headers=_auth(token),
        ).status_code == 409
        assert client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
            json={}, headers=_auth(token),
        ).status_code == 422


class TestSimulationDriver:
    """dev/67-9 (DEC-054) — the Simulation Mode driver: one transition
    function for step and auto; create → validate → auto-approve-on-PASS per
    node in topological order → connections; pause on failure with nothing
    downstream generated; resume from persisted state; the plan proposal
    PARKS while content reviews cycle through the active slot."""

    def _fake_exec(self, monkeypatch, fail_markers=()):
        def _exec(endpoint, payload):
            if any(m in payload["code"] for m in fail_markers):
                return {"stdout": [], "stderr": "Traceback: boom",
                        "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "",
                    "output": {"path": "art", "dataType": "dataframe"}}

        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec", _exec
        )

    def _setup(self, client, user, token, project_id, monkeypatch, replies):
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, project_id, monkeypatch, replies=replies,
        )
        client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": "agent.node-content-builder@1.0.0"}, headers=_auth(token),
        )
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal, calls

    def _simulate(self, client, token, project_id, att_id, mode):
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/simulate",
            json={"mode": mode}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_json()
        return TestStreamedSolve()._sse_events(r)

    def _spec(self, user, project_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        return projects_storage.read_spec(_user_dir_key(user), project_id)

    def test_auto_builds_and_validates_the_whole_plan(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch)
        att_id, proposal, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('generated')"],
        )
        events = self._simulate(client, token, alice_project, att_id, "auto")
        done = events[-1][1]
        assert done["status"] == "completed"
        session = done["builderSession"]
        assert set(session["nodeStates"].values()) == {"approved"}
        assert session["edgeStates"] == {"0": "applied"}
        assert session["phase"] == "ready"  # everything solved and connected
        # The canvas mutations rode the stream.
        names = [k for k, _ in events]
        assert names.count("node_created") == 2
        assert names.count("node_content_applied") == 2
        assert "edges_created" in names
        # The spec is fully materialized: contents written, edge wired.
        spec = self._spec(user, alice_project)
        created = [n for n in spec["dataflow"]["nodes"] if n.get("id") != "n1"]
        assert all(n["content"] == "print('generated')" for n in created)
        # Auto-approval is recorded, never silent (DEC-054).
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
        assert active["status"] == "applied"

    def test_step_performs_exactly_one_action(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch)
        att_id, proposal, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('generated')"],
        )
        events = self._simulate(client, token, alice_project, att_id, "step")
        done = events[-1][1]
        assert done["status"] == "stepped"
        assert done["nextAction"] == {"action": "validate",
                                      "ref": proposal["plan"]["nodes"][0]["ref"]}
        session = done["builderSession"]
        created_states = [s for s in session["nodeStates"].values() if s == "created"]
        assert len(created_states) == 1  # exactly ONE node created
        # Step to completion — N step calls ≡ one auto run. The completing
        # step reports nextAction None; a further call refuses honestly.
        for _ in range(20):
            events = self._simulate(client, token, alice_project, att_id, "step")
            done = events[-1][1]
            if done["status"] == "completed" or (
                done["status"] == "stepped" and done.get("nextAction") is None
            ):
                break
        assert set(done["builderSession"]["nodeStates"].values()) == {"approved"}
        assert done["builderSession"]["edgeStates"] == {"0": "applied"}
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/simulate",
            json={"mode": "step"}, headers=_auth(token),
        )
        assert r.status_code == 409  # complete: nothing to simulate

    def test_validation_failure_pauses_and_resume_continues(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        # Every generation fails validation: the run pauses at the FIRST node.
        self._fake_exec(monkeypatch, fail_markers=("always_bad",))
        att_id, proposal, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "always_bad()"],
        )
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        events = self._simulate(client, token, alice_project, att_id, "auto")
        done = events[-1][1]
        assert done["status"] == "paused"
        assert done["reason"]["kind"] == "validation-failed"
        assert done["reason"]["ref"] == refs[0]
        session = done["builderSession"]
        assert session["nodeStates"][refs[0]] == "failed"
        # Nothing downstream of the failure was generated or created.
        assert session["nodeStates"][refs[1]] == "planned"
        # The user reviews and applies anyway — then RESUME continues past it.
        content_proposal_id = done["reason"]["proposalId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{content_proposal_id}/apply",
            headers=_auth(token),
        )
        self._fake_exec(monkeypatch)  # the sandbox behaves for the rest
        events = self._simulate(client, token, alice_project, att_id, "auto")
        done = events[-1][1]
        assert done["status"] == "completed"
        assert set(done["builderSession"]["nodeStates"].values()) == {"approved"}

    def test_cancel_stops_at_the_next_boundary(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch)
        att_id, proposal, _ = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('generated')"],
        )
        # Service-level: cancel after the first action_result.
        from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig

        config = ProviderConfig(api_key="k", api_type="openai_compatible",
                                base_url="http://x", model="m")
        gen = simulation.simulate_stream(
            _user_dir_key(user), alice_project, att_id, config, mode="auto",
        )
        seen = []
        for kind, payload in gen:
            seen.append((kind, payload))
            if kind == "action_result":
                simulation.request_simulate_cancel(
                    _user_dir_key(user), alice_project, att_id
                )
        done = seen[-1][1]
        assert done["status"] == "cancelled"
        # Everything already done stays done; the guard is cleared.
        assert "simulatingSince" not in done["builderSession"]
        assert "created" in done["builderSession"]["nodeStates"].values()

    def test_preflight_guards(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch)
        base = f"/api/agents/projects/{alice_project}/attachments/{att_id}/simulate"
        # No plan minted yet.
        assert client.post(base, json={"mode": "auto"}, headers=_auth(token)).status_code == 409
        assert client.post(base, json={"mode": "bulk"}, headers=_auth(token)).status_code == 400
        assert client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/simulate/cancel",
            headers=_auth(token),
        ).status_code == 409


class TestValidateNode:
    """dev/67-7 — Simulation Mode: validate. Generate → execute-through →
    verdict → self-correct → propose; the spec is never mutated by
    validation; PASS or FAIL, the user decides."""

    def _fake_exec(self, monkeypatch, fail_markers=()):
        calls = []

        def _exec(endpoint, payload):
            calls.append((endpoint, payload))
            if any(m in payload["code"] for m in fail_markers):
                return {"stdout": [], "stderr": "Traceback: ValueError bad column",
                        "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "",
                    "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec", _exec
        )
        return calls

    def _setup_plan_node(self, client, user, token, project_id, monkeypatch, replies):
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, project_id, monkeypatch, replies=replies,
        )
        client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": "agent.node-content-builder@1.0.0"}, headers=_auth(token),
        )
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        ref = proposal["plan"]["nodes"][0]["ref"]
        created = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()["createdNode"]
        return att_id, ref, created, calls

    def _validate(self, client, token, project_id, att_id, body):
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/validate-node",
            json=body, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_json()
        return TestStreamedSolve()._sse_events(r)

    def test_pass_verdict_mints_a_validated_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch)
        att_id, ref, created, _ = self._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('validated code')"],
        )
        events = self._validate(client, token, alice_project, att_id, {"ref": ref})
        names = [k for k, _ in events]
        assert names[0] == "validation_started"
        assert "generation_round" in names and "node_executed" in names
        assert names[-1] == "done"
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["rounds"] == 1
        assert done["evidence"]["outputDataType"] == "dataframe"
        assert done["builderSession"]["nodeStates"][ref] == "validated"
        # The spec is untouched — the candidate lives in the proposal.
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        node = next(n for n in spec["dataflow"]["nodes"] if n["id"] == created["id"])
        assert node["content"] == ""
        # The transcript part carries the validation block — in the session the
        # mint reports (dev/126: the plan node now has its own Node Builder, so
        # dev/73's rule homes the review there).
        mint_att_id = done.get("proposalAttachmentId") or att_id
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{mint_att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        part = next(
            p for t in reversed(turns) for p in (t.get("content") or [])
            if p.get("type") == "proposal" and p.get("proposalId") == done["proposalId"]
        )
        assert part["validation"]["verdict"] == "pass"

    def test_failure_self_corrects_with_the_traceback(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch, fail_markers=("bad_attempt",))
        att_id, ref, created, calls = self._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "bad_attempt()", "good_attempt()"],
        )
        events = self._validate(client, token, alice_project, att_id, {"ref": ref})
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["rounds"] == 2
        verdicts = [p["verdict"] for k, p in events if k == "round_verdict"]
        assert verdicts == ["fail", "pass"]
        # The corrective child saw the previous attempt AND the traceback.
        correction = calls[-1][-1]["content"]
        assert '"previousAttempt"' in correction and "bad_attempt" in correction
        assert "ValueError bad column" in correction

    def test_exhaustion_fails_loudly_but_still_proposes(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        self._fake_exec(monkeypatch, fail_markers=("always_bad",))
        att_id, ref, _, _ = self._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            # Three DIFFERENT failing corrections: a comment-only repeat is not
            # run again (dev/116 live fix).
            replies=["Plan.\n" + helper._plan_tail(), "always_bad()", "always_bad(1)", "always_bad(2)"],
        )
        events = self._validate(client, token, alice_project, att_id, {"ref": ref})
        done = events[-1][1]
        assert done["verdict"] == "fail" and done["rounds"] == 3
        assert done["builderSession"]["nodeStates"][ref] == "failed"
        # Apply-anyway semantics: the failing candidate IS still reviewable.
        assert done["proposalId"]
        assert "Traceback" in done["evidence"]["stderrTail"]

    def test_a_browser_rendered_plan_node_is_proposed_as_not_executable(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # dev/118 (DEC-075): a data-pool (or Vega) plan node used to validate
        # as PASS with nothing executed. The generation is still proposed —
        # labeled — and the plan ledger proceeds as for a pass.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        calls = self._fake_exec(monkeypatch)
        pool_plan = helper._plan_tail(
            nodes=[{"ref": "p", "nodeType": "curio.builtin/data-pool", "title": "Pool", "intent": "hold the data"}],
            edges=[],
        )
        att_id, ref, _, _ = self._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + pool_plan, "{}"],
        )
        events = self._validate(client, token, alice_project, att_id, {"ref": ref})
        done = events[-1][1]
        assert done["verdict"] == "not-executable" and done["rounds"] == 1
        assert done["evidence"]["kind"] == "not-executable"
        assert "no code the sandbox could run" in done["evidence"]["detail"]
        assert calls == []  # nothing reached the sandbox
        assert done["builderSession"]["nodeStates"][ref] == "validated"  # the plan proceeds
        assert done["proposalId"]
        session = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{done['proposalAttachmentId']}/session",
            headers=_auth(token),
        ).get_json()
        part = next(q for t in reversed(session["turns"]) for q in (t.get("content") or [])
                    if q.get("type") == "proposal" and q.get("proposalId") == done["proposalId"])
        assert part["validation"]["verdict"] == "not-executable"
        assert part["validation"]["attempts"][0]["kind"] == "not-executable"

    def test_preflight_guards(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch)
        base = f"/api/agents/projects/{alice_project}/attachments/{att_id}/validate-node"
        # No ref/nodeId; unknown node; ref without a created node.
        assert client.post(base, json={}, headers=_auth(token)).status_code == 422
        assert client.post(base, json={"nodeId": "ghost"}, headers=_auth(token)).status_code == 404
        assert client.post(base, json={"ref": "a"}, headers=_auth(token)).status_code == 409


class TestNodeContextEnrichment:
    """dev/67-6 — content generation is never blind: Solve children and
    node.content.generate delegates receive the composed node context."""

    def test_solve_children_receive_the_neighborhood(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestSolve()
        att_id, applied, calls = helper._applied_plan(client, user, token, alice_project, monkeypatch)
        helper._solve(client, token, alice_project, att_id)
        child_frames = [
            c[-1]["content"] for c in calls
            if c and "[delegated task" in (c[-1].get("content") or "")
        ]
        assert child_frames  # the children ran
        framed = child_frames[-1]
        assert '"nodeContext"' in framed
        assert '"upstream"' in framed and '"graphSummary"' in framed
        assert '"runtimeStatus"' in framed

    def test_delegate_inputs_enriched_only_for_content_generation(self, tmp_curio):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        from utk_curio.backend.app.projects import storage as projects_storage

        projects_storage.write_spec("4242", "p-enrich", {"dataflow": {"nodes": [
            {"id": "n1", "type": "t", "goal": "g", "content": ""},
        ], "edges": []}})
        loop_ctx = {"target": {"kind": "node", "targetId": "n1"}}
        enriched = delegates._enriched_delegate_inputs(
            "4242", "p-enrich", loop_ctx, "node.content.generate", {"intent": "x"}
        )
        assert enriched["nodeContext"]["nodeId"] == "n1"
        assert enriched["intent"] == "x"  # the model's keys survive
        # Other capabilities and explicit model-provided context: untouched.
        assert delegates._enriched_delegate_inputs(
            "4242", "p-enrich", loop_ctx, "workflow.plan.create", {"a": 1}
        ) == {"a": 1}
        assert delegates._enriched_delegate_inputs(
            "4242", "p-enrich", loop_ctx, "node.content.generate",
            {"nodeContext": {"mine": True}},
        ) == {"nodeContext": {"mine": True}}


class TestSolveTraceHome:
    """dev/72 — a node's Solve lifecycle lives in its attached Node Builder:
    the trace, the content review, and the cross-attachment ledger advance."""

    def _setup(self, client, user, token, project_id, monkeypatch, replies):
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, project_id, monkeypatch, replies=replies,
        )
        for coord in ("agent.node-content-builder@1.0.0", "agent.node-builder@1.0.0"):
            client.post(
                f"/api/agents/projects/{project_id}/install",
                json={"coord": coord}, headers=_auth(token),
            )
        r = helper._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        ref = proposal["plan"]["nodes"][0]["ref"]
        created = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()
        return att_id, ref, created

    def test_validate_homes_the_trace_and_review_at_the_nodes_agent(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {
                "stdout": [], "stderr": "",
                "output": {"path": "art", "dataType": "dataframe"},
            },
        )
        att_id, ref, created = self._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('validated')"],
        )
        home_id = created["attachedAgentId"]  # dev/71's auto-attached agent
        assert home_id
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/validate-node",
            json={"ref": ref}, headers=_auth(token),
        )
        done = TestStreamedSolve()._sse_events(r)[-1][1]
        assert done["verdict"] == "pass"
        # The review lives with the NODE's agent (dev/72).
        assert done["proposalAttachmentId"] == home_id
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        home = next(c for c in cards if c["attachmentId"] == home_id)
        assert home["activeProposal"]["tool"] == "node.content.write"
        # Its transcript: the framed task, then the trace card + proposal.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{home_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert any("[Delegated by Dataflow Builder] Solve" in t["text"] for t in turns)
        result_turn = next(
            t for t in turns
            if any(p.get("type") == "proposal" for p in (t.get("content") or []))
        )
        trace = next(p for p in result_turn["content"] if p.get("type") == "card")
        assert trace["title"] == "Solve trace · PASS"
        assert any(line.startswith("round 1: pass") for line in trace["lines"])
        # The PARENT summarizes and links (the delegation part).
        builder_turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        link = next(
            p for t in reversed(builder_turns) for p in (t.get("content") or [])
            if p.get("type") == "delegation"
        )
        assert link["attachmentId"] == home_id and link["status"] == "ok"
        # Applying the review AT THE NODE'S AGENT advances the BUILDER ledger.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{home_id}/proposals/{done['proposalId']}/apply",
            headers=_auth(token),
        )
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        session = next(c for c in cards if c["attachmentId"] == att_id)["builderSession"]
        assert session["nodeStates"][ref] == "approved"

    def test_driver_approves_through_the_home(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {
                "stdout": [], "stderr": "",
                "output": {"path": "art", "dataType": "dataframe"},
            },
        )
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + helper._plan_tail(), "print('generated')"],
        )
        for coord in ("agent.node-content-builder@1.0.0", "agent.node-builder@1.0.0"):
            client.post(
                f"/api/agents/projects/{alice_project}/install",
                json={"coord": coord}, headers=_auth(token),
            )
        r = helper._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/simulate",
            json={"mode": "auto"}, headers=_auth(token),
        )
        done = TestStreamedSolve()._sse_events(resp)[-1][1]
        assert done["status"] == "completed"
        assert set(done["builderSession"]["nodeStates"].values()) == {"approved"}
        # nodeProposals carries the dev/72 {proposalId, attachmentId} shape.
        entry = next(iter(done["builderSession"]["nodeProposals"].values()))
        assert entry["proposalId"] and entry["attachmentId"] != att_id
