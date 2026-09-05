"""Tests for projects/services.py — business logic."""
import copy

import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, OutputRef, ProjectUpdate
from utk_curio.backend.app.projects.repositories import NotFoundError


def _make_spec(name="test"):
    # A complete trill, per docs/schemas/trill.v1.json — see the note on _spec()
    # in test_routes.py for why the round-trip assertions need all six fields.
    return {
        "dataflow": {
            "name": name,
            "nodes": [],
            "edges": [],
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": name,
        }
    }


def test_save_new_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    data = ProjectCreate(name="My Project", spec=_make_spec(), outputs=[])
    detail = services.save_project(user, data)
    assert detail.id
    assert detail.name == "My Project"
    assert detail.spec_revision == 1
    assert storage.read_spec(services._user_dir_key(user), detail.id) == _make_spec()

def test_rename_project(app, db, user_and_token, tmp_curio):
    from utk_curio.backend.app.projects.schemas import _slugify

    user, _ = user_and_token
    data = ProjectCreate(name="Old Name", spec=_make_spec(), outputs=[])
    detail = services.save_project(user, data)
    assert detail.name == "Old Name"

    # Verifying the change
    summary = services.rename_project(user, detail.id, "New Name")
    assert summary.name == "New Name", "Did not return as expected"
    assert summary.id == detail.id, "Did not return as expected"
    assert summary.slug == _slugify("New Name"), "Did not return as expected"

    # Verifying that the change persisted
    db.session.expire_all()
    result = services.load_project(user, detail.id)
    assert result["project"].name == "New Name", "Failed the persistence check or didn't load properly"
    assert result["project"].slug == _slugify("New Name"), "Failed the persistence check or didn't load properly"


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
    # A rename now mirrors into ``spec.dataflow.name`` (#230) - the name has two
    # stores and they have to agree. Everything ELSE in the spec, dataset refs
    # included, must still come back byte-identical, so the expectation is the
    # saved spec with exactly that one field moved: still a full-equality check,
    # just one that no longer asserts the two stores may disagree.
    expected_spec = copy.deepcopy(saved_spec)
    expected_spec["dataflow"]["name"] = "Renamed"
    assert loaded["spec"] == expected_spec
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


def test_load_shared_project(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "data1.data").write_bytes(b"payload")

    data = ProjectCreate(
        name="Load Shared Test",
        spec=_make_spec("Shared Project"),
        outputs=[OutputRef(node_id="n1", filename="data1.data")],
    )
    detail = services.save_project(user, data)

    result = services.load_shared_project(detail.id)
    assert result["spec"] == _make_spec("Shared Project"), f"{result["spec"]} does not equal {_make_spec("Shared Project")}"
    assert len(result["outputs"]) == 1
    assert result["outputs"][0]["node_id"] == "n1"

    assert result["project"].folder_path == ""

    from utk_curio.backend.app.projects import repositories as repo
    db_project = repo.get_for_user(detail.id, user.id)
    assert db_project.last_opened_at is None


def test_list_projects(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    services.save_project(user, ProjectCreate(name="P1", spec=_make_spec()))
    services.save_project(user, ProjectCreate(name="P2", spec=_make_spec()))

    items = services.list_projects(user)
    assert len(items) == 2


def test_delete_removes_the_row_and_the_files(app, db, user_and_token, tmp_curio):
    """Delete is a hard delete. There is no soft variant since Archive was
    removed (#261) — nothing survives it to be listed under another scope."""
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Del", spec=_make_spec()))
    proj_dir = storage.project_dir(services._user_dir_key(user), detail.id)
    assert proj_dir.exists()

    services.delete_project(user, detail.id)
    assert not proj_dir.exists()

    assert services.list_projects(user) == []


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

    result = services._auto_install_computed_outputs("1", refs, spec, dataflow_id="df-b3")

    # The spec's datasets are returned unchanged — no ref written, junk preserved.
    assert result["dataflow"]["datasets"] == ["junk", None, 123]
    # The output was saved to the account store, namespaced by the dataflow.
    assert (dataset_dir("1", "computed.df-b3.b3node@1") / "manifest.json").is_file()


def test_auto_install_without_dataflow_id_persists_nothing(app, tmp_curio):
    """#166: no dataflow id → no legacy un-namespaced dir is ever written."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "nodf_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    refs = [OutputRef(node_id="nodf", filename="nodf_out.csv")]
    failures: list = []
    result = services._auto_install_computed_outputs(
        "1", refs, {"dataflow": {"datasets": []}}, failures
    )

    assert result["dataflow"]["datasets"] == []
    assert not any(d.name.startswith("computed.nodf") for d in list_user_datasets("1"))
    assert len(failures) == 1 and "dataflow id" in failures[0]["reason"]


def test_prune_sink_node_dataset_refs(app, tmp_curio):
    """Dataset refs keyed on a visualization/sink node are pruned on save; the
    real producer's ref stays. The account-store dir SURVIVES the prune (#174):
    account-level assets are shared across dataflows, and only an explicit
    delete_dataset may remove them."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    # Install two computed datasets: a transform (producer) and a vis node
    # (passthrough duplicate, same data).
    install_computed_file_for_node(
        "1", b"a,b\n1,2\n", "out.csv", "csv", node_id="transform-x", dataflow_id="df-p",
    )
    install_computed_file_for_node(
        "1", b"a,b\n1,2\n", "out.csv", "csv", node_id="visnode-y", dataflow_id="df-p",
    )
    vis_dir = dataset_dir("1", "computed.df-p.visnode-y@1")
    assert vis_dir.exists()

    spec = {
        "dataflow": {
            "nodes": [
                {"id": "transform-x", "type": "curio.builtin/data-transformation"},
                {"id": "visnode-y", "type": "curio.builtin/vis-vega"},
                # Palette-dragged sinks carry the versioned form (#169).
                {"id": "visnode-z", "type": "curio.builtin/vis-simple@1"},
            ],
            "datasets": [
                {"datasetId": "computed.df-p.transform-x", "dirName": "computed.df-p.transform-x@1",
                 "origin": "computed", "producerNodeId": "transform-x"},
                {"datasetId": "computed.df-p.visnode-y", "dirName": "computed.df-p.visnode-y@1",
                 "origin": "computed", "producerNodeId": "visnode-y"},
                {"datasetId": "computed.df-p.visnode-z", "dirName": "computed.df-p.visnode-z@1",
                 "origin": "computed", "producerNodeId": "visnode-z"},
            ],
        }
    }

    pruned = services._prune_sink_node_dataset_refs(spec)

    ds = pruned["dataflow"]["datasets"]
    producers = {r["producerNodeId"] for r in ds}
    assert producers == {"transform-x"}, producers       # vis refs pruned
    assert vis_dir.exists()                                # shared dir KEPT (#174)
    assert spec["dataflow"]["datasets"] != ds              # original not mutated in place


def test_prune_sink_node_dataset_refs_noop_without_sink(app, tmp_curio):
    """No sink nodes → spec returned unchanged (same object)."""
    spec = {"dataflow": {
        "nodes": [{"id": "t", "type": "curio.builtin/data-transformation"}],
        "datasets": [{"datasetId": "computed.t", "producerNodeId": "t", "dirName": "computed.t@1"}],
    }}
    assert services._prune_sink_node_dataset_refs(spec) is spec


def test_auto_install_skips_sink_node_outputs(app, tmp_curio):
    """#174 prevention: a sink node's passthrough output is never persisted, so
    no duplicate dir exists for the ref prune to worry about."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "sink_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (shared / "prod_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    spec = {"dataflow": {
        "nodes": [
            {"id": "prod-n", "type": "curio.builtin/data-transformation"},
            {"id": "sink-n", "type": "curio.builtin/vis-vega@1"},
        ],
        "datasets": [],
    }}
    refs = [
        OutputRef(node_id="prod-n", filename="prod_out.csv"),
        OutputRef(node_id="sink-n", filename="sink_out.csv"),
    ]
    failures: list = []
    services._auto_install_computed_outputs("1", refs, spec, failures, dataflow_id="df-sink")

    names = {d.name for d in list_user_datasets("1")}
    assert "computed.df-sink.prod-n@1" in names
    assert not any("sink-n" in n for n in names)
    assert failures == []  # a skipped sink is intentional, not a failure


def test_duplicate_project_does_not_delete_source_sink_dir(app, db, user_and_token, tmp_curio):
    """#174: duplicating a project copies its refs verbatim — an inherited
    sink-node ref must not rmtree the ORIGINAL project's account-store dir."""
    from utk_curio.backend.app.datasets.install.installer import (
        computed_dataset_id,
        install_computed_file_for_node,
    )
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    user, _ = user_and_token
    user_key = services._user_dir_key(user)

    # Original project with a sink node; its store dir exists (legacy leftover
    # from before the prevention landed).
    original = services.save_project(
        user,
        ProjectCreate(name="Original", spec={"dataflow": {
            "name": "Original",
            "nodes": [{"id": "vis-1", "type": "curio.builtin/vis-vega"}],
            "edges": [],
        }}),
    )
    install_computed_file_for_node(
        user_key, b"a\n1\n", "vis_out.csv", "csv",
        node_id="vis-1", dataflow_id=original.id,
    )
    src_id = computed_dataset_id("vis-1", original.id)
    src_dir = dataset_dir(user_key, f"{src_id}@1")
    assert src_dir.exists()

    # Wire the sink ref into the original's spec (the shape duplicate copies).
    from utk_curio.backend.app.projects import storage as project_storage
    spec = project_storage.read_spec(user_key, original.id)
    spec["dataflow"]["datasets"] = [{
        "datasetId": src_id,
        "dirName": f"{src_id}@1",
        "origin": "computed", "producerNodeId": "vis-1",
    }]
    project_storage.write_spec(user_key, original.id, spec)

    services.duplicate_project(user, original.id)

    # The copy's save pruned the inherited sink ref — but the ORIGINAL
    # project's store dir must survive.
    assert src_dir.exists()


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


def test_load_serves_the_effective_lockfile_not_the_raw_list(app, db, user_and_token, tmp_curio):
    """memo dev/101 D3: the frontend seeds its palette/registry mirror from the
    list it loads. A clobbered ``[]`` with a package node on the canvas must
    load as the backfilled list the backend itself acts on — otherwise the
    palette shows 0 and the node paints "Loading node…" forever."""
    from utk_curio.backend.app.packages import services as packages_services

    user, _ = user_and_token
    ukey = services._user_dir_key(user)
    detail = services.save_project(
        user, ProjectCreate(name="Heal", spec={"dataflow": {"nodes": [], "edges": [], "packages": []}}),
    )
    packages_services.install_to_project(ukey, detail.id, "ai.urbanlab.uhvi@1")
    spec = storage.read_spec(ukey, detail.id)
    spec["dataflow"]["nodes"] = [{"id": "n1", "type": "ai.urbanlab.uhvi/uhvi-load@1"}]
    spec["dataflow"]["packages"] = []
    storage.write_spec(ukey, detail.id, spec)

    loaded = services.load_project(user, detail.id)
    assert loaded["spec"]["dataflow"]["packages"] == ["ai.urbanlab.uhvi@1"]
    assert loaded["project"].spec["dataflow"]["packages"] == ["ai.urbanlab.uhvi@1"]
    # On disk it is still ``[]`` until the next save writes it down (commit 1).
    assert storage.read_spec(ukey, detail.id)["dataflow"]["packages"] == []


def test_load_leaves_a_spec_without_the_packages_key_alone(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Legacy", spec=_make_spec()))
    loaded = services.load_project(user, detail.id)
    assert "packages" not in loaded["spec"]["dataflow"]


class TestSyncDataflowName:
    """``_sync_dataflow_name`` mirrors an explicit rename into the spec (#230).

    Kept separate from ``_ensure_dataflow_identity`` on purpose: that one is a
    backfill and must never overwrite a spec's own name (#148), while this one
    exists precisely to overwrite it — but only when the caller asked to rename.
    """

    def test_renames_and_reports_the_change(self):
        spec = _make_spec("old")
        assert services._sync_dataflow_name(spec, "new") is True
        assert spec["dataflow"]["name"] == "new"

    def test_leaves_provenance_id_alone(self):
        # Already-recorded provenance versions are keyed on the old name, so
        # rewriting this would orphan them.
        spec = _make_spec("old")
        services._sync_dataflow_name(spec, "new")
        assert spec["dataflow"]["provenance_id"] == "old"

    def test_touches_nothing_else_in_the_spec(self):
        spec = _make_spec("old")
        before = {k: v for k, v in spec["dataflow"].items() if k != "name"}
        services._sync_dataflow_name(spec, "new")
        after = {k: v for k, v in spec["dataflow"].items() if k != "name"}
        assert after == before

    def test_reports_no_change_when_the_name_already_matches(self):
        # The caller uses the return value to decide whether to rewrite the spec
        # file, so a no-op rename must not dirty it.
        spec = _make_spec("same")
        assert services._sync_dataflow_name(spec, "same") is False

    @pytest.mark.parametrize(
        "spec",
        [None, "not a dict", 42, {}, {"dataflow": None}, {"dataflow": "nope"}],
    )
    def test_tolerates_a_spec_it_cannot_use(self, spec):
        assert services._sync_dataflow_name(spec, "new") is False

    @pytest.mark.parametrize("name", [None, "", 0, 123])
    def test_ignores_a_name_that_is_not_a_rename(self, name):
        spec = _make_spec("old")
        assert services._sync_dataflow_name(spec, name) is False
        assert spec["dataflow"]["name"] == "old"
