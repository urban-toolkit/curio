"""Ownership of ``spec.dataflow.datasets`` across client saves (dev/81 Fix 2).

The per-dataflow install state is backend-owned: it is written only by the
dataset endpoints (through :meth:`InstalledDatasetRepository.replace_refs` →
``projects.services.replace_dataflow_datasets``), by the save path's
sink-node ref prune, and by the computed-id migration. A canvas save still
*sends* the section — it is the create-time seed for "Save a copy" and trill
import — but on an update the on-disk section is authoritative: this module's
carry-forward overwrites whatever the client sent, so a stale client mirror
can neither resurrect an uninstalled ref nor drop a fresh install
(last-writer-wins fix; mirrors ``agents.project_agents.preserve_agent_state``).
"""

from __future__ import annotations

from typing import Any


def preserve_dataset_refs(
    effective_spec: dict[str, Any] | None, existing_spec: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Carry the on-disk ``dataflow.datasets`` forward across a client save.

    Unlike the agents carry-forward (which honors a client-sent section), the
    datasets section the client sends on an UPDATE is always overwritten: the
    client serializes its mirror on every save, and honoring it would reopen
    the two-writer race this exists to close. An on-disk dataflow *without*
    refs means "no installs" and yields ``[]`` — keeping the client's rows
    there would reintroduce resurrection.

    The one exception: when there is no spec on disk at all
    (*existing_spec* is ``None``), the client section is left untouched. That
    is the seed rule — ``create()`` (Save a copy, trill import, first save)
    has no carry-forward, and a project whose spec file is missing must not
    have its seed wiped. Mutates and returns *effective_spec*.
    """
    if not isinstance(effective_spec, dict):
        return effective_spec
    if not isinstance(existing_spec, dict):
        return effective_spec
    dataflow = effective_spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        return effective_spec
    existing_df = existing_spec.get("dataflow")
    on_disk = existing_df.get("datasets") if isinstance(existing_df, dict) else None
    # Filter to dict rows, matching ``InstalledDatasetRepository.list_refs`` —
    # malformed residue is dropped rather than carried forever.
    dataflow["datasets"] = [
        ref for ref in (on_disk if isinstance(on_disk, list) else []) if isinstance(ref, dict)
    ]
    return effective_spec
