"""The order a run on the server follows, decided as Run All decides it.

- :func:`is_interaction_edge`: a two-way link between views carries a
  selection, not data, so a run never orders nodes by it. The one rule for it
  is ``src/contracts/interactionEdges.json``, read here, and these functions
  are its one definition on the backend, the twin of the canvas's
  ``contracts/interactionEdges.ts``; both run ``interactionEdges.cases.json``.
  A node's own interaction handle is ``in/out``, and a view of a node has one
  of its own, ``in/out@<id>`` (:func:`interaction_handle_view` reads its id,
  :func:`interaction_view_handle` makes it from one). An edge is an
  interaction edge when a saved dataflow types it ``Interaction``, an agent's
  plan gives it the kind ``interaction``, or both its handles are interaction
  handles.
- :func:`topological_levels` is the twin of ``computeTopologicalLevels`` in
  ``providers/flow/runLevels.ts``: nodes with no edge at all first, then the
  roots that feed something, then each level whose inputs are all done.
  ``runLevels.cases.json`` beside the TypeScript holds the cases both run.
- :func:`ancestors` is the slice ``playNodesUpTo`` runs for one node.
- :func:`node_role`: what a run does with a node. ``run`` executes it in the
  sandbox, as an executable template or an Autark node whose document only
  loads data (``autk_spec_kind``); ``forward`` passes its input on, as a chart,
  a pool or a download does on the canvas, or has nothing to run, as a Note;
  ``browser`` makes data only the browser can (an Autark compute node, an
  Autark node with no data of its own to load), so nothing below it can run
  until a tab does; ``missing`` is a node whose type names a
  package's template that no installed package provides (a saved Compare
  Scenarios node, a node of a package only another account's store holds):
  the canvas cannot run it either, so a run fails it, naming the
  type as the canvas's card for it does (:func:`missing_type_message`), and
  skips what it feeds. A node is what its
  template's declared ``behavior`` says (``projects/template_grammars``),
  never what its type is named.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Iterable, Optional

from utk_curio.common import shared_constants

if TYPE_CHECKING:
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

_RULE = shared_constants.read("interactionEdges")
#: A node's own interaction handle.
INTERACTION_HANDLE: str = _RULE["handle"]
#: What a view's interaction handle starts with: a node's own, then the mark.
_VIEW_HANDLE_PREFIX: str = _RULE["handle"] + _RULE["viewMark"]
#: The type a saved dataflow gives an interaction edge.
INTERACTION_EDGE_TYPE: str = _RULE["edgeType"]
#: The kind an agent's plan gives an interaction edge.
INTERACTION_PLAN_KIND: str = _RULE["planKind"]

#: The behaviors of the nodes a run forwards besides the ones a dashboard walk
#: passes through: a Note only holds text, and has nothing to run. The built-in
#: nodes of a type no template declares a behavior for are forwarded by their
#: ids.
_FORWARD_BEHAVIORS = frozenset({"note"})
_FORWARD_TYPES = frozenset({"curio.builtin/note"})


def interaction_handle_view(handle: object) -> Optional[str]:
    """The id of the view *handle* names (``in/out@<id>``): None for a node's
    own handle, and for any other."""
    if not isinstance(handle, str) or not handle.startswith(_VIEW_HANDLE_PREFIX):
        return None
    return handle[len(_VIEW_HANDLE_PREFIX):] or None


def is_interaction_handle(handle: object) -> bool:
    """Whether *handle* is an interaction handle: a node's own, or a view's."""
    return handle == INTERACTION_HANDLE or interaction_handle_view(handle) is not None


def interaction_view_handle(view: object) -> str:
    """The interaction handle of the view whose id is *view*: a node's own
    handle, the mark, then the id; a node's own handle for no id. An agent's
    plan draws an interaction edge on a view's dot through it."""
    return _VIEW_HANDLE_PREFIX + view if isinstance(view, str) and view else INTERACTION_HANDLE


def is_interaction_edge(edge: object) -> bool:
    """Whether *edge* (a saved dataflow's, the canvas's or a plan's) is an
    interaction edge: typed so, of that kind, or with an interaction handle at
    both ends."""
    if not isinstance(edge, Mapping):
        return False
    return (
        edge.get("type") == INTERACTION_EDGE_TYPE
        or edge.get("kind") == INTERACTION_PLAN_KIND
        or (is_interaction_handle(edge.get("sourceHandle")) and is_interaction_handle(edge.get("targetHandle")))
    )


def directed_edges(edges: Iterable[dict]) -> list[dict]:
    """The edges a run orders nodes by: every edge but an interaction link."""
    return [e for e in edges if isinstance(e, dict) and not is_interaction_edge(e)]


def topological_levels(node_ids: list[str], edges: Iterable[dict]) -> list[list[str]]:
    """The levels a run executes, one after another (``computeTopologicalLevels``).

    A node inside a cycle is in no level. Edges with an end outside *node_ids*
    are ignored.
    """
    known = set(node_ids)
    in_degree = {node_id: 0 for node_id in node_ids}
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in directed_edges(edges):
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known:
            continue
        in_degree[target] += 1
        successors[source].append(target)

    roots = [node_id for node_id in node_ids if in_degree[node_id] == 0]
    isolated = [node_id for node_id in roots if not successors[node_id]]
    sources = [node_id for node_id in roots if successors[node_id]]
    if not isolated and not sources:
        return []

    levels: list[list[str]] = []
    if isolated:
        levels.append(isolated)
    if sources:
        levels.append(sources)
    remaining = dict(in_degree)
    visited = set(isolated) | set(sources)
    queue = sources
    while queue:
        following: list[str] = []
        for node_id in queue:
            for successor in successors[node_id]:
                remaining[successor] -= 1
                if remaining[successor] == 0 and successor not in visited:
                    following.append(successor)
                    visited.add(successor)
        if following:
            levels.append(following)
        queue = following
    return levels


def ancestors(target_id: str, edges: Iterable[dict]) -> set[str]:
    """*target_id* and every node it reads from, through data edges."""
    predecessors: dict[str, list[str]] = {}
    for edge in directed_edges(edges):
        predecessors.setdefault(edge.get("target"), []).append(edge.get("source"))
    wanted = {target_id}
    frontier = [target_id]
    while frontier:
        node_id = frontier.pop()
        for source in predecessors.get(node_id, []):
            if source not in wanted:
                wanted.add(source)
                frontier.append(source)
    return wanted


def missing_type_message(node_type: object) -> str:
    """What a run says of a node no installed package provides: the title of
    the card the canvas shows for it (``unresolvedNodeMessage`` in
    ``components/UnresolvedNode.tsx``)."""
    return f"No installed package provides {node_type}"


def _provided(node_type: str, templates: dict | None, packages: "TemplateGrammars") -> bool:
    """Whether an installed package provides *node_type*: the project's roster
    (*templates*) holds its template, or a manifest in the account's store,
    the catalog or the packages Curio ships does."""
    from utk_curio.backend.app.packages.service import unversioned_node_type

    if templates and unversioned_node_type(node_type) in templates:
        return True
    return packages.provides(node_type)


def node_role(
    node: dict,
    templates: dict | None = None,
    packages: Optional["TemplateGrammars"] = None,
) -> str:
    """``run``, ``forward``, ``browser`` or ``missing`` for a node as a saved
    dataflow holds it.

    What a node forwards as is what its template declares, read through
    *packages*: the account's store, the catalog, then the packages Curio
    ships (``TemplateGrammars.for_account()`` when None). A chart a package's
    template draws with the Vega-Lite grammar is forwarded as a Vega-Lite chart
    is, and so is one the project's roster (*templates*) says draws with it.
    A node of a package's template that neither the roster nor a manifest
    holds is ``missing``; a type that names no package (a legacy plain string,
    or one of any other shape) reads nothing and stays the browser's."""
    from utk_curio.backend.app.execution.autk_spec_kind import is_autk_data_node
    from utk_curio.backend.app.execution.workflow_spec import grammar_id_of, is_executable_kind
    from utk_curio.backend.app.packages.service import is_package_node_type
    from utk_curio.backend.app.projects.dashboard_payload import passes_through
    from utk_curio.backend.app.projects.template_grammars import (
        VEGA_LITE,
        TemplateGrammars,
        declares_behavior,
    )

    if is_executable_kind(node.get("type"), templates):
        return "run"
    packages = packages or TemplateGrammars.for_account()
    if (passes_through(node, packages)
            or declares_behavior(node.get("type"), _FORWARD_BEHAVIORS, _FORWARD_TYPES, packages)
            or grammar_id_of(str(node.get("type") or ""), templates) == VEGA_LITE):
        return "forward"
    if is_autk_data_node(node):
        return "run"
    node_type = node.get("type")
    if is_package_node_type(node_type) and not _provided(node_type, templates, packages):
        return "missing"
    return "browser"
