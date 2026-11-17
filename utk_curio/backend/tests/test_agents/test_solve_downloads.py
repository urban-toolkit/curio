"""What an agent's Solve downloads on first use, and what it says while it does.

On a pip install, a shipped dataset whose data file the pip package leaves out
is downloaded the first time a run reads it
(``datasets/infrastructure/left_out_files.py``), and a model whose package's
``fetch`` names its weights downloads them the first time a node runs it
(``packages/infrastructure/fetched_weights.py``). A Solve runs its nodes
through the dataflow on the server (``execution/runner.py``), so its runs
download what they read too.

- A Solve's start downloads no dataset its nodes never read: a dataset's path
  is resolved when a round's code reads it (``grounding._session_dataset_paths``).
  A round reads the slice it runs, the node and the nodes it reads from, so
  neither a Solve nor a Run node from chat downloads what only another
  branch of the dataflow reads.
- A download that fails is asked for once in a Solve's run, and the node that
  reads it says why once: a correction of its code cannot change that. A
  model's weights are kept so too, so another node of a plan that loads the
  model does not download them again.
- Once a file whose download failed is saved by hand, where the failure says
  to save it, the running Solve reads it: a plan's Solve attempts the node
  again, a dataset's file or a model's weights alike.
- While a node's dataset or weights download, the Solve and a Run node from
  chat say how far they have come (``node_download``, with no message once
  they are over), as a run on the server says it (``step_progress``).

No test opens a socket: ``FakeGitHub`` and ``FakeHuggingFace`` stand in for
the hosts (``tests/_support``). Every test imports what it tests inside itself,
so a checkout without it fails test by test.
"""
from __future__ import annotations

#: A shipped dataset whose data file the pip package leaves out.
MRT = "datasets/data.utk.milan-mrt@1/data/milan-mrt.tif"
MRT_ID = "data.utk.milan-mrt"


def _as_a_pip_install(tmp_path, monkeypatch, github):
    """The Data Catalog as a pip install has it: the Milan MRT dataset's
    folder without its data file, which the release's record names, and
    *github* serving that file."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.tests._support.left_out_files import catalog_copy, write_record

    site_packages = tmp_path / "site-packages"
    catalog_copy("datasets/data.utk.milan-mrt@1", site_packages)
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(site_packages / "datasets"))
    monkeypatch.setattr(left_out_files, "RECORD_PATH", write_record(tmp_path / "record.json", [MRT]))
    assert not (site_packages / MRT).exists()
    return github.serve(monkeypatch)


def _loading(line: str = "") -> str:
    """A loader of the Milan MRT dataset, *line* telling one attempt from another."""
    return f'data = curio_load_data("{MRT_ID}")\n{line}return data'


# ---------------------------------------------------------------------------
# A Solve's start
# ---------------------------------------------------------------------------

def test_a_nodes_solve_downloads_no_dataset_its_node_never_reads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The node reads a dataset of the account's own. The Data Catalog also
    lists a shipped dataset whose file a pip install leaves out, which the
    node never reads: its Solve downloads nothing of it."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub())
    solve = verified_rounds.TestSolveNode()
    ctx = solve._setup(client, user, token, monkeypatch, content=solve.LOADER)

    events = solve._solve_node(client, token, ctx)

    assert github.urls == [], f"the node's Solve downloaded what its node never reads: {github.urls}"
    done = events[-1][1]
    assert done["verdict"] == "pass", done
    assert ctx["payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat.csv"), ctx["payloads"][0]


def test_a_plans_solve_downloads_no_dataset_its_nodes_never_read(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """A plan's Solve, whose loader reads a dataset of the account's own,
    downloads nothing of the shipped dataset its nodes never read."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub())
    solve = verified_rounds.TestVerifiedSolve()
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[solve.LOADER], with_stats=False)
    landed = list(github.urls)

    body = solve._solve(client, token, ctx)

    assert github.urls == landed, (
        f"the plan's Solve downloaded what its nodes never read: {github.urls[len(landed):]}"
    )
    assert body["results"][ctx["load"]]["status"] == "solved", body["results"]
    assert ctx["exec_payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat_tracts.csv")


def test_a_dataset_a_solves_node_reads_is_downloaded_when_its_round_reads_it(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The loader reads the shipped dataset itself: its first round
    downloads the file, once, and runs with its path."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub())
    solve = verified_rounds.TestSolveNode()
    ctx = solve._setup(client, user, token, monkeypatch, content=_loading())

    events = solve._solve_node(client, token, ctx)

    assert events[-1][1]["verdict"] == "pass", events[-1]
    assert github.urls == [url_of(MRT)], github.urls
    path = ctx["payloads"][0]["dataset_paths"][MRT_ID]
    assert path.endswith("milan-mrt.tif"), ctx["payloads"][0]


# ---------------------------------------------------------------------------
# A download that fails
# ---------------------------------------------------------------------------

def test_a_dataset_whose_download_fails_is_asked_for_once_in_a_solve_and_its_node_says_why_once(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The plan's loader reads the shipped dataset, whose download fails.
    Its first round fails with the download's reason. A correction of the
    code cannot change that, so no later round asks GitHub again, and the
    node says why in one attempt, never asking the sandbox."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    # Three attempts at most, so a node whose rounds kept trying shows it at once.
    monkeypatch.setenv("CURIO_SOLVE_MAX_ATTEMPTS", "3")
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(fail=OSError("Network is unreachable")))
    solve = verified_rounds.TestVerifiedSolve()
    ctx = solve._setup(
        client, user, token, monkeypatch, with_stats=False,
        dl_replies=[_loading(), _loading("data = data\n"), _loading("print(type(data))\n")],
    )

    body = solve._solve(client, token, ctx)

    assert github.urls == [url_of(MRT)], f"the Solve asked for the dataset {len(github.urls)} times: {github.urls}"
    load = body["results"][ctx["load"]]
    assert load["status"] == "failed", load
    attempts = load.get("attempts") or []
    assert len(attempts) == 1, f"the node said why in {len(attempts)} attempts: {attempts}"
    for words in (MRT, "Network is unreachable"):
        assert words in (attempts[0].get("stderrTail") or ""), attempts[0]
    assert ctx["exec_payloads"] == [], "the sandbox was asked to run a loader whose dataset could not be had"


def test_a_solves_lookups_keep_a_failed_download_for_its_run(
    app, tmp_curio, user_and_token, alice_project, tmp_path, monkeypatch,
):
    """Each round of a Solve looks up the datasets its code reads. A
    download that failed in the Solve's run is not asked for again: each
    later lookup gives the first one's reason."""
    from utk_curio.backend.app.agents.application.turns import grounding
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of

    user, _token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(fail=OSError("Network is unreachable")))
    mapping: dict = {}
    failed: dict = {}
    told = []
    # The job's thread: no request, the acting user held.
    for _round in range(3):
        unavailable: dict = {}
        paths = grounding._session_dataset_paths(
            alice_project, user, mapping, [_loading()], {}, unavailable, failed=failed,
        )
        told.append(unavailable.get(MRT_ID, ""))

    assert github.urls == [url_of(MRT)], github.urls
    assert paths == {} and mapping == {}, (paths, mapping)
    assert all(MRT in reason and "Network is unreachable" in reason for reason in told), told


# ---------------------------------------------------------------------------
# What a Solve says while a node's weights download
# ---------------------------------------------------------------------------

def test_a_nodes_solve_says_how_far_its_weights_have_come_while_they_download(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """The node loads a model whose package's ``fetch`` names its weights.
    Its Solve's first round downloads them before the node runs, and the
    Solve's stream says how far they have come, then that they are over."""
    from utk_curio.backend.tests._support.fetched_weights import FakeHuggingFace
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_model_catalog import test_fetched_weights as weights

    user, token = user_and_token
    catalog = tmp_curio / "catalog"
    weights._write_package(catalog / weights.DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    FakeHuggingFace(
        weights.REPOSITORY, weights.REVISION, weights.FILES, redirect=("model.safetensors",), chunk_size=16,
    ).serve(monkeypatch)
    solve = verified_rounds.TestSolveNode()
    ctx = solve._setup(
        client, user, token, monkeypatch, node_type=verified_rounds.CA,
        content=f'model = curio_load_model("{weights.PACKAGE_ID}")\nreturn 1',
    )
    weights._add(weights._key(user), catalog)

    events = solve._solve_node(client, token, ctx)

    names = [name for name, _payload in events]
    said = [payload for name, payload in events if name == "node_download"]
    assert said, f"the Solve said nothing while the node's weights downloaded: {names}"
    first, last = names.index("node_download"), len(names) - 1 - names[::-1].index("node_download")
    assert names.index("node_executed") < first and last < names.index("round_verdict"), names
    assert {payload["nodeId"] for payload in said} == {"n1"}, said
    weights_said = [payload for payload in said if "model.safetensors" in payload["message"]]
    assert (weights_said[0]["done"], weights_said[-1]["done"], weights_said[-1]["total"]) == (
        0, len(weights.WEIGHTS), len(weights.WEIGHTS),
    ), weights_said
    assert "100%" in weights_said[-1]["message"], weights_said[-1]
    # The downloads over, the node runs.
    assert said[-1]["message"] == "", said[-1]
    assert events[-1][1]["verdict"] == "pass", events[-1]
    assert len(ctx["payloads"]) == 1, "the node did not run once its weights were here"


# ---------------------------------------------------------------------------
# What a round reads: the slice it runs
# ---------------------------------------------------------------------------

DL = "curio.builtin/data-loading"
CA = "curio.builtin/python-computation"
#: A loader of the account's own dataset, ``{DATASET}``, which the setups seed.
LOADER = 'import pandas as pd\ndataset_path = curio_data_path("{DATASET}")\ndf = pd.read_csv(dataset_path)\nreturn df'
#: The bytes of each file the tests' fake hosts send at a time, so a download
#: says how far it has come several times.
CHUNK = 1 << 20


def _the_loader() -> dict:
    """The node a test solves or runs: a loader of the account's own dataset."""
    return {"id": "n1", "type": DL, "goal": "load the heat data", "content": LOADER, "x": 0, "y": 0}


def _another_branch(content: str) -> dict:
    """A node of another branch of the dataflow, wired to nothing, whose code is *content*."""
    return {"id": "n2", "type": CA, "goal": "read what the other branch reads", "content": content, "x": 400, "y": 0}


def _dataflow_of(client, user, token, monkeypatch, nodes: list) -> dict:
    """A dataflow of *nodes*, wired to nothing, with the Node Builder attached
    to the first, as ``TestSolveNode._setup`` makes a dataflow of one node:
    its replies scripted, the sandbox a fake, and ``{DATASET}`` in a node's
    content the account's own dataset."""
    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.tests._support.agent_routes import _auth
    from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
    from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    ukey = _user_dir_key(user)
    routes_proposals.TestNodeCreate()._write_builtin_package(ukey, templates=verified_rounds.TEMPLATES)
    dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
    placed = [{**node, "content": node["content"].replace("{DATASET}", dataset_id)} for node in nodes]
    body = {"name": "p", "spec": {"dataflow": {"nodes": placed, "edges": [], "packages": []}}, "outputs": []}
    pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
    builder = verified_rounds.TestSolveNode.NB
    client.post(f"/api/agents/projects/{pid}/install", json={"coord": builder}, headers=_auth(token))
    att = client.post(
        f"/api/agents/projects/{pid}/attachments",
        json={"coord": builder, "target": {"kind": "node", "targetId": placed[0]["id"]}}, headers=_auth(token),
    ).get_json()["attachmentId"]

    def _reply(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        return "df = input_0[0]\nreturn df"

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _reply)
    payloads: list = []

    def _exec(endpoint, payload):
        payloads.append(payload)
        return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

    monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
    return dict(pid=pid, att=att, ukey=ukey, dataset_id=dataset_id, payloads=payloads)


def _run_node(client, token, ctx, node_id: str = "n1") -> list:
    """The events of a Run node from the chat of *ctx*'s agent: the dataflow
    run through *node_id* (``run_node.run_node_stream``)."""
    from utk_curio.backend.tests._support.agent_routes import _auth
    from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve

    r = client.post(
        f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/run-node",
        json={"nodeId": node_id}, headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return routes_solve.TestStreamedSolve()._sse_events(r)


def test_a_nodes_solve_downloads_no_dataset_another_branch_reads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The node solved loads the account's own dataset. A node of another
    branch, wired to nothing, reads the shipped dataset a pip install leaves
    out. The node's rounds run its slice alone, so its Solve downloads
    nothing that only the other branch reads."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub())
    ctx = _dataflow_of(client, user, token, monkeypatch, [_the_loader(), _another_branch(_loading())])

    events = verified_rounds.TestSolveNode()._solve_node(client, token, ctx)

    assert events[-1][1]["verdict"] == "pass", events[-1]
    assert github.urls == [], f"the node's Solve downloaded what only another branch reads: {github.urls}"
    assert MRT_ID not in (ctx["payloads"][0].get("dataset_paths") or {}), ctx["payloads"][0]


def test_a_run_node_downloads_no_dataset_another_branch_reads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """A Run node from chat runs the node's slice: it downloads nothing that
    only a node of another branch reads."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub())
    ctx = _dataflow_of(client, user, token, monkeypatch, [_the_loader(), _another_branch(_loading())])

    events = _run_node(client, token, ctx)

    assert events[-1][0] == "done" and events[-1][1]["ok"], events[-1]
    assert github.urls == [], f"the Run node downloaded what only another branch reads: {github.urls}"
    assert ctx["payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat.csv"), ctx["payloads"][0]


# ---------------------------------------------------------------------------
# What an agent's run says while a dataset downloads
# ---------------------------------------------------------------------------

def _says_how_far_the_dataset_came(events: list, *, before: str) -> None:
    """*events* said how far the Milan MRT file had come while it downloaded,
    of the node n1, from its first byte to its last, then that the downloads
    were over, all before the event *before*."""
    from utk_curio.backend.tests._support.left_out_files import REPO

    size = (REPO / MRT).stat().st_size
    names = [name for name, _payload in events]
    said = [payload for name, payload in events if name == "node_download"]
    assert said, f"the run said nothing while the node's dataset downloaded: {names}"
    assert {payload["nodeId"] for payload in said} == {"n1"}, said
    dataset_said = [payload for payload in said if MRT in payload["message"]]
    assert dataset_said, f"no event named the dataset's file: {said}"
    assert (dataset_said[0]["done"], dataset_said[-1]["done"], dataset_said[-1]["total"]) == (0, size, size), dataset_said
    assert "100%" in dataset_said[-1]["message"], dataset_said[-1]
    # The downloads over, the node runs.
    assert said[-1]["message"] == "", said[-1]
    last = len(names) - 1 - names[::-1].index("node_download")
    assert last < names.index(before), names


def test_a_nodes_solve_says_how_far_its_dataset_has_come_while_it_downloads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The node reads the shipped dataset a pip install leaves out. Its
    Solve's first round downloads the file before the node runs, and the
    Solve's stream says how far it has come, then that it is over, as it says
    a model's weights."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(chunk_size=CHUNK))
    solve = verified_rounds.TestSolveNode()
    ctx = solve._setup(client, user, token, monkeypatch, content=_loading())

    events = solve._solve_node(client, token, ctx)

    _says_how_far_the_dataset_came(events, before="round_verdict")
    assert events[-1][1]["verdict"] == "pass", events[-1]
    assert github.urls == [url_of(MRT)], github.urls
    assert ctx["payloads"][0]["dataset_paths"][MRT_ID].endswith("milan-mrt.tif"), ctx["payloads"][0]


def test_a_run_node_says_how_far_its_dataset_has_come_while_it_downloads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """A Run node from chat whose node reads the shipped dataset a pip
    install leaves out downloads the file before the node runs, and its
    stream says how far it has come, then that it is over."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(chunk_size=CHUNK))
    ctx = verified_rounds.TestSolveNode()._setup(client, user, token, monkeypatch, content=_loading())

    events = _run_node(client, token, ctx)

    _says_how_far_the_dataset_came(events, before="done")
    assert events[-1][1]["ok"], events[-1]
    assert github.urls == [url_of(MRT)], github.urls
    assert ctx["payloads"][0]["dataset_paths"][MRT_ID].endswith("milan-mrt.tif"), ctx["payloads"][0]


def test_a_run_node_says_how_far_its_models_weights_have_come_while_they_download(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """A Run node from chat whose node loads a model whose package's
    ``fetch`` names its weights downloads them before the node runs, and its
    stream says how far they have come, then that they are over, as a
    Solve's does."""
    from utk_curio.backend.tests._support.fetched_weights import FakeHuggingFace
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_model_catalog import test_fetched_weights as weights

    user, token = user_and_token
    catalog = tmp_curio / "catalog"
    weights._write_package(catalog / weights.DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    FakeHuggingFace(
        weights.REPOSITORY, weights.REVISION, weights.FILES, redirect=("model.safetensors",), chunk_size=16,
    ).serve(monkeypatch)
    ctx = verified_rounds.TestSolveNode()._setup(
        client, user, token, monkeypatch, node_type=verified_rounds.CA,
        content=f'model = curio_load_model("{weights.PACKAGE_ID}")\nreturn 1',
    )
    weights._add(weights._key(user), catalog)

    events = _run_node(client, token, ctx)

    names = [name for name, _payload in events]
    said = [payload for name, payload in events if name == "node_download"]
    assert said, f"the Run node said nothing while the node's weights downloaded: {names}"
    assert {payload["nodeId"] for payload in said} == {"n1"}, said
    weights_said = [payload for payload in said if "model.safetensors" in payload["message"]]
    assert (weights_said[0]["done"], weights_said[-1]["done"], weights_said[-1]["total"]) == (
        0, len(weights.WEIGHTS), len(weights.WEIGHTS),
    ), weights_said
    assert said[-1]["message"] == "", said[-1]
    assert events[-1][0] == "done" and events[-1][1]["ok"], events[-1]
    assert len(ctx["payloads"]) == 1, "the node did not run once its weights were here"


# ---------------------------------------------------------------------------
# A plan's Solve keeps a model's failed download for its run
# ---------------------------------------------------------------------------

def _a_plan(client, user, token, monkeypatch, nodes: list, edges: list, replies: dict):
    """A plan of *nodes* and *edges* (``{ref, nodeType, title, intent}``,
    ``{from, to}``), landed as ``TestVerifiedSolve._setup`` lands its plan,
    with its fake sandbox; each node's Solve is answered with the code
    *replies* gives for its intent, ``{DATASET}`` in it being the dataset the
    setup seeds. Its first data-loading node is ``ctx["load"]``. ``(solve, ctx)``."""
    import json

    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_agents._reconstruction_driver import InProcessDriver

    plan = "Plan.\n```curio.v1\n" + json.dumps(
        {"dataflowPlan": {"goal": "the test's plan", "nodes": nodes, "edges": edges}}
    ) + "\n```"
    solve = verified_rounds.TestVerifiedSolve()
    solve._plan_tail = lambda with_stats=True: plan
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[LOADER], with_stats=False)
    answers = {intent: code.replace("{DATASET}", ctx["dataset_id"]) for intent, code in replies.items()}

    def _reply(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        if "[delegated task" not in (messages[-1].get("content") or ""):
            return plan
        asked = str(InProcessDriver.delegate_inputs(messages).get("intent") or "")
        return next((code for intent, code in answers.items() if intent in asked), "return None")

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _reply)
    return solve, ctx


def _a_gated_model(tmp_curio, monkeypatch):
    """The test model package, whose weights its ``fetch`` names, in a
    catalog of this test's own, and a Hugging Face that refuses them, as it
    refuses a gated repository to a Curio that asks with no token.
    ``(weights module, catalog, hugging face)``."""
    from utk_curio.backend.tests._support.fetched_weights import FakeHuggingFace
    from utk_curio.backend.tests.test_model_catalog import test_fetched_weights as weights

    catalog = tmp_curio / "catalog"
    weights._write_package(catalog / weights.DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    hugging_face = FakeHuggingFace(
        weights.REPOSITORY, weights.REVISION, weights.FILES, status=401, error_code="GatedRepo",
    ).serve(monkeypatch)
    return weights, catalog, hugging_face


def _segmenting(package_id: str) -> str:
    """A node that reads its input's rows and loads the model *package_id*."""
    return f'df = input_0[0]\nmodel = curio_load_model("{package_id}")\nreturn df'


def test_a_models_failed_download_is_asked_for_once_in_a_plans_solve(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """Three nodes of a plan load the model whose weights Hugging Face
    refuses: two in the wave after the loader, which run at once, and one a
    wave later. The first download fails; the Solve keeps that failure for
    its run, so no other node asks Hugging Face again, and each node says
    why in one attempt, the sandbox never asked to run it."""
    user, token = user_and_token
    weights, catalog, hugging_face = _a_gated_model(tmp_curio, monkeypatch)
    nodes = [
        {"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the tract heat data"},
        {"ref": "left", "nodeType": CA, "title": "Left", "intent": "segment the left half"},
        {"ref": "right", "nodeType": CA, "title": "Right", "intent": "segment the right half"},
        {"ref": "keep", "nodeType": CA, "title": "Keep", "intent": "keep the loaded rows"},
        {"ref": "late", "nodeType": CA, "title": "Late", "intent": "segment the kept rows"},
    ]
    edges = [{"from": "load", "to": "left"}, {"from": "load", "to": "right"},
             {"from": "load", "to": "keep"}, {"from": "keep", "to": "late"}]
    segment = _segmenting(weights.PACKAGE_ID)
    solve, ctx = _a_plan(client, user, token, monkeypatch, nodes, edges, {
        "load the tract heat data": LOADER, "segment the left half": segment,
        "segment the right half": segment, "keep the loaded rows": "df = input_0[0]\nreturn df",
        "segment the kept rows": segment,
    })
    weights._add(weights._key(user), catalog)

    body = solve._solve(client, token, ctx)

    assert len(hugging_face.requests) == 1, (
        f"the Solve asked Hugging Face for the model's weights {len(hugging_face.requests)} times: "
        f"{hugging_face.urls}"
    )
    loading = [result for result in body["results"].values()
               if any("curio_load_model" in str(a.get("code") or "") for a in result.get("attempts") or [])]
    assert len(loading) == 3, body["results"]
    for result in loading:
        assert result["status"] == "failed", result
        attempts = result.get("attempts") or []
        assert len(attempts) == 1, f"the node said why in {len(attempts)} attempts: {attempts}"
        for words in (weights.PACKAGE_ID, "Hugging Face refused it"):
            assert words in (attempts[0].get("stderrTail") or ""), attempts[0]
    assert not [p for p in ctx["exec_payloads"] if "curio_load_model" in p["code"]], (
        "the sandbox was asked to run a node whose model's weights could not be had"
    )


# ---------------------------------------------------------------------------
# A running Solve reads a file saved by hand after its download failed
# ---------------------------------------------------------------------------

def _save_by_hand():
    """The Milan MRT file, saved where a failed download of it says to save
    it, as a person would: the folder a pip install places it in."""
    import shutil

    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.tests._support.left_out_files import COMMIT, REPO

    target = left_out_files.fetched_root(COMMIT) / MRT
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / MRT, target)
    return target


def test_a_solves_lookups_read_a_dataset_saved_by_hand_once_its_download_failed(
    app, tmp_curio, user_and_token, alice_project, tmp_path, monkeypatch,
):
    """A dataset whose download failed in a Solve's run is not asked for
    again. Once its file is saved by hand where the failure says to save it,
    the next lookup reads that file, and downloads nothing."""
    from utk_curio.backend.app.agents.application.turns import grounding
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of

    user, _token = user_and_token
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(fail=OSError("Network is unreachable")))
    mapping: dict = {}
    failed: dict = {}
    first: dict = {}
    grounding._session_dataset_paths(alice_project, user, mapping, [_loading()], {}, first, failed=failed)
    assert MRT in first.get(MRT_ID, ""), first

    target = _save_by_hand()
    assert str(target) in first[MRT_ID], f"the failure does not say to save the file at {target}: {first}"
    later: dict = {}
    paths = grounding._session_dataset_paths(alice_project, user, mapping, [_loading()], {}, later, failed=failed)

    assert github.urls == [url_of(MRT)], f"the dataset saved by hand was downloaded again: {github.urls}"
    assert later == {}, f"the lookup still gave the failure the file saved by hand ends: {later}"
    assert paths.get(MRT_ID) == str(target), paths


def _saving_while_it_waits(monkeypatch, save) -> list:
    """Call *save* the first time a Solve waits between passes, the way a
    person saves a file while the Solve runs, and wait no longer: what each
    call of *save* gave."""
    from utk_curio.backend.app.agents.application.solve import session as solve_session

    saved: list = []

    def _waiting(stop, seconds):
        if not saved:
            saved.append(save())
        return False

    monkeypatch.setattr(solve_session, "_wait_for_stop", _waiting)
    return saved


def test_a_running_plans_solve_reads_a_dataset_saved_by_hand_after_its_download_failed(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The plan's loader reads the shipped dataset, whose download fails, so
    the node fails, and the Solve waits. While it waits, the file is saved by
    hand where the failure says to save it: the running Solve attempts the
    node again, reads that file and solves it, with no second download."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_agents._solve_session import _bound_session_by_passes

    user, token = user_and_token
    _bound_session_by_passes(monkeypatch, 6)
    github = _as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(fail=OSError("Network is unreachable")))
    solve = verified_rounds.TestVerifiedSolve()
    ctx = solve._setup(client, user, token, monkeypatch, with_stats=False, dl_replies=[_loading()])
    saved = _saving_while_it_waits(monkeypatch, _save_by_hand)

    body = solve._solve(client, token, ctx)

    assert saved, "the Solve never waited between its passes"
    load = body["results"][ctx["load"]]
    assert load["status"] == "solved", (
        f"the running Solve did not read the file saved by hand at {saved[0]}: {load}"
    )
    assert github.urls == [url_of(MRT)], f"the file saved by hand was downloaded again: {github.urls}"
    assert ctx["exec_payloads"][-1]["dataset_paths"][MRT_ID] == str(saved[0]), ctx["exec_payloads"][-1]


def test_a_running_plans_solve_reads_weights_saved_by_hand_after_their_download_failed(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """A node of the plan loads the model whose weights Hugging Face refuses,
    so it fails, and the Solve waits. While it waits, the weights are saved
    by hand into the package's folder, with no digest beside them: the
    running Solve attempts the node again, checks the files, and solves it,
    with no second download."""
    from utk_curio.backend.tests.test_agents._solve_session import _bound_session_by_passes

    user, token = user_and_token
    _bound_session_by_passes(monkeypatch, 6)
    weights, catalog, hugging_face = _a_gated_model(tmp_curio, monkeypatch)
    nodes = [
        {"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the tract heat data"},
        {"ref": "seg", "nodeType": CA, "title": "Segment", "intent": "segment the loaded rows"},
    ]
    solve, ctx = _a_plan(client, user, token, monkeypatch, nodes, [{"from": "load", "to": "seg"}], {
        "load the tract heat data": LOADER, "segment the loaded rows": _segmenting(weights.PACKAGE_ID),
    })
    weights._add(weights._key(user), catalog)
    saved = _saving_while_it_waits(monkeypatch, lambda: weights._place_by_hand(catalog / weights.DIR))

    body = solve._solve(client, token, ctx)

    assert saved, "the Solve never waited between its passes"
    segmented = [nid for nid in body["results"] if nid != ctx["load"]]
    assert len(segmented) == 1, body["results"]
    result = body["results"][segmented[0]]
    assert result["status"] == "solved", f"the running Solve did not read the weights saved by hand: {result}"
    assert len(hugging_face.requests) == 1, (
        f"the weights saved by hand were downloaded again: {hugging_face.urls}"
    )
    ran = [p for p in ctx["exec_payloads"] if "curio_load_model" in p["code"]]
    assert ran and weights.PACKAGE_ID in (ran[-1].get("models") or {}), ran
