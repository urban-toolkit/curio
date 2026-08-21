"""Regression test: dataset delete/unpublish must be publisher-scoped.

Blocker (code review ``DEL-OWNERSHIP``): ``unpublish_dataset`` removed any
matching directory from the SHARED catalog tree with no ownership check, and
``delete_dataset`` cascaded into it. Any authenticated user could therefore
delete — and, via the store-copy step — silently exfiltrate another user's
published dataset. Both ``DELETE /api/datasets/<id>`` and
``DELETE /api/datasets/publish/<id>`` are behind only ``@require_auth``.

The fix gates removal on ``manifest.publisher == str(caller)``; a non-owner gets
403, the shared catalog dir is untouched, and no stealth copy lands in the
non-owner's store.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest
from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _make_user(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSession(user_id=u.id, token=token))
    db.session.commit()
    return u


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


def test_non_owner_cannot_delete_or_unpublish(app, db, client, catalog_root):
    alice = _make_user(db, "alice", "alice-tok")
    _make_user(db, "bob", "bob-tok")

    dataset_id = "computed.owned-by-alice"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher=str(alice))

    # Bob (not the publisher) is refused by BOTH delete endpoints.
    for url in (f"/api/datasets/{dataset_id}", f"/api/datasets/publish/{dataset_id}"):
        resp = client.delete(url, headers=auth_headers("bob-tok"))
        assert resp.status_code == 403, (url, resp.get_data(as_text=True))

    # The shared catalog copy is untouched...
    assert pub_dir.is_dir()
    assert (pub_dir / "data" / "out.csv").is_file()
    # ...and Bob did not silently acquire a copy in his own store.
    from utk_curio.backend.app.users.models import User
    bob = User.query.filter_by(username="bob").one()
    assert not ds_storage.list_user_datasets(str(bob.id))


def test_publisher_can_unpublish_own_dataset(app, db, client, catalog_root):
    alice = _make_user(db, "alice", "alice-tok")
    dataset_id = "computed.owned-by-alice"
    pub_dir = _publish_dir(catalog_root, dataset_id, publisher=str(alice))

    resp = client.delete(
        f"/api/datasets/publish/{dataset_id}", headers=auth_headers("alice-tok")
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    # Owner unpublish removes the shared catalog copy.
    assert not pub_dir.exists()
