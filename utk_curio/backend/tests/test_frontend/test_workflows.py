import os
import re
import json
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# from .utils import (
    # save_workflow_test_screenshot,
    # get_shared_data_dir,
    # load_dot_data,
    # strip_volatile_keys,
    # execute_workflow_programmatically,
    # dot_data_to_vega_values,
    # save_expected_svg,
    # compare_svg_structure,
# )
from .utils import (
    save_workflow_test_screenshot,
    get_shared_data_dir,
    load_artifact_as_dict,
    execute_workflow_programmatically,
    dump_browser_log,
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
        with open(workflow_file, "r", encoding="utf-8") as f:
            workflow_data = f.read()
            workflow_data = json.loads(workflow_data)
            print(f"Processing workflow file: {workflow_file}")
            nodes_count = len(workflow_data['dataflow']['nodes'])
            edges_count = len(workflow_data['dataflow']['edges'])

            print(f"{os.path.basename(workflow_file)}: {nodes_count} nodes, {edges_count} edges")
            # Edges are not required: single-node autk-grammar workflows are
            # self-contained and have zero edges by design.
            assert nodes_count > 0, f"Workflow file {workflow_file} has no nodes"



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
        """Persist canvas screenshot (see ``save_workflow_test_screenshot``)
        and dump the captured browser console/pageerror log alongside it.

        The browser log is the only window into autk's caught exceptions
        (autkBehaviorFactory swallows them into React state without ever
        calling ``console.error``), so we always write it — not just on
        failure — while we're debugging the rendering issue.
        """
        save_workflow_test_screenshot(
            self.page,
            self.spec.filepath,
            test_name=request.function.__name__,
        )
        log_entries = getattr(self.page, "_curio_browser_log", None) or []
        autk_errors = getattr(self.__class__, "_autk_error_texts", None) or {}
        webgpu_diag = getattr(self.page, "_curio_webgpu_diagnostics", None) or \
            getattr(self.__class__, "_webgpu_diagnostics_cache", None)
        if log_entries or autk_errors or webgpu_diag:
            dump_browser_log(
                self.spec.filepath,
                request.function.__name__,
                list(log_entries),
                autk_errors=dict(autk_errors),
                webgpu_diagnostics=webgpu_diag,
            )

    # AUTK_GRAMMAR nodes render via WebGPU when they carry a map/plot. The data
    # section runs in the backend sandbox (autk-db over local PBF). There is no
    # WebGPU tolerance: an autk node that errors is a hard failure. The browser
    # must provide WebGPU (the parent ``tests/conftest.py`` points
    # ``executable_path`` at system Chrome precisely so it does).
    _WEBGPU_DIAGNOSTIC_TYPES = {"AUTK_GRAMMAR"}

    def _webgpu_diagnostics(self) -> dict:
        """Return a verbose dump of the browser's WebGPU state — adapter
        info, features, fallback flag, and the result of actually creating
        a device. Cached on the class so it runs once per browser session.

        Purely diagnostic: it distinguishes *no adapter* from *adapter exists
        but device creation fails* — both surface as AUTK Errors but need
        different fixes. We log this dict once per session and attach it to
        the failure dump so the failure mode is visible in pytest output.
        """
        cached = getattr(self.__class__, "_webgpu_diagnostics_cache", None)
        if cached is not None:
            return cached
        try:
            diagnostics = self.page.evaluate(
                """async () => {
                    const out = {
                        userAgent: navigator.userAgent,
                        url: location.href,
                        isSecureContext: window.isSecureContext,
                        hasNavigatorGpu: !!navigator.gpu,
                    };
                    if (!navigator.gpu) return out;
                    try {
                        const adapter = await navigator.gpu.requestAdapter();
                        if (!adapter) {
                            out.adapter = null;
                            return out;
                        }
                        let info = null;
                        try {
                            info = adapter.requestAdapterInfo
                                ? await adapter.requestAdapterInfo()
                                : null;
                        } catch (e) { info = { error: String(e) }; }
                        out.adapter = {
                            info: info ? {
                                vendor: info.vendor,
                                architecture: info.architecture,
                                device: info.device,
                                description: info.description,
                            } : null,
                            features: [...adapter.features],
                            isFallbackAdapter: adapter.isFallbackAdapter,
                        };
                        try {
                            const device = await adapter.requestDevice();
                            out.device = { ok: !!device };
                        } catch (e) {
                            out.device = { error: String(e) };
                        }
                    } catch (e) {
                        out.requestAdapterError = String(e);
                    }
                    return out;
                }"""
            )
        except Exception as exc:
            diagnostics = {"probeError": str(exc)}
        self.__class__._webgpu_diagnostics_cache = diagnostics
        # Log once per session so pytest -s shows it in the test output AND
        # also persist it to disk so it ends up in the browser_log.txt file
        # (pytest stdout is easy to lose; the on-disk file always shows up).
        if not getattr(self.__class__, "_webgpu_diagnostics_logged", False):
            print(f"\n[webgpu-diagnostics] {json.dumps(diagnostics, indent=2)}")
            self.__class__._webgpu_diagnostics_logged = True
            # Stash on the page so dump_browser_log can include it.
            self.page._curio_webgpu_diagnostics = diagnostics  # type: ignore[attr-defined]
        return diagnostics

    def _read_code_node_error_text(self, node_el) -> str | None:
        """Return the error message text from a code node's inline output
        area. Returns ``None`` if it cannot be read.

        Works for both autk behavior nodes and Python/JS code nodes:
        CodeEditor renders any output (success or error) into the same
        ``.nowheel.nodrag`` div with the ``[N]:`` counter (CodeEditor.tsx
        ~200-219). For autk, ``autkBehaviorFactory``'s catch block sets
        ``output = { code: 'error', content: err.message }``; for
        COMPUTATION_ANALYSIS / DATA_LOADING / DATA_TRANSFORMATION the
        sandbox's stderr/exception traceback is routed there too. We
        switch to the code tab so that area is in the layout, then read
        it.
        """
        try:
            code_tab = node_el.locator(
                '.nav-link[data-rr-ui-event-key="code"]'
            ).first
            try:
                code_tab.wait_for(state="visible", timeout=2000)
                if "active" not in (code_tab.get_attribute("class") or ""):
                    code_tab.click(force=True)
            except Exception:
                # Some autk nodes may not expose a code tab depending on
                # NodeEditor config; fall through and read whatever is
                # currently visible.
                pass
            output_area = node_el.locator(".nowheel.nodrag").filter(
                has_text=re.compile(r"\[(\d+|\*| )\]:")
            ).first
            output_area.wait_for(state="visible", timeout=2000)
            return output_area.text_content()
        except Exception:
            return None

    def _capture_autk_error(self, node, node_el) -> None:
        """Print the autk error text to pytest output and stash it on the
        class so the post-test screenshot helper can include it in the
        browser log file.

        Grammar nodes have no readable error tab (the behavior's catch only
        toasts and sets node state), so the literal err.message reaches us via
        the ``console.error('[autk-grammar] node error: …')`` the behavior
        emits — scan the captured browser console for it as well.
        """
        text = self._read_code_node_error_text(node_el)
        if not text:
            log_entries = getattr(self.page, "_curio_browser_log", None) or []
            console_errors = [
                e.get("text", "") for e in log_entries
                if e.get("type") == "error" or e.get("kind") == "pageerror"
            ]
            if console_errors:
                text = " | ".join(console_errors[-5:])
        store = getattr(self.__class__, "_autk_error_texts", None)
        if store is None:
            store = {}
            self.__class__._autk_error_texts = store
        store[node.id] = text or "(could not read error tab)"
        print(
            f"\n[autk-error] node {node.id} ({node.type}): "
            f"{text or '(could not read error tab)'}"
        )

    def _node_execution_timeout_ms(self, node: NodeSpec) -> int:
        """Return a generous timeout for nodes that execute heavy data ops.

        AUTK_GRAMMAR shares the data-node budget: a node with a `data` section
        runs it in the backend sandbox — autk-db parses a local OSM PBF
        (multi-MB) via DuckDB-WASM in Node and round-trips the layers back over
        HTTP. This is deterministic and fast now that the data is local: a
        1.6 MB PBF (171k features) parses in ~12 s including cold-start WASM
        init, and the largest bundled PBF is ~6 MB, so 2 min is ~2.5x the
        worst case. The old 5-min budget dated from the Overpass era (a remote,
        throttled OSM endpoint), which has since been removed — a node that now
        runs past this budget is hung, not slow, so fail it.
        """
        if node.type in {
            "AUTK_GRAMMAR",
            "DATA_LOADING",
            "DATA_TRANSFORMATION",
            "COMPUTATION_ANALYSIS",
        }:
            return 120000
        return 30000

    def _click_play_until_started(self, node, node_el, max_attempts: int = 3):
        """Click *play* and confirm execution actually started.

        ``BoxStyles`` swaps the play SVG for a Bootstrap Spinner the moment
        ``isLoading`` flips to true (see styles.tsx:740-768) and the
        ``CodeEditor`` updates its inline counter from ``[ ]:`` to
        ``[*]:`` once the behavior reports ``output.code === 'exec'``.
        Either signal proves the click was honoured.

        We don't use ``play_btn.click(force=True)`` — ``force=True`` skips
        actionability checks so React Flow's transformed viewport, pointer
        events, or an overlay can swallow the click. Instead we
        ``element.click()`` via ``page.evaluate``, which bypasses the
        viewport transform entirely and delivers the event straight to the
        SVG's React onClick.
        """
        play_btn = node_el.locator("svg.fa-circle-play")
        spinner = node_el.locator(".spinner-border")
        if node.category == "code":
            counter = node_el.locator(".nowheel.nodrag").filter(
                has_text=re.compile(r"\[(\d+|\*)\]:")
            ).first
        else:
            counter = node_el.locator("span").filter(
                has_text=re.compile(r"^(Running|Done|Error)$")
            ).first

        last_error = None
        for attempt in range(max_attempts):
            try:
                play_btn.wait_for(state="visible", timeout=10000)
                # The play button is an ``<svg>`` (FontAwesomeIcon).
                # ``SVGElement`` has no native ``click()`` method, so
                # ``el.click()`` via ``evaluate`` raises ``TypeError`` and
                # ``page.click(force=True)`` silently misses when React
                # Flow's CSS transform throws off the click coordinates.
                # ``dispatch_event("click")`` sends a bubbling synthetic
                # ``MouseEvent`` that React's onClick picks up regardless
                # of where the element actually sits on screen.
                play_btn.dispatch_event("click")
                try:
                    self.page.wait_for_function(
                        r"""(nodeId) => {
                            const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
                            if (!el) return false;
                            if (el.querySelector('.spinner-border')) return true;
                            const texts = [...el.querySelectorAll('.nowheel.nodrag, span')]
                                .map(e => e.textContent);
                            return texts.some(
                                t => /\[(\d+|\*)\]:/.test(t) || /^(Running|Done|Error)$/.test(t.trim())
                            );
                        }""",
                        arg=node.id,
                        timeout=20000,
                    )
                    return
                except PlaywrightTimeoutError:
                    last_error = TimeoutError("No spinner or counter-flip within 20s")
            except PlaywrightTimeoutError as e:
                last_error = e
        raise AssertionError(
            f"Node {node.id} ({node.type}) never acknowledged Play after "
            f"{max_attempts} attempts; click is being silently dropped "
            f"(React handler likely not bound). Last error: {last_error}"
        )

    def _execute_all_playable_nodes(self):
        """Click *play* on every node that has a play button (topological order)
        and wait for each to finish.  Skips if already executed for the
        current workflow (guards against repeated calls across tests that
        share the same class-scoped page)."""
        if getattr(self.__class__, '_executed_workflow', None) == self.spec.filepath:
            return
        # Fire WebGPU diagnostics once per session for any autk-grammar
        # workflow so the adapter/device dump is in the log whether or not a
        # node later errors. Diagnostic only — there is no tolerance; an autk
        # node that errors fails the test. The probe is cached on the class.
        if any(n.type in self._WEBGPU_DIAGNOSTIC_TYPES for n in self.spec.nodes):
            self._webgpu_diagnostics()
        # Give React a chance to bind onClick handlers on every play button
        # before we start firing clicks. ``loaded_workflow`` only waits for
        # node count, not for handler attachment, so without this settle the
        # very first ``play_btn.click(force=True)`` of the workflow is
        # occasionally dropped on the floor.
        try:
            self.page.locator("svg.fa-circle-play").first.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            pass  # all-passive workflow — no play buttons present
        for node in self.spec.topo_sorted_nodes():
            node_el = self._node_locator(node)
            node_el.scroll_into_view_if_needed()

            # if Pool node, wait for its data table to show
            if node.type == "DATA_POOL":
                # DATA_POOL's table lives inside the NodeEditor output tab pane.
                # The pool auto-switches NodeEditor to that pane (NodeEditor sets
                # activeTab="output" when contentComponent is defined), so the
                # DataPoolContent is already mounted and active. We don't wait
                # for the output nav-link to be "visible" — the data-pool scroll
                # refactor (commit 76326a8) renders the tiny tab strip clipped,
                # which Playwright reports as not visible even though the pane is
                # shown. Best-effort dispatch a click to force the pane active
                # (dispatch_event doesn't require visibility), then wait for the
                # table that appears once the upstream output has propagated.
                output_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="output"]'
                ).first
                try:
                    output_tab.dispatch_event("click")
                except Exception:
                    pass
                data_table = node_el.locator("td.MuiTableCell-root")
                data_table.first.wait_for(state="visible", timeout=30000)
                assert data_table.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing its "
                    f"data table"
                )

            if not node.has_play_button:
                continue

            self._click_play_until_started(node, node_el)

            # Wait until either "Done" or "Error" is visible. A node that
            # never settles is a hard timeout failure — there is no
            # tolerance and no retry (all data is local/deterministic).
            result_span = node_el.locator("span").filter(
                has_text=re.compile(r"^(Done|Error)$")
            ).first
            try:
                result_span.wait_for(
                    state="visible",
                    timeout=self._node_execution_timeout_ms(node),
                )
            except PlaywrightTimeoutError:
                raise PlaywrightTimeoutError(
                    f"Node {node.id} ({node.type}) timed out after "
                    f"{self._node_execution_timeout_ms(node)} ms"
                )
            result_text = result_span.text_content() or ""

            if "Error" in result_text:
                # Capture the autk Error tab text (and the once-per-session
                # WebGPU diagnostics) so the failure dump shows the literal
                # err.message — the usual reason an autk node fails.
                if node.type == "AUTK_GRAMMAR":
                    self._capture_autk_error(node, node_el)
                # Surface the inline output text so the failure message says
                # *why* it errored.
                detail = (
                    self._read_code_node_error_text(node_el)
                    if node.category == "code" else None
                )
                raise AssertionError(
                    f"Node {node.id} ({node.type}) execution failed with Error"
                    + (f"\n--- node error output ---\n{detail}" if detail else "")
                )

            done_span = node_el.locator("span").filter(has_text=re.compile(r"^Done$"))
            assert done_span.count() >= 1, (
                f"Node {node.id} ({node.type}) did not produce 'Done'"
            )

            # verify the inline output area shows a Jupyter-style counter.
            # Grammar nodes (VIS_VEGA / AUTK_GRAMMAR) render their result via a
            # ``contentComponent`` / output tab rather than the inline code
            # counter, so this only applies to "code" category nodes (their
            # success is already proven by the Done span above).
            if node.category == "code":
                output_area = node_el.locator(".nowheel.nodrag").filter(
                    has_text=re.compile(r"\[\d+\]:")
                ).first
                output_area.wait_for(state="visible", timeout=10000)
        self.__class__._executed_workflow = self.spec.filepath

    # -- 1. Node & edge counts --------------------------------------------

    def test_node_and_edge_count(self, loaded_workflow, request):
        """The canvas must contain the exact number of nodes and edges
        declared in the workflow JSON."""
        # Guard against a brief React re-render cycle after workflow upload
        self.page.wait_for_function(
            f"document.querySelectorAll('.react-flow__node').length >= {self.spec.nodes_count}",
            timeout=15000,
        )
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
        self.page.wait_for_function(
            f"document.querySelectorAll('.react-flow__node').length >= {self.spec.nodes_count}",
            timeout=15000,
        )
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
        self.page.wait_for_function(
            f"document.querySelectorAll('.react-flow__node').length >= {self.spec.nodes_count}",
            timeout=15000,
        )
        for node in self.spec.nodes:
            node_el = self._node_locator(node)
            node_el.scroll_into_view_if_needed()
            assert node_el.count() == 1, (
                f"Node {node.id} ({node.type}) not found on canvas"
            )

            if node.category == "code":

                # 1. Check that the inline output area (below the Monaco editor)
                #    is present and shows the initial "No output yet" placeholder.
                output_area = node_el.locator(".nowheel.nodrag").filter(
                    has_text=re.compile(r"\[[ ]\]:")
                )
                assert output_area.count() >= 1, (
                    f"Code node {node.id} ({node.type}) is missing its "
                    f"inline output area"
                )
                no_output_text = node_el.locator(".nowheel.nodrag").filter(
                    has_text="No output yet"
                )
                assert no_output_text.count() >= 1, (
                    f"Code node {node.id} ({node.type}) inline output area "
                    f"is missing 'No output yet' placeholder"
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
                #    wait for the grammar editor to be rendered.
                #    On wide multi-node dashboards (e.g. 24-node ex.04) some
                #    nodes sit far off the visible viewport even after
                #    fitView, so ``click(force=True)`` lands on coords that
                #    React Flow's CSS transform has shifted out of the
                #    captured pointer region — the click is silently dropped
                #    and the tab never activates. ``dispatch_event("click")``
                #    fires a synthetic event directly on the element, bypassing
                #    coordinate translation entirely (same trick we use for
                #    Play in ``_click_play_until_started``).
                is_active = "active" in (grammar_tab.get_attribute("class") or "")
                if not is_active:
                    grammar_tab.first.dispatch_event("click")
                self.page.wait_for_function(
                    """({ nodeId, eventKey }) => {
                        const nodeEl = document.querySelector(
                            `.react-flow__node[data-id="${nodeId}"]`
                        );
                        if (!nodeEl) return false;
                        const tab = nodeEl.querySelector(
                            `.nav-link[data-rr-ui-event-key="${eventKey}"]`
                        );
                        return !!tab && tab.classList.contains("active");
                    }""",
                    arg={"nodeId": node.id, "eventKey": "grammar"},
                    timeout=30000,
                )

                grammar_editor = node_el.locator(
                    f'[id="grammarJsonEditor{node.id}"], '
                    f'[id="vega-editor_{node.id}"]'
                )
                grammar_editor.first.wait_for(state="visible", timeout=15000)
                assert grammar_editor.count() >= 1, (
                    f"Grammar node {node.id} ({node.type}) is missing its "
                    f"grammar editor"
                )
                # TODO: check if the grammar is rendered inside the editor
                # Verify the json loaded into the grammar editor matches the
                # workflow JSON content. 
                # Grammar editor renders a JSONEditorReact component.

            elif node.category == "datapool":
                # DataPoolContent renders a custom <Nav variant="tabs"> tagged
                # with data-testid="data-pool-tabs" inside the NodeEditor output
                # pane (the old react-bootstrap "#data-tabs-tab-0" auto-id was
                # removed in the data-pool refactor, commit 76326a8).
                data_tabs = node_el.locator('[data-testid="data-pool-tabs"]')
                assert data_tabs.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing "
                    f"its data-pool tabs"
                )

            else:
                # passive nodes (MERGE_FLOW, VIS_SIMPLE, …): just verify the
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
        programmatically (in-process, seeded) to produce expected DuckDB
        artifacts.  After the browser run, artifact content is compared via
        ``load_artifact_as_dict``; VIS_VEGA nodes are verified via SVG
        structural comparison.
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
            # Check output area (inline for code nodes; output tab for grammar)
            # ---------------------------------------------------------------

            if node.category == "code":
                # Since commit d8050b0 code nodes no longer have a separate output
                # tab – the execution result is shown inline inside CodeEditor as
                # a ".nowheel.nodrag" div with a Jupyter-style "[N]:" counter.
                # This covers every code node (DATA_LOADING, DATA_TRANSFORMATION,
                # COMPUTATION_ANALYSIS, JS_COMPUTATION, …); autk nodes are
                # category "grammar" and handled in the branch below.
                output_area = node_el.locator(".nowheel.nodrag").filter(
                    has_text=re.compile(r"\[\d+\]:")
                )
                output_area.first.wait_for(state="visible", timeout=10000)
                assert output_area.count() >= 1, (
                    f"Code node {node.id} ({node.type}) is missing its "
                    f"inline output counter after execution"
                )

                # CodeEditor writes "Saved to file: {artifact_id}" in the inline
                # output (no .data extension with DuckDB).  Extract the artifact_id
                # and compare content against the programmatic run.
                data_output = node_el.locator(".nowheel.nodrag").filter(
                    has_text=re.compile(r"Saved to file:\s\w+_\w+")
                )
                if data_output.count() >= 1 and node.id in expected_map:
                    artifact_id = data_output.first.evaluate(
                        r"""(el) => {
                            const match = el.textContent.match(/Saved to file:\s(\w+_\w+)/);
                            return match ? match[1] : null;
                        }"""
                    )
                    if artifact_id is not None:
                        actual = load_artifact_as_dict(artifact_id)
                        expected_data = expected_map[node.id]
                        if actual != expected_data:
                            diff_keys = [
                                k for k in set(actual) | set(expected_data)
                                if actual.get(k) != expected_data.get(k)
                            ]
                            raise AssertionError(
                                f"Node {node.id} ({node.type}) data content "
                                f"does not match programmatic execution. "
                                f"Differing top-level keys: {diff_keys}"
                            )

            elif node.category == "grammar":
                # Grammar nodes (VIS_VEGA) keep a dedicated output tab
                # because they pass outputId to NodeEditor.
                output_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="output"]'
                )
                output_tab.first.wait_for(state="visible", timeout=10000)
                assert output_tab.count() >= 1, (
                    f"Grammar node {node.id} ({node.type}) is missing its "
                    f"output tab"
                )
                if output_tab.count() >= 1:
                    # After execution NodeEditor auto-switches to the output tab.
                    is_active = "active" in (output_tab.get_attribute("class") or "")
                    if not is_active:
                        output_tab.click(force=True)
                        output_tab.wait_for(state="visible", timeout=3000)
                    assert is_active, (
                        f"Grammar node {node.id} ({node.type}) output tab "
                        f"is not active after execution"
                    )

                    # OutputContent (computation-tabs) may still appear for some
                    # grammar nodes that use contentComponent instead of outputId.
                    computation_tabs = node_el.locator("#computation-tabs-tab-0")

                    if computation_tabs.count() >= 1:
                        active_pane = node_el.locator(".tab-pane.active")
                        assert active_pane.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) output "
                            f"area has no active tab-pane"
                        )
                        tab_content = active_pane.locator(".tab-content")
                        tab_content.wait_for(state="visible", timeout=3000)
                        assert tab_content.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) output "
                            f"area is missing .tab-content"
                        )
                        output_heading = tab_content.locator("h6").filter(
                            has_text="Output"
                        )
                        output_heading.first.wait_for(state="visible", timeout=10000)
                        assert output_heading.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) is missing its "
                            f"output heading"
                        )
                        no_output_msg = tab_content.locator("div").filter(
                            has_text="No output available."
                        )
                        no_output_msg.first.wait_for(state="hidden", timeout=10000)
                        assert no_output_msg.count() == 0, (
                            f"Grammar node {node.id} ({node.type}) still shows "
                            f"'No output available.'"
                        )
                        # DuckDB: output shows "Saved to file: {artifact_id}" (no .data)
                        output_content = tab_content.locator("div").filter(
                            has_text=re.compile(r"Saved to file:\s\w+_\w+")
                        )
                        output_content.first.wait_for(state="visible", timeout=10000)
                        assert output_content.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) is missing its "
                            f"output content"
                        )
                        artifact_id = output_content.first.evaluate(
                            r"""(el) => {
                                const match = el.textContent.match(/Saved to file:\s(\w+_\w+)/);
                                return match ? match[1] : null;
                            }"""
                        )
                        assert artifact_id is not None, (
                            f"Grammar node {node.id} ({node.type}) is missing its artifact id"
                        )
                        # Verify the artifact is accessible from DuckDB
                        load_artifact_as_dict(artifact_id)

                    # ----------------------------------------------------------
                    # Test created Vega-Lite visualizations (canvas renderer)
                    # ----------------------------------------------------------
                    # Vega-Lite renders to a <canvas> (commit 3a2a14a switched the
                    # renderer from SVG to canvas for performance). A canvas is a
                    # bitmap with no DOM structure to compare, so instead of the
                    # old SVG structural diff we verify the chart actually
                    # rendered: the canvas exists, has a non-zero backing size,
                    # and drew non-blank content (the upstream data turned into
                    # marks). Visual regressions are still caught by the per-node
                    # screenshot comparison in ``_save_screenshot``.
                    if node.type == "VIS_VEGA":
                        vega_container_id = f"vega{node.id}"

                        canvas_locator = node_el.locator(
                            f"#{vega_container_id} canvas"
                        )
                        canvas_locator.first.wait_for(
                            state="visible", timeout=15000
                        )
                        assert canvas_locator.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) is missing "
                            f"its rendered canvas inside #{vega_container_id}"
                        )

                        canvas_info = self.page.evaluate(
                            """(containerId) => {
                                const el = document.getElementById(containerId);
                                if (!el) return null;
                                const canvas = el.querySelector('canvas');
                                if (!canvas) return null;
                                const w = canvas.width, h = canvas.height;
                                if (!w || !h) return { width: w, height: h, nonBlank: false };
                                let nonBlank = false;
                                try {
                                    const ctx = canvas.getContext('2d');
                                    const { data } = ctx.getImageData(0, 0, w, h);
                                    for (let i = 0; i < data.length; i += 4) {
                                        const r = data[i], g = data[i + 1],
                                              b = data[i + 2], a = data[i + 3];
                                        // any opaque, non-white pixel means a mark was drawn
                                        if (a !== 0 && !(r === 255 && g === 255 && b === 255)) {
                                            nonBlank = true;
                                            break;
                                        }
                                    }
                                } catch (e) {
                                    // getImageData throws on a tainted canvas —
                                    // treat as drawn rather than failing.
                                    nonBlank = true;
                                }
                                return { width: w, height: h, nonBlank };
                            }""",
                            vega_container_id,
                        )
                        assert canvas_info is not None, (
                            f"Grammar node {node.id} ({node.type}): could not "
                            f"find a canvas inside #{vega_container_id}"
                        )
                        assert canvas_info["width"] > 0 and canvas_info["height"] > 0, (
                            f"VIS_VEGA node {node.id}: canvas has zero backing "
                            f"size ({canvas_info['width']}x{canvas_info['height']})"
                        )
                        assert canvas_info["nonBlank"], (
                            f"VIS_VEGA node {node.id}: canvas rendered blank — "
                            f"no chart marks drawn from the upstream data"
                        )

        # ---- VIS_SIMPLE content verification -----------------------------------
        # VIS_SIMPLE has no play button so the loop above skips it.  After all
        # upstream code nodes have finished, VIS_SIMPLE fetches the data async
        # and sets its contentComponent (table / image mode) or leaves it empty
        # (text / passthrough mode).  Wait up to 10 s for the async fetch, then
        # verify the rendered content makes sense for the mode.
        for node in self.spec.nodes:
            if node.type != "VIS_SIMPLE":
                continue
            node_el = self._node_locator(node)
            output_tab = node_el.locator(
                '.nav-link[data-rr-ui-event-key="output"]'
            )
            # table and image modes → NodeEditor auto-switches to output tab;
            # text (passthrough) mode → no output tab at all.
            output_tab_visible = False
            try:
                output_tab.first.wait_for(state="visible", timeout=10000)
                output_tab_visible = True
            except Exception:
                pass

            if output_tab_visible:
                # Ensure the tab is active.
                is_active = "active" in (
                    output_tab.first.get_attribute("class") or ""
                )
                if not is_active:
                    output_tab.first.click(force=True)

                active_pane = node_el.locator(".tab-pane.active")
                active_pane.first.wait_for(state="visible", timeout=5000)

                # table mode → MUI TableCell; image mode → <img> elements.
                table_cells = active_pane.locator(
                    "td.MuiTableCell-root, th.MuiTableCell-root"
                )
                images = active_pane.locator("img")
                assert table_cells.count() >= 1 or images.count() >= 1, (
                    f"VIS_SIMPLE node {node.id}: output tab is visible but "
                    f"contains neither table cells nor images"
                )
            # text mode: no output tab → nothing further to assert.

        self._save_screenshot(request)
