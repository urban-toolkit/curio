"""The Data Catalog's "Add to all projects", the dataset twin of package defaults.

Datasets had no account-level concept at all: nodes had ``packages/defaults.py``
and agents had account imports, but a dataset could only ever be attached to one
project at a time. That left the standalone ``/catalog/data`` page with no action
it could offer, because the page has no project to attach to.

"All your projects, present and future" is two mechanisms wearing one label, and
both halves are asserted here separately, because only one of them is obvious:

  * **present** - an eager walk at the moment of the POST, which installs the
    dataset into every project that already exists. Nothing else can do this:
    opening an old project never consults defaults.
  * **future** - the id joins the user's list, and ``save_project`` installs it
    into each project created afterwards.

A test that only checked one half would pass against an implementation that
silently dropped the other.
"""
from __future__ import annotations

import io

import pytest
from utk_curio.backend.app.common.user_storage import users_base


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _import_csv(client, token, name="cities.csv", body=b"a,b\n1,2\n"):
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _project_dataset_ids(client, token, project_id):
    """The dataset ids the project's spec actually references."""
    resp = client.get(f"/api/projects/{project_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    spec = resp.get_json().get("spec") or {}
    refs = (spec.get("dataflow") or {}).get("datasets") or []
    return {r.get("datasetId") for r in refs}


# ── The list itself ──────────────────────────────────────────────────────────


def test_defaults_start_empty_and_round_trip(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get("/api/datasets/defaults", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.get_json()["datasets"] == []

    dataset_id = _import_csv(client, token)
    add = client.post(
        "/api/datasets/defaults",
        headers=_auth(token),
        json={"datasetId": dataset_id},
    )
    assert add.status_code == 200, add.get_data(as_text=True)
    assert dataset_id in add.get_json()["datasets"]

    again = client.get("/api/datasets/defaults", headers=_auth(token))
    assert again.get_json()["datasets"] == [dataset_id]


def test_adding_twice_is_idempotent(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    dataset_id = _import_csv(client, token)

    for _ in range(2):
        resp = client.post(
            "/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id}
        )
        assert resp.status_code == 200
    assert client.get("/api/datasets/defaults", headers=_auth(token)).get_json()[
        "datasets"
    ] == [dataset_id]


def test_datasetid_is_required(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    resp = client.post("/api/datasets/defaults", headers=_auth(token), json={})
    assert resp.status_code == 400


def test_defaults_require_auth(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    assert client.get("/api/datasets/defaults").status_code == 401
    assert client.post("/api/datasets/defaults", json={"datasetId": "x"}).status_code == 401


# ── The "present" half ───────────────────────────────────────────────────────


def test_adding_to_defaults_installs_into_projects_that_already_exist(
    client, user_and_token, tmp_path, monkeypatch
):
    """The eager walk. Without it, "all your projects" would quietly mean "all
    the projects you make from now on", and the projects the user already has -
    which is all of them, at the moment they click - would be untouched."""
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    first = create_project(client, token, name="Already here")
    second = create_project(client, token, name="Also already here")
    dataset_id = _import_csv(client, token)

    assert dataset_id not in _project_dataset_ids(client, token, first)

    resp = client.post(
        "/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    reported = {p["id"]: p for p in resp.get_json()["projects"]}
    assert reported[first]["ok"] is True
    assert reported[second]["ok"] is True

    assert dataset_id in _project_dataset_ids(client, token, first)
    assert dataset_id in _project_dataset_ids(client, token, second)


def test_the_listing_the_palette_reads_reports_it_installed(
    client, user_and_token, tmp_path, monkeypatch
):
    """The contract the canvas surfaces actually depend on.

    The datasets palette and the drawer's "In project" tab both filter the
    catalog listing, scoped to the open dataflow. Asserting only that the
    project SPEC gained a ref would pass while both surfaces stayed empty, which
    is the symptom that was reported twice - so assert what they read.
    """
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    project_id = create_project(client, token, name="Open in the canvas")
    dataset_id = _import_csv(client, token)

    before = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}", headers=_auth(token)
    ).get_json()["items"]
    row = next(i for i in before if i["id"] == dataset_id)
    assert row["installed"] is False
    assert row["inAllProjects"] is False

    add = client.post(
        "/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id}
    )
    assert add.status_code == 200, add.get_data(as_text=True)

    after = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}", headers=_auth(token)
    ).get_json()["items"]
    row = next(i for i in after if i["id"] == dataset_id)
    # `installed` is what the palette filters on for a saved dataflow.
    assert row["installed"] is True, "the eager walk must reach an open dataflow"
    # And the account-level flag, which is what the surfaces fall back to when
    # there is no dataflow yet.
    assert row["inAllProjects"] is True


def test_an_unsaved_dataflow_can_still_see_it(client, user_and_token, tmp_path, monkeypatch):
    """With no dataflow, the listing is unscoped and nothing is `installed` -
    so `inAllProjects` is the only thing that can tell the palette what this
    dataflow will contain the moment it is saved."""
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    dataset_id = _import_csv(client, token)
    client.post("/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id})

    unscoped = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
    row = next(i for i in unscoped if i["id"] == dataset_id)
    assert row.get("installed") is not True
    assert row["inAllProjects"] is True


# ── The "future" half ────────────────────────────────────────────────────────


def test_a_project_created_afterwards_gets_the_dataset(
    client, user_and_token, tmp_path, monkeypatch
):
    """Loading a project never consults defaults, so if `save_project` does not
    seed, a defaulted dataset is missing from every project made later and the
    label is simply false."""
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    dataset_id = _import_csv(client, token)
    client.post("/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id})

    later = create_project(client, token, name="Made afterwards")
    assert dataset_id in _project_dataset_ids(client, token, later)


def test_a_stale_default_does_not_break_project_creation(
    client, user_and_token, tmp_path, monkeypatch
):
    """A default can go stale - the dataset was deleted from the account. That
    must degrade to "it is missing from the new project", never to "the project
    could not be created"."""
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    dataset_id = _import_csv(client, token)
    client.post("/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id})
    # Delete the dataset itself, leaving the id in the defaults list.
    gone = client.delete(f"/api/datasets/{dataset_id}", headers=_auth(token))
    assert gone.status_code in (200, 204), gone.get_data(as_text=True)

    later = create_project(client, token, name="Survives a stale default")
    assert later, "project creation must survive a default that no longer resolves"
    assert dataset_id not in _project_dataset_ids(client, token, later)


# ── Removal ──────────────────────────────────────────────────────────────────


def test_removing_from_defaults_detaches_but_does_not_delete(
    client, user_and_token, tmp_path, monkeypatch
):
    """Unlike the package list, the dataset list is user-managed in both
    directions. Removal detaches from existing projects and stops the seeding,
    but the dataset stays in the account catalog - deleting it outright is a
    different, louder action."""
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    project_id = create_project(client, token, name="Has it for now")
    dataset_id = _import_csv(client, token)
    client.post("/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id})
    assert dataset_id in _project_dataset_ids(client, token, project_id)

    resp = client.delete(f"/api/datasets/defaults/{dataset_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["datasets"] == []

    assert dataset_id not in _project_dataset_ids(client, token, project_id)

    # Still in the account catalog: detach, not delete.
    catalog = client.get("/api/datasets/catalog", headers=_auth(token))
    assert dataset_id in {item["id"] for item in catalog.get_json()["items"]}

    # And no longer seeded into anything new.
    later = create_project(client, token, name="Made after removal")
    assert dataset_id not in _project_dataset_ids(client, token, later)


# ── Isolation ────────────────────────────────────────────────────────────────


def test_defaults_are_per_user(client, user_and_token, tmp_path, monkeypatch):
    """The list lives under the user's own key, so one account's choice cannot
    seed itself into another account's projects."""
    from utk_curio.backend.app.datasets import defaults as dataset_defaults

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    dataset_id = _import_csv(client, token)
    client.post("/api/datasets/defaults", headers=_auth(token), json={"datasetId": dataset_id})

    assert dataset_defaults.load_dataset_defaults("guest") == set()


# ── The store's own contract ─────────────────────────────────────────────────


def test_a_corrupt_defaults_file_reads_as_empty(tmp_path, monkeypatch):
    """Never raise from the read path: this file is seeded into every project
    creation, and a hand-edited or half-written one must not make the app
    unusable. Same convention as packages/seed_state.py."""
    from utk_curio.backend.app.datasets import defaults as dataset_defaults

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    path = users_base() / "guest" / "default-datasets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")

    assert dataset_defaults.load_dataset_defaults("guest") == set()


def test_junk_entries_are_filtered_not_trusted(tmp_path, monkeypatch):
    """The file is on disk and hand-editable, so a traversal-shaped entry must
    not survive the read and reach an installer."""
    from utk_curio.backend.app.datasets import defaults as dataset_defaults

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    path = users_base() / "guest" / "default-datasets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"version": 1, "datasets": ["imported.ok@1", "../../etc/passwd", "", 7,'
        ' "with space"]}',
        encoding="utf-8",
    )

    assert dataset_defaults.load_dataset_defaults("guest") == {"imported.ok@1"}


def test_saving_is_sorted_deduped_and_atomic(tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets import defaults as dataset_defaults

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    dataset_defaults.save_dataset_defaults(
        "guest", ["imported.b@1", "imported.a@1", "imported.b@1"]
    )
    path = users_base() / "guest" / "default-datasets.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"version": 1, "datasets": ["imported.a@1", "imported.b@1"]}
    # No temp file left behind by the atomic swap.
    assert not list(path.parent.glob("*.tmp"))
