"""The Data Catalog's two sorts give the same order on every listing (#764).

"Sort: Recent activity" ordered by ``updatedAt`` alone and "Sort: Name" by the
title alone. Two datasets with the same key then kept the order the sources
listed them in, which for the user store is its folder names, and a computed
dataset's folder name holds the project and node ids (new on every run). Two
computed outputs saved in the same second (their manifests are stamped to the
second) so swapped places from one run to the next.

Each test writes its datasets so the store lists them in the REVERSE of the
expected order, checks that it does, and then asks the catalog route for the
sort. A listing that falls back to store order on a tie fails here.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

DATAFLOW = "sortflow"
SAME_SECOND = "2026-10-06T12:00:00Z"
NEXT_SECOND = "2026-10-06T12:00:01Z"


def _user_key(app, user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    with app.app_context():
        return _user_dir_key(user)


def _write_computed(user_key: str, node_id: str, title: str, updated_at: str) -> str:
    """A computed dataset in the user store, as the installer leaves it, with a
    chosen title and ``updatedAt``. Returns its id."""
    from utk_curio.backend.app.datasets.domain.manifest import (
        DatasetManifest,
        write_manifest,
    )
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    dataset_id = computed_dataset_id(node_id, DATAFLOW)
    dest = dataset_dir(user_key, f"{dataset_id}@1")
    (dest / "data").mkdir(parents=True, exist_ok=True)
    (dest / "data" / "out.json").write_bytes(b'{"v": 1}')
    write_manifest(
        DatasetManifest(
            id=dataset_id,
            name=title,
            version="1.0.0",
            format="json",
            description="JSON dataset computed by a dataflow node.",
            publisher="User",
            license="",
            tags=["json", "computed"],
            data_file="data/out.json",
            major=1,
            source_label="Computed",
            created_at=updated_at,
            updated_at=updated_at,
            producer_node_id=node_id,
            producer_dataflow_id=DATAFLOW,
        ),
        dest,
    )
    return dataset_id


def _store_order(user_key: str, ids: list[str]) -> list[str]:
    """The order the user store lists *ids* in (its folder order)."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    names = [root.name for root in list_user_datasets(user_key)]
    return [dataset_id for name in names for dataset_id in ids if name == f"{dataset_id}@1"]


def _listed(client, token, sort: str, ids: list[str]) -> list[str]:
    resp = client.get(
        f"/api/datasets/catalog?includeHub=true&sort={sort}", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    wanted = set(ids)
    return [item["id"] for item in resp.get_json()["items"] if item["id"] in wanted]


def test_recent_breaks_a_same_second_tie_by_title(app, client, user_and_token):
    user, token = user_and_token
    user_key = _user_key(app, user)
    zulu = _write_computed(user_key, "a-node", "Zulu", SAME_SECOND)
    alpha = _write_computed(user_key, "b-node", "Alpha", SAME_SECOND)
    # A newer dataset still leads, whatever its title: the tie-break orders
    # equal times only.
    mike = _write_computed(user_key, "c-node", "Mike", NEXT_SECOND)
    ids = [zulu, alpha, mike]
    assert _store_order(user_key, ids) == [zulu, alpha, mike]

    assert _listed(client, token, "recent", ids) == [mike, alpha, zulu]


def test_recent_breaks_a_tie_of_time_and_title_by_id(app, client, user_and_token):
    user, token = user_and_token
    user_key = _user_key(app, user)
    # "-" sorts before "@", so the folder ``...n-2@1`` lists before ``...n@1``
    # while the id ``...n`` sorts before ``...n-2``.
    first = _write_computed(user_key, "n", "Same title", SAME_SECOND)
    second = _write_computed(user_key, "n-2", "Same title", SAME_SECOND)
    ids = [first, second]
    assert _store_order(user_key, ids) == [second, first]

    assert _listed(client, token, "recent", ids) == [first, second]


def test_name_breaks_a_title_tie_by_id(app, client, user_and_token):
    user, token = user_and_token
    user_key = _user_key(app, user)
    first = _write_computed(user_key, "n", "Same title", SAME_SECOND)
    second = _write_computed(user_key, "n-2", "same TITLE", NEXT_SECOND)
    # The title still comes first: this one's id sorts after both.
    alpha = _write_computed(user_key, "z-node", "Alpha", SAME_SECOND)
    ids = [first, second, alpha]
    assert _store_order(user_key, ids) == [second, first, alpha]

    assert _listed(client, token, "name", ids) == [alpha, first, second]
