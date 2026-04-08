import os

from .utils import REPO_ROOT

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    # Uncomment to run the deatailed examples
    # "docs/examples/01-visual-analytics.json",
    # "docs/examples/02-what-if.json",
    # "docs/examples/03-expert-in-the-loop.json",
    # "docs/examples/04-accessibility-analysis.json",
    # "docs/examples/05-flooding-complaints.json",
    # "docs/examples/07-speed-camera.json",
    # "docs/examples/08-red-light-violation.json",
    # "docs/examples/09-energy-efficiency.json",
    # "docs/examples/10-green-roofs.json",


    # TODO: extract the worrkflows inside
    # "NewMerge.json",

    "docs/examples/dataflows/DefaultWorkflow.json",

    "docs/examples/dataflows/DataPool_df.json",
    "docs/examples/dataflows/DataPool_gdf.json",

    "docs/examples/dataflows/DataPool_Vega_2.json",
    "docs/examples/dataflows/DataPool_Vega.json",
    "docs/examples/dataflows/DataPool_UTK.json",

    "docs/examples/dataflows/Image.json",
    "docs/examples/dataflows/Merge.json",
    "docs/examples/dataflows/MergeFlowDataPool.json",

    "docs/examples/dataflows/Interaction.json",
    "docs/examples/dataflows/Interaction_UTK.json",
    "docs/examples/dataflows/Interaction_Vega.json",

    "docs/examples/dataflows/Number Multiplier (Widget).json",

    "docs/examples/dataflows/Vega.json",

    "docs/examples/dataflows/UTK.json",
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
