"""Regression tests: shared-guest sessions cannot write the shared catalog (#222).

Reported as "a shared guest can delete published datasets". The publisher gate
added by ``DEL-OWNERSHIP`` (see ``test_delete_ownership.py``) does not stop it,
for a reason that is structural rather than a missing check: every guest sign-in
resolves to ONE ``User`` row (``users.services.signin_guest`` ->
``_shared_guest_user``), so ``manifest.publisher == str(user)`` is true for guest
B on anything guest A published -- ``User.__repr__`` yields ``<User
'guest_shared'>`` for all of them.

Investigating it surfaced a second, worse hole the report only guessed at:
``publish_dataset`` never checked its DESTINATION. Any authenticated user could
publish over another account's entry, overwriting it. That one is not
guest-specific, so it is covered here for a regular user too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest
from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _stub_publish_source(monkeypatch, dataset_id: str, local_file: Path) -> None:
    """Make ``publish_dataset`` see *local_file* as the dataset's on-disk data.

    ``publish_dataset`` reads the item through ``self._owner.get_dataset`` -- the
    service facade, which the route constructs per request. Patching the facade
    METHOD (rather than the instance) is what reaches that request-built object,
    and it is the same seam ``test_publish_dataset.py`` uses. Building a real
    account-store entry per test would only obscure what is being asserted.
    """
    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )

    def _fake_get_dataset(self, *a, **k):
        return {
            "id": dataset_id,
            "title": "Stub",
            "format": "csv",
            "path": local_file.as_posix(),
            "origin": "computed",
            "producerNodeId": "n1",
        }

    monkeypatch.setattr(DatasetCatalogService, "get_dataset", _fake_get_dataset)


def _make_user(db, username: str, token: str, *, is_guest: bool = False):
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(
        username=username,
        name=username.title(),
        email=f"{username}@test.com",
        is_guest=is_guest,
    )
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSession(user_id=u.id, token=token))
    db.session.commit()
    return u


def _make_shared_guest(db, token: str):
    """The single account every guest sign-in lands on."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    return _make_user(db, CURIO_SHARED_GUEST_USERNAME, token, is_guest=True)


def _publish_dir(catalog_root: Path, dataset_id: str, publisher: str) -> Path:
    d = catalog_root / f"{dataset_id}@1"
    (d / "data").mkdir(parents=True)
    (d / "data" / "out.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    write_manifest(
        DatasetManifest(
            id=dataset_id, name="Owned dataset", version="1.0.0", format="csv",
            description="", publisher=publisher, license="MIT", tags=[],
            data_file="data/out.csv", major=1,
        ),
        d,
    )
    return d


@pytest.fixture()
def catalog_root(tmp_path, monkeypatch):
    root = tmp_path / "shared_catalog"
    root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: root)
    return root


# --------------------------------------------------------------------------
# The reported bug: a guest removing another guest's published dataset.
# --------------------------------------------------------------------------

def test_guest_cannot_delete_or_unpublish_a_guest_published_dataset(
    app, db, client, catalog_root
):
    """The exact reported path, and the one the publisher gate cannot catch.

    The dataset is published BY the shared guest, so ``publisher ==
    str(caller)`` holds for the guest doing the deleting. Only an account-level
    rule can refuse this.
    """
    guest = _make_shared_guest(db, "guest-tok")
    dataset_id = "computed.published-by-a-guest"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher=str(guest))

    for url in (f"/api/datasets/{dataset_id}", f"/api/datasets/publish/{dataset_id}"):
        resp = client.delete(url, headers=auth_headers("guest-tok"))
        assert resp.status_code == 403, (url, resp.get_data(as_text=True))

    # The shared catalog copy survives, data file and all.
    assert pub_dir.is_dir()
    assert (pub_dir / "data" / "out.csv").is_file()
    assert (pub_dir / "manifest.json").is_file()


def test_guest_cannot_remove_a_manifestless_leftover(app, db, client, catalog_root):
    """The no-manifest escape hatch is closed for guests, not for everyone.

    ``_assert_is_publisher`` deliberately skips a directory with no manifest so
    legacy leftovers stay removable (``test_delete_ownership`` pins that). For a
    guest that skip is a way straight past the gate, so the account rule has to
    run first. See the sibling test below for the half that must keep working.
    """
    _make_shared_guest(db, "guest-tok")
    dataset_id = "computed.leftover"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher="someone-else")
    (pub_dir / "manifest.json").unlink()

    resp = client.delete(
        f"/api/datasets/publish/{dataset_id}", headers=auth_headers("guest-tok")
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert pub_dir.is_dir()


def test_a_real_account_can_still_remove_a_manifestless_leftover(
    app, db, client, catalog_root
):
    """The guest rule must not stiffen the gate for everyone else.

    Guards against "fix the guest hole by failing closed on a missing
    manifest", which would strand corrupt leftovers in the shared catalog with
    no way to remove them.
    """
    _make_user(db, "alice", "alice-tok")
    dataset_id = "computed.leftover"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher="someone-else")
    (pub_dir / "manifest.json").unlink()

    resp = client.delete(
        f"/api/datasets/publish/{dataset_id}", headers=auth_headers("alice-tok")
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert not pub_dir.exists()


def test_guest_delete_of_an_unpublished_dataset_is_not_blocked(
    app, db, client, catalog_root
):
    """A guest still owns the guest store; the rule is about SHARED state.

    ``delete_dataset`` cascades through ``unpublish_dataset`` and re-raises any
    403, so an account gate placed before the "not published" 404 would stop a
    guest deleting a dataset of their own that was never published. The gate
    therefore sits after the lookup. A 404 here means the cascade got past the
    account rule and found nothing to unpublish, which is the correct path.
    """
    _make_shared_guest(db, "guest-tok")

    resp = client.delete(
        "/api/datasets/publish/computed.never-published",
        headers=auth_headers("guest-tok"),
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)


# --------------------------------------------------------------------------
# The hole found while investigating: publish never checked its destination.
# --------------------------------------------------------------------------

def test_a_user_cannot_publish_over_another_users_dataset(
    app, db, client, catalog_root, monkeypatch, tmp_path
):
    """The write-side hole: publish resolved a path and mkdir'd into it.

    ``dest`` is derived from the dataset id, so two accounts collide on it.
    Before the fix this overwrote the incumbent's manifest and data with no
    check at all.
    """
    alice = _make_user(db, "alice", "alice-tok")
    _make_user(db, "bob", "bob-tok")

    dataset_id = "computed.contested"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher=str(alice))

    bob_file = tmp_path / "bob.csv"
    bob_file.write_text("x\n9\n", encoding="utf-8")
    _stub_publish_source(monkeypatch, dataset_id, bob_file)

    resp = client.post(
        "/api/datasets/publish",
        json={"datasetId": dataset_id, "title": "Bob version"},
        headers=auth_headers("bob-tok"),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)

    # Alice's entry is byte-for-byte intact -- a 403 that had already written
    # would still have destroyed what it refused to touch.
    assert (pub_dir / "data" / "out.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"
    from utk_curio.backend.app.datasets.domain.manifest import (
        load_dataset_manifest_from_dir,
    )
    assert load_dataset_manifest_from_dir(pub_dir).publisher == str(alice)


def test_publisher_can_still_republish_their_own_dataset(
    app, db, client, catalog_root, monkeypatch, tmp_path
):
    """Republishing your own entry is how an update is applied -- keep it working."""
    alice = _make_user(db, "alice", "alice-tok")
    dataset_id = "computed.mine"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher=str(alice))

    newer = tmp_path / "newer.csv"
    newer.write_text("a,b\n3,4\n", encoding="utf-8")
    _stub_publish_source(monkeypatch, dataset_id, newer)

    resp = client.post(
        "/api/datasets/publish",
        json={"datasetId": dataset_id, "title": "Mine, updated"},
        headers=auth_headers("alice-tok"),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert (pub_dir / "data" / "newer.csv").is_file()


def test_guest_cannot_publish_at_all(
    app, db, client, catalog_root, monkeypatch, tmp_path
):
    """Publishing attributes authorship to an account. A guest has none to give."""
    _make_shared_guest(db, "guest-tok")
    src = tmp_path / "g.csv"
    src.write_text("a\n1\n", encoding="utf-8")
    _stub_publish_source(monkeypatch, "computed.guest-thing", src)

    resp = client.post(
        "/api/datasets/publish",
        json={"datasetId": "computed.guest-thing", "title": "Guest thing"},
        headers=auth_headers("guest-tok"),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert not (catalog_root / "computed.guest-thing@1").exists()
