"""Unit tests for computed output path resolution and catalog dedupe."""
from __future__ import annotations

def test_resolve_computed_output_path_present(app):
    """A file present in the shared-data dir should be resolved correctly."""
    import os
    from pathlib import Path

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    output_file = shared / "my_output.csv"
    output_file.write_text("a,b\n1,2\n", encoding="utf-8")

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/my_output.csv",
        "path": "my_output.csv",
    }
    resolved = svc._resolve_computed_output_path(item)
    assert resolved == str(output_file)


def test_resolve_computed_output_path_missing(app):
    """If the output file does not exist, None is returned (no exception)."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/ghost.csv",
        "path": "ghost.csv",
    }
    assert svc._resolve_computed_output_path(item) is None


def test_resolve_item_path_delegates_for_computed(app):
    """_resolve_item_path routes curio://outputs/ URIs through the computed resolver."""
    import os
    from pathlib import Path

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "scores.csv").write_text("id,score\n1,99\n", encoding="utf-8")

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/scores.csv",
        "path": "curio://outputs/scores.csv",
    }
    result = svc._resolve_item_path(item)
    assert result is not None
    assert result.endswith("scores.csv")
def test_dedupe_prefers_installed_copy_over_live_output(tmp_path):
    """When the same computed id appears as an installed folder and a live
    output row, dedupe must keep the installed record (dirName + user path)."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user_file = tmp_path / "store.parquet"
    user_file.write_bytes(b"PAR1")
    svc = DatasetCatalogService()
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
    merged = svc._dedupe_items([installed, live])
    assert len(merged) == 1
    assert merged[0]["dirName"] == "computed.node-abc@1"
    assert merged[0]["path"] == user_file.as_posix()

