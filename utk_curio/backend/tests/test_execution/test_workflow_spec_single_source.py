"""dev/120 (F2 of dev/119): ONE workflow-spec classifier.

dev/67-7 promoted the e2e suite's ``workflow_spec.py`` into the app package and
left a shim; the ``619ab203`` merge replaced the shim with main's full copy and
the two drifted in both directions (the copy missed the dev/119 version strip
and the roster functions; the app module kept two phantom kinds main had
removed). These tests make the single source a property the suite checks, not
a promise a merge can undo.
"""

from __future__ import annotations

import ast
import inspect

from utk_curio.backend.app.execution import workflow_spec as app_spec
from utk_curio.backend.tests.test_frontend import workflow_spec as shim


class TestShimIdentity:
    def test_the_e2e_module_re_exports_the_app_objects(self):
        assert shim.NodeSpec is app_spec.NodeSpec
        assert shim.WorkflowSpec is app_spec.WorkflowSpec
        assert shim.parse_workflow is app_spec.parse_workflow
        assert shim.parse_workflow_dict is app_spec.parse_workflow_dict
        assert shim.normalize_type is app_spec.normalize_type
        assert shim.classify_node is app_spec.classify_node
        assert shim.is_executable_kind is app_spec.is_executable_kind
        assert shim.PY_CODE_TYPES is app_spec.PY_CODE_TYPES
        assert shim.CODE_EDITOR_TYPES is app_spec.CODE_EDITOR_TYPES
        assert shim.NAMESPACED_TO_LEGACY is app_spec.NAMESPACED_TO_LEGACY

    def test_the_shim_defines_nothing(self):
        # A copy starts as "just one helper" — refuse the first definition.
        tree = ast.parse(inspect.getsource(shim))
        defined = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        assigned = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        assert defined == [] and assigned == [], (defined, assigned)

    def test_the_version_strip_reaches_the_e2e_suite(self):
        # fixtures.py seeds Python nodes by ``normalize_type(...) in PY_CODE_TYPES``;
        # a palette-dragged (versioned) node used to fall through the copy.
        assert shim.normalize_type("curio.builtin/data-loading@1") == "DATA_LOADING"
        assert shim.normalize_type("curio.builtin/data-loading@1") in shim.PY_CODE_TYPES


class TestNoPhantomKinds:
    def test_every_legacy_code_kind_has_a_namespaced_spelling(self):
        # A legacy name with no namespaced twin can never arrive from a canvas
        # (every workflow JSON has carried namespaced ids since the builtin
        # manifest) — it is a phantom by construction. CONSTANTS and
        # FLOW_SWITCH were exactly that.
        reachable = set(app_spec.NAMESPACED_TO_LEGACY.values())
        phantoms = sorted(app_spec.CODE_TYPES - reachable)
        assert phantoms == [], phantoms
        assert app_spec.CODE_EDITOR_TYPES <= app_spec.CODE_TYPES
        for gone in ("CONSTANTS", "FLOW_SWITCH"):
            assert gone not in app_spec.CODE_TYPES and gone not in app_spec.CODE_EDITOR_TYPES
