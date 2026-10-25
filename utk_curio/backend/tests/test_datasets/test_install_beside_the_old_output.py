"""A node's new output goes into its computed dataset beside the old one.

A play with Save on installs each new output of a node into the same dataset
folder, ``computed.<dataflow>.<node>@1``, and it does so without the project's
spec lock. The install used to remove the folder first and then write the new
output, so a reader in between (a dashboard being built, a visitor's canvas, a
run reading the saved output as an input) found no output at all. Until now a
copy of each saved output in the shared data directory covered for it.

Now the new output's files go in beside the old one's, the manifest is then
replaced to name them, and only then do the old output's files go. A reader
finds the whole old output or the whole new one, and an install that fails
leaves the old one as it was.

Artifacts are written through the real ``save_to_duckdb``, as node runs write
them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from utk_curio.backend.app.datasets.domain import manifest as manifest_domain
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install import bundle as bundle_module
from utk_curio.backend.app.datasets.install import installer as installer_module
from utk_curio.backend.app.datasets.install.bundle import install_node_output
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import store_sandbox_artifact
from utk_curio.sandbox.util.catalog_helpers import files_read_beside, listed_bundle_parts

USER = "1"
DATAFLOW = "df-beside"
NODE = "py-1"


def _install(art_id: str, data_type: str):
    return install_node_output(
        USER,
        node_id=NODE,
        path_ref=art_id,
        data_type=data_type,
        node_name="Python Computation",
        dataflow_id=DATAFLOW,
        node_type="curio.builtin/computation-analysis",
    )


def _dest() -> Path:
    return dataset_dir(USER, f"{computed_dataset_id(NODE, DATAFLOW)}@1")


def _whole_output(dest: Path):
    """What a reader finds in *dest*: the bytes of the data file its manifest
    names, and of every part a bundle lists, by name. None when the folder
    names no whole output."""
    try:
        manifest = manifest_domain.load_dataset_manifest(dest)
    except Exception:  # noqa: BLE001 - no manifest, or half of one, is no output
        return None
    data = dest / manifest.data_file
    if not data.is_file():
        return None
    if data.name != "bundle.json":
        return {manifest.data_file: data.read_bytes()}
    listed = listed_bundle_parts(data)
    if len(listed) != len(json.loads(data.read_text(encoding="utf-8"))["parts"]):
        return None
    return {entry["file"]: file.read_bytes() for entry, file in listed}


def _files_in(dest: Path) -> set[Path]:
    return {path for path in dest.rglob("*") if path.is_file()}


def _files_of_the_output(dest: Path) -> set[Path]:
    """The files of the output the manifest names: the manifest, the data
    file and the files read beside it, and for a bundle every part it lists
    with theirs."""
    data = dest / manifest_domain.load_dataset_manifest(dest).data_file
    files = {dest / "manifest.json", data, *files_read_beside(data)}
    if data.name == "bundle.json":
        for _entry, part in listed_bundle_parts(data):
            files |= {part, *files_read_beside(part)}
    return {file.resolve() for file in files}


def _table(n: int) -> str:
    return store_sandbox_artifact(pd.DataFrame({"n": list(range(n))}))


def _pair(n: int) -> str:
    return store_sandbox_artifact((pd.DataFrame({"a": [n]}), pd.DataFrame({"b": [n, n]})))


def _record_readers(monkeypatch, module, name: str, seen: list) -> None:
    """Have *module*.*name* note what a reader of the dataset finds each time
    the install calls it, then do what it does."""
    real = getattr(module, name)

    def noting(*args, **kwargs):
        seen.append(_whole_output(_dest()))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, noting)


# -- A reader during an install --------------------------------------------

def test_a_reader_finds_the_old_table_while_the_new_one_goes_in(app, monkeypatch):
    _install(_table(2), "dataframe")
    old = _whole_output(_dest())
    assert old is not None
    seen: list = []
    _record_readers(monkeypatch, installer_module, "_link_or_copy", seen)

    _install(_table(3), "dataframe")

    assert seen, "the new table was never placed"
    assert all(found == old for found in seen), (
        "while the new table went in, a reader found "
        f"{[None if found is None else sorted(found) for found in seen]}, not the old output"
    )
    new = _whole_output(_dest())
    assert new is not None and new != old


def test_a_reader_finds_the_old_bundle_while_the_new_one_goes_in(app, monkeypatch):
    _install(_pair(1), "outputs")
    old = _whole_output(_dest())
    assert old is not None and len(old) == 2
    seen: list = []
    _record_readers(monkeypatch, bundle_module, "_write_frame_sidecar", seen)

    _install(_pair(2), "outputs")

    assert len(seen) == 2, "each new frame part is written with its sidecar"
    assert all(found == old for found in seen), (
        "while the new bundle went in, a reader found "
        f"{[None if found is None else sorted(found) for found in seen]}, not the old output"
    )
    new = _whole_output(_dest())
    assert new is not None and len(new) == 2 and new != old


# -- An install that fails --------------------------------------------------

def test_an_install_that_fails_leaves_the_old_table(app, monkeypatch):
    _install(_table(2), "dataframe")
    old = _whole_output(_dest())

    def disk_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(installer_module, "_link_or_copy", disk_full)
    with pytest.raises(OSError):
        _install(_table(3), "dataframe")

    assert _whole_output(_dest()) == old


def test_an_install_that_fails_leaves_the_old_bundle(app, monkeypatch):
    _install(_pair(1), "outputs")
    old = _whole_output(_dest())

    def disk_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(bundle_module, "_write_frame_sidecar", disk_full)
    with pytest.raises(OSError):
        _install(_pair(2), "outputs")

    assert _whole_output(_dest()) == old


# -- What the folder holds afterwards ---------------------------------------

@pytest.mark.parametrize(
    "first,second",
    [
        ((_table, 2, "dataframe"), (_table, 3, "dataframe")),
        ((_pair, 1, "outputs"), (_pair, 2, "outputs")),
        ((_table, 2, "dataframe"), (_pair, 1, "outputs")),
        ((_pair, 1, "outputs"), (_table, 2, "dataframe")),
    ],
    ids=["table-then-table", "bundle-then-bundle", "table-then-bundle", "bundle-then-table"],
)
def test_the_old_output_files_go_once_the_new_one_is_named(app, first, second):
    make, n, data_type = first
    _install(make(n), data_type)
    make, n, data_type = second

    _install(make(n), data_type)

    dest = _dest()
    assert _whole_output(dest) is not None
    assert {file.resolve() for file in _files_in(dest)} == _files_of_the_output(dest)
    # No folder the old output's parts sat in is left behind.
    assert all(any(folder.iterdir()) for folder in dest.rglob("*") if folder.is_dir())


def test_the_same_output_again_keeps_its_files(app):
    art = _pair(1)
    _install(art, "outputs")
    data_files = {file for file in _files_in(_dest()) if file.name != "manifest.json"}
    before = {file: file.stat().st_ino for file in data_files}

    _install(art, "outputs")

    assert {file: file.stat().st_ino for file in data_files if file.exists()} == before
