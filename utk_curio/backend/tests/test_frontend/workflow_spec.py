"""Shim (memo dev/67-7): the spec model was PROMOTED to the app package —
`utk_curio.backend.app.execution.workflow_spec` is the single source; the e2e
suite keeps its historical import path through this re-export."""

from utk_curio.backend.app.execution.workflow_spec import (  # noqa: F401
    CODE_EDITOR_TYPES,
    CODE_TYPES,
    GRAMMAR_TYPES,
    NAMESPACED_TO_LEGACY,
    PY_CODE_TYPES,
    NodeSpec,
    WorkflowSpec,
    _merge_edge_handle_index,
    classify_node,
    normalize_type,
    parse_workflow,
    parse_workflow_dict,
)
