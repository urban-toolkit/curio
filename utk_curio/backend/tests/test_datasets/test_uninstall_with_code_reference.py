"""Uninstall must remove the dataset even when a node's code still names it.

``dataset_usage`` counts a dataset as used when a node's *source* mentions it
(#250), which is right for the detail page and for lineage. The uninstall
orphan gate consulted the same query, and applying a dataset writes
``curio_dataset_path("<id>")`` straight into the node's source - so for the
ordinary drag-it-in-then-uninstall flow the gate always fired: the store folder
survived, the Data Hub card survived, and "uninstalling removes all traces"
stopped being true.

``test_import_uninstall_lifecycle.py::test_uninstall_imported_removes_all_traces``
looks like it covers this and does not: it installs into a project with no nodes
at all, so there is no source for the widened scan to find. This is the sibling
case with a real code reference in it - the one that fails when the gate reads
code.

The dangling call left in the node is deliberate and is not new. Nothing has
ever rewritten node ``content`` on uninstall, and execution resolves dataset
paths fail-open, so the node raises a clear per-id error on its next run rather
than breaking the dataflow. The UI warns about that before it gets here.
"""

from __future__ import annotations

import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _auth(token):
    return auth_headers(token)


def _import(client, token, *, name="roads.csv", body=b"a,b\n1,2\n"):
    import io

    resp = client.post(
        "/api/datasets/import",
        headers=_auth(token),
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _project_with_loader(client, token, dataset_id, *, name="Uses it in code"):
    """A project whose single node names *dataset_id* in its source only."""
    spec = {
        "dataflow": {
            "name": name,
            "nodes": [
                {
                    "id": "loader",
                    "type": "curio.builtin/data-loading",
                    "x": 0,
                    "y": 0,
                    "content": (
                        "import pandas as pd\n"
                        f'dataset_path = curio_dataset_path("{dataset_id}")\n'
                        "df = pd.read_csv(dataset_path)\n"
                    ),
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
            "datasets": [],
        }
    }
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def test_a_code_reference_does_not_keep_the_store_folder_alive(
    client, user_and_token, tmp_path, monkeypatch
):
    """The regression: the folder and the card both survived an uninstall."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        create_project,
    )

    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    imported = _import(client, token)
    dataset_id, dir_name = imported["id"], imported["dirName"]
    store_dir = dataset_dir(str(user.id), dir_name)
    assert store_dir.is_dir()

    project_id = create_project(client, token, name="Install target")
    inst = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        headers=_auth(token),
        data=json.dumps({"datasetId": dataset_id}),
    )
    assert inst.status_code in (200, 201), inst.get_data(as_text=True)

    # A SECOND project that names the dataset in code only. This is what the
    # existing lifecycle test lacks, and the only reason it passes today.
    _project_with_loader(client, token, dataset_id)

    un = client.delete(
        f"/api/dataflows/{project_id}/datasets/{dataset_id}", headers=_auth(token)
    )
    assert un.status_code == 200, un.get_data(as_text=True)

    assert not store_dir.exists(), (
        "a code-only mention must not keep the store folder alive: applying a "
        "dataset writes curio_dataset_path into the node, so this is the "
        "ordinary flow, not an edge case"
    )
    listed = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
    assert dataset_id not in {i["id"] for i in listed}


def test_usage_marks_a_code_only_dataflow_so_the_warning_can_be_honest(
    client, user_and_token
):
    """``codeOnly`` is what stops the confirmation dialog lying.

    The dialog predicts "the uploaded file is also deleted" by counting
    usages. If it counted code-only ones it would promise the file survives
    while the gate - which ignores them - deletes it. One request has to answer
    both questions: what blocks deletion, and what merely dangles afterwards.
    """
    _user, token = user_and_token

    imported = _import(client, token, name="flagged.csv")
    dataset_id = imported["id"]
    _project_with_loader(client, token, dataset_id, name="Code-only user")

    resp = client.get(f"/api/datasets/{dataset_id}/usage", headers=_auth(token))
    dataflows = resp.get_json()["dataflows"]

    by_name = {d["dataflowName"]: d for d in dataflows}
    assert by_name["Code-only user"]["codeOnly"] is True


def test_usage_still_reports_the_code_reference(client, user_and_token):
    """Narrowing the gate must not narrow what the detail page shows (#250)."""
    _user, token = user_and_token

    imported = _import(client, token, name="usage.csv")
    dataset_id = imported["id"]
    _project_with_loader(client, token, dataset_id, name="Code-only user")

    resp = client.get(f"/api/datasets/{dataset_id}/usage", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    names = {d["dataflowName"] for d in resp.get_json()["dataflows"]}
    assert "Code-only user" in names, (
        "/usage must still see code references; only the destructive gate opts out"
    )
