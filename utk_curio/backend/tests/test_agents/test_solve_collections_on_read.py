"""A Solve looks a Data Catalog collection up only when a round's code reads it.

A collection's lookup (``discovery/application/exec_collections.resolve_collections``)
asks the Discovery Catalog for it, and for a bucket this deployment mounts it
mounts the bucket (``bucket_mount_sources.ensure``). So no agent's run looks up
a collection it does not read:

- a Solve's start, a node's Solve or a plan's, looks up none of the
  collections its dataflow's Data Catalog lists: each round looks up those its
  code reads, as it looks up a dataset's path (``grounding._session_collections``);
- a Run node from chat looks up those the node's slice reads, the node and the
  nodes it reads from, never those of another branch of the dataflow.

Each test counts the collections the Discovery Catalog is asked for
(``DiscoveryService.collection``), however a lookup comes to ask. Every test
imports what it tests inside itself, so a checkout without it fails test by
test.
"""
from __future__ import annotations


def _asked_for(monkeypatch) -> list:
    """Every collection id the Discovery Catalog is asked for from now on."""
    from utk_curio.backend.app.discovery.service import DiscoveryService

    asked: list = []
    collection = DiscoveryService.collection

    def asking(service, dataset_id, *args, **kwargs):
        asked.append(dataset_id)
        return collection(service, dataset_id, *args, **kwargs)

    monkeypatch.setattr(DiscoveryService, "collection", asking)
    return asked


def test_a_nodes_solve_looks_up_no_collection_its_node_never_reads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The account's Data Catalog holds a collection the node never reads:
    the node's Solve never asks for it."""
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import _a_collection

    user, token = user_and_token
    collection = _a_collection(user, tmp_path)
    solve = verified_rounds.TestSolveNode()
    ctx = solve._setup(client, user, token, monkeypatch, content=solve.LOADER)
    asked = _asked_for(monkeypatch)

    events = solve._solve_node(client, token, ctx)

    assert events[-1][1]["verdict"] == "pass", events[-1]
    assert collection not in asked, f"the node's Solve looked up a collection its node never reads: {asked}"


def test_a_plans_solve_looks_up_no_collection_its_nodes_never_read(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """The account's Data Catalog holds a collection none of the plan's
    nodes reads: the plan's Solve never asks for it."""
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import _a_collection

    user, token = user_and_token
    collection = _a_collection(user, tmp_path)
    solve = verified_rounds.TestVerifiedSolve()
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[solve.LOADER], with_stats=False)
    asked = _asked_for(monkeypatch)

    body = solve._solve(client, token, ctx)

    assert body["results"][ctx["load"]]["status"] == "solved", body["results"]
    assert collection not in asked, f"the plan's Solve looked up a collection its nodes never read: {asked}"


def test_a_run_node_looks_up_no_collection_another_branch_reads(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """A node of another branch, wired to nothing, reads a collection of the
    account's Data Catalog. A Run node from chat runs the node's slice, so it
    never asks for that collection."""
    from utk_curio.backend.tests.test_agents import test_solve_downloads as downloads
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import _a_collection

    user, token = user_and_token
    collection = _a_collection(user, tmp_path)
    photos = downloads._another_branch(f'photos = curio_load_collection("{collection}")\nreturn photos')
    ctx = downloads._dataflow_of(client, user, token, monkeypatch, [downloads._the_loader(), photos])
    asked = _asked_for(monkeypatch)

    events = downloads._run_node(client, token, ctx)

    assert events[-1][0] == "done" and events[-1][1]["ok"], events[-1]
    assert collection not in asked, f"the Run node looked up a collection only another branch reads: {asked}"
    assert collection not in (ctx["payloads"][0].get("collections") or {}), ctx["payloads"][0]
