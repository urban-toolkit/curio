"""Find the datasets a node's code refers to.

A node can reach a dataset two ways: a *binding*, recorded in
``node.metadata.datasetRefs`` when the dataset is dragged onto it, and a literal
``curio_dataset_path("<id>")`` call in the node's own source. The second is the
common one. Curio's shipped examples all use it, because a hand-written or
generated loader is just code, and the generators emit exactly this call.

This scanner used to exist only twice, in two places that needed it for
execution: ``api/routes.py`` (resolving ids to real paths before a run) and the
frontend's ``datasetIdsInCode``. Lineage had no equivalent, so a dataset
referenced only in code was invisible to the usage helper while being perfectly
visible to the thing that ran it (#250, and the backend half of what #205 fixed
on the canvas).

Kept in ``domain/`` so the lineage path and the execution path share one answer
rather than two that can drift.
"""

from __future__ import annotations

import re

#: Literal ``curio_dataset_path("<id>")`` calls in node code. The id charset must
#: stay in sync with ``_SAFE_DATASET_ID_RE`` in ``catalog_item.py`` (the backend
#: snippet generator) and the frontend ``datasetLoaderSnippets.ts``: the
#: generators only ever emit ids this scan can find. Single or double quotes are
#: accepted because users edit the generated code, and the backreference means a
#: mismatched pair is not a reference at all.
DATASET_PATH_CALL_RE = re.compile(
    r"""curio_dataset_path\(\s*(["'])([A-Za-z0-9][A-Za-z0-9._@-]{0,199})\1\s*\)"""
)

#: Bound the work against pathological or generated code. Shared with the
#: execution path, which has always had this cap.
MAX_DATASET_IDS = 32


def dataset_ids_in_code(code: object, *, limit: int = MAX_DATASET_IDS) -> list[str]:
    """Dataset ids referenced by literal calls in *code*, in first-seen order.

    Returns ``[]`` for anything that is not a string. The substring fast path
    matters: this runs over every node of every project when the catalog counts
    consumers, and most nodes never mention a dataset.

    Only literal calls are found. An id built at runtime is not a reference this
    can see, which is the same limitation the execution resolver has always had
    and is why the result is used to *add* usage, never to deny it.
    """
    if not isinstance(code, str) or "curio_dataset_path" not in code:
        return []
    ids: list[str] = []
    for match in DATASET_PATH_CALL_RE.finditer(code):
        dataset_id = match.group(2)
        if dataset_id not in ids:
            ids.append(dataset_id)
        if len(ids) >= limit:
            break
    return ids


def code_refers_to_dataset(code: object, dataset_id: str) -> bool:
    """Whether *code* contains a literal reference to *dataset_id*."""
    if not dataset_id:
        return False
    return dataset_id in dataset_ids_in_code(code)


def node_code(node: object) -> str:
    """The source carried by a saved spec node, or ``""``.

    Saved specs put it at the top level as ``content`` (sibling of ``metadata``),
    which is NOT where the frontend canvas keeps it (``node.data.code``). The two
    shapes meeting here is exactly the kind of thing that made lineage disagree
    with itself, so the lookup is named rather than inlined.
    """
    if not isinstance(node, dict):
        return ""
    content = node.get("content")
    return content if isinstance(content, str) else ""
