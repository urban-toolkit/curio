"""A saved dataflow's node histories, keyed as a load keys them.

The twin of ``utils/nodeProvenanceKeys.ts`` (``rekeyNodeProvenance``), which a
load runs on a dataflow's ``nodeProvenance`` before the nodes' Provenance
drawers read it; ``utils/nodeProvenanceKeys.cases.json`` beside it holds the
cases both sides run. The agents' ``node.history.read`` reads a node's history
through it, so an agent reads what the node's drawer lists.

Dataflows saved before #448 carry a node's entries under everything after the
first dash of ``nodeType + "-" + nodeId`` (``loading@1-<uuid>`` for a
data-loading node). Each such key moves under the longest node id it ends
with, merging with the entries already filed there in the order they were
made (their ids). A key that already is a node id, or that ends with none,
stays as it is, and a value that is no list is left out.
"""
from __future__ import annotations

from typing import Mapping, Sequence


def _entry_id(record: object) -> float:
    """An entry's id, which orders a merge: the order the entries were made."""
    value = record.get("id") if isinstance(record, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def rekey_node_provenance(saved: Mapping, node_ids: Sequence[str]) -> dict[str, list]:
    """*saved*, a dataflow's ``nodeProvenance``, with each list of entries
    under the node id a load files it under, for a dataflow whose nodes are
    *node_ids*. *saved* is left as it was."""
    ids = set(node_ids)
    by_length = sorted(node_ids, key=len, reverse=True)
    out: dict[str, list] = {}
    for key, records in saved.items():
        if not isinstance(records, list):
            continue
        target = key if key in ids else next((node_id for node_id in by_length if key.endswith("-" + node_id)), key)
        out[target] = sorted([*out[target], *records], key=_entry_id) if target in out else records
    return out
