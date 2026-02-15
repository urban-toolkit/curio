import os

from .utils import REPO_ROOT

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    "DefaultWorkflow.json",

    "DataPool_df.json",
    "DataPool_gdf.json",

    "DataPool_Vega_2.json",
    "DataPool_Vega.json",
    "DataPool_UTK.json",

    "Image.json",
    "Merge.json",
    "MergeFlowDataPool.json",

    "Interaction.json",
    "Interaction_UTK.json",
    "Interaction_Vega.json",

    # "NewMerge.json",
    "Number Multiplier (Widget).json",

    "Vega.json",

    "UTK.json",
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
    return [os.path.join(REPO_ROOT, "tests", name) for name in names]


# ------------------------------------------------------------------ #
# Dynamic parametrization hook
# ------------------------------------------------------------------ #

def pytest_generate_tests(metafunc):
    """Parametrize any test / fixture that requests ``loaded_workflow``.

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
