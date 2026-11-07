"""A dataset added to the dataflow's Data Catalog while a Solve runs is one its later nodes may load.

The Dataflow Builder's Solve reads the dataflow's Data Catalog once, when it
starts (``grounding._solve_grounding_base``), and its grounding gate held each
node's code to the ids that read found (``source_grounding._judge_refs``). A
dataset added while the Solve runs, by the Dataset Finder's Apply or an
install between two nodes, was refused in a later node's code as one the
Data Catalog does not hold, though the node's run would have loaded it.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations


def test_a_dataset_added_while_a_plans_solve_runs_is_loaded_by_a_later_node(
    app, client, user_and_token, tmp_curio, monkeypatch,
):
    import threading

    from utk_curio.backend.app.agents.infrastructure import providers
    from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    solve = verified_rounds.TestVerifiedSolve()
    # A plan of a Data Loading node and the computation it feeds, in two waves.
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[solve.LOADER])
    scripted = providers.run_chat_turn
    added: dict = {}

    def _import():
        # The account imports a file in a request of its own.
        with app.app_context():
            added["id"] = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")

    def _model(config, messages, **kwargs):
        frame = (messages[-1].get("content") or "") if messages else ""
        if "[delegated task" not in frame:
            return scripted(config, messages, **kwargs)
        if f'"nodeType": "{verified_rounds.DL}"' in frame:
            if not added:
                # While the Solve writes the plan's loader, the file lands.
                importer = threading.Thread(target=_import)
                importer.start()
                importer.join(30)
            return scripted(config, messages, **kwargs)
        # The node after the loader also reads the new dataset, by its id.
        return (
            "df = input_0[0]\n"
            f'areas = curio_load_data("{added["id"]}")\n'
            "return df.assign(areas=len(areas)).describe()"
        )

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _model)

    body = solve._solve(client, token, ctx)

    assert added.get("id"), "the dataset never landed while the Solve ran"
    stats = body["results"][ctx["stats"]]
    assert stats["status"] == "solved", stats
    sent = [payload for payload in ctx["exec_payloads"] if added["id"] in payload["code"]]
    assert sent, "the node that reads the new dataset never reached the sandbox"
    paths = sent[0].get("dataset_paths") or {}
    assert str(paths.get(added["id"], "")).endswith("areas.csv"), paths
