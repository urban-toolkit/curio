import os
import re
import json
import time
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
    dot_data_to_vega_values,
    save_expected_svg,
    compare_svg_structure,
    dump_browser_log,
)
from .workflow_spec import NodeSpec, CODE_EDITOR_TYPES, JS_CODE_TYPES

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
        """Persist canvas screenshot (see ``save_workflow_test_screenshot``)
        and dump the captured browser console/pageerror log alongside it.

        The browser log is the only window into autk's caught exceptions
        (autkLifecycleFactory swallows them into React state without ever
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

    # AUTK nodes that render via WebGPU. AUTK_DB is the only JS_CODE_TYPES
    # member that does not need WebGPU (it talks to the Node.js sandbox and
    # Overpass), so its "Error" status — if it occurs — is a real failure,
    # not a missing-GPU side-effect.
    _WEBGPU_REQUIRED_TYPES = JS_CODE_TYPES - {"AUTK_DB"}

    # How many times to click Play on a node flagged
    # ``_tolerate_external_service_error`` (currently AUTK_DB / Overpass)
    # before giving up and falling through to the tolerance branch. The
    # public Overpass endpoint rate-limits per-IP and individual
    # requests intermittently come back with 0 elements; re-issuing the
    # request after the throttle clears typically succeeds.
    _EXTERNAL_SERVICE_RETRIES = 5

    # Seconds to wait between retry attempts on
    # ``_tolerate_external_service_error`` nodes. Hammering Overpass 5×
    # in rapid succession burns through the per-IP rate-limit window 5×
    # faster than waiting. A short backoff lets the window clear before
    # the next attempt.
    _EXTERNAL_SERVICE_RETRY_BACKOFF_S = 15

    def _webgpu_diagnostics(self) -> dict:
        """Return a verbose dump of the browser's WebGPU state — adapter
        info, features, fallback flag, and the result of actually creating
        a device. Cached on the class so it runs once per browser session.

        The earlier ``_webgpu_available`` returned only a bool, which hid
        the difference between *no adapter* and *adapter exists but device
        creation fails* — both surface as AUTK Errors but need different
        fixes. We log this dict once per session so the failure mode is
        visible in pytest output.
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

    def _webgpu_available(self) -> bool:
        """Whether the browser can both obtain an adapter AND create a
        device. Both are required by autk-map's ``await map.init()``.
        Backed by ``_webgpu_diagnostics`` so we log the verbose dump once
        even when callers only need the bool.
        """
        cached = getattr(self.__class__, "_webgpu_available_cache", None)
        if cached is not None:
            return cached
        diag = self._webgpu_diagnostics()
        adapter = diag.get("adapter") if isinstance(diag, dict) else None
        device = diag.get("device") if isinstance(diag, dict) else None
        available = bool(adapter) and isinstance(device, dict) and device.get("ok") is True
        self.__class__._webgpu_available_cache = available
        return available

    def _read_code_node_error_text(self, node_el) -> str | None:
        """Return the error message text from a code node's inline output
        area. Returns ``None`` if it cannot be read.

        Works for both autk lifecycle nodes and Python/JS code nodes:
        CodeEditor renders any output (success or error) into the same
        ``.nowheel.nodrag`` div with the ``[N]:`` counter (CodeEditor.tsx
        ~200-219). For autk, ``autkLifecycleFactory``'s catch block sets
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
        """
        text = self._read_code_node_error_text(node_el)
        store = getattr(self.__class__, "_autk_error_texts", None)
        if store is None:
            store = {}
            self.__class__._autk_error_texts = store
        store[node.id] = text or "(could not read error tab)"
        print(
            f"\n[autk-error] node {node.id} ({node.type}): "
            f"{text or '(could not read error tab)'}"
        )

    def _tolerate_webgpu_error(self, node: NodeSpec) -> bool:
        """``True`` when an AUTK_MAP/PLOT/COMPUTE node errored only because
        the headless browser has no WebGPU adapter."""
        return (
            node.type in self._WEBGPU_REQUIRED_TYPES
            and not self._webgpu_available()
        )

    def _tolerate_external_service_error(self, node: NodeSpec) -> bool:
        """``True`` for nodes whose execution depends on a flaky external
        service the test cannot stub.

        AUTK_DB calls Overpass via ``db.loadOsm({ queryArea: ... })``. The
        public Overpass instance throttles aggressively when the suite hits
        it back-to-back from the same host, so a single test run will
        intermittently see Overpass timeouts (no Done within budget) or
        Overpass HTTP errors (autk-db rejects → node Error). Manual
        single-shot use works fine because nothing else is hammering the
        service. We tolerate both outcomes with a warning rather than
        failing the suite on environmental flakiness.
        """
        return node.type == "AUTK_DB"

    def _mark_tolerated(self, node: NodeSpec) -> None:
        """Record that a node's failure was tolerated in
        ``_execute_all_playable_nodes`` so downstream per-node assertions in
        ``test_node_execution`` know to skip it."""
        tolerated = getattr(self.__class__, "_tolerated_node_ids", None)
        if tolerated is None:
            tolerated = set()
            self.__class__._tolerated_node_ids = tolerated
        tolerated.add(node.id)

    def _was_tolerated(self, node: NodeSpec) -> bool:
        tolerated = getattr(self.__class__, "_tolerated_node_ids", None)
        return tolerated is not None and node.id in tolerated

    def _upstream_was_tolerated(self, node: NodeSpec) -> bool:
        """``True`` if any *transitive* data-flow upstream of *node* was
        tolerated.

        Topological iteration guarantees upstreams are processed first, so
        by the time we reach a downstream node the tolerated set is
        already populated. We walk the upstream subgraph (BFS) because
        passive nodes like ``MERGE_FLOW`` have no play button and never
        get into the tolerated set themselves — but their inputs do —
        and the autk-compute / autk-map nodes downstream of them
        otherwise wouldn't see the tolerance and would error on
        "roads layer missing from upstream" or similar.
        """
        tolerated = getattr(self.__class__, "_tolerated_node_ids", None)
        if not tolerated:
            return False
        seen: set[str] = set()
        frontier: list[str] = list(self.spec.upstream_nodes(node.id))
        while frontier:
            uid = frontier.pop()
            if uid in seen:
                continue
            seen.add(uid)
            if uid in tolerated:
                return True
            frontier.extend(self.spec.upstream_nodes(uid))
        return False

    def _node_execution_timeout_ms(self, node: NodeSpec) -> int:
        """Return a generous timeout for nodes that execute heavy data ops.

        AUTK_DB gets the largest budget because its default code does a live
        Overpass HTTP fetch (``db.loadOsm({ queryArea: { geocodeArea: ... }
        })``), and Overpass latency varies wildly when the suite hits it
        repeatedly from the same IP. ``_tolerate_external_service_error``
        catches the case where Overpass errors out outright; this just buys
        autk-db enough time to finish on the slow-but-eventually-OK path.
        """
        if node.type == "AUTK_DB":
            return 300000  # 5 min — Overpass is the bottleneck, not us
        if node.type in {
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
        ``[*]:`` once the lifecycle reports ``output.code === 'exec'``.
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
                        """(nodeId) => {
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
        # Fire WebGPU diagnostics once per session so the dump appears even
        # on workflows that complete without an AUTK Error (e.g. they only
        # have AUTK_DB, or all autk nodes happened to recover). The probe
        # is cached on the class.
        if any(n.type in JS_CODE_TYPES for n in self.spec.nodes):
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

            # if Pool node activate output tab then wait for data table to show
            if node.type == "DATA_POOL":
                # DATA_POOL's table lives inside the NodeEditor output tab pane.
                # Click the output nav button first so the pane becomes visible.
                # Skip the table assertion when an upstream was tolerated
                # (e.g. AUTK_DB Overpass throttle) — the pool will never
                # receive data, so waiting 30s for a row is just a hang.
                # Mark the pool tolerated so its own downstreams skip their
                # data-dependent checks too.
                if self._upstream_was_tolerated(node):
                    import warnings
                    warnings.warn(
                        f"DataPool {node.id} skipped — an upstream node was "
                        f"tolerated, so the pool has no data to display."
                    )
                    self._mark_tolerated(node)
                    continue
                output_tab = node_el.locator(
                    '.nav-link[data-rr-ui-event-key="output"]'
                )
                output_tab.first.wait_for(state="visible", timeout=10000)
                is_active = "active" in (
                    output_tab.first.get_attribute("class") or ""
                )
                if not is_active:
                    output_tab.first.click(force=True)
                data_table = node_el.locator("td.MuiTableCell-root")
                data_table.first.wait_for(state="visible", timeout=30000)
                assert data_table.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing its "
                    f"data table"
                )

            if not node.has_play_button:
                continue

            # If any upstream was tolerated (failed/timed out), this node
            # has no input data and can't succeed. Skip it transitively so
            # the tolerance propagates down the graph (e.g. AUTK_COMPUTE /
            # AUTK_MAP after a tolerated AUTK_DB).
            if self._upstream_was_tolerated(node):
                import warnings
                warnings.warn(
                    f"Node {node.id} ({node.type}) skipped — an upstream "
                    f"node was tolerated, so this node has no input data."
                )
                self._mark_tolerated(node)
                continue

            # For nodes whose tolerance is driven by a flaky external
            # service (currently just AUTK_DB / Overpass), retry up to
            # ``_EXTERNAL_SERVICE_RETRIES`` times if the first attempt
            # errors or times out before falling through to the
            # tolerance branch. Overpass throttles aggressively and a
            # single 0-result response shouldn't fail a whole workflow
            # when re-issuing the request typically succeeds.
            is_retryable = self._tolerate_external_service_error(node)
            max_attempts = self._EXTERNAL_SERVICE_RETRIES if is_retryable else 1
            timed_out = False
            result_text = ""
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    import warnings
                    warnings.warn(
                        f"Node {node.id} ({node.type}) attempt "
                        f"{attempt}/{max_attempts} after transient "
                        f"external-service failure; sleeping "
                        f"{self._EXTERNAL_SERVICE_RETRY_BACKOFF_S}s "
                        f"to let the rate-limit window clear, then "
                        f"clicking Play again."
                    )
                    time.sleep(self._EXTERNAL_SERVICE_RETRY_BACKOFF_S)
                self._click_play_until_started(node, node_el)

                # Wait until either "Done" or "Error" is visible
                result_span = node_el.locator("span").filter(
                    has_text=re.compile(r"^(Done|Error)$")
                ).first
                try:
                    result_span.wait_for(
                        state="visible",
                        timeout=self._node_execution_timeout_ms(node),
                    )
                except PlaywrightTimeoutError:
                    timed_out = True
                    if attempt == max_attempts:
                        break
                    timed_out = False  # retrying
                    continue
                result_text = result_span.text_content() or ""
                if "Error" not in result_text:
                    break
                if attempt == max_attempts:
                    break
                # else: errored but retries remain — loop will click Play again

            if timed_out:
                if is_retryable:
                    import warnings
                    warnings.warn(
                        f"Node {node.id} ({node.type}) did not finish within "
                        f"{self._node_execution_timeout_ms(node)} ms across "
                        f"{max_attempts} attempts — likely an Overpass "
                        f"throttle. Tolerating; the suite hits Overpass in "
                        f"rapid succession which the public endpoint "
                        f"rate-limits."
                    )
                    self._mark_tolerated(node)
                    continue
                raise PlaywrightTimeoutError(
                    f"Node {node.id} ({node.type}) timed out after "
                    f"{self._node_execution_timeout_ms(node)} ms"
                )
            if "Error" in result_text and node.type in JS_CODE_TYPES:
                # Always read the autk Error tab text, regardless of whether
                # we're going to tolerate it. The user is debugging *why*
                # autk fails, so we need the literal err.message.
                self._capture_autk_error(node, node_el)
            if "Error" in result_text and self._tolerate_webgpu_error(node):
                import warnings
                warnings.warn(
                    f"Node {node.id} ({node.type}) errored — WebGPU is "
                    f"unavailable in this headless session. Tolerating; "
                    f"run with --headed to actually exercise the renderer."
                )
                self._mark_tolerated(node)
                continue
            if "Error" in result_text and self._tolerate_external_service_error(node):
                import warnings
                warnings.warn(
                    f"Node {node.id} ({node.type}) errored — likely an "
                    f"Overpass HTTP failure (autk-db rejected the layer "
                    f"load). Tolerating; this is environmental, not a code "
                    f"regression."
                )
                self._mark_tolerated(node)
                continue
            if "Error" in result_text:
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

            # verify the inline output area shows a Jupyter-style counter (code nodes only).
            # All autk lifecycle nodes (JS_CODE_TYPES) render via
            # ``contentComponent`` and NodeEditor auto-switches to the output
            # tab on success, hiding the code editor (and its inline counter).
            # Their successful execution is already proven by the Done span above.
            if node.category == "code" and node.type not in JS_CODE_TYPES:
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

                    # autark nodes also expose an output tab (their lifecycle
                    # factory provides a contentComponent). Switch back to it
                    # so the screenshot captures the rendered canvas/widget
                    # rather than the Monaco editor we just verified.
                    if node.type in JS_CODE_TYPES:
                        output_tab = node_el.locator(
                            '.nav-link[data-rr-ui-event-key="output"]'
                        )
                        assert output_tab.count() >= 1, (
                            f"Autark node {node.id} ({node.type}) is missing "
                            f"its output tab"
                        )
                        is_active = "active" in (
                            output_tab.get_attribute("class") or ""
                        )
                        if not is_active:
                            output_tab.click(force=True)
                        self.page.wait_for_function(
                            """({ nodeId }) => {
                                const nodeEl = document.querySelector(
                                    `.react-flow__node[data-id="${nodeId}"]`
                                );
                                if (!nodeEl) return false;
                                const tab = nodeEl.querySelector(
                                    '.nav-link[data-rr-ui-event-key="output"]'
                                );
                                return !!tab && tab.classList.contains("active");
                            }""",
                            arg={"nodeId": node.id},
                            timeout=15000,
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
                data_tabs = node_el.locator("#data-tabs-tab-0")
                assert data_tabs.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing "
                    f"#data-tabs"
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

            # ``_execute_all_playable_nodes`` already tolerated this node's
            # Error/timeout (WebGPU unavailable, or Overpass rate-limited it).
            # It will never reach Done in this session, so skip the rest of
            # the per-node assertions. Successful AUTK_DB nodes still flow
            # through the Done check below.
            if self._was_tolerated(node):
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

            if node.category == "code" and node.type not in JS_CODE_TYPES:
                # Since commit d8050b0 code nodes no longer have a separate output
                # tab – the execution result is shown inline inside CodeEditor as
                # a ".nowheel.nodrag" div with a Jupyter-style "[N]:" counter.
                # All JS_CODE_TYPES nodes (AUTK_DB / AUTK_MAP / AUTK_PLOT /
                # AUTK_COMPUTE) are exceptions: their lifecycles declare a
                # ``contentComponent``, so NodeEditor auto-switches to the
                # output tab on success and the inline counter is no longer
                # the visible result. Done span (above) is sufficient proof.
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

                # autark nodes render their visualization in the output tab via
                # a contentComponent (canvas or div wrapper). NodeEditor
                # auto-switches on contentComponent change, but force the tab
                # explicitly so the post-execution screenshot deterministically
                # captures the rendered output instead of the code editor.
                if node.type in JS_CODE_TYPES:
                    output_tab = node_el.locator(
                        '.nav-link[data-rr-ui-event-key="output"]'
                    )
                    output_tab.first.wait_for(state="visible", timeout=10000)
                    is_active = "active" in (
                        output_tab.get_attribute("class") or ""
                    )
                    if not is_active:
                        output_tab.click(force=True)
                    active_pane = node_el.locator(".tab-pane.active")
                    active_pane.first.wait_for(state="visible", timeout=5000)
                    # AUTK_DB uses ``container: 'hidden'`` (display:none wrapper
                    # around an offscreen 1×1 canvas) — no visible rendering by
                    # design. The other AUTK types render into a visible
                    # canvas/div.
                    if node.type != "AUTK_DB":
                        canvas_or_div = active_pane.locator(
                            "canvas, .nodrag.nopan.nowheel"
                        )
                        canvas_or_div.first.wait_for(state="visible", timeout=10000)

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
                    # Test created SVG Vega-Lite visualizations
                    # ----------------------------------------------------------
                    if node.type == "VIS_VEGA":
                        vega_container_id = f"vega{node.id}"

                        # A -- Verify SVG exists and is non-empty
                        svg_locator = node_el.locator(f"#{vega_container_id} svg")
                        svg_locator.first.wait_for(state="visible", timeout=15000)
                        assert svg_locator.count() >= 1, (
                            f"Grammar node {node.id} ({node.type}) is missing "
                            f"its rendered SVG inside #{vega_container_id}"
                        )

                        # B -- Re-compile the spec programmatically and save
                        #      the expected SVG (mirrors .data baseline pattern)
                        spec_json = json.loads(
                            node.content.replace("\r\n", "\n").replace("\r", "\n")
                        )

                        upstream_ids = self.spec.upstream_nodes(node.id)
                        vega_values: list[dict] = []
                        for uid in upstream_ids:
                            candidate = uid
                            visited: set[str] = set()
                            while candidate and candidate not in expected_map:
                                visited.add(candidate)
                                parents = self.spec.upstream_nodes(candidate)
                                candidate = next(
                                    (p for p in parents if p not in visited),
                                    None,
                                )
                            if candidate and candidate in expected_map:
                                upstream_data = expected_map[candidate]
                                vega_values = dot_data_to_vega_values(upstream_data)
                                break

                        assert vega_values, (
                            f"VIS_VEGA node {node.id}: no upstream data found in "
                            f"expected_map — searched upstream ids: {upstream_ids}"
                        )

                        container_dims = self.page.evaluate(
                            """(containerId) => {
                                const el = document.getElementById(containerId);
                                if (!el) return null;
                                return {
                                    width: el.clientWidth,
                                    height: el.clientHeight
                                };
                            }""",
                            vega_container_id,
                        )

                        expected_svg = self.page.evaluate(
                            """({ spec, values, dims }) => {
                                const vega = window.__curio_vega;
                                const lite = window.__curio_vegaLite;
                                if (!vega || !lite) return null;
                                spec.data = { values: values, name: 'data' };
                                spec.width = dims ? dims.width : 300;
                                spec.height = dims ? dims.height : 200;
                                const vegaSpec = lite.compile(spec).spec;
                                const view = new vega.View(vega.parse(vegaSpec))
                                    .renderer('svg')
                                    .initialize(document.createElement('div'));
                                return view.runAsync().then(() => view.toSVG());
                            }""",
                            {
                                "spec": spec_json,
                                "values": vega_values,
                                "dims": container_dims,
                            },
                        )
                        assert expected_svg is not None, (
                            f"Grammar node {node.id} ({node.type}): "
                            f"programmatic Vega-Lite re-compilation returned null "
                            f"(window.__curio_vega / __curio_vegaLite missing?)"
                        )

                        dataflow_name = os.path.splitext(
                            os.path.basename(self.spec.filepath)
                        )[0]
                        save_expected_svg(dataflow_name, node.id, expected_svg)

                        # C -- Extract the actual SVG from the DOM
                        actual_svg = self.page.evaluate(
                            """(containerId) => {
                                const el = document.getElementById(containerId);
                                if (!el) return null;
                                const svg = el.querySelector('svg');
                                return svg ? svg.outerHTML : null;
                            }""",
                            vega_container_id,
                        )
                        assert actual_svg is not None, (
                            f"Grammar node {node.id} ({node.type}): "
                            f"could not extract SVG from #{vega_container_id}"
                        )

                        # D -- Structural comparison
                        diffs = compare_svg_structure(
                            actual_svg,
                            expected_svg,
                        )
                        assert not diffs, (
                            f"Grammar node {node.id} ({node.type}) SVG "
                            f"structural mismatch:\n"
                            + "\n".join(f"  - {d}" for d in diffs)
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
