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


def _refs_in(value) -> set[tuple]:
    """``(collection, file id, run's folder or None)`` of each media URL
    anywhere in *value*."""
    from utk_curio.sandbox.util.collections import media_refs

    return {tuple(ref) for ref in media_refs(value)}


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


#: What every media URL starts with (``collections.media_url``): a value
#: without it names no file, and is not parsed.
_MEDIA_URL_START = "/api/datasets/"


def _holds_text(kind) -> bool:
    """Whether a column of the Arrow type *kind* holds text anywhere: a
    string, or a list, struct, map or dictionary of them. A binary column, a
    feature's geometry among them, and a column of numbers hold no URL."""
    import pyarrow as pa

    if pa.types.is_string(kind) or pa.types.is_large_string(kind):
        return True
    if pa.types.is_dictionary(kind):
        return _holds_text(kind.value_type)
    if pa.types.is_map(kind):
        return _holds_text(kind.key_type) or _holds_text(kind.item_type)
    if pa.types.is_list(kind) or pa.types.is_large_list(kind) or pa.types.is_fixed_size_list(kind):
        return _holds_text(kind.value_type)
    if pa.types.is_struct(kind):
        return any(_holds_text(kind.field(i).type) for i in range(kind.num_fields))
    return False


def _refs_in_column(column, *, encoded: bool) -> set[tuple]:
    """The media URLs one batch of one column holds (:func:`_refs_in`): a
    text column's values, the JSON they hold when *encoded*, or a nested
    column's values. Only the values that hold a media URL are read in
    Python."""
    import pyarrow as pa
    import pyarrow.compute as pc

    from utk_curio.sandbox.util.collections import media_ref

    if pa.types.is_dictionary(column.type):
        column = column.cast(column.type.value_type)
    if not (pa.types.is_string(column.type) or pa.types.is_large_string(column.type)):
        return _refs_in(column.to_pylist())
    # JSON text holds a URL anywhere, a list's or a dict's; a URL column's
    # value is the URL.
    holds = pc.match_substring(column, _MEDIA_URL_START) if encoded else pc.starts_with(column, _MEDIA_URL_START)
    found: set[tuple] = set()
    for value in pc.unique(pc.filter(column, holds)).to_pylist():
        if not isinstance(value, str):
            continue
        if encoded:
            try:
                found |= _refs_in(json.loads(value))
            except ValueError:
                found |= _refs_in(value)
            continue
        ref = media_ref(value)
        if ref is not None:
            found.add(tuple(ref))
    return found


def _refs_in_parquet(data_path: Path) -> set[tuple]:
    """The media URLs the rows of a parquet file hold: its text columns'
    (the JSON its object columns hold, decoded), and its nested columns' that
    hold text, read a batch at a time."""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(data_path)
    try:
        wanted = [field.name for field in parquet.schema_arrow if _holds_text(field.type)]
        if not wanted:
            return set()
        encoded = _encoded_columns(data_path)
        found: set[tuple] = set()
        for batch in parquet.iter_batches(columns=wanted):
            for name, column in zip(batch.schema.names, batch.columns):
                found |= _refs_in_column(column, encoded=name in encoded)
        return found
    finally:
        parquet.close()


def refs_in_file(data_path) -> set[tuple]:
    """``(collection, file id, run's folder or None)`` of each media URL the
    rows of the data file *data_path* hold: a parquet file's
    (:func:`_refs_in_parquet`), or a JSON file's, read whole. Any other file
    holds none. A file that cannot be read holds none, and says so in the
    log."""
    path = Path(data_path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            return _refs_in_parquet(path)
        if suffix == ".json":
            return _refs_in(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - an output Curio cannot read names no file
        logger.warning("Could not read which files the rows of %s name", path, exc_info=True)
    return set()


def folders_in_file(data_path) -> set[str]:
    """The runs' folders the rows of the data file *data_path* name
    (:func:`refs_in_file`)."""
    return {kept for _dataset, _file, kept in refs_in_file(data_path) if kept}


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


def _read_record(record: Path) -> set[str]:
    """The runs' folders one record names; none when there is no record."""
    from utk_curio.sandbox.util.collections import KEPT_NAME_RE

    if not record.is_file():
        return set()
    try:
        named = json.loads(record.read_text(encoding="utf-8")).get("folders")
    except (OSError, ValueError, AttributeError):
        logger.warning("Could not read the record %s", record)
        return set()
    if not isinstance(named, list):
        return set()
    return {name for name in named if isinstance(name, str) and KEPT_NAME_RE.match(name)}


def recorded_folders(folder) -> set[str]:
    """The runs' folders the records in the dataset folder *folder* name,
    every data file's and every bundle part's."""
    found: set[str] = set()
    root = Path(folder)
    if not root.is_dir():
        return found
    for record in root.rglob(f"*{MEDIA_SIDECAR_SUFFIX}"):
        found |= _read_record(record)
    return found


def folders_of_data_file(data_path) -> set[str]:
    """The runs' folders a saved output's data file *data_path* records, the
    file a run reads it from (``node_exec.resolve_saved_inputs``): its own
    record, and for a bundle (``bundle.json``) its parts' records."""
    from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts

    path = Path(data_path)
    files = [path]
    if path.name == "bundle.json":
        files += [file for _part, file in listed_bundle_parts(path)]
    found: set[str] = set()
    for file in files:
        found |= _read_record(record_path(file))
    return found


def _recorded_in_store(user_key: str, prefix: str) -> set[str]:
    """The folders the records of the datasets of the store *user_key* whose
    folder names start with *prefix* name."""
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
    """The runs' folders the datasets of the account *user_key* name: the
    records of every dataset of its store, its saved outputs and its copies
    of another account's (an added published dataset, Save a copy, an Apply
    of an editor's, ``carry``). None for a key that names no account's
    store."""
    return _recorded_in_store(user_key, "")


def dataflow_folders(user_key: str, dataflow_id: str) -> set[str]:
    """The runs' folders the saved outputs of the dataflow *dataflow_id*
    name, in the store *user_key* of its owner: its nodes' computed
    datasets', found by the dataflow's part of their ids, never by a node's
    id alone."""
    from utk_curio.backend.app.datasets.install.installer import sanitize_node_id_segment

    return _recorded_in_store(user_key, f"computed.{sanitize_node_id_segment(str(dataflow_id))}.")
