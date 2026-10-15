"""The account's dataflows that use a catalog item, one row per dataflow.

What the catalogs' usage reads answer (``GET /api/datasets/<id>/usage`` for a
dataset, ``GET /api/packages/<dir>/usage`` for a package) and their Remove
dialogs read: each dataflow that uses the item, its nodes that do, and whether
it uses the item only through node code (``codeOnly``), which keeps nothing.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from utk_curio.backend.app.projects import repositories, storage

#: How one dataflow uses the item, from its saved spec and its project id:
#: ``None`` when it does not, else its nodes that do (``[{nodeId, nodeType}]``)
#: and whether it uses the item only through node code.
Uses = Callable[[dict, str], Optional[tuple[list[dict[str, Any]], bool]]]


def dataflow_usage(user_id: int, user_key: str, uses: Uses) -> list[dict[str, Any]]:
    """``[{dataflowId, dataflowName, nodeCount, nodes, codeOnly}]``, sorted by
    name: every project of the user whose saved spec *uses* answers for.

    Reads every project the user has. The destructive gates count on that: a
    project this scan missed would lose what it still uses (#176)."""
    rows: list[dict[str, Any]] = []
    for project in repositories.list_for_user(user_id):
        spec = storage.read_spec(user_key, project.id) or {}
        found = uses(spec, project.id)
        if found is None:
            continue
        nodes, code_only = found
        rows.append({
            "dataflowId": project.id,
            "dataflowName": project.name,
            "nodeCount": len(nodes),
            "nodes": nodes,
            "codeOnly": code_only,
        })
    rows.sort(key=lambda row: (row["dataflowName"] or "").casefold())
    return rows
