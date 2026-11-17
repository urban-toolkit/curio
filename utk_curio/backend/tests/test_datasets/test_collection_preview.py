"""The Data Catalog's preview of a collection: its index's rows as node code
gets them, their files found and their rows named by one id."""

from __future__ import annotations

import os

import pandas as pd


def test_a_collections_files_are_found_by_the_id_its_rows_are_named_by(app, user_and_token, tmp_path, monkeypatch):
    """Both are the item's id, whose index the preview reads. On every real
    path the id asked is the item's; a catalog whose ``get_dataset`` answers
    with an item of another id (the facade lets a caller override it) once
    showed one id's files under the other's name."""
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir
    from utk_curio.backend.app.datasets.service import DatasetCatalogService
    from utk_curio.backend.app.discovery.application import exec_collections

    user, _token = user_and_token
    service = DatasetCatalogService(user=user)
    held = "imported.xheld@1"
    index = user_datasets_dir(service._paths._user_key()) / held / "data" / "index.parquet"
    index.parent.mkdir(parents=True)
    pd.DataFrame({
        "name": ["a.jpg"], "kind": ["image"], "file_id": ["f1"], "relpath": ["walk/a.jpg"], "ext": ["jpg"],
    }).to_parquet(index)
    # The lookup answers with the item it holds, whichever id it is asked.
    service.get_dataset = lambda *_args, **_kwargs: {  # type: ignore[assignment]
        "id": held, "title": "Walk", "format": "collection", "origin": "imported", "path": str(index),
    }

    def found(ids, _user_key, **_kwargs):
        # Each id's files in a folder of its own, so a row's path says whose it is.
        return {dataset_id: {"root": str(tmp_path / "files" / dataset_id)} for dataset_id in ids}

    monkeypatch.setattr(exec_collections, "resolve_collections", found)
    [row] = service.preview("imported.xasked@1")["rows"]

    assert row["dataset_id"] == held
    assert row["path"] == os.path.join(str(tmp_path / "files" / held), "walk", "a.jpg"), (
        f"the preview named its row {row['dataset_id']} and found its file as another id's: {row['path']}"
    )
