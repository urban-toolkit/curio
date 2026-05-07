import os

import pytest

from .utils import REPO_ROOT
from .fixtures import _clean_db

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    # Uncomment to run the detailed examples
    # "docs/examples/01-visual-analytics.json",
    # "docs/examples/02-what-if.json",
    # "docs/examples/03-expert-in-the-loop.json",
    # "docs/examples/04-accessibility-analysis.json",
    # "docs/examples/05-flooding-complaints.json",
    # "docs/examples/07-speed-camera.json",
    # "docs/examples/08-red-light-violation.json",
    # "docs/examples/09-energy-efficiency.json",
    # "docs/examples/10-green-roofs.json",

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
