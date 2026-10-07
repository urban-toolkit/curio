"""Copy a node's saved output into another dataflow (#662).

A scenario dragged into another project brings outputs its source saved: its
fixed context, which a Data Loading node reads there, and its outcomes, so they
show without a run. Each is copied under the computed id of the node that holds
it in the target dataflow, and its manifest names that node and dataflow as its
producer, so a reload of the target restores it as that node's output. The copy
is the target's own: a later run of the source rewrites the source's dataset,
never this one.

The folder is copied as it is, sidecars and bundle parts included, rather than
installed again from the sandbox's artifacts, which the run that made it may no
longer have.
"""
from __future__ import annotations

import dataclasses
import shutil

from utk_curio.backend.app.common.record_clock import utc_now
from utk_curio.backend.app.datasets.domain.manifest import (
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import (
    InstallerError,
    InstallResult,
    _index,
    computed_dataset_id,
)


def copy_computed_dataset(
    user_key: str,
    source_dir_name: str,
    *,
    node_id: str,
    dataflow_id: str,
    dataflow_name: str | None = None,
) -> InstallResult:
    """Copy the dataset at *source_dir_name* to ``computed.<dataflow>.<node>@1``."""
    if not dataflow_id or not node_id:
        raise InstallerError("A copied output needs the node and the dataflow that hold it.")
    source = dataset_dir(user_key, source_dir_name)
    try:
        manifest = load_dataset_manifest(source)
    except ManifestError as exc:
        raise InstallerError(f"{source_dir_name} cannot be read: {exc}") from exc

    dataset_id = computed_dataset_id(node_id, dataflow_id)
    dest = dataset_dir(user_key, f"{dataset_id}@1")
    if dest.resolve() == source.resolve():
        raise InstallerError(f"{source_dir_name} would be copied onto itself.")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(source, dest)

    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
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
        dest,
    )
    try:
        copied = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to write the copied manifest: {exc}") from exc
    return _index(user_key, InstallResult(manifest=copied, dest=dest, replaced=True))
