import os

import pytest
from playwright.sync_api import Browser, BrowserType

from .utils import REPO_ROOT
from .fixtures import _clean_db


# ------------------------------------------------------------------ #
# Class-scoped browser override
# ------------------------------------------------------------------ #
#
# pytest-playwright ships a session-scoped ``browser`` fixture, so one
# Chromium process handles the whole run.  Over the ~25 parametrized
# workflow classes in this suite, Chromium's V8/GPU/renderer heaps don't
# fully reclaim across closed contexts; on a 16 GiB GH-hosted runner the
# host has leaked >7 GiB by the heavy linked-view workflow (#09), pushing
# the runner into OOM and "lost communication with the server" failures.
# Re-launching Chromium between workflow classes drops it back to baseline
# at the cost of ~5 s × workflow_count of startup overhead.

@pytest.fixture(scope="class")
def browser(
    browser_type: "BrowserType",
    browser_type_launch_args: dict,
) -> "Browser":
    launched = browser_type.launch(**browser_type_launch_args)
    yield launched
    launched.close()

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    "docs/examples/dataflows/DefaultWorkflow.json",

    "docs/examples/dataflows/DataPool_Dataframe.json",
    "docs/examples/dataflows/DataPool_Geodataframe.json",

    "docs/examples/dataflows/DataPool_Vega.json",
    "docs/examples/dataflows/DataPool_Vega_2.json",
    "docs/examples/dataflows/DataPool_AutkMap.json",

    "docs/examples/dataflows/Image.json",
    "docs/examples/dataflows/SimpleView.json",
    "docs/examples/dataflows/Merge.json",
    "docs/examples/dataflows/MergeFlowDataPool.json",

    "docs/examples/dataflows/JSComputation.json",

    "docs/examples/dataflows/Interaction_Vega.json",
    "docs/examples/dataflows/Interaction_Vega_Simple.json",
    "docs/examples/dataflows/Interaction_AutkMap.json",
    "docs/examples/dataflows/Interaction_Autark.json",
    "docs/examples/dataflows/Interaction_Vega_Autark.json",

    "docs/examples/dataflows/Widget.json",

    "docs/examples/dataflows/Vega.json",
    "docs/examples/dataflows/AutkMap.json",

    "docs/examples/dataflows/Regression.json",

    # Curated examples shown in docs/README.md
    "docs/examples/01-vega-lite-chained-transforms.json",
    "docs/examples/02-vega-lite-spatial-density.json",
    "docs/examples/03-vega-lite-linked-temporal-charts.json",
    "docs/examples/04-vega-lite-multi-flow-dashboard.json",
    "docs/examples/05-vega-lite-multi-view-drilldown.json",
    "docs/examples/06-autark-what-if-shadow-study.json",
    "docs/examples/07-autark-gpu-shader.json",
    "docs/examples/08-autark-spatial-join-regression.json",
    "docs/examples/09-heterogeneous-data-linked-views.json",
]


def load_workflow_files_from_folder():
    """Return absolute paths for every workflow in WORKFLOW_FILES.

    Respects the ``CURIO_E2E_WORKFLOWS`` environment variable: when set
    to a comma-separated list of basenames (e.g.
    ``CURIO_E2E_WORKFLOWS=Vega.json,AutkMap.json``) only those workflows
    are included.  Basenames are resolved against ``WORKFLOW_FILES`` so
    callers don't need to know the ``docs/examples/dataflows/`` prefix.
    This makes it easy to run a quick subset during development or in CI
    smoke tests.
    """
    subset = os.environ.get("CURIO_E2E_WORKFLOWS")
    if not subset:
        return [os.path.join(REPO_ROOT, name) for name in WORKFLOW_FILES]
    requested = [n.strip() for n in subset.split(",") if n.strip()]
    by_basename = {os.path.basename(p): p for p in WORKFLOW_FILES}
    resolved: list[str] = []
    for name in requested:
        # Already a relative path that exists in WORKFLOW_FILES — use as-is.
        if name in WORKFLOW_FILES:
            resolved.append(name)
            continue
        # Bare basename — look it up in the master list.
        match = by_basename.get(os.path.basename(name))
        if match is None:
            raise ValueError(
                f"CURIO_E2E_WORKFLOWS entry {name!r} is not in WORKFLOW_FILES; "
                f"valid basenames: {sorted(by_basename)}"
            )
        resolved.append(match)
    return [os.path.join(REPO_ROOT, name) for name in resolved]


# ------------------------------------------------------------------ #
# Dynamic parametrization hook
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def e2e_clean_db(request, test_db_paths):
    """Truncate mutable SQLAlchemy tables before and after each frontend test.

    Scoped to ``test_frontend/`` via this conftest so ``test_projects`` /
    ``test_users`` (their own ``app`` fixture) are not affected.  Uses HTTP
    ``/api/testing/reset-db`` when ``CURIO_E2E_USE_EXISTING=1`` so the
    running backend wipes its own sqlite file.
    """
    _clean_db(request, test_db_paths)
    yield
    _clean_db(request, test_db_paths)


def pytest_generate_tests(metafunc):
    """Parametrize any test / fixture that requests ``loaded_workflow``.
    Ref: https://docs.pytest.org/en/stable/example/parametrize.html#a-quick-port-of-testscenarios
    This replaces the previous
    ``@pytest.mark.parametrize("loaded_workflow", ..., indirect=True)``
    on ``TestWorkflowCanvas``.  Because it lives in conftest.py, it
    applies to every module collected under ``test_frontend/``.
    """
    if "loaded_workflow" in metafunc.fixturenames:
        files = load_workflow_files_from_folder()
        metafunc.parametrize(
            "loaded_workflow",
            files,
            indirect=True,
            ids=[os.path.basename(f) for f in files],
        )
