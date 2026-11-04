"""An agent's Run node, in an invited editor's chat, writes to the editor's media folder.

alice owns a dataflow that lists a collection of hers whose files came down
from a service, into her media folder. bob, an editor she invited, runs the
dataflow through a node from an agent's chat (``run_node_stream``). The node
that loads the collection is sent where alice's store keeps its files, and the
media folder it writes what it derives into is bob's own, as on Play. Nothing
is made in alice's media folder.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_run_node_datasets import (
    _loader,
    _run_through_the_node_after,
    _save_under_an_agent,
)
from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, SERVICE, _a_collection

BOB_TOKEN = "bob-token-for-tests"


def _account(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


def test_an_editors_run_node_derives_into_his_media_folder_and_makes_nothing_in_the_owners(
    client, db, user_and_token, tmp_curio, alice_project, tmp_path, monkeypatch,
):
    from utk_curio.backend.app.discovery.application import cache_collection
    from utk_curio.backend.app.discovery.infrastructure import media_dirs, storage
    from utk_curio.backend.app.projects import access

    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))
    alice, alice_token = user_and_token
    bob = _account(db, "bob", BOB_TOKEN)
    collection = _a_collection(alice, tmp_path, source_id=SERVICE)
    added = client.post(
        f"/api/dataflows/{alice_project}/datasets/install",
        json={"datasetId": collection}, headers=_auth(alice_token),
    )
    assert added.status_code == 200, added.get_data(as_text=True)
    _save_under_an_agent(alice, alice_project, _loader(f'photos = curio_load_collection("{collection}")\nreturn photos\n'))
    access.add_editor(alice, alice_project, "bob")
    alices_media = media_dirs.media_work_root(str(alice.id))

    _done, sent = _run_through_the_node_after(client, BOB_TOKEN, alice_project, monkeypatch)

    loading = sent[0]
    assert loading.get("media_dir") == str(media_dirs.media_work_root(str(bob.id))), (
        f"bob's run from the agent's chat derives into {loading.get('media_dir')}"
    )
    assert loading.get("collections") == {collection: {
        "kind": "audio",
        "objects": str(cache_collection.objects_dir(str(alice.id), collection, create=False)),
    }}, loading.get("collections")
    assert not alices_media.exists(), sorted(str(p) for p in alices_media.rglob("*"))
