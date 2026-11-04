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
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns

NB = "agent.curio.node-builder@1"
DF = "agent.curio.dataset-finder@1"
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

    routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
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
        from utk_curio.backend.app.agents.application.turns import titles as services_mod

        if messages and messages[0].get("content") == services_mod.title_prompt():
            return "Title"
        calls.append(messages)
        entry = replies[min(len(calls) - 1, len(replies) - 1)]
        return entry(calls) if callable(entry) else entry

    monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
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


def _changes(body):
    """The cards of the changes that landed with a run's reply."""
    return [p for p in body["content"] if p["type"] == "change"]


def _the_change(body) -> dict:
    """The reply's one change card; the parts it holds instead when it has none."""
    cards = _changes(body)
    assert len(cards) == 1, [p["type"] for p in body["content"]]
    return cards[0]


def _landed_plan(body) -> dict:
    """The plan that landed with a blocking run's reply, shaped as an apply's
    answer was: its graph (``appliedGraph``) is the canvas mutation the reply
    carries for a canvas no doc binds."""
    assert not _proposals(body), "a plan waited for review"
    landed = [c for c in body.get("changes") or [] if c["tool"] == "dataflow.plan.write"]
    assert len(landed) == 1, body.get("changes")
    return {"appliedGraph": landed[0]["canvas"]}


def _fake_probe(monkeypatch, verdicts: dict, counter: list | None = None):
    def _verify(url, **kw):
        if counter is not None:
            counter.append(url)
        if not url:
            return {"status": "unverified", "detail": "no probeable URL — the identifier was never checked"}
        return dict(verdicts.get(url) or {"status": "unreachable", "httpStatus": 404,
                                          "detail": "the endpoint answered 404"})
    monkeypatch.setattr('utk_curio.backend.app.agents.application.verify.verify_external_source', _verify)


class TestRegression298:
    """The reported shape: ``pd.read_csv("bras_ibge_data.csv")`` — never
    proposed; the refusal names the literal; the correction is a free round
    (dev/105 D2) and the grounded proposal carries the catalog's real id."""

    def test_fabricated_filename_refused_then_catalog_path_grounded(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="ibge.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)

        def _corrected(calls):
            rows = _rows_from_search_result(calls[-1])
            row = next(r for r in rows if r["id"] == dataset_id)
            assert row["path"] and row["loader"] == f'df = curio_load_data("{dataset_id}")'  # main's portable recipe
            return _create_tail(row["loader"] + "\nreturn df", goal="load IBGE demographics")

        calls = _script(monkeypatch, [
            _search_tail(),                      # round 1: the model searches
            _create_tail(ISSUE_298),             # round 2: the #298 shape
            _corrected,                          # round 3: corrected with the catalog path
            "Proposed — review it above.",
        ])
        body = _run(client, token, project, att, "build a node that loads Brazilian IBGE demographics")
        proposals = _changes(body)
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
        assert _changes(body) == [] and _proposals(body) == []
        assert "bras_geosampa_boundary.shp" in calls[1][-1]["content"]
        assert "please tell me where" in body["reply"]


class TestCatalogGrounding:
    def test_catalog_search_rows_carry_path_and_loader_for_node_builder(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="tracts.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_search_tail(), "ok"])
        _run(client, token, project, att)
        rows = _rows_from_search_result(calls[-1])
        row = next(r for r in rows if r["id"] == dataset_id)
        assert row["path"].endswith("tracts.csv")
        assert row["loader"] == f'df = curio_load_data("{dataset_id}")'
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
        proposal = _the_change(body)
        assert proposal["source"]["kind"] == "user-path"
        assert proposal["source"]["refs"][0]["value"] == "data/tracts.geojson"

    def test_a_dataset_other_than_the_one_the_user_named_is_refused(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """#411: asked for one Data Catalog dataset by its id, the Node Builder
        loaded another. Both are real catalog datasets, so only the request
        tells them apart: nothing is proposed and the refusal names both."""
        user, token = user_and_token
        seed = routes_turns.TestDatasetFinderTools()._seed_dataset
        asked = seed(user, filename="building_footprints.csv")
        other = seed(user, filename="cook_buildings_2022.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [
            _create_tail(
                "import pandas as pd\n"
                f'dataset_path = curio_data_path("{other}")\n'
                "df = pd.read_csv(dataset_path)\nreturn df"
            ),
            "Which dataset should the node load?",
        ])
        body = _run(client, token, project, att, f"Build a data-loading node for the {asked} dataset.")
        assert _changes(body) == [] and _proposals(body) == []
        refusal = calls[1][-1]["content"]
        assert "refused" in refusal.split("\n", 1)[0]
        assert asked in refusal and other in refusal

    def test_the_named_dataset_is_proposed_even_beside_another(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """#411's guard: a node that loads the dataset the user named is
        proposed, here with a second catalog dataset read beside it."""
        user, token = user_and_token
        seed = routes_turns.TestDatasetFinderTools()._seed_dataset
        asked = seed(user, filename="building_footprints.csv")
        boundary = seed(user, filename="city_boundary.csv")
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, [
            _create_tail(
                "import pandas as pd\n"
                f'df = pd.read_csv(curio_data_path("{asked}"))\n'
                f'edge = pd.read_csv(curio_data_path("{boundary}"))\n'
                "return df"
            ),
            "Proposed.",
        ])
        body = _run(client, token, project, att, f"Build a data-loading node for {asked}.")
        proposal = _the_change(body)
        assert {ref["datasetId"] for ref in proposal["source"]["refs"]} == {asked, boundary}

    def _two_turns(self, client, token, project, monkeypatch, asked, loaded):
        """#867: the user names a dataset, the agent asks before building, and
        the user answers "go ahead"; the node is built in that second turn."""
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [
            "I can build a data-loading node for it. Shall I go ahead?",
            _create_tail(
                "import pandas as pd\n"
                f'dataset_path = curio_data_path("{loaded}")\n'
                "df = pd.read_csv(dataset_path)\nreturn df"
            ),
            "Done.",
        ])
        first = _run(client, token, project, att, f"Load the {asked} dataset into a node.")
        assert _changes(first) == [] and _proposals(first) == []
        return _run(client, token, project, att, "go ahead"), calls

    def test_go_ahead_keeps_the_dataset_named_in_the_turn_before(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """#867: "go ahead" names no dataset, so the one named in the turn
        before it is still the one asked for: loading another is refused."""
        user, token = user_and_token
        seed = routes_turns.TestDatasetFinderTools()._seed_dataset
        asked = seed(user, filename="building_footprints.csv")
        other = seed(user, filename="cook_buildings_2022.csv")
        body, calls = self._two_turns(client, token, project, monkeypatch, asked, other)
        assert _changes(body) == [] and _proposals(body) == []
        [refusal] = [t for t in _tool_results(calls[-1], "node.create") if "refused" in t.split("\n", 1)[0]]
        assert asked in refusal and other in refusal

    def test_go_ahead_proposes_the_dataset_named_in_the_turn_before(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """#867's guard: the dataset named in the turn before is proposed."""
        user, token = user_and_token
        seed = routes_turns.TestDatasetFinderTools()._seed_dataset
        asked = seed(user, filename="building_footprints.csv")
        seed(user, filename="cook_buildings_2022.csv")
        body, _calls = self._two_turns(client, token, project, monkeypatch, asked, asked)
        proposal = _the_change(body)
        assert [ref["datasetId"] for ref in proposal["source"]["refs"]] == [asked]


DDRNET = "model.curio.ddrnet23-slim"


def _models_tail(**params):
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": "models.search", "params": params}}) + "\n```"


def _model_rows(messages):
    """The models.search rows the model was shown."""
    text = _tool_results(messages, "models.search")[-1]
    assert text.startswith("[tool result] models.search: ok\n"), text[:200]
    return json.loads(text.split("\n", 1)[1].split("\nNo further")[0])["models"]


class TestModelGrounding:
    """models.search in a scripted run: the agents that write node code are
    shown the model packages the account holds, each with the line that loads
    it: DDRNet23-Slim, added as the examples' seeding adds it, and not Deep
    Umbra, which ships but was never added."""

    @pytest.fixture(autouse=True)
    def _ddrnet_added(self, user_and_token, tmp_curio):
        from pathlib import Path

        from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, _ = user_and_token
        packages = Path(__file__).resolve().parents[4] / "packages"
        install_package_from_directory(_user_dir_key(user), packages / f"{DDRNET}@1")

    def test_node_builder_searches_the_model_catalog(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_models_tail(q="street"), "ok"])
        _run(client, token, project, att, "build a node that segments street photos")
        [row] = _model_rows(calls[-1])
        assert row["id"] == DDRNET and row["origin"] == "shipped"
        assert row["loader"] == f'model = curio_load_model("{DDRNET}")'
        # The grant reaches the run: the tail's tool list offers it.
        assert "- models.search: " in calls[0][0]["content"]

    def test_the_node_builder_on_a_node_searches_the_model_catalog(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att, calls = routes_proposals.TestReviewProposals()._setup(
            client, token, alice_project, monkeypatch, replies=[_models_tail(), "ok"],
        )
        _run(client, token, alice_project, att, "segment the photos with a model")
        assert "- models.search: " in calls[0][0]["content"]
        rows = _model_rows(calls[-1])
        assert {row["id"] for row in rows} == {DDRNET}
        assert all(row["loader"] == f'model = curio_load_model("{row["id"]}")' for row in rows)


def _candidates_reply(external, catalog):
    payload = {"datasetCandidates": {"lanes": {"external": external, "catalog": catalog}}}
    return "Two lanes.\n```curio.v1\n" + json.dumps(payload) + "\n```"


class TestExternalDiscovery:
    """No catalog match → Node Builder delegates dataset.discover; the tool-less
    Dataset Finder child gets the catalog as INPUT; its candidates are
    runtime-minted onto the two-lane card (catalog rows tool-grounded,
    external rows probed); the user confirms before any node is proposed."""

    def _discover_run(self, client, user, token, project, monkeypatch, *, extra_replies=()):
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
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
        assert _changes(body) == [] and _proposals(body) == []
        # The child was handed the catalog and the ONE reply schema (#269).
        child_frame = calls[1][-1]["content"]
        assert '"catalog"' in child_frame and dataset_id in child_frame
        assert "datasetCandidates" in child_frame and "discoveryReplyContract" in child_frame
        # The parent learned the outcome and the two-turn rule.
        assert "shown to the user to choose from" in calls[2][-1]["content"]
        assert "1 catalog row(s) were dropped" in calls[2][-1]["content"]
        entry = next(p for p in body["content"] if p["type"] == "delegation")
        assert entry["status"] == "ok" and "select and confirm" in entry["summary"]

    def test_same_turn_create_after_candidates_is_refused(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, calls, body, _ = self._discover_run(
            client, user, token, project, monkeypatch,
            extra_replies=[_create_tail(f'import requests\nr = requests.get("{NOAA}", timeout=10)\nreturn r.json()')],
        )
        assert _changes(body) == [] and _proposals(body) == []
        assert "shown to the user to choose from: do not add a node in this turn" in calls[3][-1]["content"]

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
        proposal = _the_change(body)
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
        assert _changes(body) == [] and _proposals(body) == []
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
        assert _changes(body) == [] and _proposals(body) == []
        assert "answered 404" in calls[1][-1]["content"]

    def test_a_guessed_local_filename_never_passes_even_with_external_context(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, _, _, _ = self._discover_run(client, user, token, project, monkeypatch)
        calls = _script(monkeypatch, [_create_tail('df = pd.read_csv("noaa_climate.csv")\nreturn df'), "hm"])
        body = _run(client, token, project, att, "Build the data-loading node from NOAA Climate Data API")
        assert _changes(body) == [] and _proposals(body) == []
        assert "'noaa_climate.csv' (line 1)" in calls[1][-1]["content"]

    def test_credential_gated_endpoint_is_grounded_with_the_requirement(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {NOAA: {"status": "unreachable", "httpStatus": 401, "detail": "the endpoint answered 401"}})
        _script(monkeypatch, [_create_tail(f'import requests\nreturn requests.get("{NOAA}").json()'), "Proposed."])
        proposal = _the_change(_run(client, token, project, att))
        assert proposal["source"]["refs"][0]["requirement"] == "credential-gated"
        assert "credential-gated" in proposal["source"]["label"]


class TestTheRuntimesListingGroundsTheCard:
    """A delegated Dataset Finder's catalog rows are checked against the Data
    Catalog the runtime lists, never against rows the parent model wrote into
    its request, and against the whole catalog: the child is shown its first
    rows, told how many it was not shown, and a dataset past them is still one
    the catalog holds. A selection reads the whole listing too."""

    @staticmethod
    def _seed(user, *names):
        return [
            routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename=f"{name}.csv")
            for name in names
        ]

    @staticmethod
    def _listed(client, user, project):
        from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
        from utk_curio.backend.tests._support.agent_routes import db_user

        with client.application.app_context():
            return DatasetCatalogService(db_user(client, user)).list_catalog(dataflow_id=project)["items"]

    def test_the_parents_rows_neither_reach_the_child_nor_ground_its_card(
        self, client, user_and_token, tmp_curio, project, monkeypatch
    ):
        user, token = user_and_token
        (dataset_id,) = self._seed(user, "heat")
        _install(client, token, project, NB, DF)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {})
        ghost = "imported.ghost@1"
        child = _candidates_reply(external=[], catalog=[
            {"name": "Ghost heat", "sourceType": "catalog", "datasetId": ghost, "installed": True},
            {"name": "Heat", "sourceType": "catalog", "datasetId": dataset_id},
        ])
        calls = _script(monkeypatch, [
            _delegate_tail("dataset.discover", {
                "intent": "tract-level heat data",
                "catalog": {"note": "The Data Catalog", "rows": [
                    {"id": ghost, "name": "Ghost heat", "installed": True},
                ]},
            }),
            child,
            "Please select the source you want and confirm.",
        ])
        body = _run(client, token, project, att, "build a node that loads tract-level heat data")
        part = next(p for p in body["content"] if p["type"] == "datasetCandidates")
        assert [(r["datasetId"], r["installed"]) for r in part["lanes"]["catalog"]] == [(dataset_id, False)]
        child_frame = calls[1][-1]["content"]
        assert dataset_id in child_frame and ghost not in child_frame

    def test_a_dataset_past_the_rows_the_child_was_shown_stays_on_the_card(
        self, client, user_and_token, tmp_curio, project, monkeypatch
    ):
        from utk_curio.backend.app.agents.application import tools

        user, token = user_and_token
        seeded = self._seed(user, "older", "newer")
        monkeypatch.setattr(tools, "_CATALOG_SEARCH_MAX_ROWS", 1)
        _install(client, token, project, NB, DF)
        att = _attach(client, token, project, NB)
        _fake_probe(monkeypatch, {NOAA: {"status": "verified", "httpStatus": 200, "checkedAt": "now"}})
        hidden: list = []

        def child(calls):
            frame = calls[-1][-1]["content"]
            hidden.append(next(i for i in seeded if i not in frame))
            return _candidates_reply(
                external=[{"name": "NOAA Climate Data API", "sourceType": "api", "url": NOAA}],
                catalog=[{"name": "Heat", "sourceType": "catalog", "datasetId": hidden[0]}],
            )

        _script(monkeypatch, [
            _delegate_tail("dataset.discover", {"intent": "tract-level heat data"}),
            child,
            "Please select the source you want and confirm.",
        ])
        body = _run(client, token, project, att, "build a node that loads tract-level heat data")
        part = next(p for p in body["content"] if p["type"] == "datasetCandidates")
        assert [r["datasetId"] for r in part["lanes"]["catalog"]] == hidden

    def test_the_child_is_told_how_many_catalog_rows_it_was_not_shown(
        self, client, user_and_token, tmp_curio, project, monkeypatch
    ):
        from utk_curio.backend.app.agents.application import tools

        user, token = user_and_token
        self._seed(user, "older", "newer")
        monkeypatch.setattr(tools, "_CATALOG_SEARCH_MAX_ROWS", 1)
        _install(client, token, project, NB, DF)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [
            _delegate_tail("dataset.discover", {"intent": "tract-level heat data"}),
            "I found nothing.",
            "Nothing was found.",
        ])
        _run(client, token, project, att, "build a node that loads tract-level heat data")
        framed = json.loads(calls[1][-1]["content"].split("\n", 1)[1])
        assert len(framed["catalog"]["rows"]) == 1
        assert framed["catalog"].get("rowsElided") == len(self._listed(client, user, project)) - 1

    def test_a_dataset_past_the_first_rows_can_be_confirmed(
        self, client, user_and_token, tmp_curio, project, monkeypatch
    ):
        from utk_curio.backend.app.agents.application import tools

        user, token = user_and_token
        seeded = self._seed(user, "older", "newer")
        monkeypatch.setattr(tools, "_CATALOG_SEARCH_MAX_ROWS", 1)
        first = self._listed(client, user, project)[0]["id"]
        hidden = next(i for i in seeded if i != first)
        _install(client, token, project, DF)
        finder = _attach(client, token, project, DF, target={"kind": "node", "targetId": "n1"})
        r = client.post(
            f"/api/agents/projects/{project}/attachments/{finder}/dataset-selection",
            json={"picks": [{"lane": "catalog", "key": hidden}]}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_json()
        assert [pick["datasetId"] for pick in r.get_json()["picks"]] == [hidden]


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
        assert _changes(body) == [] and _proposals(body) == []
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
        proposal = _the_change(_run(client, token, project, att, "generate synthetic sample data for 5 tracts"))
        assert proposal["source"]["kind"] == "synthetic"
        assert "no external source" in proposal["source"]["label"]

    def test_inline_data_without_the_request_is_fabrication(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_create_tail(self.INLINE, synthetic=True), "hm"])
        body = _run(client, token, project, att, "load the IBGE demographic data for the tracts")
        assert _changes(body) == [] and _proposals(body) == []
        assert "no grounded source" in calls[1][-1]["content"]

    def test_computation_nodes_are_untouched(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, [_create_tail("df = input_0[0]\nreturn df.describe()", node_type=CA), "Proposed."])
        proposal = _the_change(_run(client, token, project, att, "summarize the upstream frame"))
        assert "source" not in proposal


class TestValuesACallMakesUp:
    """Step 45: a node that loads a Data Catalog dataset and makes a column up
    with random numbers is refused, the call named, unless the user asked for
    synthetic data; then it lands, its card naming the call beside the
    dataset."""

    def _create(self, client, token, project, monkeypatch, message, replies):
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, replies)
        return _run(client, token, project, att, message), calls

    def _loaders(self, user):
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="tracts.csv")
        loads = f'df = curio_load_data("{dataset_id}")'
        return loads + "\nreturn df", loads + '\ndf["population"] = np.random.randint(1000, 50000, len(df))\nreturn df'

    def test_a_random_column_beside_a_catalog_dataset_is_refused_by_name(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        loads, made_up = self._loaders(user)
        body, calls = self._create(
            client, token, project, monkeypatch, "Load the tracts with their population.",
            [_create_tail(made_up), _create_tail(loads), "Proposed."],
        )
        refusals = [t for t in _tool_results(calls[-1], "node.create") if "refused" in t.split("\n", 1)[0]]
        assert len(refusals) == 1, _tool_results(calls[-1], "node.create")
        assert "np.random.randint (line 2)" in refusals[0], refusals[0]
        assert "DataFrame.sample" in refusals[0] and "synthetic" in refusals[0], refusals[0]
        change = _the_change(body)
        assert change["source"]["kind"] == "catalog" and "np.random" not in change["preview"], change["source"]

    def test_a_synthetic_column_the_user_asked_for_lands_labeled(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        _loads, made_up = self._loaders(user)
        body, _calls = self._create(
            client, token, project, monkeypatch, "Load the tracts and add a synthetic population column to test with.",
            [_create_tail(made_up), "Proposed."],
        )
        change = _the_change(body)
        assert change["source"]["kind"] == "mixed", change["source"]
        assert change["source"]["refs"][-1] == {"kind": "synthetic", "value": "np.random.randint"}, change["source"]
        assert change["source"]["refs"][0]["kind"] == "catalog"


#: The shipped example whose chart step 39's live runs asked for two more bars.
VEGA = Path(__file__).resolve().parents[4] / "docs" / "examples" / "dataflows" / "vega.json"
#: Its two kinds of node: the module's Data Loading, and its Vega-Lite chart.
VEGA_TEMPLATES = [*TEMPLATES, {
    "id": "vis-vega", "label": "Vega-Lite", "category": "vis_grammar", "engine": "python",
    "editor": "grammar", "grammarId": "vega-lite", "hasCode": False, "hasGrammar": True,
    "behavior": "vega", "description": "Draw a Vega-Lite chart.",
    "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
    "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}],
}]


class TestValuesTheUserTyped:
    """Step 39's live runs (10-30): on vega.json, asked "Add two more bars to
    this chart: J with 60 and K with 33.", the Node Builder wrote the two rows
    into the Data Loading node, and the gate refused them as made-up data in
    all 6 runs, so the agent made a new node instead. The rows the user typed
    land in the node, beside its own; a value the user did not type is still
    refused, and named, whether the agent writes it or a delegate does."""

    MESSAGE = "Add two more bars to this chart: J with 60 and K with 33."
    LOADER = "8d428948-f5e4-485b-9812-51a4212678a7"

    @pytest.fixture()
    def bars(self, client, user_and_token):
        """A dataflow holding vega.json as it ships, and its loader's content."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=VEGA_TEMPLATES)
        spec = json.loads(VEGA.read_text(encoding="utf-8"))
        resp = client.post("/api/projects", json={"name": "vega", "spec": spec, "outputs": []}, headers=_auth(token))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        loader = next(n for n in spec["dataflow"]["nodes"] if n["id"] == self.LOADER)
        return resp.get_json()["id"], loader["content"]

    def _held(self, user, project) -> str:
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), project)
        return next(n for n in spec["dataflow"]["nodes"] if n["id"] == self.LOADER)["content"]

    def _write(self, client, token, project, monkeypatch, content):
        """The loader's Node Builder, asked MESSAGE, writes *content* into it."""
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": self.LOADER})
        write = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": self.LOADER, "content": content}}}
        calls = _script(monkeypatch, ["```curio.v1\n" + json.dumps(write) + "\n```", "Done."])
        return _run(client, token, project, att, self.MESSAGE), calls

    def test_the_rows_the_user_typed_land_in_the_loading_node(self, client, user_and_token, tmp_curio, bars, monkeypatch):
        user, token = user_and_token
        project, loader = bars
        rows = loader.replace('"I"]', '"I", "J", "K"]').replace("52]", "52, 60, 33]")
        body, _calls = self._write(client, token, project, monkeypatch, rows)
        change = _the_change(body)
        assert change["source"]["kind"] == "user-values"
        assert change["source"]["refs"] == [{"kind": "user-values", "value": "'J', 'K', 60, 33"}]
        held = self._held(user, project)
        assert '"I", "J", "K"]' in held and "52, 60, 33]" in held, held

    def test_a_row_the_user_did_not_type_is_refused_and_named(self, client, user_and_token, tmp_curio, bars, monkeypatch):
        user, token = user_and_token
        project, loader = bars
        rows = loader.replace('"I"]', '"I", "J", "K", "L"]').replace("52]", "52, 60, 33, 99]")
        body, calls = self._write(client, token, project, monkeypatch, rows)
        assert _changes(body) == [] and _proposals(body) == []
        [refusal] = [t for t in _tool_results(calls[-1], "node.content.write") if "refused" in t.split("\n", 1)[0]]
        assert "'L' (line 3)" in refusal and "99 (line 3)" in refusal, refusal
        assert "'J' (line" not in refusal and "60 (line" not in refusal, refusal
        held = self._held(user, project)
        assert '"I"]' in held and "52]" in held, held  # the node kept its own rows, and only them

    def test_a_delegates_intent_is_not_the_users_message(self, client, user_and_token, tmp_curio, bars, monkeypatch):
        """The intent the agent hands its content delegate is the agent's own
        words: a row only the intent names is a value the user did not type."""
        user, token = user_and_token
        project, loader = bars
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": self.LOADER})
        intent = "add J with 60 and L with 99 to the rows"
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": self.LOADER, "intent": intent}),
            loader.replace('"I"]', '"I", "J", "L"]').replace("52]", "52, 60, 99]"),
            "The rows could not be written.",
        ])
        body = _run(client, token, project, att, self.MESSAGE)
        assert _changes(body) == [] and _proposals(body) == []
        result = calls[2][-1]["content"]
        assert "could not be written into the node" in result, result
        assert "'L' (line 3)" in result and "99 (line 3)" in result, result
        assert "'J' (line" not in result and "60 (line" not in result, result
        # The delegate was told it may add the values the user typed.
        assert "may be added inline to the values the node holds" in calls[1][-1]["content"]
        held = self._held(user, project)
        assert '"I"]' in held and "52]" in held, held

    def test_a_random_column_beside_the_rows_the_user_typed_is_refused(
        self, client, user_and_token, tmp_curio, bars, monkeypatch,
    ):
        """Step 45: the gate read only literals, so a column of random numbers
        written beside the bar the user typed landed as user-provided values.
        The call is refused by name, and the column the user asked for,
        computed from the bars, lands instead."""
        user, token = user_and_token
        project, loader = bars
        message = "Add a bar J with 60, and a column c with each bar's share of the total."
        bar = loader.replace('"I"]', '"I", "J"]').replace("52]", "52, 60]")
        random_c = bar.replace("df = pd.DataFrame(data=d)", "df = pd.DataFrame(data=d)\r\ndf['c'] = np.random.rand(len(df))")
        share_c = bar.replace("df = pd.DataFrame(data=d)", "df = pd.DataFrame(data=d)\r\ndf['c'] = df['b'] / df['b'].sum()")

        def _write(content):
            write = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": self.LOADER, "content": content}}}
            return "```curio.v1\n" + json.dumps(write) + "\n```"

        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": self.LOADER})
        calls = _script(monkeypatch, [_write(random_c), _write(share_c), "Done."])
        body = _run(client, token, project, att, message)
        refusals = [t for t in _tool_results(calls[-1], "node.content.write") if "refused" in t.split("\n", 1)[0]]
        assert len(refusals) == 1, _tool_results(calls[-1], "node.content.write")
        assert "np.random.rand (line 5)" in refusals[0], refusals[0]
        assert "'J' (line" not in refusals[0] and "60 (line" not in refusals[0], refusals[0]
        change = _the_change(body)
        assert change["source"]["refs"] == [{"kind": "user-values", "value": "'J', 60, 'c'"}], change["source"]
        held = self._held(user, project)
        assert "np.random" not in held and "df['b'].sum()" in held and '"I", "J"]' in held, held


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
        _install(client, token, project, "agent.curio.dataflow-builder@1", NB)
        att = _attach(client, token, project, "agent.curio.dataflow-builder@1")

        def _reply(calls):
            frame = calls[-1][-1]["content"]
            if "[delegated task" not in frame:
                return self._plan_tail()
            return child_reply(frame)

        calls = _script(monkeypatch, [_reply])
        body = _run(client, token, project, att, "plan the heat analysis")
        return att, _landed_plan(body), calls

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

        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat_tracts.csv")

        def child(frame):
            if f'"nodeType": "{DL}"' in frame:
                return 'import pandas as pd\ndf = pd.read_csv("heat_tracts.csv")\nreturn df'
            return "df = input_0[0]\nreturn df.describe()"

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
        assert body["results"][load]["status"] == "failed"
        # dev/118 live fix: the computation sibling WAITS for the refused
        # loader (pending, reason named) instead of running against an empty
        # upstream — and NOTHING of the fabricated code reached the sandbox.
        assert body["results"][stats]["status"] == "pending"
        assert body["results"][stats]["reason"].startswith("upstream node")
        assert exec_payloads == []
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
        assert nodes[stats]["content"] == ""  # it waited
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
        assert len(exec_payloads) == 1 and exec_payloads[-1]["nodeType"] == DL  # the retried loader alone
        assert path in exec_payloads[-1]["code"]
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        assert path in next(n for n in spec["dataflow"]["nodes"] if n["id"] == load)["content"]


class TestSolveRequestedDatasets:
    """#867: a Solve with ``verify: false`` writes content without running it,
    and holds it to the dataset the node's goal names, as a verified Solve does."""

    def _applied_plan(self, client, user, token, project, monkeypatch, *, load_the_asked=False):
        seed = routes_turns.TestDatasetFinderTools()._seed_dataset
        asked = seed(user, filename="building_footprints.csv")
        other = seed(user, filename="cook_buildings_2022.csv")
        plan = {
            "goal": "building footprints",
            "nodes": [{"ref": "load", "nodeType": DL, "title": "Load",
                       "intent": f"load the {asked} dataset"}],
            "edges": [],
        }
        plan_tail = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"
        loader = (
            "import pandas as pd\n"
            f'dataset_path = curio_data_path("{asked if load_the_asked else other}")\n'
            "df = pd.read_csv(dataset_path)\nreturn df"
        )
        _install(client, token, project, "agent.curio.dataflow-builder@1", NB)
        att = _attach(client, token, project, "agent.curio.dataflow-builder@1")
        _script(monkeypatch, [
            lambda calls: loader if "[delegated task" in calls[-1][-1]["content"] else plan_tail,
        ])
        applied = _landed_plan(_run(client, token, project, att, "plan the footprints"))
        load = next(n["id"] for n in applied["appliedGraph"]["nodes"] if str(n.get("type", "")).startswith(DL))
        return att, load, asked, other

    def _content(self, user, project, node_id):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        spec = projects_storage.read_spec(_user_dir_key(user), project)
        return next(n for n in spec["dataflow"]["nodes"] if n["id"] == node_id)["content"]

    def test_an_unverified_solve_refuses_a_dataset_the_goal_does_not_name(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, load, asked, other = self._applied_plan(client, user, token, project, monkeypatch)
        body = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve",
            json={"verify": False}, headers=_auth(token),
        ).get_json()
        result = body["results"][load]
        assert result["status"] == "failed", result
        assert asked in result["error"] and other in result["error"]
        assert self._content(user, project, load) == ""

    def test_an_unverified_streamed_solve_refuses_it_too(self, client, user_and_token, tmp_curio, project, monkeypatch):
        user, token = user_and_token
        att, load, asked, other = self._applied_plan(client, user, token, project, monkeypatch)
        r = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve/stream",
            json={"verify": False}, headers=_auth(token),
        )
        events = routes_solve.TestStreamedSolve()._sse_events(r)
        results = [p for k, p in events if k == "node_result" and p.get("nodeId") == load]
        assert results and all(p["status"] == "failed" for p in results), results
        assert asked in results[-1]["error"] and other in results[-1]["error"]
        assert self._content(user, project, load) == ""

    def test_an_unverified_streamed_solve_writes_the_requested_dataset(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """#880: an unverified Solve's checks run with the batch's catalog
        listing, so the requested catalog dataset is accepted and written, not
        refused as not in the project's Data Catalog."""
        user, token = user_and_token
        att, load, asked, _other = self._applied_plan(client, user, token, project, monkeypatch, load_the_asked=True)
        r = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve/stream",
            json={"verify": False}, headers=_auth(token),
        )
        events = routes_solve.TestStreamedSolve()._sse_events(r)
        result = next(p for k, p in events if k == "node_result" and p.get("nodeId") == load)
        assert result["status"] == "solved", result
        assert asked in self._content(user, project, load)


class TestContentReviewMintInheritsTheGate:
    def test_delegated_generation_with_a_fabricated_path_mints_no_review(self, client, user_and_token, tmp_curio, project, monkeypatch):
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "n1"})
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "n1", "intent": "load the demographics"}),
            'import pandas as pd\ndf = pd.read_csv("bras_ibge_data.csv")\nreturn df',
            "The generated content could not be grounded; which file should it load?",
        ])
        body = _run(client, token, project, att, "fill this node")
        assert _changes(body) == [] and _proposals(body) == []
        result = calls[2][-1]["content"]
        assert "could not be written into the node" in result
        assert "bras_ibge_data.csv" in result
        entry = next(p for p in body["content"] if p["type"] == "delegation")
        assert entry["status"] == "ok"  # the child ran; the mint refused honestly
        # The child received the grounding inputs for a data-loading node.
        assert '"sourceGrounding"' in calls[1][-1]["content"]

    def test_a_path_only_the_delegates_intent_names_is_not_the_users(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """The task the runtime records in the delegate's chat holds the
        delegating agent's words: a path only its intent names was read there
        as one the user typed, and the content reading it landed."""
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "n1"})
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "n1", "intent": "load data/tracts.geojson"}),
            'import geopandas as gpd\ngdf = gpd.read_file("data/tracts.geojson")\nreturn gdf',
            "The file could not be loaded.",
        ])
        body = _run(client, token, project, att, "fill this node")
        assert _changes(body) == [] and _proposals(body) == []
        result = calls[2][-1]["content"]
        assert "could not be written into the node" in result, result
        assert "'data/tracts.geojson' (line 2)" in result, result

    def test_a_delegate_is_handed_only_the_paths_the_user_typed(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """The paths a content delegate is handed are the ones its write's gate
        accepts: the user's, never one only the delegating agent's intent names."""
        _, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "n1"})
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "n1", "intent": "load data/tracts.geojson"}),
            "No source is grounded for this node.",
            "Which file should it load?",
        ])
        _run(client, token, project, att, "fill this node from my file data/blocks.geojson")
        frame = calls[1][-1]["content"]
        handed, _end = json.JSONDecoder().raw_decode(frame[frame.index("\n{") + 1:])
        assert handed["sourceGrounding"]["userPaths"] == ["data/blocks.geojson"], handed["sourceGrounding"]

    def test_the_delegated_write_reads_the_chat_that_asked(self, client, user_and_token, tmp_curio, project, monkeypatch):
        """A canvas chat's Node Builder hands a node's content to the node's own
        agent, whose chat the change lands in. The gate reads the user's words
        in the chat that asked, where the user named the file a turn before,
        not the node's chat, which holds only the delegated task."""
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        _script(monkeypatch, ["Noted: I will load it when you ask."])
        _run(client, token, project, att, "my tracts are in data/tracts.geojson")
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "n1", "intent": "load the user's tracts file"}),
            'import geopandas as gpd\ngdf = gpd.read_file("data/tracts.geojson")\nreturn gdf',
            "Done.",
        ])
        _run(client, token, project, att, "fill the loader node with them")
        assert "the generated content is in node 'n1'" in calls[2][-1]["content"], calls[2][-1]["content"]
        spec = projects_storage.read_spec(_user_dir_key(user), project)
        loader = next(n for n in spec["dataflow"]["nodes"] if n["id"] == "n1")
        assert 'gpd.read_file("data/tracts.geojson")' in loader["content"], loader["content"]


class TestContentForANewNode:
    """A Node Builder attached to a node that delegates the content of a new
    node names its nodeType: the content mode is grounded as that template,
    never as the node the agent is attached to, whose context it is not given."""

    def _delegate_for_a_new_node(self, client, token, pid, monkeypatch, node_type):
        _install(client, token, pid, NB)
        att = _attach(client, token, pid, NB, target={"kind": "node", "targetId": "n1"})
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"intent": "a new node below n1", "nodeType": node_type}),
            "return input_0.mean()",
            "Here is the content for the new node.",
        ])
        body = _run(client, token, pid, att, "add a node below this one")
        return body, calls[1][-1]["content"]

    def test_a_loaders_builder_writing_an_analysis_is_not_handed_the_loaders_sources(
        self, client, user_and_token, tmp_curio, project, monkeypatch
    ):
        _, token = user_and_token
        body, task = self._delegate_for_a_new_node(client, token, project, monkeypatch, CA)
        assert task.startswith("[delegated task")
        assert '"sourceGrounding"' not in task
        assert '"nodeContext"' not in task
        assert _changes(body) == [] and _proposals(body) == []  # the loader's own content is offered no change

    def test_an_analysis_builder_writing_a_loader_is_handed_its_sources(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        from utk_curio.backend.app.projects.services import _user_dir_key

        routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
        resp = client.post("/api/projects", json={
            "name": "p",
            "spec": {"dataflow": {"nodes": [
                {"id": "n1", "type": CA, "goal": "average the readings", "content": "return input_0.mean()",
                 "x": 10, "y": 20},
            ], "edges": [], "packages": []}},
            "outputs": [],
        }, headers=_auth(token))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        _, task = self._delegate_for_a_new_node(client, token, resp.get_json()["id"], monkeypatch, DL)
        assert '"sourceGrounding"' in task
        assert '"nodeContext"' not in task


class TestCandidatesMint:
    """The runtime mint over a tool-less Dataset Finder child's reply."""

    def test_schema_recognition_bare_fenced_and_chat_json(self):
        from utk_curio.backend.app.agents.application.turns import delegates as s

        block = {"datasetCandidates": {"lanes": {"external": [], "catalog": []}}}
        assert s._extract_candidates_reply(json.dumps(block)) == block["datasetCandidates"]
        assert s._extract_candidates_reply("Here.\n```curio.v1\n" + json.dumps(block) + "\n```") == block["datasetCandidates"]
        assert s._extract_candidates_reply("```json\n" + json.dumps(block) + "\n```") == block["datasetCandidates"]
        assert s._extract_candidates_reply(json.dumps({"answer": "x", "lanes": {}})) is None
        assert s._extract_candidates_reply("no json here") is None

    def test_mint_drops_unknown_catalog_rows_and_verifies_external(self, monkeypatch):
        from utk_curio.backend.app.agents.application.turns import delegates as s

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
        from utk_curio.backend.app.agents.application.turns import delegates as s

        part, text, outcome = s._mint_candidates_from_delegate(
            {}, _candidates_reply(external=[], catalog=[{"name": "Fake", "sourceType": "catalog", "datasetId": "ds-9"}]),
            [],
        )
        assert part is None and outcome == "no-candidates"
        assert "1 catalog row(s) dropped" in text and "ask the user for a path or URL" in text
        part, text, outcome = s._mint_candidates_from_delegate({}, "Sure! Here are some ideas.", [])
        assert part is None and outcome == "no-candidates" and "do not invent" in text
