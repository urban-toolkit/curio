"""Integration tests for /api/projects routes."""
import json
import pytest

from utk_curio.backend.app.projects import storage


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _spec():
    # A complete trill, per docs/schemas/trill.v1.json. Completeness matters for
    # the round-trip assertions below: save_project backfills the identity fields
    # a spec arrives without (services._ensure_dataflow_identity), so a partial
    # fixture would not come back equal to itself and the preservation tests
    # would be measuring the backfill instead of preservation.
    return {
        "dataflow": {
            "name": "route-test",
            "nodes": [],
            "edges": [],
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "route-test",
        }
    }


def test_create_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": "Test", "spec": _spec(), "outputs": []}),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Test"
    assert body["id"]


def test_list_projects(client, user_and_token, tmp_curio):
    _, token = user_and_token
    client.post(
        "/api/projects",
        data=json.dumps({"name": "A", "spec": _spec()}),
        headers=_auth(token),
    )
    client.post(
        "/api/projects",
        data=json.dumps({"name": "B", "spec": _spec()}),
        headers=_auth(token),
    )
    resp = client.get("/api/projects", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2


def test_list_projects_serves_a_registered_users_examples(
    client, user_and_token, tmp_curio, monkeypatch
):
    """#200 end to end at the route: the gallery is not empty under --auth.

    Examples were seeded to the shared guest alone and listing is a plain owner
    filter, so a signed-in account got `[]` here however the stack was started.
    """
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")
    _, token = user_and_token

    resp = client.get("/api/projects", headers=_auth(token))

    assert resp.status_code == 200
    names = {p["name"] for p in resp.get_json()}
    assert names, "a registered user's gallery came back empty"
    # Named, not just counted: the rows must be the curated examples rather
    # than any project that happens to exist.
    assert "Vega-Lite chained transforms" in names, sorted(names)


def test_get_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Detail", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"]["name"] == "Detail"
    assert body["spec"] is not None


def test_update_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Upd", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(), "outputs": [], "name": "Updated"}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Updated"
    assert resp.get_json()["spec_revision"] == 2


def test_rename_project_preserves_existing_spec(client, user_and_token, tmp_curio):
    """A rename must not disturb the GRAPH the spec describes.

    This used to assert ``spec == _spec()`` outright, which also pinned
    ``dataflow.name`` to the pre-rename value - i.e. it asserted the #230 bug as
    expected behaviour. A rename now mirrors into the spec, so the assertion is
    narrowed to what it was actually protecting: nodes, edges and the identity
    fields a rename has no business touching.
    """
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Rename Me", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    rename = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"name": "Renamed"}),
        headers=_auth(token),
    )
    assert rename.status_code == 200
    assert rename.get_json()["name"] == "Renamed"

    loaded = client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert loaded.status_code == 200
    dataflow = loaded.get_json()["spec"]["dataflow"]
    original = _spec()["dataflow"]
    for field in ("nodes", "edges", "task", "timestamp"):
        assert dataflow[field] == original[field], f"the rename disturbed {field}"
    # provenance_id keys the already-recorded provenance versions, so a rename
    # deliberately leaves it on the old name rather than orphaning them.
    assert dataflow["provenance_id"] == original["provenance_id"]
    # And the half this test was silently asserting backwards:
    assert dataflow["name"] == "Renamed"


def test_rename_mirrors_into_the_spec_dataflow_name(client, user_and_token, tmp_curio):
    """#230, the Projects-list direction: a name-only PUT must reach the spec.

    The name has two stores - the project row (what the Projects list renders)
    and ``spec.dataflow.name`` (what the canvas title renders). A name-only PUT
    never entered the spec block at all, so renaming from the Projects list left
    the canvas showing the old title until the next canvas save overwrote it.
    """
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "List Rename", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    rename = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"name": "Renamed From The List"}),
        headers=_auth(token),
    )
    assert rename.status_code == 200

    # The GET returns the LoadResponse shape: {project, spec, outputs}.
    body = client.get(f"/api/projects/{pid}", headers=_auth(token)).get_json()
    assert body["project"]["name"] == "Renamed From The List"
    assert body["spec"]["dataflow"]["name"] == "Renamed From The List", (
        "the row was renamed but the spec still holds the old name, so the canvas "
        "title and the Projects card disagree"
    )


def test_saving_a_renamed_spec_updates_the_row(client, user_and_token, tmp_curio):
    """#230, the canvas direction: a save carrying a new name moves the card.

    The client used to send the load-time ``projectName`` here while generating
    the spec from the freshly edited ``workflowName``, so the two stores parted
    company on every canvas rename.
    """
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Canvas Rename", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    renamed_spec = _spec()
    renamed_spec["dataflow"]["name"] = "Renamed On The Canvas"
    put = client.put(
        f"/api/projects/{pid}",
        data=json.dumps(
            {"spec": renamed_spec, "outputs": [], "name": "Renamed On The Canvas"}
        ),
        headers=_auth(token),
    )
    assert put.status_code == 200

    listed = client.get("/api/projects", headers=_auth(token)).get_json()
    names = [p["name"] for p in listed]
    assert "Renamed On The Canvas" in names, names
    assert "Canvas Rename" not in names, (
        f"the old name is still listed, so the rename forked instead of moving: {names}"
    )


def test_delete_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Del", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.delete(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 204

    listing = client.get("/api/projects", headers=_auth(token))
    assert len(listing.get_json()) == 0


def test_duplicate_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Dup", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.post(f"/api/projects/{pid}/duplicate", headers=_auth(token))
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "Dup (copy)"


def test_auth_required(client, tmp_curio):
    resp = client.get("/api/projects")
    assert resp.status_code in (401, 403)


def test_non_shared_guest_cannot_create_project(client, guest_user_and_token, tmp_curio):
    _, token = guest_user_and_token

    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Blocked Guest", "spec": _spec(), "outputs": []}),
        headers=_auth(token),
    )
    assert create.status_code == 403
    assert "Guest users cannot save" in create.get_json()["error"]


def test_ownership_isolation(client, user_and_token, db, tmp_curio):
    _, alice_token = user_and_token

    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Alice's", "spec": _spec()}),
        headers=_auth(alice_token),
    )
    pid = create.get_json()["id"]

    from utk_curio.backend.app.users.models import User, UserSession
    bob = User(username="bob", name="Bob")
    db.session.add(bob)
    db.session.flush()
    s = UserSession(user_id=bob.id, token="bob-token")
    db.session.add(s)
    db.session.commit()

    resp = client.get(f"/api/projects/{pid}", headers=_auth("bob-token"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /shared — link-based public read
# ---------------------------------------------------------------------------

def test_get_shared_project_no_auth(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Shared", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.get(f"/api/projects/{pid}/shared")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"]["name"] == "Shared"
    assert body["spec"] == _spec()
    # folder_path is internal — don't leak FS layout to anonymous visitors.
    assert body["project"].get("folder_path") == ""


def test_get_shared_project_from_other_user(client, user_and_token, db, tmp_curio):
    _, alice_token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Alice's", "spec": _spec()}),
        headers=_auth(alice_token),
    )
    pid = create.get_json()["id"]

    from utk_curio.backend.app.users.models import User, UserSession
    bob = User(username="bob", name="Bob")
    db.session.add(bob)
    db.session.flush()
    db.session.add(UserSession(user_id=bob.id, token="bob-token"))
    db.session.commit()

    resp = client.get(f"/api/projects/{pid}/shared", headers=_auth("bob-token"))
    assert resp.status_code == 200
    assert resp.get_json()["project"]["name"] == "Alice's"


def test_get_shared_project_missing(client, tmp_curio):
    resp = client.get("/api/projects/00000000-0000-0000-0000-000000000000/shared")
    assert resp.status_code == 404


def test_get_shared_project_deleted(client, user_and_token, tmp_curio):
    """Deleting revokes the public share link."""
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Soon Deleted", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    deleted = client.delete(f"/api/projects/{pid}", headers=_auth(token))
    assert deleted.status_code == 204

    resp = client.get(f"/api/projects/{pid}/shared")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# dev/124 — a save may not delete what the client never saw
# ---------------------------------------------------------------------------

def _spec_with(nodes, edges=()):
    spec = _spec()
    spec["dataflow"]["nodes"] = list(nodes)
    spec["dataflow"]["edges"] = list(edges)
    return spec


def _node(node_id, content=""):
    return {"id": node_id, "type": "curio.builtin/data-loading",
            "x": 0, "y": 0, "content": content}


def _open_project(client, token, name="Concurrency"):
    """Create a project and read it the way the canvas does, returning the id
    and the basis a canvas would then be holding."""
    pid = client.post(
        "/api/projects", data=json.dumps({"name": name, "spec": _spec()}),
        headers=_auth(token),
    ).get_json()["id"]
    loaded = client.get(f"/api/projects/{pid}", headers=_auth(token)).get_json()
    return pid, loaded["project"]["spec_revision"]


def _server_side_write(user_key, pid, nodes, edges=()):
    """What an agent apply or a Solve wave does: straight through the spec,
    with no idea a browser is holding the old one."""
    spec = storage.read_spec(user_key, pid)
    spec["dataflow"]["nodes"] = list(nodes)
    spec["dataflow"]["edges"] = list(edges)
    storage.write_spec(user_key, pid, spec)


def test_a_stale_save_that_would_delete_a_server_side_write_is_refused(
    client, user_and_token, tmp_curio
):
    """The defect in its general form: load, background write, stale save."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, basis = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a"), _node("b")])

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(), "outputs": [], "baseRevision": basis}),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert "2 nodes" in resp.get_json()["error"]
    # Nothing was written: the two nodes are still there.
    spec = storage.read_spec(_user_dir_key(user), pid)
    assert [n["id"] for n in spec["dataflow"]["nodes"]] == ["a", "b"]


def test_the_same_save_with_a_current_basis_is_accepted(
    client, user_and_token, tmp_curio
):
    """A person deleting nodes they can see is not a conflict."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, _ = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a")])
    fresh = client.get(f"/api/projects/{pid}", headers=_auth(token)).get_json()

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({
            "spec": _spec(), "outputs": [],
            "baseRevision": fresh["project"]["spec_revision"],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert storage.read_spec(_user_dir_key(user), pid)["dataflow"]["nodes"] == []


def test_a_stale_save_that_adds_without_deleting_is_accepted(
    client, user_and_token, tmp_curio
):
    """Staleness alone never refuses — the canvas hears about an apply through
    a live event and its basis goes stale while its content stays current."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, basis = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a")])

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({
            "spec": _spec_with([_node("a"), _node("mine")]),
            "outputs": [], "baseRevision": basis,
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    saved = storage.read_spec(_user_dir_key(user), pid)["dataflow"]["nodes"]
    assert sorted(n["id"] for n in saved) == ["a", "mine"]


def test_a_stale_save_may_not_blank_code_solve_wrote(
    client, user_and_token, tmp_curio
):
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, basis = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a", content="import x")])

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({
            "spec": _spec_with([_node("a", content="")]),
            "outputs": [], "baseRevision": basis,
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert "the code in 1 node" in resp.get_json()["error"]


def test_a_save_with_no_basis_is_unchecked_as_before(
    client, user_and_token, tmp_curio
):
    """The contract that keeps scripts, tests and internal callers working."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, _ = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a")])

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(), "outputs": []}),
        headers=_auth(token),
    )
    assert resp.status_code == 200


def test_a_malformed_basis_is_no_opinion_rather_than_a_400(
    client, user_and_token, tmp_curio
):
    _, token = user_and_token
    pid, _ = _open_project(client, token)
    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(), "outputs": [], "baseRevision": "nonsense"}),
        headers=_auth(token),
    )
    assert resp.status_code == 200


def test_the_reported_revision_counts_background_writes(
    client, user_and_token, tmp_curio
):
    """The property the spec_revision column could not have: a write nobody
    routed through the projects service still moves the number."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    pid, basis = _open_project(client, token)
    _server_side_write(_user_dir_key(user), pid, [_node("a")])
    after = client.get(
        f"/api/projects/{pid}", headers=_auth(token)
    ).get_json()["project"]["spec_revision"]
    assert after > basis
