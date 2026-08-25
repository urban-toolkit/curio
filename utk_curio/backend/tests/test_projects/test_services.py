"""Tests for projects/services.py — business logic."""
import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, OutputRef, ProjectUpdate
from utk_curio.backend.app.projects.repositories import NotFoundError


def _make_spec(name="test"):
    return {"dataflow": {"name": name, "nodes": [], "edges": []}}


def test_save_new_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    data = ProjectCreate(name="My Project", spec=_make_spec(), outputs=[])
    detail = services.save_project(user, data)
    assert detail.id
    assert detail.name == "My Project"
    assert detail.spec_revision == 1
    assert storage.read_spec(services._user_dir_key(user), detail.id) == _make_spec()


def test_update_project_bumps_revision(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    data = ProjectCreate(name="Rev Test", spec=_make_spec(), outputs=[])
    detail = services.save_project(user, data)
    assert detail.spec_revision == 1

    update = ProjectUpdate(spec=_make_spec("v2"), outputs=[])
    updated = services.update_project(user, detail.id, update)
    assert updated.spec_revision == 2


def test_metadata_only_update_preserves_spec_and_outputs(
    app, db, user_and_token, tmp_curio
):
    user, _ = user_and_token
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "kept.data").write_bytes(b"payload")

    original = ProjectCreate(
        name="Original",
        spec=_make_spec("keep-me"),
        outputs=[OutputRef(node_id="n1", filename="kept.data")],
    )
    detail = services.save_project(user, original)
    # save_project auto-installs outputs and adds lean dataset refs to the spec.
    saved_spec = detail.spec

    updated = services.update_project(user, detail.id, ProjectUpdate(name="Renamed"))
    loaded = services.load_project(user, detail.id)

    assert updated.name == "Renamed"
    assert loaded["spec"] == saved_spec
    assert loaded["outputs"] == [{"node_id": "n1", "filename": "kept.data"}]


def test_load_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "data1.data").write_bytes(b"payload")

    data = ProjectCreate(
        name="Load Test",
        spec=_make_spec(),
        outputs=[OutputRef(node_id="n1", filename="data1.data")],
    )
    detail = services.save_project(user, data)

    result = services.load_project(user, detail.id)
    assert result["spec"] is not None
    assert len(result["outputs"]) == 1
    assert result["outputs"][0]["node_id"] == "n1"


def test_list_projects(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    services.save_project(user, ProjectCreate(name="P1", spec=_make_spec()))
    services.save_project(user, ProjectCreate(name="P2", spec=_make_spec()))

    items = services.list_projects(user, scope="mine")
    assert len(items) == 2


def test_soft_delete(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Del", spec=_make_spec()))
    services.delete_project(user, detail.id, purge=False)

    items = services.list_projects(user, scope="mine")
    assert len(items) == 0

    archived = services.list_projects(user, scope="archived")
    assert len(archived) == 1


def test_purge_delete(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Purge", spec=_make_spec()))
    proj_dir = storage.project_dir(services._user_dir_key(user), detail.id)
    assert proj_dir.exists()

    services.delete_project(user, detail.id, purge=True)
    assert not proj_dir.exists()

    items = services.list_projects(user, scope="mine")
    assert len(items) == 0


def test_duplicate_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Orig", spec=_make_spec()))
    dup = services.duplicate_project(user, detail.id)
    assert dup.id != detail.id
    assert dup.name == "Orig (copy)"


def test_ownership_404(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Private", spec=_make_spec()))

    from utk_curio.backend.app.users.models import User, UserSession
    other = User(username="bob", name="Bob")
    db.session.add(other)
    db.session.flush()

    with pytest.raises(NotFoundError):
        services.load_project(other, detail.id)


def test_shared_guest_can_save(app, db, guest_user_and_token, tmp_curio):
    user, _ = guest_user_and_token
    user.username = services.CURIO_SHARED_GUEST_USERNAME
    db.session.commit()

    first = services.save_project(user, ProjectCreate(name="Shared1", spec=_make_spec()))
    second = services.save_project(user, ProjectCreate(name="Shared2", spec=_make_spec()))

    assert first.id
    assert second.id


def test_guest_cannot_create_project(app, db, guest_user_and_token, tmp_curio):
    user, _ = guest_user_and_token

    with pytest.raises(services.ProjectError, match="Guest users cannot save"):
        services.save_project(user, ProjectCreate(name="Blocked", spec=_make_spec()))


def test_guest_cannot_update_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_make_spec()))

    user.is_guest = True
    db.session.commit()

    with pytest.raises(services.ProjectError, match="Guest users cannot save"):
        services.update_project(user, detail.id, ProjectUpdate(name="Renamed"))


def test_non_guest_can_save_and_update(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token

    detail = services.save_project(user, ProjectCreate(name="RealUser", spec=_make_spec()))
    assert detail.id

    updated = services.update_project(user, detail.id, ProjectUpdate(name="Renamed"))
    assert updated.name == "Renamed"


def test_auto_install_computed_outputs_saves_account_level_no_ref(app, tmp_curio):
    """Computed outputs are saved to the account store with NO project ref, and a
    non-dict entry in client-supplied dataflow.datasets is left untouched (never
    iterated), so it can't 500 the save (review finding B3)."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "b3_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    spec = {"dataflow": {"datasets": ["junk", None, 123]}}
    refs = [OutputRef(node_id="b3node", filename="b3_out.csv")]

    result = services._auto_install_computed_outputs("1", refs, spec)

    # The spec's datasets are returned unchanged — no ref written, junk preserved.
    assert result["dataflow"]["datasets"] == ["junk", None, 123]
    # The output was saved to the account store (un-namespaced here: no dataflow_id).
    assert (dataset_dir("1", "computed.b3node@1") / "manifest.json").is_file()


def test_prune_sink_node_dataset_refs(app, tmp_curio):
    """Dataset refs keyed on a visualization/sink node are pruned on save and
    their orphaned user-store dir is removed; the real producer's ref stays."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    # Install two computed datasets: a transform (producer) and a vis node
    # (passthrough duplicate, same data).
    install_computed_file_for_node("1", b"a,b\n1,2\n", "out.csv", "csv", node_id="transform-x")
    install_computed_file_for_node("1", b"a,b\n1,2\n", "out.csv", "csv", node_id="visnode-y")
    vis_dir = dataset_dir("1", "computed.visnode-y@1")
    assert vis_dir.exists()

    spec = {
        "dataflow": {
            "nodes": [
                {"id": "transform-x", "type": "curio.builtin/data-transformation"},
                {"id": "visnode-y", "type": "curio.builtin/vis-vega"},
            ],
            "datasets": [
                {"datasetId": "computed.transform-x", "dirName": "computed.transform-x@1",
                 "origin": "computed", "producerNodeId": "transform-x"},
                {"datasetId": "computed.visnode-y", "dirName": "computed.visnode-y@1",
                 "origin": "computed", "producerNodeId": "visnode-y"},
            ],
        }
    }

    pruned = services._prune_sink_node_dataset_refs("1", spec)

    ds = pruned["dataflow"]["datasets"]
    producers = {r["producerNodeId"] for r in ds}
    assert producers == {"transform-x"}, producers       # vis ref pruned
    assert not vis_dir.exists()                            # orphaned dir removed
    assert spec["dataflow"]["datasets"] != ds              # original not mutated in place


def test_prune_sink_node_dataset_refs_noop_without_sink(app, tmp_curio):
    """No sink nodes → spec returned unchanged (same object)."""
    spec = {"dataflow": {
        "nodes": [{"id": "t", "type": "curio.builtin/data-transformation"}],
        "datasets": [{"datasetId": "computed.t", "producerNodeId": "t", "dirName": "computed.t@1"}],
    }}
    assert services._prune_sink_node_dataset_refs("1", spec) is spec


def test_save_drops_non_persisted_output_from_manifest(
    app, db, user_and_token, tmp_curio
):
    """#144: an output whose source can't be installed must not be recorded as a
    phantom in the manifest (it would silently vanish on reload)."""
    user, _ = user_and_token
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "good.data").write_bytes(b"payload")
    # "ghost.data" is intentionally absent -> install_node_output returns None.

    data = ProjectCreate(
        name="Phantom",
        spec=_make_spec(),
        outputs=[
            OutputRef(node_id="n1", filename="good.data"),
            OutputRef(node_id="n2", filename="ghost.data"),
        ],
    )
    detail = services.save_project(user, data)

    ukey = services._user_dir_key(user)
    manifest = storage.read_manifest(ukey, detail.id)
    names = {o["filename"] for o in manifest["outputs"]}
    assert names == {"good.data"}, "ghost output must not be persisted as a phantom"

    # The save response and a fresh load both reflect only the durable output.
    assert {o["filename"] for o in (services.load_project(user, detail.id)["outputs"])} == {
        "good.data"
    }


# ---------------------------------------------------------------------------
# memo dev/101 — dataflow.packages is backend-owned on update
# ---------------------------------------------------------------------------

def test_client_save_cannot_clobber_the_project_lockfile(app, db, user_and_token, tmp_curio):
    """The reported bug: the Package Builder's promotion wrote the lockfile,
    then a canvas save from a tab whose mirror still said ``[]`` overwrote it.
    Datasets and agents already survived a client save; packages now do too."""
    from utk_curio.backend.app.packages import services as packages_services

    user, _ = user_and_token
    ukey = services._user_dir_key(user)
    detail = services.save_project(
        user, ProjectCreate(name="Clobber", spec={"dataflow": {"nodes": [], "edges": [], "packages": []}}),
    )
    packages_services.install_to_project(ukey, detail.id, "ai.urbanlab.uhvi@1")
    assert storage.read_spec(ukey, detail.id)["dataflow"]["packages"] == ["ai.urbanlab.uhvi@1"]

    stale = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
    services.update_project(user, detail.id, ProjectUpdate(spec=stale, outputs=[]))

    assert storage.read_spec(ukey, detail.id)["dataflow"]["packages"] == ["ai.urbanlab.uhvi@1"]


def test_client_save_cannot_add_to_the_project_lockfile(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    ukey = services._user_dir_key(user)
    detail = services.save_project(
        user, ProjectCreate(name="Add", spec={"dataflow": {"nodes": [], "edges": [], "packages": []}}),
    )
    services.update_project(
        user, detail.id,
        ProjectUpdate(spec={"dataflow": {"nodes": [], "edges": [], "packages": ["never.installed@1"]}}, outputs=[]),
    )
    assert storage.read_spec(ukey, detail.id)["dataflow"]["packages"] == []


def test_metadata_only_update_does_not_touch_the_lockfile(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    ukey = services._user_dir_key(user)
    detail = services.save_project(user, ProjectCreate(name="Meta", spec=_make_spec()))
    services.update_project(user, detail.id, ProjectUpdate(name="Renamed"))
    assert "packages" not in storage.read_spec(ukey, detail.id)["dataflow"]
