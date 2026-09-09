"""Shim (memo dev/67-7, restored by memo dev/120): the workflow spec model was
PROMOTED to the app package — ``utk_curio.backend.app.execution.workflow_spec``
is the single source. The e2e suite keeps its historical import path through
this re-export, and ``tests/test_execution/test_workflow_spec_single_source.py``
pins identity so a merge can never turn this file back into a copy (the
``619ab203`` merge did exactly that once, and the two drifted in both
directions).

Add a name here only when the app module exports it; never define anything.
"""

from utk_curio.backend.app.execution.workflow_spec import (  # noqa: F401
    CODE_EDITOR_TYPES,
    CODE_TYPES,
    GRAMMAR_TYPES,
    NAMESPACED_TO_LEGACY,
    PY_CODE_TYPES,
    NodeSpec,
    WorkflowSpec,
    classify_node,
    is_executable_kind,
    normalize_type,
    parse_workflow,
    parse_workflow_dict,
)
