"""Agents are chosen by the capabilities they declare, never by their ids.

Curio picks the agent for each job by what its manifest declares: the one that
writes a node's content declares ``node.content.generate``, the one that finds
datasets ``dataset.discover``, the one a selection is recorded on
``dataset.select``. A data-loading node is one whose template declares
``loadsDataset``. So a user's own agent that declares what a shipped one does
is picked where the shipped one would be.

The fixtures copy the Dataflow Builder's, the Node Builder's and the Dataset
Finder's manifests under new ids and names, with every shipped id inside them
rewritten, and install only the copies. The Node Builder's copy has another
version than the shipped agents' 1.0.0. A site that still picks an agent by
id finds nothing, or a shipped agent, and every assertion names a copy.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application.proposals import plans
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_dataset_discovery_routes as discovery_routes
from utk_curio.backend.tests.test_agents import test_fetch_delegation as fetch_routes
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve

DFB = "agent.dataflow-builder@1.0.0"
NB = "agent.node-builder@1.0.0"
DF = "agent.dataset-finder@1.0.0"
RESEARCHER = "agent.researcher@1.0.0"
MY_ORCHESTRATOR = "agent.my-orchestrator@1.0.0"
MY_BUILDER = "agent.my-builder@2.0.0"
MY_FINDER = "agent.my-finder@1.0.0"
#: Each shipped card a copy stands in for: its coordinate, the copy's, and the copy's name.
COPIES = (
    (DFB, MY_ORCHESTRATOR, "My Orchestrator"),
    (NB, MY_BUILDER, "My Builder"),
    (DF, MY_FINDER, "My Finder"),
)
_RENAMED = {shipped.split("@")[0]: copy.split("@")[0] for shipped, copy, _ in COPIES}

DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"
URL = "https://data.example.org/areas.geojson"
#: A user key with an agent store of its own (``tmp_curio`` isolates it).
UKEY = "7"


def _write_copy(ukey: str, shipped: str, coord: str, name: str) -> None:
    """Put a copy of the shipped agent *shipped* in *ukey*'s agent store as
    *coord*, named *name*, imported as the user's own. Every shipped id it
    names becomes its copy's, so nothing in it leads back to a shipped agent."""
    from utk_curio.backend.app.agents.application import catalog
    from utk_curio.backend.app.agents.repositories import imports, storage

    bundle = catalog.builtin_definition_bundle(shipped)
    manifest = json.loads(json.dumps(bundle["manifest"]))
    own_id, version = coord.split("@", 1)
    renamed = {**_RENAMED, shipped.split("@")[0]: own_id}

    def rename(entry):
        if isinstance(entry, str):
            return renamed.get(entry, entry)
        return {**entry, "id": renamed.get(entry["id"], entry["id"])}

    manifest.update(id=own_id, version=version, name=name)
    manifest["provenance"] = {"publisher": "alice", "license": "MIT", "trust": "imported"}
    manifest["delegatesTo"] = [rename(entry) for entry in manifest.get("delegatesTo", [])]
    if "requiresAgents" in manifest:
        manifest["requiresAgents"] = [rename(agent_id) for agent_id in manifest["requiresAgents"]]
    storage.write_definition(ukey, coord, manifest, bundle["prompts"])
    imports.add_imported_agent(ukey, coord)


def _write_copies(ukey: str) -> None:
    for shipped, coord, name in COPIES:
        _write_copy(ukey, shipped, coord, name)


def _spec(*attached: str, node_type: str = DL, agents=(MY_BUILDER, MY_FINDER, RESEARCHER)) -> dict:
    """A one-node spec whose lockfile holds *agents*, with *attached* on the node."""
    spec = {"dataflow": {"nodes": [{"id": "n1", "type": node_type}], "edges": [],
                         "agents": list(agents), "agentAttachments": []}}
    for coord in attached:
        attachments.attach(spec, coord, {"kind": "node", "targetId": "n1"},
                           attachment_id="att-" + coord.split("@")[0].split(".", 1)[1],
                           session_id="s-" + coord)
    return spec


def _node_records(spec: dict, node_id: str) -> list[dict]:
    return [
        r for r in attachments.list_attachments(spec)
        if (r.get("target") or {}) == {"kind": "node", "targetId": node_id}
    ]


def _attachment_of(spec: dict, node_id: str, coord: str) -> dict | None:
    return next((r for r in _node_records(spec, node_id) if r.get("coord") == coord), None)


def _node_coords(spec: dict, node_id: str) -> set[str]:
    return {r.get("coord") for r in _node_records(spec, node_id)}


def _turns(client, token, project_id, attachment_id) -> list[dict]:
    return client.get(
        f"/api/agents/projects/{project_id}/attachments/{attachment_id}/session",
        headers=_auth(token),
    ).get_json()["turns"]


class TestAUsersAgentIsVisibleAtAnyVersion:
    def test_find_visible_reads_a_users_agent_at_its_highest_version(self, tmp_curio):
        from utk_curio.backend.app.agents.application import delegation

        _write_copies(UKEY)
        # 10.0.0 sorts before 2.0.0 as text; the version order puts it last.
        _write_copy(UKEY, NB, "agent.my-builder@10.0.0", "My Builder")
        coord, manifest = delegation.find_visible(UKEY, "agent.my-builder")
        assert coord == "agent.my-builder@10.0.0" and manifest.name == "My Builder"
        assert delegation.find_visible(UKEY, "agent.my-finder")[0] == MY_FINDER
        # A shipped id still finds the shipped agent, whatever version of that
        # id the user imported.
        _write_copy(UKEY, NB, "agent.node-builder@3.0.0", "Their Node Builder")
        assert delegation.find_visible(UKEY, "agent.node-builder")[0] == NB
        assert delegation.find_visible(UKEY, "agent.nobody") == (None, None)

    def test_installing_the_copied_orchestrator_installs_its_copies(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        user, token = user_and_token
        _write_copies(_user_dir_key(user))
        r = client.post(f"/api/agents/projects/{alice_project}/install",
                        json={"coord": MY_ORCHESTRATOR}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        assert set(r.get_json()["installed"]) == {MY_ORCHESTRATOR, MY_BUILDER, MY_FINDER}


class TestSpecLookupsReadCapabilities:
    def test_the_finder_and_the_builder_on_a_node_are_found_by_capability(self, tmp_curio):
        from utk_curio.backend.app.agents.application.solve import rounds

        _write_copies(UKEY)
        spec = _spec(RESEARCHER, MY_BUILDER, MY_FINDER)
        finder = dr.finder_attachment(spec, "n1", user_key=UKEY)
        assert finder["coord"] == MY_FINDER
        assert rounds._dataset_finder_attachment_id(spec, "n1", user_key=UKEY) == finder["attachmentId"]
        result = {"attempts": [{"kind": "executed", "verdict": "fail", "detail": "boom"}], "rounds": 1}
        part = rounds._solve_attempts_part(spec, "n1", "Load", result, user_key=UKEY)
        assert part["attachmentId"] == _attachment_of(spec, "n1", MY_BUILDER)["attachmentId"]
        # The node's source is recorded on the copy, and read from there.
        finder[dr.RECORD_KEY] = {"status": dr.STATE_RESOLVED,
                                 "picks": [{"lane": "external", "name": "Areas", "url": URL}]}
        assert dr.node_source_state(spec, "n1", user_key=UKEY)["attachmentId"] == finder["attachmentId"]
        assert dr.source_record(spec, "n1", user_key=UKEY)["status"] == dr.STATE_RESOLVED
        assert dr.confirmed_source(spec, "n1", user_key=UKEY)["picks"][0]["url"] == URL

    def test_an_installed_dataset_resolves_the_copied_finder(self, tmp_curio):
        spec = _spec(MY_FINDER)
        record = _attachment_of(spec, "n1", MY_FINDER)
        record[dr.RECORD_KEY] = {
            "status": dr.STATE_AWAITING_INSTALL,
            "picks": [{"lane": "catalog", "datasetId": "d1", "installed": False}],
        }
        assert dr.mark_dataset_installed(spec, "d1") == [record["attachmentId"]]
        assert record[dr.RECORD_KEY]["status"] == dr.STATE_RESOLVED

    def test_work_for_a_node_homes_at_the_copies_never_at_the_researcher(self, tmp_curio):
        from utk_curio.backend.app.agents.application.turns import delegates

        _write_copies(UKEY)
        # The Researcher is attached to the node: it attaches to any node.
        spec = _spec(RESEARCHER)
        home, created = delegates._delegation_home(
            spec, MY_FINDER, "dataset.discover", {}, node_id="n1", user_key=UKEY,
        )
        assert created is True and home["coord"] == MY_FINDER
        again, created = delegates._delegation_home(
            spec, MY_FINDER, "dataset.select", {}, node_id="n1", user_key=UKEY,
        )
        assert created is False and again["attachmentId"] == home["attachmentId"]
        content, created = delegates._delegation_home(
            spec, MY_BUILDER, "node.content.generate", {}, node_id="n1", user_key=UKEY,
        )
        assert created is True and content["coord"] == MY_BUILDER
        # A fact checked for the node lands where its content does.
        checked, created = delegates._delegation_home(
            spec, RESEARCHER, "research.verify", {}, node_id="n1", user_key=UKEY,
        )
        assert created is False and checked["attachmentId"] == content["attachmentId"]

    def test_the_builder_wrapper_attaches_the_copy(self, tmp_curio):
        _write_copies(UKEY)
        spec = _spec()
        att_id = plans._attach_node_builder(spec, "n1", user_key=UKEY)
        assert att_id and _attachment_of(spec, "n1", MY_BUILDER)["attachmentId"] == att_id

    def test_a_plan_node_gets_its_parents_delegates_in_solve_order(self, tmp_curio):
        from utk_curio.backend.app.agents.application import catalog

        _write_copies(UKEY)
        parent = catalog._resolve_definition(UKEY, MY_ORCHESTRATOR)
        spec = _spec()
        out = plans._attach_plan_node_agents(UKEY, spec, "n1", DL, parent=parent)
        assert [r["agentId"] for r in out["attached"]] == ["agent.my-builder", "agent.my-finder"]
        assert out["skipped"] == []
        spec = _spec(node_type=CA)
        out = plans._attach_plan_node_agents(UKEY, spec, "n1", CA, parent=parent)
        assert [r["agentId"] for r in out["attached"]] == ["agent.my-builder"]
        assert [r["agentId"] for r in out["skipped"]] == ["agent.my-finder"]
        assert "does not attach to computation-analysis nodes" in out["skipped"][0]["reason"]
        # The Researcher is installed and attaches to any node; it is never one of them.
        assert {r["coord"] for r in attachments.list_attachments(spec)} == {MY_BUILDER}

    def test_without_a_parent_the_installed_agents_that_declare_them_are_attached(self, tmp_curio):
        _write_copies(UKEY)
        spec = _spec()
        out = plans._attach_plan_node_agents(UKEY, spec, "n1", DL)
        assert [r["agentId"] for r in out["attached"]] == ["agent.my-builder", "agent.my-finder"]
        assert _node_coords(spec, "n1") == {MY_BUILDER, MY_FINDER}


class TestPlannedNodesGetTheCopies:
    def _mint(self, client, user, token, project_id, monkeypatch):
        _write_copies(_user_dir_key(user))
        mint = routes_proposals.TestDataflowPlanMint()
        apply = routes_proposals.TestDataflowPlanApply()
        att_id, _ = mint._setup(
            client, user, token, project_id, monkeypatch,
            replies=["Plan.\n" + apply._data_loading_plan()], coord=MY_ORCHESTRATOR,
        )
        # The Researcher attaches to any node, so it would be given to every one
        # if the plan took each installed agent whose target matches.
        r = client.post(f"/api/agents/projects/{project_id}/install",
                        json={"coord": RESEARCHER}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        apply._add_data_loading_template(user)
        r = mint._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        return att_id, proposal

    def test_whole_plan_apply_attaches_the_copies_per_node_kind(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        body = routes_proposals.TestDataflowPlanApply()._apply(
            client, token, alice_project, att_id, proposal["proposalId"],
        ).get_json()
        ids = {n["goal"].split(" —")[0]: n["id"] for n in body["appliedGraph"]["nodes"]}
        by_node: dict[str, set] = {}
        for row in body["attachedAgents"]:
            by_node.setdefault(row["nodeId"], set()).add(row["agentId"])
        assert by_node == {
            ids["Load boundaries"]: {"agent.my-builder", "agent.my-finder"},
            ids["Analyze"]: {"agent.my-builder"},
        }
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert _node_coords(spec, ids["Load boundaries"]) == {MY_BUILDER, MY_FINDER}
        assert _node_coords(spec, ids["Analyze"]) == {MY_BUILDER}
        assert RESEARCHER in project_agents.project_agents(spec)
        assert not [r for r in attachments.list_attachments(spec) if r.get("coord") == RESEARCHER]
        # The applied card names them as their manifests do.
        card = next(
            p for t in reversed(_turns(client, token, alice_project, att_id))
            for p in (t.get("content") or []) if p.get("title") == "Applied: dataflow plan"
        )
        line = next(l for l in card["lines"] if l.startswith("agents attached:"))
        assert line == "agents attached: My Builder ×2 · My Finder"

    def test_per_node_apply_names_the_content_agents_attachment(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal = self._mint(client, user, token, alice_project, monkeypatch)
        per_node = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/"
            f"{proposal['proposalId']}/apply-node",
            json={"ref": "a"}, headers=_auth(token),
        ).get_json()
        assert {r["agentId"] for r in per_node["attachedAgents"]} == {
            "agent.my-builder", "agent.my-finder",
        }
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        node_id = per_node["createdNode"]["id"]
        assert per_node["attachedAgentId"] == _attachment_of(spec, node_id, MY_BUILDER)["attachmentId"]


class TestSolveUsesTheCopies:
    INVENTED = 'import pandas as pd\nreturn pd.read_csv("invented.csv")'

    def _harness(self, client, user, token, monkeypatch, **kw):
        def prepare(h):
            _write_copies(h.ukey)
            r = client.post(f"/api/agents/projects/{h.pid}/install",
                            json={"coord": RESEARCHER}, headers=_auth(token))
            assert r.status_code == 201, r.get_data(as_text=True)

        return discovery_routes._Harness(
            client, user, token, monkeypatch, parent=MY_ORCHESTRATOR, prepare=prepare, **kw,
        )

    def test_discovery_runs_at_the_copied_finder_and_the_node_waits_for_it(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = self._harness(client, user, token, monkeypatch)
        load = h.solve()["results"][h.load]
        assert load["status"] == "pending"
        assert load["remedy"]["kind"] == "dataset-selection"
        finder = _attachment_of(h.spec(), h.load, MY_FINDER)
        assert finder is not None and load["remedy"]["attachmentId"] == finder["attachmentId"]
        parts = [
            p for t in h.session_turns(finder["attachmentId"]) for p in (t.get("content") or [])
            if p.get("type") == "datasetCandidates"
        ]
        assert len(parts) == 1 and len(h.discover_calls) == 1
        assert finder[dr.RECORD_KEY]["status"] == dr.STATE_CANDIDATES_PENDING
        # Only the copies were given work; the Researcher is never a home.
        assert {r["coord"] for r in attachments.list_attachments(h.spec())} == {
            MY_ORCHESTRATOR, MY_BUILDER, MY_FINDER,
        }

    def test_a_confirmed_source_is_built_by_the_copied_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = self._harness(
            client, user, token, monkeypatch,
            dl_replies=[self.INVENTED, self.INVENTED, self.INVENTED,
                        f'import geopandas as gpd\nreturn gpd.read_file("{URL}")'],
        )
        h.solve()
        finder_id = _attachment_of(h.spec(), h.load, MY_FINDER)["attachmentId"]
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(fetch_routes.API_OBSERVATION),
        )
        body = fetch_routes._select(h, finder_id, [{"lane": "external", "key": URL}]).get_json()
        assert body["status"] == dr.STATE_RESOLVED, body
        delegated = body["delegated"]
        assert delegated["status"] == "delegating", delegated
        builder_id = _attachment_of(h.spec(), h.load, MY_BUILDER)["attachmentId"]
        assert delegated["attachmentId"] == builder_id
        done = next(p for k, p in fetch_routes._drain(h, builder_id) if k == "done")
        assert done["verdict"] == "pass"
        # The build read the source recorded on the copied finder.
        assert "confirmedSource" in h.dl_calls[-1]
        assert URL in h.node_content(h.load)

    def test_a_selection_belongs_to_an_agent_that_selects_datasets(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = self._harness(client, user, token, monkeypatch)
        h.solve()
        builder_id = _attachment_of(h.spec(), h.load, MY_BUILDER)["attachmentId"]
        refused = fetch_routes._select(h, builder_id, [{"lane": "external", "key": URL}])
        assert refused.status_code == 400
        error = refused.get_json()["error"]
        assert "dataset.select" in error and "My Builder" in error

    def _plan_node(self, client, user, token, project_id, monkeypatch, reply):
        _write_copies(_user_dir_key(user))
        mint = routes_proposals.TestDataflowPlanMint()
        att_id, _ = mint._setup(
            client, user, token, project_id, monkeypatch,
            replies=["Plan.\n" + mint._plan_tail(), reply], coord=MY_ORCHESTRATOR,
        )
        r = mint._run(client, token, project_id, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        ref = proposal["plan"]["nodes"][0]["ref"]
        created = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/"
            f"{proposal['proposalId']}/apply-node",
            json={"ref": ref}, headers=_auth(token),
        ).get_json()
        return att_id, ref, created

    def _link(self, client, token, project_id, att_id):
        """The parent's last turn that links the node's agent, and that link."""
        turn = next(
            t for t in reversed(_turns(client, token, project_id, att_id))
            if any(p.get("type") == "delegation" for p in (t.get("content") or []))
        )
        return turn, next(p for p in turn["content"] if p["type"] == "delegation")

    def test_validate_homes_the_review_at_the_copied_builder(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {"stdout": [], "stderr": "",
                                       "output": {"path": "art", "dataType": "dataframe"}},
        )
        att_id, ref, created = self._plan_node(
            client, user, token, alice_project, monkeypatch, "print('validated')",
        )
        node_id = created["createdNode"]["id"]
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        home_id = created["attachedAgentId"]
        assert home_id == _attachment_of(spec, node_id, MY_BUILDER)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/validate-node",
            json={"ref": ref}, headers=_auth(token),
        )
        done = routes_solve.TestStreamedSolve()._sse_events(r)[-1][1]
        assert done["verdict"] == "pass" and done["proposalAttachmentId"] == home_id
        home_turns = _turns(client, token, alice_project, home_id)
        assert any(t["text"].startswith("[Delegated by My Orchestrator] Solve") for t in home_turns)
        turn, link = self._link(client, token, alice_project, att_id)
        assert turn["text"].endswith("the trace and content review live in the node's My Builder.")
        assert (link["attachmentId"], link["name"], link["coord"]) == (home_id, "My Builder", MY_BUILDER)

    def test_propose_mode_mints_the_review_at_the_copied_builder(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, _ref, created = self._plan_node(
            client, user, token, alice_project, monkeypatch, "print('generated')",
        )
        node_id = created["createdNode"]["id"]
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/solve/stream",
            json={"mode": "propose", "nodeIds": [node_id], "verify": False},
            headers=_auth(token),
        )
        result = next(p for k, p in routes_solve.TestStreamedSolve()._sse_events(resp)
                      if k == "node_result")
        assert result["status"] == "proposed", result
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        home_id = _attachment_of(spec, node_id, MY_BUILDER)["attachmentId"]
        assert result["proposalAttachmentId"] == home_id
        turn, link = self._link(client, token, alice_project, att_id)
        assert turn["text"].endswith("the review lives in the node's My Builder.")
        assert (link["attachmentId"], link["name"], link["coord"]) == (home_id, "My Builder", MY_BUILDER)


class TestADataLoadingNodeIsATemplateThatLoadsADataset:
    #: A package's own loader that declares the flag, and a template that only
    #: has the built-in loader's name.
    TEMPLATES = {"ai.test.loaders/fetch-weather": {"loadsDataset": True},
                 "ai.test.loaders/data-loading": {}}

    def test_a_node_target_reads_the_flag(self):
        finder = builtin.get_builtin_manifest(DF)
        for node_type in (DL, f"{DL}@1", "DATA_LOADING"):
            assert attachments.node_target_matches(finder, node_type, None), node_type
        assert not attachments.node_target_matches(finder, CA, None)
        assert attachments.node_target_matches(finder, "ai.test.loaders/fetch-weather", self.TEMPLATES)
        assert not attachments.node_target_matches(finder, "ai.test.loaders/data-loading", self.TEMPLATES)

    def test_solve_reads_the_flag(self):
        from utk_curio.backend.app.agents.application import source_grounding

        assert source_grounding.loads_dataset(DL)
        assert source_grounding.loads_dataset(f"{DL}@1")
        assert source_grounding.loads_dataset("DATA_LOADING")
        assert not source_grounding.loads_dataset(CA)
        assert source_grounding.loads_dataset("ai.test.loaders/fetch-weather", self.TEMPLATES)
        assert not source_grounding.loads_dataset("ai.test.loaders/data-loading", self.TEMPLATES)
        # The shipped package loaders declare nothing, as before.
        for loader in ("curio.weather/weather-load", "ai.utk.uhvi/uhvi-load"):
            assert not source_grounding.loads_dataset(loader), loader

    def test_a_package_template_that_declares_it_takes_the_finder(
        self, client, user_and_token, tmp_curio
    ):
        from utk_curio.backend.tests.test_packages import test_available_templates as roster

        user, token = user_and_token
        ukey = _user_dir_key(user)
        roster._write_package(ukey, "ai.test.loaders", 1, [
            {**roster._template("fetch-weather", "Fetch weather"), "loadsDataset": True},
            roster._template("data-loading", "Named like the built-in loader"),
        ])
        body = {"name": "p", "spec": {"dataflow": {"nodes": [
            {"id": "w1", "type": "ai.test.loaders/fetch-weather", "content": ""},
            {"id": "w2", "type": "ai.test.loaders/data-loading", "content": ""},
        ], "edges": [], "packages": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        roster._lockfile_add(ukey, pid, "ai.test.loaders@1")
        client.post(f"/api/agents/projects/{pid}/install", json={"coord": DF}, headers=_auth(token))

        def attach(node_id):
            return client.post(
                f"/api/agents/projects/{pid}/attachments",
                json={"coord": DF, "target": {"kind": "node", "targetId": node_id}},
                headers=_auth(token),
            )

        accepted = attach("w1")
        assert accepted.status_code == 201, accepted.get_data(as_text=True)
        refused = attach("w2")
        assert refused.status_code == 400
        assert "loadsDataset" in refused.get_json()["error"]


class TestNamesComeFromManifests:
    def test_the_remedy_names_the_agent_it_opens(self):
        from utk_curio.backend.app.agents.application.turns import grounding

        assert "open My Finder on this node" in grounding._ungrounded_remedy("att-1", name="My Finder")
        assert "resolve the source with My Finder" in grounding._ungrounded_remedy(None, name="My Finder")
        # With no agent named, the shipped one that finds datasets is.
        assert "open Dataset Finder on this node" in grounding._ungrounded_remedy("att-1")

    def test_the_agent_models_rows_say_what_each_agent_declares(
        self, client, user_and_token, tmp_curio
    ):
        user, token = user_and_token
        _write_copies(_user_dir_key(user))
        listing = client.get("/api/agents/llm", headers=_auth(token)).get_json()
        rows = {row["id"]: row for row in listing["agents"]}
        builder = rows["agent.dataflow-builder"]
        assert "dataflow.orchestrate" in builder["capabilities"]
        # The agents its Solve runs, in the order Solve asks them.
        assert builder["solveRuns"] == ["Node Builder", "Dataset Finder"]
        assert rows["agent.my-orchestrator"]["solveRuns"] == ["My Builder", "My Finder"]
        assert "node.content.generate" in rows["agent.my-builder"]["capabilities"]
        assert "solveRuns" not in rows["agent.my-builder"]

    def test_the_attachment_card_says_what_its_agent_declares(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        user, token = user_and_token
        _write_copies(_user_dir_key(user))
        client.post(f"/api/agents/projects/{alice_project}/install",
                    json={"coord": MY_FINDER}, headers=_auth(token))
        card = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": MY_FINDER, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()
        assert card["capabilities"] == ["dataset.discover", "dataset.select"]
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token),
        ).get_json()["attachments"]
        assert [c["capabilities"] for c in listed] == [["dataset.discover", "dataset.select"]]

    def test_the_attachment_card_names_the_agent_it_hands_nodes_to_build(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        user, token = user_and_token
        _write_copies(_user_dir_key(user))
        # The copied builder requires the copied finder, so both are installed.
        r = client.post(f"/api/agents/projects/{alice_project}/install",
                        json={"coord": MY_BUILDER}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        cards = {}
        for coord in (MY_FINDER, MY_BUILDER):
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments",
                json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token),
            )
            assert r.status_code == 201, r.get_data(as_text=True)
            cards[coord] = r.get_json()
        # The copied finder hands node.build to the copied builder, named as its
        # manifest names it: the candidates card's hand-off reads this name.
        assert cards[MY_FINDER]["nodeBuildDelegate"] == "My Builder"
        # An agent that builds nodes itself hands that to no one.
        assert cards[MY_BUILDER]["nodeBuildDelegate"] is None
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token),
        ).get_json()["attachments"]
        assert {c["coord"]: c["nodeBuildDelegate"] for c in listed} == {
            MY_FINDER: "My Builder", MY_BUILDER: None,
        }

    @pytest.mark.parametrize("coord, hinted", [
        (MY_ORCHESTRATOR, True), (DFB, True), (RESEARCHER, False),
    ])
    def test_the_discovery_hint_follows_what_the_parent_delegates(self, tmp_curio, coord, hinted):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.turns import grounding

        _write_copies(UKEY)
        base = {"catalog_paths": {}, "catalog_ids": {}, "texts": [], "verified": {}, "secrets": {}}
        manifest = catalog._resolve_definition(UKEY, coord)
        ctx = grounding._grounding_context(UKEY, "p", {"manifest": manifest}, node_type=DL, base=base)
        assert any("delegate the dataset.discover capability" in h for h in ctx.hints) is hinted
