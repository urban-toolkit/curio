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

    updated = services.update_project(user, detail.id, ProjectUpdate(name="Renamed"))
    loaded = services.load_project(user, detail.id)

    assert updated.name == "Renamed"
    assert loaded["spec"] == _make_spec("keep-me")
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
