"""Unit tests for computed output path resolution and catalog dedupe."""
from __future__ import annotations

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    store_sandbox_artifact,
    stored_artifact_file,
)


def test_resolve_computed_output_path_present(app):
    """An output the store holds resolves to the store's file of it."""
    import pandas as pd

    my_output = store_sandbox_artifact(pd.DataFrame({"a": [1], "b": [2]}))
    output_file = stored_artifact_file(my_output)

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": f"curio://outputs/{my_output}",
        "path": my_output,
    }
    resolved = svc._paths._resolve_computed_output_path(item)
    # _resolve_computed_output_path returns as_posix() by contract; str(Path)
    # is backslashed on Windows, so compare in posix form.
    assert resolved == output_file.as_posix()


def test_resolve_computed_output_path_missing(app):
    """If the output file does not exist, None is returned (no exception)."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/ghost.csv",
        "path": "ghost.csv",
    }
    assert svc._paths._resolve_computed_output_path(item) is None


def test_resolve_item_path_delegates_for_computed(app):
    """_resolve_item_path routes curio://outputs/ URIs through the computed resolver."""
    import pandas as pd

    scores = store_sandbox_artifact(pd.DataFrame({"id": [1], "score": [99]}))

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": f"curio://outputs/{scores}",
        "path": f"curio://outputs/{scores}",
    }
    result = svc._paths._resolve_item_path(item)
    assert result is not None
    assert result == stored_artifact_file(scores).as_posix()


def test_resolve_item_path_installed_computed_uses_absolute_path(app):
    """Installed/published computed datasets resolve via their absolute path.

    Once a computed dataset is installed it carries a ``curio://datasets/{dir}``
    URI and an absolute store path instead of ``curio://outputs/``.  Export must
    still locate the file (regression for the 404-on-export bug).

    The store path lives under an allowed read root in production (the user's
    dataset store); the workspace's ``data/`` folder is used here as a
    stand-in root so the containment check (#143) still passes. The store's
    files are not one: a store file is read only as an output its caller may
    read.
    """
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    data_file = Path(os.environ["CURIO_LAUNCH_CWD"]) / "data" / "computed_output.parquet"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_bytes(b"PAR1")

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://datasets/computed.node-abc@1",
        "path": data_file.as_posix(),
        "dirName": "computed.node-abc@1",
        "installed": True,
    }
    result = svc._paths._resolve_item_path(item)
    assert result == data_file.as_posix()


def test_resolve_item_path_computed_missing_absolute_path_returns_none(app):
    """A computed item whose absolute path no longer exists resolves to None."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://datasets/computed.node-gone@1",
        "path": "/nonexistent/store/computed_output.parquet",
        "dirName": "computed.node-gone@1",
        "installed": True,
    }
    assert svc._paths._resolve_item_path(item) is None


def test_dedupe_prefers_installed_copy_over_live_output(tmp_path):
    """When the same computed id appears as an installed folder and a live
    output row, dedupe must keep the installed record (dirName + user path)."""
    from utk_curio.backend.app.datasets.domain.dedup import dedupe_items

    user_file = tmp_path / "store.parquet"
    user_file.write_bytes(b"PAR1")
    installed = {
        "id": "computed.node-abc",
        "origin": "computed",
        "dirName": "computed.node-abc@1",
        "path": user_file.as_posix(),
        "installed": True,
        "producerNodeId": "node-abc",
    }
    live = {
        "id": "computed.node-abc",
        "origin": "computed",
        "uri": "curio://outputs/live.parquet",
        "path": "live.parquet",
        "producerNodeId": "node-abc",
    }
    merged = dedupe_items([installed, live])
    assert len(merged) == 1
    assert merged[0]["dirName"] == "computed.node-abc@1"
    assert merged[0]["path"] == user_file.as_posix()

