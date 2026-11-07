"""The Dataflow Builder's Solve hands the sandbox the datasets a node's code names, as a node's Solve does.

A Solve over a plan is a batch that solves each node on a thread of its pool
(``SolveBatch._run_pass``). When the Solve starts, its request resolves the
paths of the dataflow's Data Catalog datasets; an id those paths do not hold
is resolved for the node's run, on the pool's thread
(``grounding._session_dataset_paths``). A layer group's id is always one: it
names no file of its own, and only its entry, which that lookup reads, names
its layers. The lookup reads the Data Catalog, which reads the database, and
a pool's thread starts with no app context of its own. There it found
nothing, so the node ran as if the dataset were missing, while a node's own
Solve, which looks it up on its job's thread, loads it.

Every test imports what it tests inside itself, so a checkout without it
fails test by test.
"""
from __future__ import annotations


def test_a_plans_solve_hands_a_layer_groups_loader_its_layers_and_its_entry(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_datasets.test_layer_group_execution import _imported_group

    user, token = user_and_token
    # A GeoPackage of four layers the account imported: a layer group of its own.
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)
    solve = verified_rounds.TestVerifiedSolve()
    # A plan of one Data Loading node, whose content builder loads the group by its id.
    ctx = solve._setup(
        client, user, token, monkeypatch,
        dl_replies=[f'layers = curio_load_data("{group_id}")\nreturn layers'], with_stats=False,
    )

    body = solve._solve(client, token, ctx)

    assert body["results"][ctx["load"]]["status"] == "solved", body["results"]
    assert ctx["exec_payloads"], "the loader never reached the sandbox"
    sent = ctx["exec_payloads"][0]
    assert set(sent.get("dataset_paths") or {}) == {i for _name, i in layers}, (
        f"the Solve sent the loader of {group_id} no path for its layers: {sent.get('dataset_paths')}"
    )
    assert (sent.get("dataset_formats") or {}).get(group_id) == {
        "format": "layer-group", "layers": [[name, i] for name, i in layers],
    }, sent.get("dataset_formats")
