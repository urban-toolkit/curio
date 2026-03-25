import os

from .utils import REPO_ROOT

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    # "docs/examples/01-visual-analytics.json",

    # TODO: extract the worrkflows inside
    # "NewMerge.json",

    "docs/examples/flows/DefaultWorkflow.json",

    "docs/examples/flows/DataPool_df.json",
    "docs/examples/flows/DataPool_gdf.json",

    "docs/examples/flows/DataPool_Vega_2.json",
    "docs/examples/flows/DataPool_Vega.json",
    "docs/examples/flows/DataPool_UTK.json",

    "docs/examples/flows/Image.json",
    "docs/examples/flows/Merge.json",
    "docs/examples/flows/MergeFlowDataPool.json",

    "docs/examples/flows/Interaction.json",
    "docs/examples/flows/Interaction_UTK.json",
    "docs/examples/flows/Interaction_Vega.json",

    "docs/examples/flows/Number Multiplier (Widget).json",

    "docs/examples/flows/Vega.json",

    "docs/examples/flows/UTK.json",
]


def load_workflow_files_from_folder():
    """Return absolute paths for every workflow in WORKFLOW_FILES.

    Respects the ``CURIO_E2E_WORKFLOWS`` environment variable: when set
    to a comma-separated list of basenames (e.g.
    ``CURIO_E2E_WORKFLOWS=Vega.json,UTK.json``) only those workflows
    are included.  This makes it easy to run a quick subset during
    development or in CI smoke tests.
    """
    subset = os.environ.get("CURIO_E2E_WORKFLOWS")
    names = (
        [n.strip() for n in subset.split(",") if n.strip()]
        if subset
        else WORKFLOW_FILES
    )
    return [os.path.join(REPO_ROOT, name) for name in names]


# ------------------------------------------------------------------ #
# Dynamic parametrization hook
# ------------------------------------------------------------------ #

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
