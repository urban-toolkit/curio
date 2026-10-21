"""What a run on the server can do for a scenario drop: whether the account's
runs go to the server, and which node a run of a context node would leave to
the browser. The run itself is started by the canvas, through the runs API."""
from __future__ import annotations


def refusal(user) -> str | None:
    """Why *user*'s runs do not go to the server, or ``None``, as the canvas
    decides it (``runsOnServer`` in ``FlowProvider``): a hosted guest
    (``capabilities.run_refusal``), and ``--no-project``, run in the browser."""
    from utk_curio.backend import config
    from utk_curio.backend.app.users.capabilities import run_refusal

    if config.CURIO_NO_PROJECT:
        return "Runs on the server are off with --no-project."
    return run_refusal(user)


#: The run roles of the nodes a run on the server cannot make an output for:
#: one only the browser runs, and one no installed package provides.
_NOT_MADE_ON_THE_SERVER = ("browser", "missing")


def browser_node(user, project_id: str, nodes: list[dict], edges: list[dict], node_id: str) -> dict | None:
    """The node a run on the server of *node_id* cannot make an output for:
    *node_id* itself, else the first node it reads from whose run role is
    ``browser`` (an Autark compute node, a Spatial Join) or ``missing`` (no
    installed package provides its type). ``None`` when the server runs them
    all."""
    from utk_curio.backend.app.execution.run_plan import ancestors, node_role
    from utk_curio.backend.app.packages.service import roster_templates
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    templates = roster_templates(_user_dir_key(user), project_id)
    packages = TemplateGrammars.for_account(_user_dir_key(user))
    by_id = {node["id"]: node for node in nodes}
    if node_id in by_id and node_role(by_id[node_id], templates, packages) in _NOT_MADE_ON_THE_SERVER:
        return by_id[node_id]
    upstream = ancestors(node_id, edges)
    for node in nodes:
        if node["id"] in upstream and node_role(node, templates, packages) in _NOT_MADE_ON_THE_SERVER:
            return node
    return None
