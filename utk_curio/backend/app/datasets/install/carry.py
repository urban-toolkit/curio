"""What a dataset's rows need beyond its table, carried with each copy of it
into another account, and kept for it while it is published.

A saved output's rows name the files a node derived in its run's own folder
(``media_records``), and the collection those files came from, by the id it
has in the account that added it (``installer._install_imported``): another
account holds neither. Every copy of a dataset into another account brings
them (:func:`into_account`): an add of a published dataset
(:func:`from_catalog`), Save a copy into another account
(``projects/services._copy_saved_outputs``) and an owner's Apply of an invited
editor's dataset (``datasets/application/editor_requests``). It links the
runs' folders the rows name into the target's media folder under the same
names; it puts each collection they name that the shared catalog does not hold
in the target's store under its own id, with only the files they name; and it
points each row's ``path`` at the target's copy of its file
(:func:`point_paths_at`).

Publishing keeps the same for the published dataset in a companion folder
(:func:`publish`, :func:`companion`) beside the accounts' folders, on the same
disk as every media folder, so its files are linked there, never copied. An
unpublish removes it (:func:`unpublish`); copies already added keep theirs.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

#: In Curio's state folder, beside the accounts' folders: one companion
#: folder per published dataset (:func:`companion`).
PUBLISHED = "published"
#: In a companion: the collections its rows name, each in its store folder.
COLLECTIONS = "collections"
#: The lock file of an account's store that one copy into it at a time holds.
_LOCK_NAME = ".carry.lock"
_LOCK_NAMESPACE = "carried-files"
#: A path in a run's own folder, ``<media>/kept/<name>/<the file>``: the
#: folder's name and the file's place in it.
_RUN_FILE_RE = re.compile(r"^.*[/\\]kept[/\\](k[0-9a-f]{32})[/\\](.+)$")


def companion(entry_name: str) -> Path:
    """The companion folder of the published dataset *entry_name*
    (``<id>@<major>``): ``<state>/published/<entry>/``, holding the runs'
    folders its rows name (``kept/<name>/``) and the collections they name
    (``collections/<store folder>/``)."""
    from utk_curio.backend.app.common.user_storage import users_base
    from utk_curio.backend.app.datasets.infrastructure.storage import DatasetId

    DatasetId.parse_dir(entry_name)
    return users_base().parent / PUBLISHED / entry_name


@dataclass(frozen=True)
class Account:
    """An account whose runs' folders and collections a copy takes from."""

    key: str

    def run_folder(self, name: str) -> Path:
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        return media_dirs.derived_root(self.key, kept=name)

    def collection(self, dataset_id: str) -> Path | None:
        return held(self.key, dataset_id)


@dataclass(frozen=True)
class Companion:
    """A published dataset's companion folder (:func:`companion`), which an
    add takes from."""

    root: Path

    def run_folder(self, name: str) -> Path:
        from utk_curio.sandbox.util.collections import KEPT_MEDIA

        return self.root / KEPT_MEDIA / name

    def collection(self, dataset_id: str) -> Path | None:
        return _held(self.root / COLLECTIONS, dataset_id)


@dataclass
class _Needs:
    """What rows need beyond their table: the runs' folders they name, and
    each collection's files they name, by its id."""

    folders: set[str] = field(default_factory=set)
    files: dict[str, set[str]] = field(default_factory=dict)


def _held(store: Path, dataset_id: str) -> Path | None:
    """The folder of the dataset *dataset_id* in *store*, its newest major."""
    if not store.is_dir():
        return None
    folders = sorted(path for path in store.glob(f"{dataset_id}@*") if (path / "manifest.json").is_file())
    return folders[-1] if folders else None


def held(user_key: str, dataset_id: str) -> Path | None:
    """The folder of the dataset *dataset_id* in the store of the account
    *user_key*; None when it holds none."""
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    return _held(user_datasets_dir(user_key), dataset_id)


def collections_named(folder: Path) -> list[str]:
    """The ids of the collections the rows of the dataset folder *folder*
    name that the shared catalog does not hold: those a copy into another
    account carries (:func:`into_account`), and a dataflow that lists the
    dataset lists with it, so its editors read their files
    (``mutations.install_dataset``)."""
    return sorted(dataset_id for dataset_id in _needs(_data_files(folder)).files if not _shared(dataset_id))


def _shared(dataset_id: str) -> bool:
    """Whether the shared catalog holds *dataset_id*, which every account
    reads: a shipped collection."""
    from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root

    return _held(catalog_root(), dataset_id) is not None


def _data_files(folder: Path) -> list[Path]:
    """The data files of the dataset folder *folder*: its manifest's, and a
    bundle's parts."""
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
    from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts

    data = folder / load_dataset_manifest(folder).data_file
    files = [data]
    if data.name == "bundle.json":
        files += [Path(file) for _part, file in listed_bundle_parts(data)]
    return [file for file in files if file.is_file()]


def _needs(data_files: Iterable[Path]) -> _Needs:
    """What the rows of *data_files* need: the runs' folders their media
    URLs name, and each collection's files, a derived file by the file it was
    derived from."""
    from utk_curio.backend.app.datasets.install import media_records

    needs = _Needs()
    for file in data_files:
        for dataset_id, file_id, kept in media_records.refs_in_file(file):
            if kept:
                needs.folders.add(kept)
            if dataset_id and file_id:
                needs.files.setdefault(dataset_id, set()).add(str(file_id).split("@", 1)[0])
    return needs


def _link_folder(source: Path, target: Path, *, grant_up_to: Path | None = None) -> bool:
    """*source*'s files linked into *target*, a folder that does not exist
    yet, each a second name of the same file (``media_dirs._link_or_copy``),
    built under a temporary name and then renamed, so a copy stopped partway
    leaves none. Its folders are handed to the execution user up to
    *grant_up_to*. Whether it put one."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    if not source.is_dir() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        shutil.copytree(source, staging, copy_function=media_dirs._link_or_copy, symlinks=False)
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    if grant_up_to is not None:
        for folder in [target, *(path for path in target.rglob("*") if path.is_dir())]:
            media_dirs.grant_to_child(folder, up_to=grant_up_to)
    return True


def _write_over(path: Path, table) -> None:
    """Write the Arrow *table* as the parquet file *path*: a new file renamed
    over it, never a write into it, since a copy's file may be a second name
    of its source's (``datasets/install/copy.py``)."""
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        pq.write_table(table, partial)
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def _only(table, wanted) -> object:
    """The rows of the Arrow *table* whose ``file_id`` is in *wanted*."""
    import pyarrow as pa

    return table.filter(pa.array([file_id in wanted for file_id in table["file_id"].to_pylist()]))


def _rows_of(index: Path, wanted: set[str]):
    """The rows of the collection index *index* whose files are *wanted*;
    None for an index with no ``file_id``."""
    import pyarrow.parquet as pq

    table = pq.read_table(index)
    if "file_id" not in table.column_names:
        return None
    return _only(table, wanted)


def _carry_collection(source: Path, target: Path, wanted: set[str]) -> bool:
    """The collection in the store folder *source*, with only its rows of the
    files *wanted*, put in the store folder *target*: copied there under a
    temporary name and renamed when *target* holds none, else the rows it
    lacks added to its index. Its files stay in their source, read with the
    reading account's own access. Whether it changed."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

    manifest = load_dataset_manifest(source)
    rows = _rows_of(source / manifest.data_file, wanted)
    if rows is None or rows.num_rows == 0:
        return False
    if (target / "manifest.json").is_file():
        index = target / load_dataset_manifest(target).data_file
        held = pq.read_table(index)
        lacking = set(rows["file_id"].to_pylist()) - set(held["file_id"].to_pylist())
        extra = _only(rows, lacking)
        if extra.num_rows == 0:
            return False
        _write_over(index, pa.concat_tables([held, extra], promote_options="permissive"))
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        staging.mkdir()
        shutil.copy2(source / "manifest.json", staging / "manifest.json")
        _write_over(staging / manifest.data_file, rows)
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return True


def point_paths_at(data_file: Path, target_key: str) -> bool:
    """Point each ``path`` value of the parquet file *data_file* that lies in
    a run's own folder (``<media>/kept/<name>/...``) at the same file of that
    folder in the media folder of the account *target_key*, which holds the
    copy's files under the same names: a node of that account reading a row
    opens its own copy. Written as a new file renamed over it
    (:func:`_write_over`). Whether it changed."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    if data_file.suffix.lower() != ".parquet" or not data_file.is_file():
        return False
    table = pq.read_table(data_file)
    if "path" not in table.column_names:
        return False
    at = table.column_names.index("path")
    column = table.column(at)
    if not (pa.types.is_string(column.type) or pa.types.is_large_string(column.type)):
        return False
    changed = False
    values = []
    for value in column.to_pylist():
        found = _RUN_FILE_RE.match(value) if isinstance(value, str) else None
        if found is not None:
            moved = str(media_dirs.derived_root(target_key, kept=found.group(1)) / found.group(2))
            if moved != value:
                value, changed = moved, True
        values.append(value)
    if not changed:
        return False
    metadata = table.schema.metadata
    table = table.set_column(at, table.schema.field(at), pa.array(values, type=column.type))
    _write_over(data_file, table.replace_schema_metadata(metadata))
    return True


def into_account(source, target_key: str, folders: Iterable[Path]) -> None:
    """Bring into the account *target_key* what the rows of the dataset
    folders *folders*, its copies of the *source*'s (an :class:`Account` or a
    :class:`Companion`), need beyond their tables: the runs' folders they
    name, linked into its media folder under the same names
    (:func:`_link_folder`); each collection they name that the shared catalog
    does not hold, in its store under its own id, with only the files they
    name (:func:`_carry_collection`); and each row's ``path`` pointed at its
    copy of the file (:func:`point_paths_at`). What it holds already stays.
    One copy into an account at a time, under its store's lock."""
    from utk_curio.backend.app.common.file_locks import exclusive_lock
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir, user_datasets_dir
    from utk_curio.backend.app.datasets.repositories import index as index_repo
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    data_files = [file for folder in folders for file in _data_files(Path(folder))]
    needs = _needs(data_files)
    if not needs.folders and not needs.files:
        return
    store = user_datasets_dir(target_key)
    store.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(store / _LOCK_NAME, namespace=_LOCK_NAMESPACE, key=target_key):
        up_to = media_dirs.media_work_root(target_key).parent
        for name in sorted(needs.folders):
            _link_folder(source.run_folder(name), media_dirs.derived_root(target_key, kept=name), grant_up_to=up_to)
        for dataset_id, wanted in sorted(needs.files.items()):
            held = None if _shared(dataset_id) else source.collection(dataset_id)
            if held is None:
                continue
            target = dataset_dir(target_key, held.name)
            if _carry_collection(held, target, wanted):
                index_repo.safe_upsert_from_dir(target_key, target)
        for file in data_files:
            point_paths_at(file, target_key)


def publish(publisher_key: str, entry: Path) -> None:
    """Keep for the published dataset *entry*, a folder of the shared
    catalog, what its rows need beyond its table, in its companion
    (:func:`companion`): every data file's record of the runs' folders its
    rows name (``media_records.write_record``), those folders linked from the
    media folder of the account *publisher_key*, and each collection the rows
    name that the shared catalog does not hold, with only the files they name.
    It replaces what an earlier publish of it kept."""
    from utk_curio.backend.app.datasets.install import media_records
    from utk_curio.sandbox.util.collections import KEPT_MEDIA

    data_files = _data_files(entry)
    for file in data_files:
        media_records.write_record(file)
    needs = _needs(data_files)
    source = Account(publisher_key)
    target = companion(entry.name)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        for name in sorted(needs.folders):
            _link_folder(source.run_folder(name), staging / KEPT_MEDIA / name)
        for dataset_id, wanted in sorted(needs.files.items()):
            held = None if _shared(dataset_id) else source.collection(dataset_id)
            if held is not None:
                _carry_collection(held, staging / COLLECTIONS / held.name, wanted)
        shutil.rmtree(target, ignore_errors=True)
        if staging.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def unpublish(entry_name: str) -> None:
    """Remove what publishing kept for the dataset *entry_name*
    (:func:`publish`). Copies already added keep their own."""
    shutil.rmtree(companion(entry_name), ignore_errors=True)


def from_catalog(entry_name: str, target_key: str, dest: Path) -> None:
    """Bring into the account *target_key* what the rows of *dest*, its copy
    of the published dataset *entry_name*, need beyond their table, from
    what publishing kept for it (:func:`publish`)."""
    root = companion(entry_name)
    if root.is_dir():
        into_account(Companion(root), target_key, [dest])
