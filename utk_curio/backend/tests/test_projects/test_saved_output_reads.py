"""A dataflow's saved output is read where its owner's Data Catalog keeps it.

``storage.saved_output_file`` names that file for a filename the project's
manifest records. The canvas's output routes hand it to the sandbox as
``savedPath``, which the sandbox reads when its store has no row of that name
for the caller's session, so a reopen reads the one file the Data Catalog
keeps. A name the dataflow did not save, or another dataflow's, is never
named.
"""
import json

from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.schemas import OutputRef
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project

SAVED = "1700000000020_beef0020_output.parquet"


def _save(user_key, project_id, node_id="node-a", name=SAVED, data_type="dataframe"):
    """A node's output saved as a run saves it: its computed dataset, and the
    manifest entry that names it. Returns the dataset's data file."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node

    result = install_computed_file_for_node(
        user_key, b"PAR1 a table", name, "parquet", node_id=node_id, dataflow_id=project_id,
    )
    storage.write_manifest(
        user_key, project_id, 1, [OutputRef(node_id=node_id, filename=name, data_type=data_type)],
    )
    return result.dest / result.manifest.data_file


# ── the resolver ────────────────────────────────────────────────────────────

def test_a_name_the_manifest_records_is_read_from_its_nodes_dataset(tmp_curio):
    held = _save("1", "proj-saved")

    saved = storage.saved_output_file("1", "proj-saved", SAVED)

    assert saved is not None
    assert (saved.path, saved.data_type) == (held, "dataframe")
    assert not (storage._shared_data_dir() / SAVED).exists(), "reading it made a copy"


def test_a_name_the_manifest_does_not_record_is_read_from_nowhere(tmp_curio):
    _save("1", "proj-saved")

    assert storage.saved_output_file("1", "proj-saved", "1700000000021_beef0021") is None
    assert storage.saved_output_file("1", "proj-other", SAVED) is None


def test_a_name_that_is_not_one_safe_component_is_read_from_nowhere(tmp_curio):
    _save("1", "proj-saved")

    for name in ("../" + SAVED, "a/" + SAVED, "..", ""):
        assert storage.saved_output_file("1", "proj-saved", name) is None, name


def test_a_node_that_reads_an_installed_dataset_is_read_from_that_dataset(tmp_curio):
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node

    installed = install_computed_file_for_node(
        "1", b"PAR1 a dataset", "elsewhere.parquet", "parquet",
        node_id="producer", dataflow_id="proj-elsewhere",
    )
    storage.write_spec("1", "proj-loader", {"dataflow": {"nodes": [], "edges": [], "datasets": [{
        "datasetId": installed.manifest.id, "dirName": installed.manifest.dir_name,
        "origin": "computed", "producerNodeId": "loader",
    }]}})
    storage.write_manifest(
        "1", "proj-loader", 1, [OutputRef(node_id="loader", filename=SAVED, data_type="dataframe")],
    )

    saved = storage.saved_output_file("1", "proj-loader", SAVED)

    assert saved is not None and saved.path == installed.dest / installed.manifest.data_file


# ── the canvas's output routes ──────────────────────────────────────────────

def _sandbox_reads(monkeypatch):
    """Record what each read asks the sandbox, which answers that it cannot
    be reached."""
    from utk_curio.backend.app.api import routes as api_routes

    asked = []

    def fake(method, path, **kwargs):
        asked.append((path, dict(kwargs.get("params") or {})))
        return "the sandbox cannot be reached", 503

    monkeypatch.setattr(api_routes, "_sandbox_call", fake)
    return asked


def _user_key(user):
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def test_each_output_route_hands_the_sandbox_the_saved_file(client, user_and_token, monkeypatch):
    user, token = user_and_token
    project_id = create_project(client, token, name="Saved reads")
    held = _save(_user_key(user), project_id)
    asked = _sandbox_reads(monkeypatch)

    for read in ("get", "get-preview", "raster"):
        resp = client.get(f"/api/projects/{project_id}/outputs/{read}?fileName={SAVED}",
                          headers=auth_headers(token))
        assert resp.status_code == 503, (read, resp.get_data(as_text=True))

    assert [path for path, _params in asked] == ["/get", "/get", "/raster"]
    for _path, params in asked:
        assert (params["fileName"], params["sessionId"]) == (SAVED, token)
        assert params["savedPath"] == str(held)


def test_a_name_the_dataflow_did_not_save_goes_to_the_store_alone(client, user_and_token, monkeypatch):
    user, token = user_and_token
    project_id = create_project(client, token, name="Live reads")
    _save(_user_key(user), project_id)
    asked = _sandbox_reads(monkeypatch)
    live = "1700000000022_beef0022"

    client.get(f"/api/projects/{project_id}/outputs/get?fileName={live}", headers=auth_headers(token))

    ((_path, params),) = asked
    assert (params["fileName"], params["sessionId"]) == (live, token)
    assert "savedPath" not in params


def test_another_dataflows_saved_output_is_not_named_on_this_one(client, user_and_token, monkeypatch):
    user, token = user_and_token
    this_one = create_project(client, token, name="This one")
    other = create_project(client, token, name="The other one")
    _save(_user_key(user), other)
    asked = _sandbox_reads(monkeypatch)

    client.get(f"/api/projects/{this_one}/outputs/get?fileName={SAVED}", headers=auth_headers(token))

    ((_path, params),) = asked
    assert "savedPath" not in params


def test_an_output_route_of_a_dataflow_that_is_gone_is_a_404(client, user_and_token, monkeypatch):
    _user, token = user_and_token
    asked = _sandbox_reads(monkeypatch)

    resp = client.get(f"/api/projects/no-such-dataflow/outputs/get?fileName={SAVED}",
                      headers=auth_headers(token))

    assert resp.status_code == 404
    assert asked == []


def test_an_output_route_needs_a_sign_in(client, user_and_token, monkeypatch):
    user, token = user_and_token
    project_id = create_project(client, token, name="Signed in")
    _save(_user_key(user), project_id)
    asked = _sandbox_reads(monkeypatch)

    resp = client.get(f"/api/projects/{project_id}/outputs/get?fileName={SAVED}")

    assert resp.status_code == 401
    assert asked == []
