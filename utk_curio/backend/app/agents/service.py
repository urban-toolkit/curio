"""Public facade of the agents application layer (memo dev/142, B2; re-derived on enh/agent-catalog).

The implementation lives in the layered ``application/`` subpackages; this
module is the single stable entry point. Routes, ``projects``, ``evaluation``
and ``training`` import the service API from here, never from a layer module.
Nothing is defined here. Mirrors ``datasets/service.py`` and ``packages/service.py``.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application.attachment_management import (
    attach_agent,
    clear_attachment_session,
    detach_agent,
    get_attachment_session,
    list_project_attachments,
    update_attachment_intent,
    update_attachment_title,
)
from utk_curio.backend.app.agents.application.catalog import (
    agent_catalog_facets,
    builtin_definition_bundle,
    catalog_settings_listing,
    choosable_agents,
    list_global_catalog,
    list_installed_in_project,
    list_my_imports,
    read_definition_bundle_anywhere,
)
from utk_curio.backend.app.agents.application.dataset_selection import (
    record_dataset_selection,
)
from utk_curio.backend.app.agents.application.errors import (
    AgentServiceError,
)
from utk_curio.backend.app.agents.application.lifecycle import (
    import_agent,
    install_in_project,
    publish_agent,
    remove_import,
    seed_project_with_imported_agents,
    uninstall_from_project,
    unpublish_agent,
)
from utk_curio.backend.app.agents.application.proposals.apply import (
    apply_proposal,
    dismiss_proposal,
)
from utk_curio.backend.app.agents.application.proposals.plans import (
    apply_plan_edges,
    apply_plan_node,
    set_plan_goal,
)
from utk_curio.backend.app.agents.application.solve.budgets import (
    DEFAULT_SOLVE_ATTEMPTS,
    DEFAULT_SOLVE_BATCH_DEADLINE_S,
    DEFAULT_SOLVE_NODE_BUDGET_S,
    DEFAULT_SOLVE_SESSION_DEADLINE_S,
    DEFAULT_SOLVE_SESSION_WAIT_S,
    MAX_SOLVE_ATTEMPTS,
    solve_batch_deadline_s,
    solve_correction_rounds,
    solve_max_attempts,
    solve_node_budget_s,
    solve_session_deadline_s,
    solve_session_wait_s,
)
from utk_curio.backend.app.agents.application.solve.node_solve import (
    solve_node_stream,
)
from utk_curio.backend.app.agents.application.solve.rounds import (
    STOPPED_BY_PHRASES,
)
from utk_curio.backend.app.agents.application.solve.run_node import (
    run_node_stream,
)
from utk_curio.backend.app.agents.application.solve.session import (
    request_solve_cancel,
    solve_attachment,
    solve_attachment_stream,
)
from utk_curio.backend.app.agents.application.solve.simulation import (
    request_simulate_cancel,
    simulate_stream,
)
from utk_curio.backend.app.agents.application.solve.validate import (
    validate_node_stream,
)
from utk_curio.backend.app.agents.application.spec_reads import (
    attachment_agent_id,
)
from utk_curio.backend.app.agents.application.tool_rounds import (
    MAX_REFUSED_ROUNDS,
    MAX_TOOL_ROUNDS,
    MUTATE_PROPOSAL_TOOLS,
    ParamRefusal,
)
from utk_curio.backend.app.agents.application.turns.attachment_turn import (
    run_attachment,
    stream_attachment,
)
from utk_curio.backend.app.agents.application.turns.delegates import (
    PACKAGE_AUTHORING_CAPABILITIES,
)
from utk_curio.backend.app.agents.application.turns.policy import (
    CONTEXT_MAX_CHARS,
    DEPLOYMENT_MAX_OUTPUT_TOKENS,
)
from utk_curio.backend.app.agents.application.turns.roster import (
    roster_block,
)
from utk_curio.backend.app.agents.application.turns.titles import (
    TITLE_MAX_OUTPUT_TOKENS,
    TITLE_PROMPT,
    sanitize_title,
)
from utk_curio.backend.app.agents.application.upload_import import (
    upload_import,
)

__all__ = [
    "attach_agent",
    "clear_attachment_session",
    "detach_agent",
    "get_attachment_session",
    "list_project_attachments",
    "update_attachment_intent",
    "update_attachment_title",
    "agent_catalog_facets",
    "builtin_definition_bundle",
    "catalog_settings_listing",
    "choosable_agents",
    "list_global_catalog",
    "list_installed_in_project",
    "list_my_imports",
    "read_definition_bundle_anywhere",
    "record_dataset_selection",
    "AgentServiceError",
    "import_agent",
    "install_in_project",
    "publish_agent",
    "remove_import",
    "seed_project_with_imported_agents",
    "uninstall_from_project",
    "unpublish_agent",
    "apply_proposal",
    "dismiss_proposal",
    "apply_plan_edges",
    "apply_plan_node",
    "set_plan_goal",
    "DEFAULT_SOLVE_ATTEMPTS",
    "DEFAULT_SOLVE_BATCH_DEADLINE_S",
    "DEFAULT_SOLVE_NODE_BUDGET_S",
    "DEFAULT_SOLVE_SESSION_DEADLINE_S",
    "DEFAULT_SOLVE_SESSION_WAIT_S",
    "MAX_SOLVE_ATTEMPTS",
    "solve_batch_deadline_s",
    "solve_correction_rounds",
    "solve_max_attempts",
    "solve_node_budget_s",
    "solve_session_deadline_s",
    "solve_session_wait_s",
    "solve_node_stream",
    "STOPPED_BY_PHRASES",
    "run_node_stream",
    "request_solve_cancel",
    "solve_attachment",
    "solve_attachment_stream",
    "request_simulate_cancel",
    "simulate_stream",
    "validate_node_stream",
    "attachment_agent_id",
    "MAX_REFUSED_ROUNDS",
    "MAX_TOOL_ROUNDS",
    "MUTATE_PROPOSAL_TOOLS",
    "ParamRefusal",
    "run_attachment",
    "stream_attachment",
    "PACKAGE_AUTHORING_CAPABILITIES",
    "CONTEXT_MAX_CHARS",
    "DEPLOYMENT_MAX_OUTPUT_TOKENS",
    "roster_block",
    "TITLE_MAX_OUTPUT_TOKENS",
    "TITLE_PROMPT",
    "sanitize_title",
    "upload_import",
]
