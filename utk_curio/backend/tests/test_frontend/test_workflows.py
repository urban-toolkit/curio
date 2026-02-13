import os
import re
import time
import pytest
import json
from .utils import FrontendPage


# Repo root is 4 levels up from this file (test_frontend -> tests -> backend -> utk_curio)
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
TEST_WORKFLOWS_PATH = os.path.join(_REPO_ROOT, "tests")

# workflow_nodes = {
#     "DataPool_df.json": (2, names:['', ''], contents: ['', '']),
# }

# This is the setup, it should run for every workflow json file
# create a fixture that loads all workflow json files from a folder
def load_workflow_files_from_folder():
    """Load all workflow JSON files from the specified folder."""
    workflow_files = [
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

#         "NewMerge.json",
        "Number Multiplier (Widget).json",

        "Vega.json",

        "UTK.json",

    ]

    # append the path to the folder path
    workflow_files = [os.path.join(TEST_WORKFLOWS_PATH, filename) for filename in workflow_files]
#     print(workflow_files)

    assert len(workflow_files) > 0, f"No workflow files found in folder: {workflow_files}"

    #  assert filenames are unique
    assert len(workflow_files) == len(set(workflow_files)), "Workflow files have duplicate filenames"

    return workflow_files

# TODO: see how to use decorators and pass an array for loop
# use parametrize to loop through each workflow file and run the test
@pytest.mark.parametrize("workflow_file", load_workflow_files_from_folder())
def test_upload_default_workflow(workflow_file, app_frontend: FrontendPage,  page):
    """Test that the frontend can load the default workflow correctly.

    To watch the browser (see the menu open): run with --headed, e.g.
      pytest utk_curio/backend/tests/test_frontend/test_workflows.py --headed
    """
    app_frontend.goto_page("/")
    page.wait_for_load_state("domcontentloaded")
    # page.wait_for_load_state("networkidle")  # wait for app/canvas to be ready

    #loop through each workflow
    print(f"Testing workflow file: {workflow_file}")

    # Wait for the app to render the menu bar, then open the File dropdown
    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=15000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the canvas/ReactFlow layer on top
    file_menu_btn.click(force=True)

    # Wait for the dropdown menu to appear
    load_spec = page.get_by_role("button", name="Load specification")
    load_spec.wait_for(state="visible", timeout=5000)
    assert load_spec.is_visible()

    # Then click on "Load specification" and upload the default workflow file
    with page.expect_file_chooser() as fc_info:
        page.get_by_text("Load specification").click()
    file_chooser = fc_info.value
    file_chooser.set_files(workflow_file)

    time.sleep(5)  # 1 min – pause to see the menu opened

# @pytest.mark.parametrize("workflow_file", load_workflow_files_from_folder())
def test_load_workflow_files():
    """Test that workflow files can be loaded from the folder."""
    workflow_files = load_workflow_files_from_folder()
    # For each workflow file print the Nodes and Edges count
    for workflow_file in workflow_files:
        with open(workflow_file, "r") as f:
            workflow_data = f.read()
            workflow_data = json.loads(workflow_data)
            print(f"Processing workflow file: {workflow_file}")
            nodes_count = len(workflow_data['dataflow']['nodes'])
            edges_count = len(workflow_data['dataflow']['edges'])
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DataPool_df.json
            # DataPool_df.json: 2 nodes, 1 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DataPool_gdf.json
            # DataPool_gdf.json: 2 nodes, 1 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DataPool_UTK.json
            # DataPool_UTK.json: 3 nodes, 2 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DataPool_Vega_2.json
            # DataPool_Vega_2.json: 4 nodes, 3 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DataPool_Vega.json
            # DataPool_Vega.json: 3 nodes, 2 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/DefaultWorkflow.json
            # DefaultWorkflow.json: 2 nodes, 1 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Interaction_UTK.json
            # Interaction_UTK.json: 5 nodes, 5 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Interaction_Vega.json
            # Interaction_Vega.json: 5 nodes, 5 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Interaction.json
            # Interaction.json: 6 nodes, 7 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Merge.json
            # Merge.json: 5 nodes, 4 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/MergeFlowDataPool.json
            # MergeFlowDataPool.json: 7 nodes, 6 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Number Multiplier (Widget).json
            # Number Multiplier (Widget).json: 6 nodes, 6 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/UTK.json
            # UTK.json: 2 nodes, 1 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Vega.json
            # Vega.json: 2 nodes, 1 edges
            # Processing workflow file: /Users/karla/coding/curio-main/tests/Image.json
            # Image.json: 2 nodes, 1 edges
            # how to see this print output when running pytest? run with -s to see print statements, e.g.:
            # pytest utk_curio/backend/tests/test_frontend/test_workflows.py -s
            # and how to run this test function only?
            # pytest utk_curio/backend/tests/test_frontend/test_workflows.py -s -k test_load_workflow_files
            print(f"{os.path.basename(workflow_file)}: {nodes_count} nodes, {edges_count} edges")
            # # add assertion to check that the workflow file has at least 1 node and 1 edge
            # assert nodes_count > 0, f"Workflow file {workflow_file} has no nodes"
            # assert edges_count > 0, f"Workflow file {workflow_file} has no edges"

# ----------------
# TODO TESTS
# ----------------

# New Test: Check that the workflow is loaded correctly by checking the number of nodes and edges

# Check if the boxes positions appear correctly(without errors) on the canvas
# New Test: Check if the boxes positions appear correctly(without errors) on the canvas

# New Function Test: Check each node box name and check if the title matches by checking the Box Titles
# New Test: Check each box content: if it is being loaded correctly (GRAMMAR OR CODE)
# New Test: Check each box execution: run the box(play button) and see if the result is correct
# Check each box execution: run the box(play button) and see if the result is correct










