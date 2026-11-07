"""What an invited editor's Solve of a node derives goes to his own media folder, as on his Play.

Solve runs each attempt it checks through ``validation.validate_candidate``,
which looks up the collections the code loads and names the media folder the
node writes what it derives into (``resolve_spec_collections``). alice's
dataflow lists a collection of hers, and bob, an editor she invited, solves a
node that loads it. The lookup was made under the dataflow's store, hers, so
the frames, clips and overlays bob's node derives went to her media folder,
while his Play and an agent's Run node write them to his own.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

from utk_curio.backend.tests._support.agent_routes import _auth


def _bobs_solve_of_a_node_loading_alices_collection(client, db, user_and_token, tmp_path, monkeypatch):
    """bob's Solve this node, on alice's node that loads a collection her
    dataflow lists from her store, the sandbox stood in for: ``(alice, bob,
    the collection's id, what the sandbox was sent)``."""
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.tests.test_agents.test_editor_run_node_collections import BOB_TOKEN, _account
    from utk_curio.backend.tests.test_agents.test_verified_rounds import TestSolveNode
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, SERVICE, _a_collection

    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))
    alice, alice_token = user_and_token
    bob = _account(db, "bob", BOB_TOKEN)
    # Images a service gave alice: her store keeps their files in her media folder.
    collection = _a_collection(alice, tmp_path, source_id=SERVICE)
    solve = TestSolveNode()
    ctx = solve._setup(client, alice, alice_token, monkeypatch,
                       content=f'photos = curio_load_collection("{collection}")\nreturn photos')
    added = client.post(
        f"/api/dataflows/{ctx['pid']}/datasets/install",
        json={"datasetId": collection}, headers=_auth(alice_token),
    )
    assert added.status_code == 200, added.get_data(as_text=True)
    access.add_editor(alice, ctx["pid"], "bob")

    events = solve._solve_node(client, BOB_TOKEN, ctx)

    assert ctx["payloads"], f"bob's Solve never reached the sandbox: {events[-1]}"
    return alice, bob, collection, ctx["payloads"][0]


def test_what_an_editors_solve_derives_goes_to_his_media_folder(
    client, db, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    alice, bob, _collection, sent = _bobs_solve_of_a_node_loading_alices_collection(
        client, db, user_and_token, tmp_path, monkeypatch,
    )

    assert sent.get("media_dir") == str(media_dirs.media_work_root(str(bob.id))), (
        f"bob's Solve derives into {sent.get('media_dir')}"
    )
    alices_media = media_dirs.media_work_root(str(alice.id))
    assert not alices_media.exists(), sorted(str(p) for p in alices_media.rglob("*"))
