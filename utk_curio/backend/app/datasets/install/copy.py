"""Copy a node's saved output into another dataflow (#662).

A scenario dragged into another project brings outputs its source saved: its
fixed context, which a Data Loading node reads there, and its outcomes, so they
show without a run. A copy of a dataflow brings them too: Duplicate, and Save a
copy, whichever account owns the dataflow it copies. Each is copied under the
computed id of the node that holds it in the target dataflow, into the store of
the target's account, and its manifest names that node and dataflow as its
producer, so a reload of the target restores it as that node's output. The copy
is the target's own: a later run of the source rewrites the source's dataset,
never this one, and the source's account deleting its dataset leaves the copy.

The folder is copied as it is, sidecars and bundle parts included, rather than
installed again from the sandbox's artifacts, which the run that made it may no
longer have. Its files are linked, not copied: an output's files are written
once, so the copy holds the source's data under a second name and a drop adds
no bytes. Only the manifest, written anew, and the counts sidecar, which a read
rewrites in place, are the copy's own.

A save installs each output it sends again under its project's spec lock, and
installing one replaces its folder (#941). So a copy is made in two steps, each
under one project's lock:

* :func:`stage_computed_copy` copies the source's folder, whole, to a staging
  folder of its own in the target account's store, under the source project's
  lock. Nothing in the store changes, and nothing is written to the database.
* :func:`place_staged_copy` swaps the staged copy in for the copy's folder and
  indexes it, under the target project's lock.

A copier never holds one project's lock while it waits for the other's, and
the source may be the target. :func:`discard_staged_copy` removes a staged copy
that never took its place.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
from pathlib import Path

from utk_curio.backend.app.common.record_clock import utc_now
from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.datasets.infrastructure.file_meta import META_SIDECAR_SUFFIX
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import (
    InstallerError,
    InstallResult,
    _index,
    _link_or_copy,
    computed_dataset_id,
)

#: The name a staging folder starts with: hidden, and never a dataset's
#: ``<id>@<major>``, so no listing of the store takes it for a dataset.
_STAGING_PREFIX = ".copy-"


def _link_written_once(source: str, target: str) -> str:
    """Put *source* at *target* for a copied dataset: linked when no one
    writes it again (``installer._link_or_copy``), copied when a read rewrites
    it in place, as ``file_meta`` does its counts sidecar, so the copy's write
    never changes the source's file."""
    if source.endswith(META_SIDECAR_SUFFIX):
        return shutil.copy2(source, target)
    _link_or_copy(Path(source), Path(target))
    return target


@dataclasses.dataclass(frozen=True)
class StagedCopy:
    """A copy of a saved output, whole, waiting to take its place. *folder* is
    named for the copy's ``<id>@1`` and sits in a staging folder of its own
    beside the account's datasets; *manifest* is the copy's."""

    folder: Path
    manifest: DatasetManifest


def stage_computed_copy(
    source_key: str,
    source_dir_name: str,
    *,
    target_key: str,
    node_id: str,
    dataflow_id: str,
    dataflow_name: str | None = None,
) -> StagedCopy:
    """Copy the dataset at *source_dir_name* in the store of the account
    *source_key* to a staging folder in the store of the account *target_key*,
    the same or another, as ``computed.<dataflow>.<node>@1``, its manifest
    naming that node and dataflow as its producer, and its files linked
    (:func:`_link_written_once`). The caller holds the source project's spec
    lock, so the folder is never read while a save rewrites it."""
    if not dataflow_id or not node_id:
        raise InstallerError("A copied output needs the node and the dataflow that hold it.")
    source = dataset_dir(source_key, source_dir_name)
    try:
        manifest = load_dataset_manifest(source)
    except ManifestError as exc:
        raise InstallerError(f"{source_dir_name} cannot be read: {exc}") from exc

    dataset_id = computed_dataset_id(node_id, dataflow_id)
    dest = dataset_dir(target_key, f"{dataset_id}@1")
    if dest == source:
        raise InstallerError(f"{source_dir_name} would be copied onto itself.")
    try:
        # A fresh account has no store yet.
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=dest.parent))
    except OSError as exc:
        raise InstallerError(f"{source_dir_name} could not be copied: {exc}") from exc
    folder = staging / dest.name
    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        # The manifest is left out and written anew: a link to the source's
        # would be the source's, and writing one would rewrite both.
        shutil.copytree(
            source, folder,
            ignore=lambda folder_path, names: ["manifest.json"] if Path(folder_path) == source else [],
            copy_function=_link_written_once,
        )
        write_manifest(
            dataclasses.replace(
                manifest,
                id=dataset_id,
                major=1,
                producer_node_id=node_id,
                producer_dataflow_id=dataflow_id,
                producer_dataflow_name=dataflow_name,
                created_at=now,
                updated_at=now,
            ),
            folder,
        )
        copied = load_dataset_manifest(folder)
    except (OSError, ManifestError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallerError(f"{source_dir_name} could not be copied: {exc}") from exc
    return StagedCopy(folder=folder, manifest=copied)


def place_staged_copy(user_key: str, staged: StagedCopy) -> InstallResult:
    """Put *staged* where its dataset goes in the store of the account
    *user_key*, the one it was staged in, replacing the copy there, and index
    it. The caller holds the target project's spec lock, under which a save of
    the target installs its outputs."""
    dest = dataset_dir(user_key, staged.folder.name)
    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        os.replace(staged.folder, dest)
    except OSError as exc:
        raise InstallerError(f"{staged.folder.name} could not be put in place: {exc}") from exc
    finally:
        discard_staged_copy(staged)
    return _index(user_key, InstallResult(manifest=staged.manifest, dest=dest, replaced=True))


def discard_staged_copy(staged: StagedCopy) -> None:
    """Remove *staged*'s staging folder, with the copy in it unless the copy
    has taken its place."""
    staging = staged.folder.parent
    if staging.name.startswith(_STAGING_PREFIX):
        shutil.rmtree(staging, ignore_errors=True)
