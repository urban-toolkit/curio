"""The runs' folders a saved output's rows name, recorded beside its data files.

A node that derives files from a collection's files (a frame, a clip, an
overlay) writes them in its run's own folder (``media_dirs.derived_root``),
whose name the URLs of the rows it derives carry (``?kept=<name>``). A saved
output holds such rows, its own run's or rows it handed on from earlier steps,
so each of its data files has a record of the folders they name beside it,
``<file>.media.json``, read from the rows when the output is installed, by the
rule the dashboard's links read media URLs by (``collections.media_ref``). A
folder a saved output records stays as long as the output does
(``runs/kept.py``), and deleting the output from the Data Catalog removes the
folders nothing else names (``datasets/application/mutations.py``). The record
is a file of the dataset's folder, so every copy of the dataset carries it
(``datasets/install/copy.py``), and it goes with that folder.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: What a data file's record of its rows' folders is named after it.
MEDIA_SIDECAR_SUFFIX = ".media.json"

#: The suffix of a parquet file's decode sidecar, which names its object
#: columns stored as JSON text (``codec.PARQUET_DECODE_SIDECAR_SUFFIX``).
_DECODE_SIDECAR_SUFFIX = ".decode.json"


def record_path(data_path) -> Path:
    """The record of *data_path*'s rows' folders: ``<file>.media.json``."""
    data_path = Path(data_path)
    return data_path.with_name(data_path.name + MEDIA_SIDECAR_SUFFIX)


def _folders_in(value) -> set[str]:
    """The runs' folders the media URLs anywhere in *value* name."""
    from utk_curio.sandbox.util.collections import media_refs

    return {kept for _dataset, _file, kept in media_refs(value) if kept}


def _encoded_columns(data_path: Path) -> set[str]:
    """The columns of the parquet file *data_path* stored as JSON text, as
    its decode sidecar names them."""
    sidecar = data_path.with_name(data_path.name + _DECODE_SIDECAR_SUFFIX)
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else None
    except (OSError, ValueError):
        return set()
    named = payload.get("encoded_object_columns") if isinstance(payload, dict) else None
    return {str(name) for name in named} if isinstance(named, list) else set()


def _folders_in_parquet(data_path: Path) -> set[str]:
    """The runs' folders the rows of a parquet file name: each text column's
    values (the JSON its object columns hold, decoded), and every nested
    column's. A binary column, a feature's geometry among them, holds no URL
    and is not read."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from utk_curio.sandbox.util.collections import media_ref

    def text(kind) -> bool:
        if pa.types.is_dictionary(kind):
            kind = kind.value_type
        return pa.types.is_string(kind) or pa.types.is_large_string(kind)

    schema = pq.read_schema(data_path)
    wanted = [
        field.name for field in schema
        if text(field.type) or pa.types.is_nested(field.type)
    ]
    if not wanted:
        return set()
    table = pq.read_table(data_path, columns=wanted)
    encoded = _encoded_columns(data_path)
    found: set[str] = set()
    for name in wanted:
        column = table.column(name)
        if not text(column.type):
            found |= _folders_in(column.to_pylist())
            continue
        if pa.types.is_dictionary(column.type):
            column = column.cast(column.type.value_type)
        for value in pc.unique(column).to_pylist():
            if not isinstance(value, str):
                continue
            if name in encoded:
                try:
                    found |= _folders_in(json.loads(value))
                except ValueError:
                    found |= _folders_in(value)
                continue
            ref = media_ref(value)
            if ref is not None and ref[2]:
                found.add(ref[2])
    return found


def folders_in_file(data_path) -> set[str]:
    """The runs' folders the rows of the data file *data_path* name: a
    parquet file's (:func:`_folders_in_parquet`), or a JSON file's, read
    whole. Any other file names none. A file that cannot be read names none,
    and says so in the log."""
    path = Path(data_path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            return _folders_in_parquet(path)
        if suffix == ".json":
            return _folders_in(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - an output Curio cannot read names no folder
        logger.warning("Could not read which runs' folders the rows of %s name", path, exc_info=True)
    return set()


def write_record(data_path) -> set[str]:
    """Record beside the data file *data_path* the runs' folders its rows
    name (:func:`folders_in_file`), or remove its record when they name
    none; the folders."""
    from utk_curio.backend.app.datasets.install.installer import write_whole

    folders = folders_in_file(data_path)
    record = record_path(data_path)
    if not folders:
        record.unlink(missing_ok=True)
        return folders
    text = json.dumps({"folders": sorted(folders)})
    write_whole(record, lambda partial: partial.write_text(text, encoding="utf-8"))
    return folders


def recorded_folders(folder) -> set[str]:
    """The runs' folders the records in the dataset folder *folder* name,
    every data file's and every bundle part's."""
    from utk_curio.sandbox.util.collections import KEPT_NAME_RE

    found: set[str] = set()
    root = Path(folder)
    if not root.is_dir():
        return found
    for record in root.rglob(f"*{MEDIA_SIDECAR_SUFFIX}"):
        try:
            named = json.loads(record.read_text(encoding="utf-8")).get("folders")
        except (OSError, ValueError, AttributeError):
            logger.warning("Could not read the record %s", record)
            continue
        if isinstance(named, list):
            found |= {name for name in named if isinstance(name, str) and KEPT_NAME_RE.match(name)}
    return found


def _computed_folders(user_key: str, prefix: str) -> set[str]:
    """The folders the records of the computed datasets of the store
    *user_key* whose folder names start with *prefix* name."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    found: set[str] = set()
    try:
        datasets = list_user_datasets(user_key)
    except ValueError:
        return found
    for dataset in datasets:
        if dataset.name.startswith(prefix):
            found |= recorded_folders(dataset)
    return found


def account_folders(user_key: str) -> set[str]:
    """The runs' folders the saved outputs of the account *user_key* name:
    the records of every computed dataset of its store, a copy of another
    dataflow's included. None for a key that names no account's store."""
    return _computed_folders(user_key, "computed.")


def dataflow_folders(user_key: str, dataflow_id: str) -> set[str]:
    """The runs' folders the saved outputs of the dataflow *dataflow_id*
    name, in the store *user_key* of its owner: its nodes' computed
    datasets', found by the dataflow's part of their ids, never by a node's
    id alone."""
    from utk_curio.backend.app.datasets.install.installer import sanitize_node_id_segment

    return _computed_folders(user_key, f"computed.{sanitize_node_id_segment(str(dataflow_id))}.")
