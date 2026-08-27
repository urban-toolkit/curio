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

    Two exceptions, and both are the same rule: carry forward only what the
    backend has actually written.

    1. No spec on disk at all (*existing_spec* is ``None``) - ``create()``
       (Save a copy, trill import, first save) has no carry-forward.
    2. A spec on disk with **no ``datasets`` key**. Absent is not the same as
       empty: absent means the backend has never written this section, so there
       is nothing to be authoritative with, and wiping the client's rows throws
       away the only copy. Empty (``[]``) does mean "no installs" and is
       carried, because an uninstall writes it.

    Conflating those two is what broke the first install of a computed dataset.
    The bytes are written into the user's store during execution
    (``install_computed_output_on_execution``), which hands the payload back to
    the client; the client is the only thing that puts the ref in the spec, and
    the save-time installer deliberately writes no ref
    (``_auto_install_computed_outputs``). So on the very first save the on-disk
    section does not exist yet, the client's row was discarded, and the dataset
    came back ``installed: false`` and never reached the palette.
    ``test_dataset_palette.py`` is the guard.

    Once the section exists on disk the resurrection guard is intact: an
    uninstall rewrites it (to ``[]`` if it was the last ref), so a stale client
    mirror can never bring a removed ref back. Mutates and returns
    *effective_spec*.
    """
    if not isinstance(effective_spec, dict):
        return effective_spec
    if not isinstance(existing_spec, dict):
        return effective_spec
    dataflow = effective_spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        return effective_spec
    existing_df = existing_spec.get("dataflow")
    if not isinstance(existing_df, dict) or "datasets" not in existing_df:
        # Nothing backend-written to be authoritative with: leave the seed.
        return effective_spec
    on_disk = existing_df.get("datasets")
    # Filter to dict rows, matching ``InstalledDatasetRepository.list_refs`` -
    # malformed residue is dropped rather than carried forever.
    dataflow["datasets"] = [
        ref for ref in (on_disk if isinstance(on_disk, list) else []) if isinstance(ref, dict)
    ]
    return effective_spec
