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
- A download that fails is asked for once in a Solve's run, and the node that
  reads it says why once: a correction of its code cannot change that.
- While a node's weights download, the Solve says how far they have come
  (``node_download``, with no message once they are over), as a run on the
  server says it (``step_progress``).

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
