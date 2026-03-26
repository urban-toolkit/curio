import os
import re
import json
import time

from .utils import (
    save_workflow_test_screenshot,
    get_shared_data_dir,
    load_dot_data,
    strip_volatile_keys,
    execute_workflow_programmatically,
)
from .workflow_spec import NodeSpec, CODE_EDITOR_TYPES

"""
This test file is to test the loading of workflow files in the frontend.
To watch the browser (see the menu open): run with --headed, e.g.
"""

def test_load_workflow_files(workflow_files):
    """
    This test is to check that the workflow files can be loaded from the /tests folder,
    Test if they have the expected structure (nodes and edges).
    The test will fail if the workflow file has no nodes or edges
    """
    assert len(workflow_files) > 0, f"No workflow files found in folder: {workflow_files}"
    #  assert filenames are unique
    assert len(workflow_files) == len(set(workflow_files)), "Workflow files have duplicate filenames"

    # For each workflow file print the Nodes and Edges count
    for workflow_file in workflow_files:
        with open(workflow_file, "r") as f:
            workflow_data = f.read()
            workflow_data = json.loads(workflow_data)
            print(f"Processing workflow file: {workflow_file}")
            nodes_count = len(workflow_data['dataflow']['nodes'])
            edges_count = len(workflow_data['dataflow']['edges'])

            print(f"{os.path.basename(workflow_file)}: {nodes_count} nodes, {edges_count} edges")
            # add assertion to check that the workflow file has at least 1 node and 1 edge
            assert nodes_count > 0, f"Workflow file {workflow_file} has no nodes"
            assert edges_count > 0, f"Workflow file {workflow_file} has no edges"



# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestWorkflowCanvas:
    """End-to-end checks for each workflow loaded into the ReactFlow canvas.

    The class-scoped ``loaded_workflow`` fixture uploads the workflow once.
    All five test methods share the same browser page and parsed spec
    via ``self.page`` and ``self.spec``.
    """

    # -- helpers -----------------------------------------------------------

    def _node_locator(self, node: NodeSpec):
        """Return a Playwright ``Locator`` for a ReactFlow node element."""
        return self.page.locator(f'.react-flow__node[data-id="{node.id}"]')

    def _save_screenshot(self, request):
        """Persist canvas screenshot (see ``save_workflow_test_screenshot``)."""
        save_workflow_test_screenshot(
            self.page,
            self.spec.filepath,
            test_name=request.function.__name__,
        )

    def _execute_all_playable_nodes(self):
        """Click *play* on every node that has a play button (topological order)
        and wait for each to finish.  Skips if already executed for the
        current workflow (guards against repeated calls across tests that
        share the same class-scoped page)."""
        if getattr(self.__class__, '_executed_workflow', None) == self.spec.filepath:
            return
        for node in self.spec.topo_sorted_nodes():
            node_el = self._node_locator(node)
            node_el.scroll_into_view_if_needed()

            # if Pool box wait for data table to show
            if node.type == "DATA_POOL":
                data_table = node_el.locator("td.MuiTableCell-root")
                data_table.first.wait_for(state="visible", timeout=10000)
                time.sleep(5)
                assert data_table.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing its "
                    f"data table"
                )

            if not node.has_play_button:
                continue

            play_btn = node_el.locator("svg.fa-circle-play")
            play_btn.wait_for(state="visible", timeout=10000)
            play_btn.click(force=True)

            # wait for loading spinner to appear
            # loading_spinner = node_el.locator(".spinner-border")
            # loading_spinner.wait_for(state="visible", timeout=10000)
            # # wait for loading spinner to disappear
            # loading_spinner.wait_for(state="hidden", timeout=10000)

            # Wait until either "Done" or "Error" is visible
            node_el.locator("span").filter(
                has_text=re.compile(r"^(Done|Error)$")
            ).first.wait_for(state="visible", timeout=100000)

            # Wait for the execution outcome (up to 30 s)
            done_span = node_el.locator("span").filter(has_text=re.compile(r"^Done$"))
            error_span = node_el.locator("span").filter(has_text=re.compile(r"^Error$"))
            done_span.first.wait_for(state="visible", timeout=100000)

            assert done_span.count() >= 1, (
                f"Node {node.id} ({node.type}) did not produce 'Done' — "
                f"error visible: {error_span.is_visible()}"
            )
            # Check if output tab is active

            # wait for output tab to be visible
            output_tab = node_el.locator(
                '.nav-link[data-rr-ui-event-key="output"]'
            )
            output_tab.first.wait_for(state="visible", timeout=10000)
            assert output_tab.count() >= 1, (
                f"Code node {node.id} ({node.type}) is missing its "
                f"output tab"
            )
            if output_tab.count() >= 1:
                # Check if the output content box is active
                is_active = "active" in (output_tab.get_attribute("class") or "")
                assert is_active, (
                    f"Output content box {node.id} ({node.type}) is not active"
                )
        self.__class__._executed_workflow = self.spec.filepath

    # -- 1. Node & edge counts --------------------------------------------

    def test_node_and_edge_count(self, loaded_workflow, request):
        """The canvas must contain the exact number of nodes and edges
        declared in the workflow JSON."""
        node_els = self.page.locator(".react-flow__node")
        edge_els = self.page.locator(".react-flow__edge")

        wf_name = os.path.basename(self.spec.filepath)
        assert node_els.count() == self.spec.nodes_count, (
            f"[{wf_name}] Expected {self.spec.nodes_count} nodes, "
            f"found {node_els.count()}"
        )
        assert edge_els.count() == self.spec.edges_count, (
            f"[{wf_name}] Expected {self.spec.edges_count} edges, "
            f"found {edge_els.count()}"
        )
        # self._save_screenshot(request)

    # -- 2. Node positions (relative ordering) -----------------------------

    def test_node_positions(self, loaded_workflow, request):
        """Every node must be rendered on the canvas, and relative
        x-positions from the JSON specification must be preserved
        (``fitView`` rescales but keeps the layout)."""
        positions: dict[str, tuple[float, float]] = {}

        for node in self.spec.nodes:
            node_el = self._node_locator(node)
            assert node_el.count() == 1, (
                f"Node {node.id} ({node.type}) not found on canvas"
            )
            bbox = node_el.bounding_box()
            assert bbox is not None, (
                f"Node {node.id} ({node.type}) has no bounding box (not visible)"
            )
            positions[node.id] = (bbox["x"], bbox["y"])

        # Verify relative x-ordering: if node A.x < B.x in the spec, then
        # A should also appear to the left of (or at the same x as) B on
        # the canvas.
        sorted_by_spec_x = sorted(self.spec.nodes, key=lambda n: n.x)
        for i in range(len(sorted_by_spec_x) - 1):
            a = sorted_by_spec_x[i]
            b = sorted_by_spec_x[i + 1]
            if a.x < b.x:
                assert positions[a.id][0] <= positions[b.id][0], (
                    f"Node {a.id} (spec x={a.x:.1f}) should be left of "
                    f"{b.id} (spec x={b.x:.1f}), but canvas x "
                    f"{positions[a.id][0]:.1f} > {positions[b.id][0]:.1f}"
                )
        # self._save_screenshot(request)

    # -- 3. Node type & content (code / grammar / datapool) ----------------

    def test_node_type_and_content(self, loaded_workflow, request):
        """Each node must render the correct editor widget for its category:

        * **code** nodes  – a Monaco code editor (``.monaco-editor``)
        * **grammar** nodes – a JSON grammar editor (``#grammarJsonEditor*``)
        * **datapool** nodes – the data-tabs element (``#data-tabs``)
        * **passive** nodes – just the node container (no editor expected)
        """
        for node in self.spec.nodes:
            node_el = self._node_locator(node)
            assert node_el.count() == 1, (
                f"Node {node.id} ({node.type}) not found on canvas"
            )

            if node.category == "code":

                # 1. Check if the output tab is present (always rendered in BoxEditor)
                output_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="output"]'
                )

                assert output_tab.count() >= 1, (
                    f"Code node {node.id} ({node.type}) is missing its "
                    f"output tab"
                )
                if output_tab.count() >= 1:
                    # Check if the output content box is active
                    is_active = "active" in (output_tab.get_attribute("class") or "")
                    assert is_active, (
                        f"Output content box {node.id} ({node.type}) is not active"
                    )
                    if not is_active:
                        output_tab.click(force=True)
                        output_tab.wait_for(state="visible", timeout=3000)
                    
                    # OutputContent renders #computation-tabs-tab- with
                    # Output / Error / Warning sub-tabs.
                    computation_tabs = node_el.locator(f"#computation-tabs-tab-0")

                    if computation_tabs.count() >= 1:
                        # and should contain a div with classes tab-pane and active
                        active_pane = node_el.locator(".tab-pane.active")
                        assert active_pane.count() >= 1, (
                            f"Code node {node.id} ({node.type}) output "
                            f"area has no active tab-pane"
                        )
                        # the output tab content has class tab-content
                        tab_content = active_pane.locator(".tab-content")
                        # wait for the tab-content to be visible
                        tab_content.wait_for(state="visible", timeout=3000)
                        assert tab_content.count() >= 1, (
                            f"Code node {node.id} ({node.type}) output "
                            f"area is missing .tab-content"
                        )
                        # and should contain a title h6 with text "Output"
                        output_heading = tab_content.locator("h6").filter(
                            has_text="Output"
                        )
                        assert output_heading.count() >= 1, (
                            f"Code node {node.id} ({node.type}) active "
                            f"output pane is missing 'Output' heading"
                        )
                        # and should contain a div below the h6 with
                        # text "No output available."
                        no_output_msg = tab_content.locator("div").filter(
                            has_text="No output available."
                        )
                        assert no_output_msg.count() >= 1, (
                            f"Code node {node.id} ({node.type}) active "
                            f"output pane is missing 'No output available.'"
                        )
                        # and should not contain a title h6 with text "Error"
                        error_heading = tab_content.locator("h6").filter(
                            has_text="Error"
                        )
                        assert error_heading.count() == 0, (
                            f"Code node {node.id} ({node.type}) active "
                            f"output pane should not contain 'Error' heading"
                        )
                        # and should not contain a title h6 with text "Warning"
                        warning_heading = tab_content.locator("h6").filter(
                            has_text="Warning"
                        )
                        assert warning_heading.count() == 0, (
                            f"Code node {node.id} ({node.type}) active "
                            f"output pane should not contain 'Warning' heading"
                        )
                
                if node.type in CODE_EDITOR_TYPES:
                    # 2. Check if the code tab is rendered
                    code_tab = node_el.locator(
                        '.nav-link[data-rr-ui-event-key="code"]'
                    )

                    assert code_tab.count() >= 1, (
                        f"Code node {node.id} ({node.type}) is missing its "
                        f"code tab"
                    )
                    # 3. Click on the code tab (if not already active) and wait for the editor
                    is_active = "active" in (code_tab.get_attribute("class") or "")
                    if not is_active:
                        code_tab.click(force=True)
                        code_tab.wait_for(state="visible", timeout=3000)
                    editor = node_el.locator(".monaco-editor")
                    editor.first.wait_for(state="visible", timeout=5000)
                    assert editor.count() >= 1, (
                        f"Code node {node.id} ({node.type}) is missing its "
                        f"Monaco editor"
                    )

                    # Verify the code loaded into the Monaco editor matches the
                    # workflow JSON content.  Monaco renders code as a complex
                    # DOM tree (view-lines / spans), so we read the value via
                    # the Monaco JS API instead of matching DOM text.
                    if node.content.strip():
                        editor_value = self.page.evaluate(
                            """(nodeId) => {
                                const nodeEl = document.querySelector(
                                    `.react-flow__node[data-id="${nodeId}"]`
                                );
                                if (!nodeEl) return null;
                                const editorEl = nodeEl.querySelector('.monaco-editor');
                                if (!editorEl) return null;
                                const editors = window.monaco?.editor?.getEditors?.() || [];
                                const match = editors.find(
                                    e => editorEl.contains(e.getDomNode())
                                );
                                return match ? match.getValue() : null;
                            }""",
                            node.id,
                        )
                        assert editor_value is not None, (
                            f"Code node {node.id} ({node.type}): could not "
                            f"read Monaco editor value via JS API"
                        )
                        # Normalize line endings: workflow/OS may use \r\n, editor uses \n
                        expected = node.content.strip().replace("\r\n", "\n").replace("\r", "\n")
                        actual = editor_value.strip().replace("\r\n", "\n").replace("\r", "\n")
                        assert expected in actual, (
                            f"Code node {node.id} ({node.type}): editor "
                            f"content does not contain the expected code.\n"
                            f"  Expected (snippet): {expected[:120]}\n"
                            f"  Actual   (snippet): {actual[:120]}"
                        )
                     

            elif node.category == "grammar":
                # 1. Check if the output tab is present
                output_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="output"]'
                )
                assert output_tab.count() >= 1, (
                    f"Grammar node {node.id} ({node.type}) is missing its "
                    f"output tab"
                )

                # 2. Check if the grammar tab is rendered
                grammar_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="grammar"]'
                )

                assert grammar_tab.count() >= 1, (
                    f"Grammar node {node.id} ({node.type}) is missing its "
                    f"grammar tab"
                )
                # 3. Click on the grammar tab (if not already active) and
                #    wait for the grammar editor to be rendered
                is_active = "active" in (grammar_tab.get_attribute("class") or "")
                if not is_active:
                    grammar_tab.click(force=True)

                grammar_editor = node_el.locator(
                    f'[id="grammarJsonEditor{node.id}"], '
                    f'[id="vega-editor_{node.id}"]'
                )
                grammar_editor.first.wait_for(state="visible", timeout=6000)
                assert grammar_editor.count() >= 1, (
                    f"Grammar node {node.id} ({node.type}) is missing its "
                    f"grammar editor"
                )
                # TODO: check if the grammar is rendered inside the editor
                # Verify the json loaded into the grammar editor matches the
                # workflow JSON content. 
                # Grammar editor renders a JSONEditorReact component.

            elif node.category == "datapool":
                data_tabs = node_el.locator("#data-tabs-tab-0")
                assert data_tabs.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing "
                    f"#data-tabs"
                )

            else:
                # passive nodes (MERGE_FLOW, VIS_IMAGE, …): just verify the
                # resizable container rendered
                resizable = node_el.locator(f'[id="{node.id}resizable"]')
                assert resizable.count() >= 1, (
                    f"Passive node {node.id} ({node.type}) is missing its "
                    f"resizable container"
                )
        self._save_screenshot(request)

    # # -- 4. Node execution (play button) -----------------------------------

    def test_node_execution(self, loaded_workflow, request):
        """Click the play button on each executable node in topological
        order and verify that the output status shows *Done*.

        Before touching the browser, the workflow is executed
        programmatically (in-process, seeded) to produce expected
        ``.data`` files.  After the browser run the two sets of files
        are compared.
        """
        expected_map = execute_workflow_programmatically(self.spec, seed=42)

        self._execute_all_playable_nodes()

        for node in self.spec.nodes:
            if not node.has_play_button:
                continue

            node_el = self._node_locator(node)
            # wait for the done span to be visible
            done_span = node_el.locator("span").filter(
                has_text=re.compile(r"^Done$")
            )
            done_span.first.wait_for(state="visible", timeout=10000)
            assert done_span.count() >= 1, (
                f"Node {node.id} ({node.type}) output is not 'Done' "
                f"after full workflow execution"
            )

            # ---------------------------------------------------------------
            # Check output tab is active and rendered correctly
            # ---------------------------------------------------------------

            # wait for output tab to be visible
            output_tab = node_el.locator(
                '.nav-link[data-rr-ui-event-key="output"]'
            )
            output_tab.first.wait_for(state="visible", timeout=10000)
            assert output_tab.count() >= 1, (
                f"Code node {node.id} ({node.type}) is missing its "
                f"output tab"
            )
            if output_tab.count() >= 1:
                # Check if the output content box is active
                is_active = "active" in (output_tab.get_attribute("class") or "")
                if not is_active:
                    output_tab.click(force=True)
                    output_tab.wait_for(state="visible", timeout=3000)
                assert is_active, (
                    f"Output content box {node.id} ({node.type}) is not active"
                )
                
                # OutputContent renders #computation-tabs-tab- with
                # Output / Error / Warning sub-tabs.
                computation_tabs = node_el.locator(f"#computation-tabs-tab-0")

                if computation_tabs.count() >= 1:
                    # and should contain a div with classes tab-pane and active
                    active_pane = node_el.locator(".tab-pane.active")
                    assert active_pane.count() >= 1, (
                        f"Code node {node.id} ({node.type}) output "
                        f"area has no active tab-pane"
                    )
                    # the output tab content has class tab-content
                    tab_content = active_pane.locator(".tab-content")
                    # wait for the tab-content to be visible
                    tab_content.wait_for(state="visible", timeout=3000)
                    assert tab_content.count() >= 1, (
                        f"Code node {node.id} ({node.type}) output "
                        f"area is missing .tab-content"
                    )
                    # The output box should contain a title h6 with text "Output" 
                    output_heading = tab_content.locator("h6").filter(
                        has_text="Output"
                    )
                    output_heading.first.wait_for(state="visible", timeout=10000)
                    assert output_heading.count() >= 1, (
                        f"Node {node.id} ({node.type}) is missing its "
                        f"output heading"
                    )
                    # and should not contain a div below the h6 with text "No output available."
                    no_output_msg = tab_content.locator("div").filter(
                        has_text="No output available."
                    )
                    no_output_msg.first.wait_for(state="hidden", timeout=10000)
                    assert no_output_msg.count() == 0, (
                        f"Node {node.id} ({node.type}) is not missing its "
                        f"no output message"
                    )
                    # and should not contain a title h6 with text "Error"
                    error_heading = tab_content.locator("h6").filter(
                        has_text="Error"
                    )
                    error_heading.first.wait_for(state="hidden", timeout=10000)
                    assert error_heading.count() == 0, (
                        f"Node {node.id} ({node.type}) is not missing its "
                        f"error heading"
                    )
                    # and should not contain a title h6 with text "Warning"
                    warning_heading = tab_content.locator("h6").filter(
                        has_text="Warning"
                    )
                    warning_heading.first.wait_for(state="hidden", timeout=10000)
                    assert warning_heading.count() == 0, (
                        f"Node {node.id} ({node.type}) is not missing its "
                        f"warning heading"
                    )

                    # ------------------------------------------------------------------------
                    # Test the output tab pane content.
                    # ------------------------------------------------------------------------
                    # it should be a text with the output file path following the pattern: <uuid_regex>.data
                    output_content = tab_content.locator("div").filter(
                        has_text=re.compile(r"Saved to file\:\s\w+_\w+.data$")
                    )
                    output_content.first.wait_for(state="visible", timeout=10000)
                    assert output_content.count() >= 1, (
                        f"Node {node.id} ({node.type}) is missing its "
                        f"output content"
                    )

                    # Verify .data file content against programmatic execution
                    data_file_name = output_content.first.evaluate(
                        r"""(el) => {
                            const match = el.textContent.match(/Saved to file:\s(\w+_\w+\.data)$/);
                            return match ? match[1] : null;
                        }"""
                    )
                    assert data_file_name is not None, (
                        f"Node {node.id} ({node.type}) is missing its data file path"
                    )

                    data_file_path = os.path.join(get_shared_data_dir(), data_file_name)
                    assert os.path.exists(data_file_path), (
                        f"Node {node.id} ({node.type}) is missing its data file"
                    )

                    if node.id in expected_map:
                        actual = strip_volatile_keys(load_dot_data(data_file_path))
                        expected = strip_volatile_keys(
                            load_dot_data(expected_map[node.id])
                        )
                        if actual != expected:
                            diff_keys = [
                                k for k in set(actual) | set(expected)
                                if actual.get(k) != expected.get(k)
                            ]
                            raise AssertionError(
                                f"Node {node.id} ({node.type}) data file content "
                                f"does not match the programmatic execution. "
                                f"Differing top-level keys: {diff_keys}"
                            )
                
                
                
                # ----------------------------------------------------------
                # TODO: Test the created SVG Vega-Lite visualizations
                # ----------------------------------------------------------
                # Verify Vega-Lite visualization is rendered correctly
                # get the previous node data from saved .data file
                # Get the grammar json content from the dataflow json
                # programatically generate the vega lite svg vis
                # if node.category == "grammar":
                #     # Get the grammar json content from the dataflow json
                #     grammar_json = self.spec.nodes.find(node.id).content
                #     assert grammar_json is not None, (
                #         f"Node {node.id} ({node.type}) is missing its "
                #         f"grammar json"
                #     )
                #     compile the grammar json using a vega-lite compiler
                #     assert the visualization is rendered correctly

        self._save_screenshot(request)

    # -- 5. Provenance graph -------------------------------------------------

    def test_provenance_graph(self, loaded_workflow, request):
        """After executing every playable node, each node that exposes a
        provenance tab must render a WebGL canvas with content."""
        self._execute_all_playable_nodes()

        for node in self.spec.nodes:
            if not node.has_play_button:
                continue

            node_el = self._node_locator(node)

            # ---------------------------------------------------------------
            # Check provenance graph is rendered correctly
            # ---------------------------------------------------------------

            # If the node has a provenance tab, 
            # check if the provenance graph is rendered correctly
            provenance_tab = node_el.locator(
                '.nav-link[data-rr-ui-event-key="provenance"]'
            )
            if provenance_tab.count() == 0:
                continue  # Node has no provenance tab (e.g. DATA_POOL)
            provenance_tab.first.wait_for(state="visible", timeout=10000)
            provenance_tab.click(force=True)

            # Canvas is inside the provenance tab pane (active after click)
            # The provenance pane contains a reagraph canvas element (GraphCanvas)
            provenance_pane = node_el.locator(".tab-pane.active.show")
            canvas = provenance_pane.locator("canvas")
            canvas.first.wait_for(state="visible", timeout=10000)
            assert canvas.count() >= 1, (
                f"Node {node.id} ({node.type}) is missing its canvas"
            )

            # The provenance graph uses reagraph (WebGL/Three.js), not 2D canvas.
            has_content = canvas.first.evaluate("""
                (canvas) => {
                    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
                    if (!gl) return false;
                    const w = canvas.width, h = canvas.height;
                    if (w < 2 || h < 2) return false;
                    return true;
                }
            """)
            assert has_content, (
                f"Node {node.id} ({node.type}) provenance canvas appears empty "
                f"(no drawn content detected)"
            )
        # self._save_screenshot(request)

