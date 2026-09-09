"""dev/114 (DEC-072) — the source-grounding gate end to end (issue #298).

Node Builder → Dataset Finder → the reviewed node, over deterministic
providers and a monkeypatched DEC-053 prober: a fabricated local filename is
refused and corrected; a catalog path is grounded with its real id; an
external URL is grounded only by the runtime's probe; an unverifiable source
yields a plain request, never code; synthetic data needs the user's words;
Solve refuses ungrounded content loudly; the dev/73 review mint inherits it.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests.test_agents import test_routes as _tr

_auth = _tr._auth

NB = "agent.node-builder@1.0.0"
DF = "agent.dataset-finder@1.0.0"
NCB = "agent.node-content-builder@1.0.0"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"

NOAA = "https://api.noaa.gov/climate/v1/data"
GHOST = "https://portal.example.gov/resource/zzzz-0000.json"

ISSUE_298 = 'import pandas as pd\ndf = pd.read_csv("bras_ibge_data.csv")\nreturn df'

TEMPLATES = [
    {
        "id": "data-loading", "label": "Data Loading", "category": "data",
        "engine": "python", "editor": "code", "description": "Load data into the flow.",
        "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
    },
    {
        "id": "computation-analysis", "label": "Computation Analysis",
        "category": "computation", "engine": "python", "editor": "code",
        "description": "Run python analysis code.",
        "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    },
]


@pytest.fixture()
def project(client, user_and_token):
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    _tr.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
    body = {
        "name": "p",
        "spec": {"dataflow": {"nodes": [
            {"id": "n1", "type": DL, "goal": "load the demographic data", "content": "", "x": 10, "y": 20},
        ], "edges": [], "packages": []}},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _install(client, token, pid, *coords):
    for coord in coords:
        client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))


def _attach(client, token, pid, coord, target=None):
    return client.post(
        f"/api/agents/projects/{pid}/attachments",
        json={"coord": coord, "target": target or {"kind": "canvas"}},
        headers=_auth(token),
    ).get_json()["attachmentId"]


def _script(monkeypatch, replies):
    """Provider script: each entry is a string or ``callable(calls) -> str``
    (a dynamic reply can read the previous tool result)."""
    calls: list = []

    def _fake_run(config, messages, **kwargs):
        from utk_curio.backend.app.agents import services as services_mod

        if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
            return "Title"
        calls.append(messages)
        entry = replies[min(len(calls) - 1, len(replies) - 1)]
        return entry(calls) if callable(entry) else entry

    monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
    return calls


def _run(client, token, pid, att_id, message="build a node that loads the data"):
    r = client.post(
        f"/api/agents/projects/{pid}/attachments/{att_id}/run",
        json={"message": message}, headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _create_tail(content, node_type=DL, **extra):
    params = {"nodeType": node_type, "content": content, **extra}
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": "node.create", "params": params}}) + "\n```"


def _search_tail():
    return '```curio.v1\n{"toolRequest": {"tool": "catalog.search", "params": {}}}\n```'


def _delegate_tail(capability, inputs):
    return "```curio.v1\n" + json.dumps({"delegateRequest": {"capability": capability, "inputs": inputs}}) + "\n```"


def _tool_results(messages, tool):
    """Every ``[tool result] <tool>:`` message in a (final) provider message
    list. NOTE: the loop mutates ONE ``messages_work`` list, so every recorded
    call aliases the same object — read by prefix, never by index."""
    prefix = f"[tool result] {tool}:"
    return [m["content"] for m in messages if m.get("role") == "user"
            and (m.get("content") or "").startswith(prefix)]


def _rows_from_search_result(messages):
    """The catalog.search rows the model was shown."""
    text = _tool_results(messages, "catalog.search")[-1]
    payload = json.loads(text.split("\n", 1)[1].split("\nNo further")[0])
    return payload["datasets"]


def _proposals(body):
    return [p for p in body["content"] if p["type"] == "proposal"]


def _fake_probe(monkeypatch, verdicts: dict, counter: list | None = None):
    def _verify(url, **kw):
        if counter is not None:
            counter.append(url)
        if not url:
            return {"status": "unverified", "detail": "no probeable URL — the identifier was never checked"}
        return dict(verdicts.get(url) or {"status": "unreachable", "httpStatus": 404,
                                          "detail": "the endpoint answered 404"})
    monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)


class TestRegression298:
    """The reported shape: ``pd.read_csv("bras_ibge_data.csv")`` — never
    proposed; the refusal names the literal; the correction is a free round
    (dev/105 D2) and the grounded proposal carries the catalog's real id."""

    def test_fabricated_filename_refused_then_catalog_path_grounded(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="ibge.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)

        def _corrected(calls):
            rows = _rows_from_search_result(calls[-1])
            row = next(r for r in rows if r["id"] == dataset_id)
            assert row["path"] and "pd.read_csv(dataset_path)" in row["loader"]
            assert f'curio_dataset_path("{dataset_id}")' in row["loader"]  # main's portable recipe
            return _create_tail(row["loader"] + "\nreturn df", goal="load IBGE demographics")

        calls = _script(monkeypatch, [
            _search_tail(),                      # round 1: the model searches
            _create_tail(ISSUE_298),             # round 2: the #298 shape
            _corrected,                          # round 3: corrected with the catalog path
            "Proposed — review it above.",
        ])
        body = _run(client, token, project, att, "build a node that loads Brazilian IBGE demographics")
        proposals = _proposals(body)
        assert len(proposals) == 1
        source = proposals[0]["source"]
        assert source["kind"] == "catalog"
        assert source["refs"][0]["datasetId"] == dataset_id
        assert "Data Catalog" in source["label"]
        assert "bras_ibge_data.csv" not in proposals[0]["preview"]
        # The refusal named the literal and the allowed routes.
        [refusal] = [t for t in _tool_results(calls[-1], "node.create") if "refused" in t.split("\n", 1)[0]]
        assert "'bras_ibge_data.csv' (line 2)" in refusal
        assert "Curio cannot see" in refusal
        assert "catalog.search" in refusal and "dataset.discover" in refusal
        assert "Never invent a filename" in refusal
        # A parameter refusal spends no round (dev/105 D2): the execution
        # record on the persisted agent turn says so.
        turns = client.get(
            f"/api/agents/projects/{project}/attachments/{att}/session", headers=_auth(token),
        ).get_json()["turns"]
        assert turns[-1]["execution"]["refusedRounds"] == 1

    def test_shapefile_guess_is_refused_and_nothing_is_proposed(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [
            _create_tail('import geopandas as gpd\ngdf = gpd.read_file("bras_geosampa_boundary.shp")\nreturn gdf'),
            "I cannot ground that file — please tell me where the boundary file is.",
        ])
        body = _run(client, token, project, att)
        assert _proposals(body) == []
        assert "bras_geosampa_boundary.shp" in calls[1][-1]["content"]
        assert "please tell me where" in body["reply"]


class TestCatalogGrounding:
    def test_catalog_search_rows_carry_path_and_loader_for_node_builder(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="tracts.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_search_tail(), "ok"])
        _run(client, token, project, att)
        rows = _rows_from_search_result(calls[-1])
        row = next(r for r in rows if r["id"] == dataset_id)
        assert row["path"].endswith("tracts.csv")
        assert row["loader"].startswith(f'dataset_path = curio_dataset_path("{dataset_id}")')
        # Node Builder's tail now offers catalog.search (granted).
        assert "catalog.search" in calls[0][0]["content"]

    def test_user_typed_path_is_grounded_as_user_path(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, [
            _create_tail('import geopandas as gpd\ngdf = gpd.read_file("data/tracts.geojson")\nreturn gdf'),
            "Proposed.",
        ])
        body = _run(client, token, project, att, "load my file data/tracts.geojson into a node")
        [proposal] = _proposals(body)
        assert proposal["source"]["kind"] == "user-path"
        assert proposal["source"]["refs"][0]["value"] == "data/tracts.geojson"


def _candidates_reply(external, catalog):
    payload = {"datasetCandidates": {"lanes": {"external": external, "catalog": catalog}}}
    return "Two lanes.\n```curio.v1\n" + json.dumps(payload) + "\n```"


class TestExternalDiscovery:
    """No catalog match → Node Builder delegates dataset.discover; the tool-less
    Dataset Finder child gets the catalog as INPUT; its candidates are
    runtime-minted onto the two-lane card (catalog rows tool-grounded,
    external rows probed); the user confirms before any node is proposed."""

    def _discover_run(self, client, user, token, project, monkeypatch, *, extra_replies=()):
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        _install(client, token, project, NB, DF)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {NOAA: {"status": "verified", "httpStatus": 200, "checkedAt": "now"}})
        child = _candidates_reply(
            external=[
                {"name": "NOAA Climate Data API", "sourceType": "api", "url": NOAA,
                 "provider": "NOAA", "format": "JSON", "fit": {"score": 94, "rationale": "direct"}},
                {"name": "Ghost portal", "sourceType": "portal", "url": GHOST,
                 "fit": {"score": 40, "rationale": "guess"}},
            ],
            catalog=[
                {"name": "Heat", "sourceType": "catalog", "datasetId": dataset_id, "installed": False},
                {"name": "Invented", "sourceType": "catalog", "datasetId": "imported.ghost@1", "installed": True},
            ],
        )
        calls = _script(monkeypatch, [
            _delegate_tail("dataset.discover", {"intent": "tract-level heat data"}),
            child,
            *extra_replies,
            "Please select the source you want and confirm.",
        ])
        body = _run(client, token, project, att, "build a node that loads tract-level heat data")
        return att, calls, body, dataset_id

    def test_candidates_are_minted_on_the_node_builder_turn(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, calls, body, dataset_id = self._discover_run(client, user, token, project, monkeypatch)
        part = next(p for p in body["content"] if p["type"] == "datasetCandidates")
        ext = {r["url"]: r["verification"]["status"] for r in part["lanes"]["external"]}
        assert ext == {NOAA: "verified", GHOST: "unreachable"}
        # Catalog rows are tool-grounded: the invented id is dropped.
        assert [r["datasetId"] for r in part["lanes"]["catalog"]] == [dataset_id]
        assert _proposals(body) == []
        # The child was handed the catalog and the ONE reply schema (#269).
        child_frame = calls[1][-1]["content"]
        assert '"catalog"' in child_frame and dataset_id in child_frame
        assert "datasetCandidates" in child_frame and "discoveryReplyContract" in child_frame
        # The parent learned the outcome and the two-turn rule.
        assert "shown to the user for review" in calls[2][-1]["content"]
        assert "1 catalog row(s) were dropped" in calls[2][-1]["content"]
        entry = next(p for p in body["content"] if p["type"] == "delegation")
        assert entry["status"] == "ok" and "select and confirm" in entry["summary"]

    def test_same_turn_create_after_candidates_is_refused(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, calls, body, _ = self._discover_run(
            client, user, token, project, monkeypatch,
            extra_replies=[_create_tail(f'import requests\nr = requests.get("{NOAA}", timeout=10)\nreturn r.json()')],
        )
        assert _proposals(body) == []
        assert "shown to the user for review — do not propose a node in this turn" in calls[3][-1]["content"]

    def test_next_turn_create_with_the_verified_url_is_grounded_without_a_new_probe(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, _, _, _ = self._discover_run(client, user, token, project, monkeypatch)
        probes: list = []
        _fake_probe(monkeypatch, {}, counter=probes)  # any probe now would say 404
        _script(monkeypatch, [
            _create_tail(f'import requests\nr = requests.get("{NOAA}", timeout=10)\nreturn r.json()',
                         goal="fetch NOAA climate data"),
            "Proposed — review above.",
        ])
        body = _run(client, token, project, att, "Build the data-loading node from NOAA Climate Data API")
        [proposal] = _proposals(body)
        assert proposal["source"]["kind"] == "external"
        assert proposal["source"]["refs"][0]["value"] == NOAA
        assert proposal["source"]["refs"][0]["verification"]["status"] == "verified"
        assert probes == []  # session evidence grounded it; nothing re-spent

    def test_unverified_url_is_probed_and_refused_with_the_status(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {GHOST: {"status": "unreachable", "httpStatus": 404, "detail": "the endpoint answered 404"}})
        calls = _script(monkeypatch, [
            _create_tail(f'import requests\nreturn requests.get("{GHOST}").json()'),
            "That endpoint does not answer — do you have another source?",
        ])
        body = _run(client, token, project, att)
        assert _proposals(body) == []
        assert "answered 404" in calls[1][-1]["content"]

    def test_a_url_in_the_users_prompt_is_not_evidence(self, client, user_and_token, tmp_curio, project, monkeypatch):
        # The DEC-047 handoff prompt is model-suggested text the user forwards.
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {})  # 404 for everything
        calls = _script(monkeypatch, [
            _create_tail(f'import requests\nreturn requests.get("{GHOST}").json()'),
            "Not reachable.",
        ])
        body = _run(client, token, project, att, f"Ask Node Builder: author a fetch node for Ghost — endpoint {GHOST}, format JSON")
        assert _proposals(body) == []
        assert "answered 404" in calls[1][-1]["content"]

    def test_a_guessed_local_filename_never_passes_even_with_external_context(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, _, _, _ = self._discover_run(client, user, token, project, monkeypatch)
        calls = _script(monkeypatch, [_create_tail('df = pd.read_csv("noaa_climate.csv")\nreturn df'), "hm"])
        body = _run(client, token, project, att, "Build the data-loading node from NOAA Climate Data API")
        assert _proposals(body) == []
        assert "'noaa_climate.csv' (line 1)" in calls[1][-1]["content"]

    def test_credential_gated_endpoint_is_grounded_with_the_requirement(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {NOAA: {"status": "unreachable", "httpStatus": 401, "detail": "the endpoint answered 401"}})
        _script(monkeypatch, [_create_tail(f'import requests\nreturn requests.get("{NOAA}").json()'), "Proposed."])
        [proposal] = _proposals(_run(client, token, project, att))
        assert proposal["source"]["refs"][0]["requirement"] == "credential-gated"
        assert "credential-gated" in proposal["source"]["label"]


class TestUnavailableSource:
    def test_no_verifiable_source_yields_a_request_never_code(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {})  # everything unreachable
        calls = _script(monkeypatch, [
            _create_tail('import requests\nreturn requests.get("https://a.example/x.json").json()'),
            _create_tail('import requests\nreturn requests.get("https://b.example/y.json").json()'),
            _create_tail('df = pd.read_csv("guess.csv")\nreturn df'),
            "I could not verify any source for this data. Please give me a file path or a working URL.",
        ])
        body = _run(client, token, project, att)
        assert _proposals(body) == []
        assert "Please give me a file path" in body["reply"]
        assert all("refused" in c[-1]["content"] for c in calls[1:4])
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        assert [n["id"] for n in spec["dataflow"]["nodes"]] == ["n1"]  # nothing changed


class TestSyntheticData:
    INLINE = 'import pandas as pd\ndf = pd.DataFrame({"tract": [1, 2, 3, 4, 5], "heat": [30, 31, 29, 33, 35]})\nreturn df'

    def test_explicitly_requested_synthetic_data_is_labeled(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, [_create_tail(self.INLINE, goal="synthetic sample", synthetic=True), "Proposed."])
        [proposal] = _proposals(_run(client, token, project, att, "generate synthetic sample data for 5 tracts"))
        assert proposal["source"]["kind"] == "synthetic"
        assert "no external source" in proposal["source"]["label"]

    def test_inline_data_without_the_request_is_fabrication(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_create_tail(self.INLINE, synthetic=True), "hm"])
        body = _run(client, token, project, att, "load the IBGE demographic data for the tracts")
        assert _proposals(body) == []
        assert "no grounded source" in calls[1][-1]["content"]

    def test_computation_nodes_are_untouched(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, [_create_tail("df = arg[0]\nreturn df.describe()", node_type=CA), "Proposed."])
        [proposal] = _proposals(_run(client, token, project, att, "summarize the upstream frame"))
        assert "source" not in proposal


class TestSolveSourceGrounding:
    """Solve never writes fabricated-path content: the data-loading node fails
    loudly with the literal and the remedy; a sibling solves; the child was
    HANDED the grounded sources (the seventh DEC-063 application)."""

    def _plan_tail(self):
        plan = {
            "goal": "heat by tract",
            "nodes": [
                {"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the tract heat data"},
                {"ref": "stats", "nodeType": CA, "title": "Stats", "intent": "compute stats"},
            ],
            "edges": [{"from": "load", "to": "stats"}],
        }
        return "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"

    def _applied_plan(self, client, user, token, project, monkeypatch, child_reply):
        _install(client, token, project, "agent.dataflow-builder@1.0.0", NCB)
        att = _attach(client, token, project, "agent.dataflow-builder@1.0.0")

        def _reply(calls):
            frame = calls[-1][-1]["content"]
            if "[delegated task" not in frame:
                return self._plan_tail()
            return child_reply(frame)

        calls = _script(monkeypatch, [_reply])
        body = _run(client, token, project, att, "plan the heat analysis")
        [proposal] = _proposals(body)
        applied = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        return att, applied, calls

    def _solve(self, client, token, project, att, node_ids=None):
        payload = {"nodeIds": node_ids} if node_ids is not None else {}
        return client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve",
            json=payload, headers=_auth(token),
        ).get_json()

    def test_fabricated_path_fails_the_node_and_the_sibling_solves(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat_tracts.csv")

        def child(frame):
            if f'"nodeType": "{DL}"' in frame:
                return 'import pandas as pd\ndf = pd.read_csv("heat_tracts.csv")\nreturn df'
            return "df = arg[0]\nreturn df.describe()"

        # dev/115: Solve now RUNS data-loading candidates; a fake sandbox that
        # passes keeps this test about grounding (the gate refuses before any run).
        exec_payloads = []

        def _exec(endpoint, payload):
            exec_payloads.append(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        att, applied, calls = self._applied_plan(client, user, token, project, monkeypatch, child)
        body = self._solve(client, token, project, att)
        nodes_applied = applied["appliedGraph"]["nodes"]
        load = next(n["id"] for n in nodes_applied if str(n.get("type", "")).startswith(DL))
        stats = next(n["id"] for n in nodes_applied if str(n.get("type", "")).startswith(CA))
        assert body["results"][stats]["status"] == "solved"
        assert body["results"][load]["status"] == "failed"
        # dev/118 (DEC-075): the computation sibling is verified in wave 2 —
        # its slice runs the (empty, refused) loader first and then the node;
        # the fake sandbox passes both. In reality an empty upstream is a
        # blocker the runner names (§6.1); here the point is that NOTHING of
        # the refused loader's fabricated code reached the sandbox.
        assert [p["nodeType"] for p in exec_payloads] == [DL, CA]
        assert "heat_tracts.csv" not in exec_payloads[0]["code"]
        # dev/115: every round was refused by the gate (kind ungrounded-source)
        # and NEVER reached the sandbox; the error names the literal + remedy.
        assert body["results"][load]["verdict"] == "fail"
        assert all(a["kind"] == "ungrounded-source" for a in body["results"][load]["attempts"])
        assert "ungrounded-source" in body["results"][load]["error"]
        assert "heat_tracts.csv" in body["results"][load]["error"]
        assert "Dataset Finder" in body["results"][load]["error"]
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        nodes = {n["id"]: n for n in spec["dataflow"]["nodes"]}
        assert nodes[load]["content"] == ""  # nothing fabricated reached the spec
        assert nodes[stats]["content"]
        # The data-loading child was HANDED the catalog's real path.
        dl_frame = next(c[-1]["content"] for c in calls if f'"nodeType": "{DL}"' in c[-1]["content"])
        assert '"sourceGrounding"' in dl_frame and dataset_id in dl_frame and "heat_tracts.csv" in dl_frame
        assert '"catalogDatasets"' in dl_frame
        # Retry with the grounded path solves.
        path = json.loads(dl_frame.split("\n", 1)[1])["sourceGrounding"]["catalogDatasets"][0]["path"] \
            if dl_frame.split("\n", 1)[1].lstrip().startswith("{") else None
        if path is None:
            import re
            path = re.search(r'"path": "([^"]+heat_tracts\.csv)"', dl_frame).group(1)

        def child2(frame):
            return f'import pandas as pd\ndataset_path = "{path}"\ndf = pd.read_csv(dataset_path)\nreturn df'

        _script(monkeypatch, [lambda calls: child2(calls[-1][-1]["content"])])
        body2 = self._solve(client, token, project, att, node_ids=[load])
        assert body2["results"][load]["status"] == "solved"
        assert body2["results"][load]["verdict"] == "pass"  # dev/115: it ran
        # dev/118: two payloads from the first batch's wave 2 (the empty loader
        # in the stats slice, then stats) + the retried loader = three; the
        # retry ran exactly one node, the grounded loader.
        assert len(exec_payloads) == 3 and exec_payloads[-1]["nodeType"] == DL
        assert path in exec_payloads[-1]["code"]
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        assert path in next(n for n in spec["dataflow"]["nodes"] if n["id"] == load)["content"]


class TestContentReviewMintInheritsTheGate:
    def test_delegated_generation_with_a_fabricated_path_mints_no_review(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB, NCB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "n1"})
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "n1", "intent": "load the demographics"}),
            'import pandas as pd\ndf = pd.read_csv("bras_ibge_data.csv")\nreturn df',
            "The generated content could not be grounded; which file should it load?",
        ])
        body = _run(client, token, project, att, "fill this node")
        assert _proposals(body) == []
        result = calls[2][-1]["content"]
        assert "could not become a reviewed proposal" in result
        assert "bras_ibge_data.csv" in result
        entry = next(p for p in body["content"] if p["type"] == "delegation")
        assert entry["status"] == "ok"  # the child ran; the mint refused honestly
        # The child received the grounding inputs for a data-loading node.
        assert '"sourceGrounding"' in calls[1][-1]["content"]


class TestCandidatesMint:
    """The runtime mint over a tool-less Dataset Finder child's reply."""

    def test_schema_recognition_bare_fenced_and_chat_json(self):
        from utk_curio.backend.app.agents import services as s

        block = {"datasetCandidates": {"lanes": {"external": [], "catalog": []}}}
        assert s._extract_candidates_reply(json.dumps(block)) == block["datasetCandidates"]
        assert s._extract_candidates_reply("Here.\n```curio.v1\n" + json.dumps(block) + "\n```") == block["datasetCandidates"]
        assert s._extract_candidates_reply("```json\n" + json.dumps(block) + "\n```") == block["datasetCandidates"]
        assert s._extract_candidates_reply(json.dumps({"answer": "x", "lanes": {}})) is None
        assert s._extract_candidates_reply("no json here") is None

    def test_mint_drops_unknown_catalog_rows_and_verifies_external(self, monkeypatch):
        from utk_curio.backend.app.agents import services as s

        _fake_probe(monkeypatch, {NOAA: {"status": "verified", "httpStatus": 200}})
        loop_ctx: dict = {}
        child = _candidates_reply(
            external=[{"name": "NOAA", "sourceType": "api", "url": NOAA}],
            catalog=[{"name": "Real", "sourceType": "catalog", "datasetId": "ds-1"},
                     {"name": "Fake", "sourceType": "catalog", "datasetId": "ds-9"}],
        )
        part, text, outcome = s._mint_candidates_from_delegate(
            loop_ctx, child, [{"id": "ds-1", "name": "Real", "installed": True}],
        )
        assert outcome == "ok"
        assert [r["datasetId"] for r in part["lanes"]["catalog"]] == ["ds-1"]
        assert part["lanes"]["catalog"][0]["installed"] is True  # the listing's truth
        assert part["lanes"]["external"][0]["verification"]["status"] == "verified"
        assert loop_ctx["_candidates_pending_review"] is True
        assert loop_ctx["_verified_urls"] == {NOAA: part["lanes"]["external"][0]["verification"]}
        assert "1 catalog row(s) were dropped" in text

    def test_nothing_usable_is_honest(self):
        from utk_curio.backend.app.agents import services as s

        part, text, outcome = s._mint_candidates_from_delegate(
            {}, _candidates_reply(external=[], catalog=[{"name": "Fake", "sourceType": "catalog", "datasetId": "ds-9"}]),
            [],
        )
        assert part is None and outcome == "no-candidates"
        assert "1 catalog row(s) dropped" in text and "ask the user for a path or URL" in text
        part, text, outcome = s._mint_candidates_from_delegate({}, "Sure! Here are some ideas.", [])
        assert part is None and outcome == "no-candidates" and "do not invent" in text
