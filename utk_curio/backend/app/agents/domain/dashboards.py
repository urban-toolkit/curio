"""Dashboards, as agents meet them.

A node pinned to its dataflow's dashboard is a tile of a page anyone with its
link can open. The page draws from the outputs saved with the dataflow, so it
refuses a pinned Autark tile whose spec loads its own data
(``projects/dashboard_payload.py``). A spec an agent writes for a pinned node
is held to that refusal by the dashboard's own check,
``dashboard_payload.tile_loads_its_own_data``, read with the account's
packages as the dashboard reads the owner's. Agents never pin a node, so only
a node the user pinned is checked, and the code it holds already is the
user's own and is never refused.
"""
from __future__ import annotations

from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.projects import dashboard_payload
from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

#: The kind of a Solve attempt this check fails.
KIND = "dashboard-tile"


def is_pinned(node) -> bool:
    """Whether the saved *node* is a tile of its dataflow's dashboard, as the
    dashboard reads it (``dashboard_payload.is_pinned``)."""
    return isinstance(node, dict) and dashboard_payload.is_pinned(node)


def refusal(user_key, project_id, node, code) -> str | None:
    """Why *code*, written by an agent for the saved *node* of *user_key*'s
    dataflow *project_id*, is refused: the node is pinned, and with *code* as
    its content it is a tile that loads its own data, which its dashboard
    refuses. None for a node that is not pinned, for code the dashboard
    carries, and for the code the node holds already, which is the user's own:
    compared as an agent's code is written into a node
    (``extract_node_content``)."""
    if not is_pinned(node):
        return None
    if content.extract_node_content(code) == content.extract_node_content(str(node.get("content") or "")):
        return None
    tile = {**node, "content": content.extract_node_content(code)}
    if not dashboard_payload.tile_loads_its_own_data(tile, TemplateGrammars.for_account(user_key)):
        return None
    return agent_text.message("dashboards.tile-loads-own-data")
