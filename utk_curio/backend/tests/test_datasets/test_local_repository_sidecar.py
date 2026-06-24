"""Regression test for the #145 phantom-sidecar finding.

``LocalDatasetRepository.list_items`` scans the data dir and, for any file it
recognizes, lazily writes a ``<file>.meta.json`` counts sidecar. The sidecars
themselves end in ``.json`` (a supported suffix), so an unguarded scan would:

  1. catalog ``foo.csv.meta.json`` as a junk JSON dataset, and
  2. write ``foo.csv.meta.json.meta.json`` for it (meta_path appends again),
     which is itself a new dataset/sidecar target next refresh — unbounded
     ``.meta.json.meta.json...`` growth on disk.

list_items must skip ``.meta.json``/``.decode.json`` files entirely.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.local_repository import LocalDatasetRepository


def _workspace_repo(tmp_path, monkeypatch):
    """A repo whose only root is an isolated tmp workspace dir."""
    repo = LocalDatasetRepository()
    monkeypatch.setattr(repo, "_roots", lambda: [("Workspace data", tmp_path)])
    return repo


def test_sidecars_are_not_cataloged_or_regrown(tmp_path, monkeypatch):
    (tmp_path / "foo.csv").write_text("a,b\n1,2\n3,4\n")
    repo = _workspace_repo(tmp_path, monkeypatch)

    # Refresh several times — the classic trigger for the regression.
    for _ in range(3):
        items = repo.list_items()

    # Exactly one real dataset, the csv. No junk ".meta" dataset.
    assert [i["path"] for i in items] == [(tmp_path / "foo.csv").as_posix()]
    assert all(not i["title"].endswith(".meta") for i in items)

    # The counts sidecar exists, but never a doubled one.
    assert (tmp_path / "foo.csv.meta.json").is_file()
    assert not (tmp_path / "foo.csv.meta.json.meta.json").exists()
    assert not list(tmp_path.glob("*.meta.json.meta.json"))


def test_decode_sidecar_is_skipped(tmp_path, monkeypatch):
    (tmp_path / "bar.parquet.decode.json").write_text('{"cols": []}')
    repo = _workspace_repo(tmp_path, monkeypatch)

    items = repo.list_items()

    assert items == []
    assert not (tmp_path / "bar.parquet.decode.json.meta.json").exists()
