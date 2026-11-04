"""What a dataflow's owner put in what her dataflow uses: the items of her
store an editor she invited may use.

A dataflow names items of its owner's store in its lists: the datasets its
``datasets`` refs name by folder (collections among them), the packages its
lockfile names, the package of each node on its canvas, and the model each
node's ``metadata.modelRefs`` binds to it. An editor's run reads from her
store what the dataflow uses of them (``InstalledDatasetRepository``,
``packages.application.project_packages.OwnersPackages``), and those lists are
in the dataflow's doc, which an editor's tab changes too. So only the owner's
own changes put an item of hers within an editor's reach: her tab's, an agent
run's she asked for, and the server's for her (``dataflow_docs._by_its_owner``,
which tells each change to :func:`noted` with the transaction that made it).

* An owner's change adds to the record each item it names anew: a dataset ref,
  a lockfile entry, a node or a model bound to a node, written where it was
  not before. It takes off the record each item the dataflow names nowhere
  after it.
* A lockfile that names no package reads as the packages of the dataflow's
  nodes, an editor's node's among them. A write that names those in it writes
  down what it read, no one's choice of them: the writer says which they are
  (``dataflow_docs.write``'s *backfilled*), and their entries name nothing
  anew. The owner's Add of a package the lockfile names already is hers all
  the same (:func:`packages_put_in`).
* Anyone else's change leaves the record as it is. An item an editor names
  stays out of it, so an editor's run reads it from the editor's own store or
  the shared catalog, as any item the owner's store does not hold, until the
  owner names it herself.

The record is ``owner-uses.json`` beside the spec, which the doc does not
carry and no tab receives. A dataflow without one, made before the record was
kept or made anew (``dataflow_docs.create``), is recorded with what it names
when it is first read (:func:`recorded`) or first changed (:func:`changed`).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from pycrdt import Map

from utk_curio.backend.app.collaboration import doc_mapping
from utk_curio.backend.app.projects import storage

logger = logging.getLogger(__name__)

#: The record's file, beside the dataflow's spec.
RECORD_FILE = "owner-uses.json"
#: The kinds of item a dataflow names, each the record's list of them.
DATASETS = "datasets"
PACKAGES = "packages"

_LAYOUT = doc_mapping.LAYOUT
#: The Trill fields a doc's ``dataflow`` map holds under their own names that
#: name items: its datasets and its lockfile, and its nodes when they are held
#: whole.
_FIELDS = frozenset({
    DATASETS, PACKAGES,
    *(name for name, place in _LAYOUT["dataflow"].items() if place == doc_mapping.NODES),
})
#: The key of a node's map that holds its ``metadata``, and the keys a change
#: of which may change the items the node names: its type and its metadata.
_METADATA = next(name for name, place in _LAYOUT["node"].items() if place == doc_mapping.METADATA)
_NODE_KEYS = frozenset({_LAYOUT["node"]["type"], _METADATA})
#: The setting of a node's ``metadata`` that binds models to it.
_MODEL_REFS = "modelRefs"
#: The entry, in :func:`entries`, of each package a lockfile names.
_LOCKFILE = "lockfile"

#: Guards each record's read-modify-write. A leaf: no other lock is asked for
#: while it is held, and the doc's own lock may be held when it is asked for.
_lock = threading.Lock()


class Record(NamedTuple):
    """The items of the owner's store her own changes put in the dataflow's
    lists, each as ``(kind, item)``."""

    items: frozenset

    def dataset(self, folder: object) -> bool:
        """Whether the dataset the folder *folder* of her store holds is one."""
        return isinstance(folder, str) and (DATASETS, folder) in self.items

    def package(self, dir_name: str) -> bool:
        """Whether the package or model package installed in her store as
        *dir_name* is one: named by its ``<packageId>@<major>`` or by its
        bare ``<packageId>`` (``spec_packages.names_package``)."""
        from utk_curio.backend.app.packages.domain.spec_packages import names_package

        return names_package({item for kind, item in self.items if kind == PACKAGES}, dir_name)


def _text(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def entries(dataflow) -> Counter:
    """The entries of the Trill *dataflow*'s lists that name items of its
    owner's store, each as ``(kind, item, entry)``: each ``datasets`` ref by
    the folder it names, each lockfile entry, the package of each node's type,
    and each model a node binds (``spec_packages.named_package``,
    ``named_model_package``). An entry written anew is another entry: a ref
    written again, a node added, a model bound to another node."""
    from utk_curio.backend.app.packages.domain.spec_packages import named_model_package, named_package

    out: Counter = Counter()
    if not isinstance(dataflow, dict):
        return out
    refs = dataflow.get(DATASETS)
    for ref in refs if isinstance(refs, list) else ():
        folder = ref.get("dirName") if isinstance(ref, dict) else None
        if isinstance(folder, str) and folder:
            out[(DATASETS, folder, _text(ref))] += 1
    lockfile = dataflow.get(PACKAGES)
    for entry in lockfile if isinstance(lockfile, list) else ():
        if isinstance(entry, str) and entry:
            out[(PACKAGES, entry, _LOCKFILE)] += 1
    nodes = dataflow.get("nodes")
    for index, node in enumerate(nodes if isinstance(nodes, list) else ()):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") if isinstance(node.get("id"), str) else f"#{index}"
        package = named_package(node.get("type"))
        if package:
            out[(PACKAGES, package, f"node {node_id} {node.get('type')}")] += 1
        metadata = node.get("metadata")
        bound = metadata.get(_MODEL_REFS) if isinstance(metadata, dict) else None
        for ref in bound if isinstance(bound, list) else ():
            model = named_model_package(ref.get("id") if isinstance(ref, dict) else None)
            if model:
                out[(PACKAGES, model, f"node {node_id} model {_text(ref)}")] += 1
    return out


def _items(named: Iterable) -> frozenset:
    """The items *named*, entries of :func:`entries`, name."""
    return frozenset((kind, item) for kind, item, _entry in named)


def _dataflow_of(spec) -> dict:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    return dataflow if isinstance(dataflow, dict) else {}


# ---------------------------------------------------------------------------
# The record's file
# ---------------------------------------------------------------------------

def _path(user_key: str, project_id: str) -> Path:
    return storage.project_dir(str(user_key), project_id) / RECORD_FILE


def _read(path: Path) -> Optional[Record]:
    """The record *path* holds; None when there is none, or one that does not
    read, which is then recorded again."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("%s does not read; the dataflow is recorded again with what it names", path, exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    return Record(frozenset(
        (kind, item) for kind in (DATASETS, PACKAGES)
        for item in (data.get(kind) if isinstance(data.get(kind), list) else ())
        if isinstance(item, str)
    ))


def _write(path: Path, record: Record) -> None:
    """Write *record* whole, so a reader never sees half of it. Never in a
    folder that is gone: a dataflow deleted meanwhile does not come back."""
    if not path.parent.is_dir():
        return
    body = {kind: sorted(item for held, item in record.items if held == kind) for kind in (DATASETS, PACKAGES)}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.error("could not write %s", path, exc_info=True)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def recorded(user_key: str, project_id: str) -> Record:
    """What the owner's own changes put in the lists of the dataflow her
    store *user_key* holds: the items of hers an editor's run may read. A
    dataflow with no record yet is recorded with what its spec names now; one
    whose spec does not read has none."""
    try:
        path = _path(user_key, project_id)
    except (OSError, ValueError):
        return Record(frozenset())
    record = _read(path)
    if record is not None:
        return record
    try:
        spec = storage.read_spec_file(str(user_key), project_id).spec
    except (OSError, ValueError):
        logger.warning("the spec of dataflow %s does not read; no item of its owner's is recorded", project_id)
        return Record(frozenset())
    if not isinstance(spec, dict):
        return Record(frozenset())
    seed = Record(_items(entries(_dataflow_of(spec))))
    with _lock:
        record = _read(path)
        if record is None:
            record = seed
            _write(path, record)
    return record


def changed(user_key: str, project_id: str, before: Counter, after: Counter, *, by_owner: bool,
            backfilled: Iterable[str] = ()) -> None:
    """A change made the dataflow's lists name *after* (:func:`entries`) in
    place of *before*. The owner's change (*by_owner*) adds to the record each
    item it named anew and takes off it each item the dataflow names nowhere
    now; anyone else's leaves it as it is. *backfilled*: the packages the
    change named in a lockfile that named none, which read as them already,
    from the dataflow's nodes; their lockfile entries name nothing anew. A
    dataflow with no record yet is first recorded with *before*."""
    try:
        path = _path(user_key, project_id)
    except (OSError, ValueError):
        return
    with _lock:
        held = _read(path)
        record = held if held is not None else Record(_items(before))
        if by_owner:
            anew = after - before
            for package in backfilled:
                anew.pop((PACKAGES, package, _LOCKFILE), None)
            record = Record((record.items | _items(anew)) - (_items(before) - _items(after)))
        if record != held:
            _write(path, record)


def forget(user_key: str, project_id: str) -> None:
    """Drop the dataflow's record: a dataflow made anew is recorded with what
    it names when it is next read or changed."""
    with _lock:
        try:
            _path(user_key, project_id).unlink()
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning("the record of what the owner put in dataflow %s could not be dropped", project_id,
                           exc_info=True)


def packages_put_in(user_key: str, project_id: str, packages: Iterable[str]) -> None:
    """The owner's own add of *packages* to the dataflow her store *user_key*
    holds, whose lockfile names each of them already: an editor's change
    named it there, or a write named it as the lockfile read. Her add changes
    nothing a transaction would note, and each goes on her record all the
    same. A dataflow with no record yet is first recorded with what it
    names."""
    recorded(user_key, project_id)
    try:
        path = _path(user_key, project_id)
    except (OSError, ValueError):
        return
    with _lock:
        held = _read(path)
        if held is None:
            return
        record = Record(held.items | {(PACKAGES, package) for package in packages})
        if record != held:
            _write(path, record)


# ---------------------------------------------------------------------------
# An open doc's changes
# ---------------------------------------------------------------------------

def watch(entry) -> None:
    """Start knowing what the open doc *entry* (``dataflow_docs._OpenDoc``)
    names (``entry.uses``), and note each transaction on it that may change
    that (``entry.uses_touched``): one that changes the ``dataflow`` map's
    datasets, lockfile or nodes held whole, that adds, removes or replaces a
    node, or that changes a node's type, its metadata or the models bound to
    it. Typing in a node's code, a drag and a widget's value are none. Called
    as the doc is attached to the entry, under its lock."""
    doc = entry.doc
    entry.uses = _named_in(entry)
    entry.uses_touched = False
    fields = doc.get("dataflow", type=Map)
    nodes = doc.get("nodes", type=Map)

    def on_fields(event) -> None:
        try:
            touched = bool(_FIELDS & set(getattr(event, "keys", None) or {}))
        except Exception:  # noqa: BLE001 - an event that does not read is taken as a change
            touched = True
        if touched:
            entry.uses_touched = True

    def on_nodes(events) -> None:
        try:
            for event in events:
                path = list(event.path)
                keys = set(getattr(event, "keys", None) or {})
                if (not path
                        or (len(path) == 1 and keys & _NODE_KEYS)
                        or (len(path) == 2 and path[1] == _METADATA and _MODEL_REFS in keys)):
                    entry.uses_touched = True
                    return
        except Exception:  # noqa: BLE001 - an event that does not read is taken as a change
            entry.uses_touched = True

    entry.uses_watching = (fields, nodes, fields.observe(on_fields), nodes.observe_deep(on_nodes))


def _named_in(entry) -> Optional[Counter]:
    """What the open doc *entry* names now (:func:`entries`); None, logged,
    when it does not read."""
    try:
        return entries(doc_mapping.doc_to_dataflow(entry.doc))
    except Exception:  # noqa: BLE001 - a change to the doc stands whatever its record makes of it
        logger.exception("dataflow %s: what its doc names does not read", entry.project_id)
        return None


def noted(entry, *, by_owner: bool, backfilled: Iterable[str] = ()) -> None:
    """After a transaction on the open doc *entry*, under its lock: when it
    may have changed what the dataflow names (:func:`watch`), what it names
    now goes to the record as :func:`changed` says, the change the owner's
    when *by_owner*, *backfilled* the packages it named in a lockfile that
    read as them already. A change made while what the doc named could not
    be read puts nothing on the record. Never raises: the doc's change
    stands."""
    if not entry.uses_touched:
        return
    entry.uses_touched = False
    before, entry.uses = entry.uses, _named_in(entry)
    if before is None or entry.uses is None or before == entry.uses:
        return
    changed(entry.user_key, entry.project_id, before, entry.uses, by_owner=by_owner, backfilled=backfilled)
