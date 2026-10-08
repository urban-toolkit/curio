import os
import re
import json
from dataclasses import dataclass

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
    INTERACTION_MIN_CHANGED_PIXELS,
    INTERACTION_RESTORED_RATIO,
    INTERACTION_SHOWN_TIMEOUT_MS,
    INTERACTION_VIEWPORT,
    CLOSEUP_PIXEL_THRESHOLD,
    _compare_images,
    _wait_for_no_node_running,
    _wait_for_reactflow_ready,
    assert_autark_drawing_fits,
    assert_autark_map_drawn,
    AUTK_MAP_MIN_FRAMED_SPAN,
    autark_map_framing,
    assert_editor_panes_clear_of_markers,
    assert_in_view,
    at_fraction,
    bar_boxes,
    brush_area,
    brush_log,
    brush_mismatches,
    canvas_painted_at_shown_zoom,
    capture_node,
    changed_pixels,
    dismiss_toasts,
    drawing_kept,
    drawing_selector,
    AUTK_PLOT_HIGHLIGHT,
    _LIT_MARKS_JS,
    frame_nodes,
    keep_drawing,
    lit_marks,
    mark_point,
    park_pointer,
    save_interaction_frame,
    save_node_closeup,
    save_dataflow_and_settle_header,
    save_workflow_test_screenshot,
    assert_vega_canvas_rendered,
    assert_vega_node_empty_state,
    get_shared_data_dir,
    load_artifact_as_dict,
    execute_workflow_programmatically,
    dump_browser_log,
    node_execution_timeout_ms,
    play_node,
    read_node_error_text,
    wait_for_node_capture,
    wait_for_node_done,
    wait_for_node_settled,
    wait_for_node_still,
    wait_for_run_guard_released,
    watch_brush,
)
from .workflow_spec import NodeSpec, CODE_EDITOR_TYPES, parse_workflow

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

#: Grammar nodes (VIS_VEGA, AUTK_GRAMMAR) that are *supposed* to have nothing
#: on their canvas, keyed by workflow then node id. A ``None`` reason means the spec compiled and drew a
#: real but markless chart (an empty frame, an all-null geometry column); a
#: string means the spec could not be drawn at all and the node body is expected
#: to say so, using that ``data-curio-node-empty`` reason.
#:
#: A view that draws nothing ends in Error with an ``empty-render`` verdict, so
#: these nodes are expected to error with that verdict, and their canvas or
#: empty-state marker is still checked. Everything not listed here still has to
#: draw and finish Done.
EXPECTED_EMPTY = {
    "13-vega-lite-geometry-columns.json": {
        "5b98d1d6-9332-5fb1-a149-c8f607025a42": "geometry-unresolved",
        "1340a3df-26a8-53db-8de3-dc04db64d6fc": "geometry-ambiguous",
    },
    "14-vega-lite-crs-and-geometry-types.json": {
        "f5626141-f328-514e-be15-779e1cf43cbc": None,  # an empty frame
        "e789669d-c845-5d49-a4ec-ae2212a535ad": None,  # every geometry null
    },
    # The same DataFrame with no geometry column, refused by both grammars.
    "17-autark-geodataframe-maps.json": {
        "08f7511f-03d0-5df3-b25e-1d7fbec33101": "geometry-unresolved",  # Autark
        "dbda2a2f-5ff1-5ce4-a88b-d4599ffa254f": "geometry-unresolved",  # Vega-Lite
    },
}

#: Maps whose drawing covers less of the area they are framed on than
#: ``autark_map_framing`` takes by default, by node id, with the share their
#: drawing still spans. Example 24's height mosaic is framed on its raster,
#: SCOUT's four zoom-16 tiles, like the shadow map on the same grid, but its
#: ground cells are 0 m and a raster draws 0 clear when its GeoTIFF names no
#: nodata, so only the buildings show: about 54% of the map's height, 9%
#: before the map opened framed (CI run 37559438022).
FRAMED_DRAWING_SPAN = {
    "ebac4811-abcc-50fe-a61a-cc9c9ac8c011": 0.5,
}


@dataclass(frozen=True)
class Interaction:
    """A gesture on one drawn node, and the node it should light up.

    *gesture* is one of:
    - ``hover``, the pointer held over a mark of a Vega chart;
    - ``pick``, a double-click on an Autark map (a pick toggles, so a second
      one on the same spot takes it back);
    - ``brush``, a drag across a Vega interval selection or an Autark plot's
      brush, from ``span[0]`` to ``span[1]`` as fractions of the area the
      marks take.
    The mark is the marked pixel of the source's drawing nearest *at*, given as
    fractions of the part of that drawing in view.

    *min_lit* is the share of an Autark plot's marks a brush on it has to
    light. A brush that lights most of a plot makes its pair's after frames
    far from the before ones, so an interaction that stops reaching fails by
    much more than the budget.
    """
    slug: str
    source: str
    target: str
    gesture: str
    at: tuple = (0.5, 0.5)
    span: tuple = ((0.25, 0.25), (0.75, 0.75))
    min_lit: float = 0.0


GESTURES = ("hover", "pick", "brush")

VEGA_AUTARK_BARS = "node12"
VEGA_AUTARK_MAP = "13d263ce-2e82-4e87-bc69-117b06a8a65b"
EXAMPLE_17_BARS = "dfdcf935-96c9-5dcf-bb44-90376fbafad8"
EXAMPLE_17_MAP = "eb39411d-d742-52c8-93aa-1424997ead25"
EXAMPLE_09_SCATTER = "3334485c-50ad-4adf-9574-45f8a9704860"
EXAMPLE_09_MAP = "6c4aa6a8-45eb-480e-bb3d-3fd54d13325b"
EXAMPLE_08_SCATTER = "niteroi-plot"
EXAMPLE_08_MAP = "niteroi-map"

#: Compare Scenarios (#662) runs its inputs through Python behind its own play
#: button, but it has no legacy category, so ``NodeSpec.has_play_button`` is
#: False for it. The canvas tests play it and check it by its type.
COMPARE_SCENARIOS = "curio.builtin/compare-scenarios"

#: Raster Calculator and Raster Statistics (#738) run their code behind their
#: own play button too, with no legacy category: example 24's Raster
#: Statistics node is played and must end Done like any other.
RASTER_TOOLS = {"curio.builtin/raster-calculator", "curio.builtin/raster-statistics"}

#: Edit Features (#662) runs the code its edit list writes behind its own play
#: button too: example 06's is played and must end Done like any other.
EDIT_FEATURES = "curio.builtin/edit-features"


def _plays(node: NodeSpec) -> bool:
    """Whether the canvas gives *node* a play button that the run clicks."""
    return (
        node.has_play_button or node.type == COMPARE_SCENARIOS or node.type in RASTER_TOOLS
        or node.type == EDIT_FEATURES
    )


#: A Compare Scenarios node's view and where its drawing stands: ``[mode,
#: state, problem]``, from its chart, or its map in Difference.
_COMPARE_VIEW_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const body = node && node.querySelector("[data-compare-mode]");
    if (!body) return null;
    const mode = body.getAttribute("data-compare-mode");
    const kind = mode === "difference" ? "map" : "chart";
    const view = node.querySelector(`[data-compare-${kind}-state]`);
    const problem = node.querySelector(`[data-compare-${kind}-problem]`);
    return [
        mode,
        view ? view.getAttribute(`data-compare-${kind}-state`) : null,
        problem ? problem.textContent : "",
    ];
}"""


def _assert_compare_view_drew(page, node_id: str) -> None:
    """A Compare Scenarios node that ran shows its view drawn: its chart
    compiled with no problem and painted, or its difference map drawn."""
    try:
        page.wait_for_function(
            "(id) => { const view = (" + _COMPARE_VIEW_JS + ")(id);"
            " return !!view && !!view[1] && view[1] !== 'drawing'; }",
            arg=node_id,
            timeout=90000,
        )
    except PlaywrightTimeoutError:
        pass
    view = page.evaluate(_COMPARE_VIEW_JS, node_id)
    assert view and view[1] == "drawn", (
        f"Compare Scenarios node {node_id}: its view ended {view!r}"
    )
    if view[0] == "difference":
        assert_autark_map_drawn(
            page, node_id, timeout=60000, attach_as=f"{node_id}'s difference map"
        )
    else:
        assert_vega_canvas_rendered(page, node_id)


#: Where an Edit Features node's map stands: "drawing", "drawn" or "problem".
_EDIT_MAP_STATE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const map = node && node.querySelector("[data-edit-map-state]");
    return map ? map.getAttribute("data-edit-map-state") : null;
}"""


def _assert_edit_map_drew(page, node_id: str) -> None:
    """An Edit Features node that ran shows its input drawn on its map, by the
    Autark node's map code, before any frame is taken of it."""
    try:
        page.wait_for_function(
            "(id) => { const state = (" + _EDIT_MAP_STATE_JS + ")(id);"
            " return !!state && state !== 'drawing'; }",
            arg=node_id,
            timeout=90000,
        )
    except PlaywrightTimeoutError:
        pass
    state = page.evaluate(_EDIT_MAP_STATE_JS, node_id)
    problem = page.locator(f'.react-flow__node[data-id="{node_id}"] [data-edit-map-problem]').all_inner_texts()
    assert state == "drawn", f"Edit Features node {node_id}: its map ended {state!r} {problem}"
    assert_autark_map_drawn(page, node_id, timeout=60000, attach_as=f"{node_id}'s map")

#: Interactions compared before and after, keyed by workflow, in the order
#: they run. Each frames its two nodes together, so a hover held on one still
#: shows while the other is captured. See ``test_node_interaction``.
INTERACTIONS = {
    # A bar chart and an Autark map, linked through a Data Pool.
    "Interaction_Vega_Autark.json": (
        Interaction("bar-hover", source=VEGA_AUTARK_BARS, target=VEGA_AUTARK_MAP, gesture="hover"),
        Interaction("map-pick", source=VEGA_AUTARK_MAP, target=VEGA_AUTARK_BARS, gesture="pick"),
    ),
    # The same pair joined directly, with no Data Pool between them.
    "17-autark-geodataframe-maps.json": (
        Interaction("bar-hover", source=EXAMPLE_17_BARS, target=EXAMPLE_17_MAP, gesture="hover"),
        Interaction("map-pick", source=EXAMPLE_17_MAP, target=EXAMPLE_17_BARS, gesture="pick"),
    ),
    # A Vega-Lite interval brush on a scatter, and an Autark map, through a pool.
    # A pick lights one point of 6,085, and most tracts' points are in the
    # scatter's dense band, drawn under thousands of others: in a sweep of 80
    # picks across the map, most changed fewer pixels than a gesture has to
    # (CI run 36809892522). This one, near the map's left edge, lights a tract
    # with gt_65 232, right of the band, where its point is alone (50 pixels).
    # The spot moves when the map's size or framing does: once the map kept
    # clear of the port markers (#631), the old spot lit nothing, and a new
    # sweep of 85 picks found the same tract there (CI run 37154691120). Once
    # the map opened framed on all its tracts (#773), a sweep of 97 picks
    # found 15 spots that light a point; this one, upper right, lights 50
    # pixels, as do its two neighbours in the sweep (CI run 37560369552).
    "09-heterogeneous-data-linked-views.json": (
        Interaction("scatter-brush", source=EXAMPLE_09_SCATTER, target=EXAMPLE_09_MAP, gesture="brush"),
        Interaction("map-pick", source=EXAMPLE_09_MAP, target=EXAMPLE_09_SCATTER, gesture="pick",
                    at=(0.76, 0.22)),
    ),
    # Autark to Autark: a histogram brush and a building map, through a pool.
    # No pick the other way: at the pair's 86% zoom a building is a few
    # pixels, so a pick that lands changes 1 to 9 of the map's pixels, and two
    # of six probes landed on none (CI run 36796749223).
    "Interaction_Autark.json": (
        Interaction("plot-brush", source="ia-plot", target="ia-map", gesture="brush"),
    ),
    # An Autark scatter's 2D brush and an Autark map, through a pool. The
    # roads crowd the right of the plot (intercept 27 to 35 of 0 to 35, most
    # of them above an angle of 0), so the brush spans that crowd across and
    # its upper two thirds down, and has to light at least half the roads. It
    # gets no road pick: a road is a few pixels, and the one point it lights
    # (1 of 8524, CI run 36805909584) hides under the others.
    "08-autark-spatial-join-regression.json": (
        Interaction("scatter-brush", source=EXAMPLE_08_SCATTER, target=EXAMPLE_08_MAP,
                    gesture="brush", span=((0.70, 0.02), (0.995, 0.70)), min_lit=0.5),
    ),
}


def _linked(spec, a: str, b: str) -> bool:
    """Whether an Interaction edge joins *a* and *b*, directly or through one Data Pool."""
    def ends(edge):
        return {edge["source"], edge["target"]}

    links = [ends(e) for e in spec.edges if e.get("type") == "Interaction"]
    if {a, b} in links:
        return True
    pools = {n.id for n in spec.nodes if n.type == "DATA_POOL"}
    return any({a, pool} in links and {b, pool} in links for pool in pools)


def test_interaction_table_matches_the_dataflows():
    """Every INTERACTIONS step names two drawing nodes of its dataflow that an
    Interaction edge links, and a gesture its source can take, so an edited
    example cannot leave the table pointing at nothing."""
    from .conftest import WORKFLOW_FILES
    from .utils import REPO_ROOT

    paths = {os.path.basename(p): os.path.join(REPO_ROOT, p) for p in WORKFLOW_FILES}
    for workflow, steps in INTERACTIONS.items():
        assert workflow in paths, f"{workflow} is not in conftest.WORKFLOW_FILES, so it never runs"
        spec = parse_workflow(paths[workflow])
        nodes = {n.id: n for n in spec.nodes}
        for step in steps:
            where = f"{workflow} {step.slug}"
            assert step.gesture in GESTURES, f"{where}: unknown gesture {step.gesture!r}"
            for node_id in (step.source, step.target):
                assert node_id in nodes, f"{where}: no node {node_id}"
                assert nodes[node_id].type in ("VIS_VEGA", "AUTK_GRAMMAR"), (
                    f"{where}: {node_id} is a {nodes[node_id].type}, which draws nothing")
            assert _linked(spec, step.source, step.target), (
                f"{where}: no Interaction edge joins {step.source} and {step.target}")
            source = json.loads(nodes[step.source].content or "{}")
            selects = [p.get("select") for p in source.get("params") or []]
            if step.gesture == "pick":
                layers = (source.get("map") or {}).get("layerRefs") or []
                assert any(layer.get("isPick") for layer in layers), (
                    f"{where}: {step.source} has no isPick layer to pick")
            elif step.gesture == "hover":
                ons = [s.get("on") for s in selects if isinstance(s, dict)]
                assert "pointerover" in ons, (
                    f"{where}: {step.source} has no selection made on pointerover")
            else:
                intervals = [s for s in selects
                             if s == "interval" or (isinstance(s, dict) and s.get("type") == "interval")]
                events = (source.get("plot") or {}).get("events") or []
                assert intervals or any(e.startswith("brush") for e in events), (
                    f"{where}: {step.source} has no interval selection or plot brush")


#: How long test_bar_hover_taken_back_when_the_map_draws_late holds the target
#: map's drawing, from just before the double-click that takes the hover back.
#: Framing the pair and the captures before the wait took 12.7 s on a loaded
#: runner (CI run 37728560442), so a wait of 15 s ended 27.7 s into a 30 s hold.
MAP_DRAWING_HELD_MS = 60000

# Holds the drawing of one map canvas: while held, its WebGPU context refuses
# to hand out its texture, so autk-map's frame for that map stops before it
# draws (autk-map catches the refusal) and the layer's changes stay pending.
# The hold ends at the first frame the map asks for once `ms` have passed, so
# it needs no timer. The record of the hold is kept on window.
_HOLD_MAP_DRAWING_JS = """({ canvas, ms }) => {
    const proto = GPUCanvasContext.prototype;
    if (!proto.__curioTakeTexture) {
        proto.__curioTakeTexture = proto.getCurrentTexture;
        proto.getCurrentTexture = function (...args) {
            const hold = window.__curioMapDrawingHold;
            if (hold && !hold.released && this.canvas && this.canvas.id === hold.canvas) {
                if (performance.now() - hold.started < hold.ms) {
                    hold.refused += 1;
                    throw new DOMException('drawing held by the test', 'InvalidStateError');
                }
                hold.released = true;
                hold.heldFor = Math.round(performance.now() - hold.started);
            }
            return proto.__curioTakeTexture.apply(this, args);
        };
    }
    window.__curioMapDrawingHold = { canvas, ms, started: performance.now(), refused: 0, released: false };
}"""

_MAP_DRAWING_HOLD_JS = """() => {
    const hold = window.__curioMapDrawingHold;
    return hold && { ...hold, elapsed: Math.round(performance.now() - hold.started) };
}"""

_UNHOLD_MAP_DRAWING_JS = """() => {
    const proto = GPUCanvasContext.prototype;
    if (proto.__curioTakeTexture) {
        proto.getCurrentTexture = proto.__curioTakeTexture;
        delete proto.__curioTakeTexture;
    }
    window.__curioMapDrawingHold = null;
}"""


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
        calling ``console.error``), so we always write it, not just on
        failure, while we're debugging the rendering issue.

        The dataflow is saved first, once no node is running, and the frame
        waits for the header to show that save: the save icon, the automatic
        category chips and the Data Catalog count only change when a save
        lands (issue #584).
        """
        _wait_for_no_node_running(self.page)
        save_dataflow_and_settle_header(self.page)
        save_workflow_test_screenshot(
            self.page,
            self.spec.filepath,
            test_name=request.function.__name__,
            # Expected-empty views leave an error toast each; keep them out of
            # the capture.
            sweep_toasts=bool(self._expected_empty()),
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
                        // Prefer the synchronous `adapter.info` property
                        // (populated in current Chrome); fall back to the
                        // deprecated requestAdapterInfo() for older builds.
                        let info = adapter.info || null;
                        if (!info) {
                            try {
                                info = adapter.requestAdapterInfo
                                    ? await adapter.requestAdapterInfo()
                                    : null;
                            } catch (e) { info = { error: String(e) }; }
                        }
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
        self._assert_hardware_webgpu(diagnostics)
        return diagnostics

    @staticmethod
    def _assert_hardware_webgpu(diagnostics: dict) -> None:
        """When ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (the self-hosted GPU
        runner), fail fast if the browser did not get a *real hardware*
        WebGPU adapter — so a misconfigured runner (e.g. a stray
        ``VK_ICD_FILENAMES`` pinning Mesa lavapipe, or a missing NVIDIA Vulkan
        ICD) can't silently run the 06/07 compute examples on software and
        pass for the wrong reason. The hardware launch path
        (``CURIO_WEBGPU_BACKEND=hardware``) passes no SwiftShader flag, so a
        GPU-less host yields a *null* adapter here rather than a software one.
        """
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") != "1":
            return
        adapter = diagnostics.get("adapter")
        info = (adapter or {}).get("info") or {}
        desc = " ".join(
            str(info.get(k, "")) for k in ("vendor", "architecture", "device", "description")
        ).lower()
        is_software = any(s in desc for s in ("llvmpipe", "swiftshader", "lavapipe", "software"))
        device = diagnostics.get("device")
        device_ok = isinstance(device, dict) and device.get("ok") is True
        dump = json.dumps(diagnostics)
        assert adapter is not None, (
            "CURIO_REQUIRE_HARDWARE_WEBGPU=1 but requestAdapter() returned no adapter "
            f"(WebGPU unavailable on the GPU runner). Diagnostics: {dump}"
        )
        assert adapter.get("isFallbackAdapter") is not True, (
            "CURIO_REQUIRE_HARDWARE_WEBGPU=1 but the WebGPU adapter is a software "
            f"fallback (isFallbackAdapter=true). Diagnostics: {dump}"
        )
        assert not is_software, (
            "CURIO_REQUIRE_HARDWARE_WEBGPU=1 but the WebGPU adapter looks like a software "
            f"renderer ({desc!r}). Ensure VK_ICD_FILENAMES is unset and the NVIDIA Vulkan "
            f"ICD is installed. Diagnostics: {dump}"
        )
        assert device_ok, (
            "CURIO_REQUIRE_HARDWARE_WEBGPU=1 but requestDevice() did not succeed. "
            f"Diagnostics: {dump}"
        )

    def _read_code_node_error_text(self, node_el) -> str | None:
        """See ``utils.read_node_error_text``. Kept as a method because
        ``_capture_autk_error`` and the failure paths below read better
        alongside the other ``self._`` diagnostics."""
        return read_node_error_text(node_el)

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

    def _expected_empty(self) -> dict:
        """This workflow's ``EXPECTED_EMPTY`` entries, keyed by node id."""
        return EXPECTED_EMPTY.get(os.path.basename(self.spec.filepath), {})

    def _drawing_autark_nodes(self) -> list[NodeSpec]:
        """The Autark nodes whose grammar draws a map or a plot.

        Read from the spec, not the page, so a node that never created its
        canvas is still on the list. A spec is read as a run reads it, its
        references resolved: one that places a widget as a value
        (``"height_factor": [!! height_factor !!]``) is not JSON until then.
        """
        drawing = []
        for node in self.spec.nodes:
            if node.type != "AUTK_GRAMMAR" or node.id in self._expected_empty():
                continue
            grammar = json.loads(self.spec.node_code(node, "json") if node.content else "{}")
            if "map" in grammar or "plot" in grammar:
                drawing.append(node)
        return drawing

    def _node_execution_timeout_ms(self, node: NodeSpec) -> int:
        """See ``utils.node_execution_timeout_ms``."""
        return node_execution_timeout_ms(node.type)

    def _execute_all_playable_nodes(self):
        """Click *play* on every node that has a play button (topological order)
        and wait for each to finish.  Skips if already executed for the
        current workflow (guards against repeated calls across tests that
        share the same class-scoped page)."""
        if getattr(self.__class__, '_executed_workflow', None) == self.spec.filepath:
            return
        # Where this workflow's run starts in the page's console log, which
        # the class's workflows share.
        self.__class__._run_log_start = len(getattr(self.page, "_curio_browser_log", None) or [])
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
                data_table = node_el.locator("td.MuiTableCell-root")
                # The pool shows data from an upstream node; for autk-grammar
                # examples that data section parses city-scale PBFs server-side,
                # which can run well past the default 30s on a busy host.
                # Env-tunable so the GPU runner can grant a larger budget.
                data_table.first.wait_for(
                    state="visible",
                    timeout=int(os.environ.get("CURIO_E2E_DATAPOOL_TIMEOUT_MS", "30000")),
                )
                assert data_table.count() >= 1, (
                    f"DataPool node {node.id} ({node.type}) is missing its "
                    f"data table"
                )

            if not _plays(node):
                continue

            play_node(self.page, node.id)

            if node.id in self._expected_empty():
                status = wait_for_node_settled(self.page, node.id, node_type=node.type)
                detail = read_node_error_text(node_el) or ""
                assert status == "error" and detail.startswith("rendered nothing"), (
                    f"Node {node.id} ({node.type}): expected an empty-render "
                    f"verdict, got {status!r}: {detail}"
                )
                wait_for_run_guard_released(
                    self.page, timeout_ms=node_execution_timeout_ms("AUTK_GRAMMAR")
                )
                continue

            # Wait for success, or fail with the node's own error text. A
            # node that never settles is a hard timeout failure - there is
            # no tolerance and no retry (all data is local/deterministic).
            try:
                wait_for_node_done(self.page, node.id, node_type=node.type)
            except AssertionError:
                # Capture the autk Error tab text (and the once-per-session
                # WebGPU diagnostics) so the failure dump shows the literal
                # err.message — the usual reason an autk node fails.
                if node.type == "AUTK_GRAMMAR":
                    self._capture_autk_error(node, node_el)
                raise
            # Play also re-ran this node's stale ancestors, and a node that
            # already showed Done settles before that run reaches it. Wait for
            # the run itself, so the next node and the checks after this loop
            # see the chain finished.
            wait_for_run_guard_released(
                self.page, timeout_ms=node_execution_timeout_ms("AUTK_GRAMMAR")
            )

            # verify the inline output area shows a Jupyter-style counter.
            # Grammar nodes (VIS_VEGA / AUTK_GRAMMAR) render their result via a
            # ``contentComponent`` / output tab rather than the inline code
            # counter, so this only applies to "code" category nodes (their
            # success is already proven by the status attribute above).
            if node.category == "code":
                output_area = node_el.locator("[data-curio-node-output]").filter(
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
        # Every box from one frame, after the view has settled. The app fits
        # the view on a timer after a load, and boxes read one by one could
        # straddle that fit: the first node measured under the identity
        # transform, the next after it, which reorders nodes that are in
        # order. Only a slower machine hit the window (ubuntu-latest did).
        _wait_for_reactflow_ready(self.page)
        boxes = self.page.evaluate(
            """() => [...document.querySelectorAll('.react-flow__node')].map((el) => {
                const r = el.getBoundingClientRect();
                return [el.dataset.id, r.x, r.y, r.width, r.height];
            })"""
        )
        positions: dict[str, tuple[float, float]] = {}

        for node in self.spec.nodes:
            found = [b for b in boxes if b[0] == node.id]
            assert len(found) == 1, (
                f"Node {node.id} ({node.type}) not found on canvas"
            )
            _, x, y, width, height = found[0]
            assert width > 0 and height > 0, (
                f"Node {node.id} ({node.type}) has no bounding box (not visible)"
            )
            positions[node.id] = (x, y)

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
                output_area = node_el.locator("[data-curio-node-output]").filter(
                    has_text=re.compile(r"\[[ ]\]:")
                )
                assert output_area.count() >= 1, (
                    f"Code node {node.id} ({node.type}) is missing its "
                    f"inline output area"
                )
                no_output_text = node_el.locator("[data-curio-node-output]").filter(
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
                #    Play in ``utils.play_node``).
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
                # passive nodes (VIS_SIMPLE, COMMENTS, …): just verify the
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
        expected_map = execute_workflow_programmatically(
            self.spec, seed=42, username=getattr(self, "username", None)
        )

        self._execute_all_playable_nodes()

        # A view below the last node that ran draws on its own once the new
        # input reaches it: after that node reports Done and after its run
        # released the run guard. On a loaded machine that draw outlasted the
        # 10 s "Done" check below (workflow 09, linked views). Let the canvas go
        # idle first, as the captures do; a node that never stops fails here,
        # named, and any node still running is noted in the report.
        _wait_for_no_node_running(self.page, report_as="running after the last Play")

        # A batched Autark compute reads every feature of its layer.
        # autk-grammar logs "[autk-grammar] batched compute ..." only when it
        # leaves features out: those past its cap, or those missing a
        # ``required`` path (#757).
        log = getattr(self.page, "_curio_browser_log", None) or []
        left_out = [
            entry.get("text", "") for entry in log[getattr(self.__class__, "_run_log_start", 0):]
            if "[autk-grammar] batched compute" in entry.get("text", "")
        ]
        assert not left_out, (
            f"{os.path.basename(self.spec.filepath)}: a batched compute left features out: " + "; ".join(left_out)
        )

        for node in self.spec.nodes:
            if not _plays(node):
                continue

            node_el = self._node_locator(node)
            # wait for the done span to be visible (an expected-empty view
            # errored with its verdict, checked in _execute_all_playable_nodes)
            if node.id not in self._expected_empty():
                # Success from the status attribute, failing with the node's own
                # error text; the text check below is then only a copy check.
                wait_for_node_done(self.page, node.id, node_type=node.type)
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
                # the "[data-curio-node-output]" div with a Jupyter-style "[N]:" counter.
                # This covers every code node (DATA_LOADING, DATA_TRANSFORMATION,
                # COMPUTATION_ANALYSIS, JS_COMPUTATION, …); autk nodes are
                # category "grammar" and handled in the branch below.
                output_area = node_el.locator("[data-curio-node-output]").filter(
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
                data_output = node_el.locator("[data-curio-node-output]").filter(
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
                    # The probe and its poll live in ``utils`` so the per-dataset
                    # suite asserts Vega rendering the same way this one does.
                    if node.type == "VIS_VEGA":
                        expected = EXPECTED_EMPTY.get(
                            os.path.basename(self.spec.filepath), {}
                        )
                        if node.id in expected:
                            reason = expected[node.id]
                            if reason is None:
                                # Draws a real but markless chart.
                                assert_vega_canvas_rendered(
                                    self.page, node.id, expect_blank=True
                                )
                            else:
                                assert_vega_node_empty_state(
                                    self.page, node.id, reason
                                )
                        else:
                            assert_vega_canvas_rendered(self.page, node.id)
                    elif node.id in EXPECTED_EMPTY.get(os.path.basename(self.spec.filepath), {}):
                        # An Autark map that cannot draw its input says why in
                        # its body, as a Vega chart does.
                        reason = EXPECTED_EMPTY[os.path.basename(self.spec.filepath)][node.id]
                        marker = node_el.locator(f'[data-curio-node-empty="{reason}"]')
                        marker.first.wait_for(state="attached", timeout=30000)
                        assert (marker.first.inner_text() or "").strip(), (
                            f"Autark node {node.id}: reported {reason!r} but "
                            f"rendered no message for the user to read"
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

        # A Compare Scenarios node shows the view it drew from its inputs.
        for node in self.spec.nodes:
            if node.type == COMPARE_SCENARIOS:
                _assert_compare_view_drew(self.page, node.id)
        # An Edit Features node shows its input drawn on its own map.
        for node in self.spec.nodes:
            if node.type == EDIT_FEATURES:
                _assert_edit_map_drew(self.page, node.id)

        # Every code and grammar node shows an editor and at least one marker.
        assert_editor_panes_clear_of_markers(
            self.page,
            expect_some=any(n.category in ("code", "grammar") for n in self.spec.nodes),
        )
        self._save_screenshot(request)

        # A map or plot that drew nothing leaves a blank node, which in the
        # full-page frame above can stay under the budget. Each one is also
        # compared on its own, up close, after checking it fills its node.
        for node in self._drawing_autark_nodes():
            assert_autark_drawing_fits(self.page, node.id)
            save_node_closeup(
                self.page,
                self.spec.filepath,
                node.id,
                test_name=f"{request.function.__name__}_closeup_{node.id}",
                sweep_toasts=bool(self._expected_empty()),
            )

        # Each map opens framed on the layers it draws (#773): not a speck in
        # the middle of the map, nor a crop past its edges. That is every
        # Autark map, and the maps Compare Scenarios and Edit Features draw
        # with the Autark node's map code. Checked once every close-up is
        # taken, and for every map before failing on one.
        maps = [
            node.id for node in self._drawing_autark_nodes()
            if "map" in json.loads(self.spec.node_code(node, "json"))
        ] + [
            node.id for node in self.spec.nodes
            if node.type in (COMPARE_SCENARIOS, EDIT_FEATURES)
            and self.page.locator(f"#autk-grammar-map-{node.id}").count()
        ]
        unframed = [
            problem for problem in (
                autark_map_framing(self.page, m, min_span=FRAMED_DRAWING_SPAN.get(m, AUTK_MAP_MIN_FRAMED_SPAN))
                for m in maps
            ) if problem
        ]
        assert not unframed, "\n".join(unframed)

    # -- 5. Interactions ---------------------------------------------------

    @pytest.mark.only_workflows(*INTERACTIONS)
    def test_node_interaction(self, loaded_workflow, request):
        """Each INTERACTIONS step lights up its target, and both of its nodes
        are compared before and after it.

        The frames show how a highlight looks. What the test asserts itself is
        that there was one: the target's capture changed, it still draws into
        the element it had (a selection highlights, it never redraws), and
        taking the gesture back puts it back as it was.
        """
        self._execute_all_playable_nodes()
        viewport = self.page.viewport_size
        self.page.set_viewport_size(INTERACTION_VIEWPORT)
        try:
            # Every capture of a step, framed or in memory, with the canvas
            # painted the same way (see canvas_painted_at_shown_zoom).
            with canvas_painted_at_shown_zoom(self.page):
                for step in INTERACTIONS[os.path.basename(self.spec.filepath)]:
                    self._interact(step, request.function.__name__)
        finally:
            if viewport:
                self.page.set_viewport_size(viewport)

    def _assert_drawn(self, node_id: str) -> None:
        node = next(n for n in self.spec.nodes if n.id == node_id)
        if node.type == "VIS_VEGA":
            assert_vega_canvas_rendered(self.page, node_id)
        elif "map" in json.loads(node.content or "{}"):
            assert_autark_map_drawn(self.page, node_id)

    def _wait_for_target(self, step: Interaction, done):
        """Capture *step*'s target until ``done(capture)`` holds: what a gesture,
        or taking it back, shows on the target. A map shows it only in a frame
        drawn after it, so this waits as long as an Autark node may run
        (``INTERACTION_SHOWN_TIMEOUT_MS``). Returns ``(capture, held)``."""
        return wait_for_node_capture(self.page, step.target, done, timeout_ms=INTERACTION_SHOWN_TIMEOUT_MS)

    def _interact(self, step: Interaction, test_name: str) -> None:
        page = self.page
        where = f"{step.slug}: a {step.gesture} on {step.source}"

        def frame(phase: str, role: str) -> None:
            node_id = step.source if role == "source" else step.target
            save_interaction_frame(
                page,
                self.spec.filepath,
                node_id,
                test_name=f"{test_name}_{step.slug}_{phase}_{node_id}",
                interaction={
                    "workflow": os.path.basename(self.spec.filepath),
                    "step": step.slug, "gesture": step.gesture, "phase": phase,
                    "role": role, "node": node_id,
                    "source": step.source, "target": step.target,
                },
            )

        # Before the gesture, while the pointer may still move: an error toast
        # stays until it is closed (example 17's two refusing nodes leave one
        # each, over the bar chart), and the frames never sweep, so that a
        # held hover is not let go.
        dismiss_toasts(page)
        frame_nodes(page, [step.source, step.target])
        _wait_for_no_node_running(page)
        for node_id in (step.source, step.target):
            self._assert_drawn(node_id)
        drawing = drawing_selector(page, step.target)
        assert drawing, f"{where}: its target {step.target} drew nothing"
        keep_drawing(page, drawing)
        before = wait_for_node_still(page, step.target)
        source_before = capture_node(page, step.source)
        frame("before", "source")
        frame("before", "target")

        source_drawing = drawing_selector(page, step.source)
        assert source_drawing, f"{where}: {step.source} drew nothing"
        on_vega = source_drawing.startswith("#vega")
        if step.gesture == "brush":
            area = brush_area(page, source_drawing)
            assert area, f"{where}: no marks on {step.source} to brush across"
            page.mouse.move(*at_fraction(area, step.span[0]))
            page.mouse.down()
            page.mouse.move(*at_fraction(area, step.span[1]), steps=8)
            page.mouse.up()
        else:
            point = mark_point(page, source_drawing, step.at)
            assert point, f"{where}: no mark near {step.at} of what {step.source} drew"
            if step.gesture == "hover":
                page.mouse.move(point["x"], point["y"])
            else:
                page.mouse.dblclick(point["x"], point["y"])
        if step.gesture != "hover":
            # A pick or a brush stays, so the pair can be framed again, as it was.
            frame_nodes(page, [step.source, step.target])

        after, reached = self._wait_for_target(
            step, lambda capture: changed_pixels(before, capture) > INTERACTION_MIN_CHANGED_PIXELS)
        # The source's own change says whether the gesture landed at all, and an
        # Autark plot's lit marks whether the selection reached it unseen.
        lit = None if reached else page.evaluate(
            _LIT_MARKS_JS, {"selector": drawing, "highlight": AUTK_PLOT_HIGHLIGHT})
        assert reached, (
            f"{where} left {step.target} as it was "
            f"({changed_pixels(before, after)} pixels changed; the source "
            f"changed by {changed_pixels(source_before, capture_node(page, step.source))}"
            + (f"; {lit['lit']} of its {lit['total']} plot marks lit" if lit and lit['total'] else "")
            + ")"
        )
        wait_for_node_still(page, step.target)
        assert drawing_kept(page, drawing), (
            f"{where} redrew {step.target} instead of highlighting it"
        )
        if step.gesture == "brush" and not on_vega:
            # The marks lit are the ones under the brush, once the selection has
            # come back to the plot through the pool (#536).
            wrong = brush_mismatches(page, source_drawing)
            assert wrong is not None, f"{where} left no brush on {step.source}"
            assert not wrong, f"{where} lit the wrong marks: " + ", ".join(
                f"{w['label']} {'lit outside the brush' if w['lit'] else 'unlit under it'}" for w in wrong)
        if step.min_lit:
            counts = lit_marks(page, source_drawing, at_least=step.min_lit)
            assert counts and counts["total"], f"{where}: {step.source} shows no plot marks"
            assert counts["lit"] >= step.min_lit * counts["total"], (
                f"{where} lit {counts['lit']} of {step.source}'s {counts['total']} marks, "
                f"under the {step.min_lit:.0%} the step is meant to cover"
            )
        frame("after", "target")
        frame("after", "source")

        # Take it back. Vega-Lite clears a point or interval selection on a
        # double-click anywhere in the view, its padding too; the pointer
        # leaving the canvas, or moving over that padding, keeps it (CI run
        # 36790868222). A pick on the same spot takes the pick back, and a
        # click on a d3 brush's overlay, away from the brush, clears it.
        if on_vega:
            box = page.locator(source_drawing).first.bounding_box()
            page.mouse.dblclick(*assert_in_view(
                page, box["x"] + box["width"] - 2, box["y"] + 2,
                f"taking back {where}: the corner of {step.source}'s chart"))
        elif step.gesture == "pick":
            page.mouse.dblclick(point["x"], point["y"])
        else:
            # Away from the brush: a click inside it starts a move instead.
            area = brush_area(page, source_drawing)
            reaches_right = max(step.span[0][0], step.span[1][0]) > 0.9
            page.mouse.click(*at_fraction(area, (0.03 if reaches_right else 0.97, 0.5)))
        frame_nodes(page, [step.source, step.target])
        _, restored = self._wait_for_target(
            step, lambda capture: _compare_images(capture, before, CLOSEUP_PIXEL_THRESHOLD).ratio
            <= INTERACTION_RESTORED_RATIO)
        assert restored, f"taking back {where} left {step.target} highlighted"

    @pytest.mark.only_workflows("17-autark-geodataframe-maps.json")
    def test_bar_hover_taken_back_when_the_map_draws_late(self, loaded_workflow):
        """Taking the bar hover back shows on the map once the map draws again,
        however late that is.

        The page clears the map's highlight a fraction of a second after the
        double-click, and the map shows it in the next frame it draws. On a
        loaded GPU runner that frame can come long after (#763): in CI run
        37724810297 the highlight was cleared 0.1 s after the double-click, and
        reading the target map back waited 20 to 35 s for the frames queued
        before it.
        This test holds the target map's drawing from just before the
        double-click for MAP_DRAWING_HELD_MS: its canvas refuses autk-map its
        texture, so autk-map draws no frame of it and the canvas keeps showing
        the hover. The take-back has to show once the hold ends.
        """
        page = self.page
        step = next(s for s in INTERACTIONS[os.path.basename(self.spec.filepath)] if s.slug == "bar-hover")
        self._execute_all_playable_nodes()
        viewport = page.viewport_size
        page.set_viewport_size(INTERACTION_VIEWPORT)
        try:
            with canvas_painted_at_shown_zoom(page):
                dismiss_toasts(page)
                frame_nodes(page, [step.source, step.target])
                _wait_for_no_node_running(page)
                for node_id in (step.source, step.target):
                    self._assert_drawn(node_id)
                before = wait_for_node_still(page, step.target)
                bars = drawing_selector(page, step.source)
                assert bars, f"{step.source} drew no chart"
                point = mark_point(page, bars, step.at)
                assert point, f"no bar near {step.at} of {step.source}'s chart"
                page.mouse.move(point["x"], point["y"])
                _, lit = self._wait_for_target(
                    step, lambda capture: changed_pixels(before, capture) > INTERACTION_MIN_CHANGED_PIXELS)
                assert lit, f"the bar hover left {step.target} as it was"
                wait_for_node_still(page, step.target)

                page.evaluate(_HOLD_MAP_DRAWING_JS, {
                    "canvas": f"autk-grammar-map-{step.target}", "ms": MAP_DRAWING_HELD_MS})
                box = page.locator(bars).first.bounding_box()
                page.mouse.dblclick(*assert_in_view(
                    page, box["x"] + box["width"] - 2, box["y"] + 2,
                    f"the corner of {step.source}'s chart"))
                frame_nodes(page, [step.source, step.target])
                while_held = capture_node(page, step.target)
                hold = page.evaluate(_MAP_DRAWING_HOLD_JS)
                _, restored = self._wait_for_target(
                    step, lambda capture: _compare_images(capture, before, CLOSEUP_PIXEL_THRESHOLD).ratio
                    <= INTERACTION_RESTORED_RATIO)
                hold_end = page.evaluate(_MAP_DRAWING_HOLD_JS)
        finally:
            page.evaluate(_UNHOLD_MAP_DRAWING_JS)
            if viewport:
                page.set_viewport_size(viewport)

        # The hold was real: the map asked for frames and got none, and the
        # canvas still showed the hover after the double-click.
        assert not hold["released"] and hold_end["refused"] > 0, (
            f"the map's drawing was not held while the hover was taken back ({hold_end}), "
            "so this test proves nothing")
        assert _compare_images(while_held, before, CLOSEUP_PIXEL_THRESHOLD).ratio > INTERACTION_RESTORED_RATIO, (
            "the map showed the take-back while its drawing was held, so this test proves nothing")
        assert restored, (
            f"taking back the bar hover left {step.target} highlighted: "
            + (f"the map drew again {hold_end['heldFor']} ms after the hold began, and still showed the hover"
               if hold_end["released"] else
               f"the wait gave up {hold_end['elapsed']} ms into the {MAP_DRAWING_HELD_MS} ms hold, "
               f"before the map drew again ({hold_end['refused']} of its frames refused)"))

    @pytest.mark.only_workflows("Interaction_Autark.json")
    def test_plot_brush_started_between_bars(self, loaded_workflow):
        """A second brush on the histogram, pressed in the gap between two bars,
        keeps its rectangle and lights the bars under it.

        The press itself covers no bar, so the plot's selection is empty for a
        moment, and the pool clears the first brush's rows and sends that back.
        The brush being drawn must not be taken away by it, even when the
        pointer holds still before letting go.
        """
        page = self.page
        self._execute_all_playable_nodes()
        viewport = page.viewport_size
        page.set_viewport_size(INTERACTION_VIEWPORT)
        try:
            dismiss_toasts(page)
            frame_nodes(page, ["ia-plot", "ia-map"])
            _wait_for_no_node_running(page)
            plot = drawing_selector(page, "ia-plot")
            assert plot, "ia-plot drew nothing"
            area = brush_area(page, plot)
            assert area, "ia-plot has no brush overlay"

            # A first brush, with its rows back through the pool.
            page.mouse.move(*at_fraction(area, (0.25, 0.5)))
            page.mouse.down()
            page.mouse.move(*at_fraction(area, (0.75, 0.5)), steps=8)
            page.mouse.up()
            assert brush_mismatches(page, plot) == [], "the first brush did not light its bars"

            # A second one, pressed between the first two bars, over the next three.
            bars = bar_boxes(page, plot)
            assert len(bars) > 4, f"ia-plot drew {len(bars)} bars"
            gap_x = (bars[0]["right"] + bars[1]["left"]) / 2
            assert bars[1]["left"] - bars[0]["right"] >= 2, "no gap between the first two bars"
            y = area["y"] + area["height"] / 2
            end_x = (bars[3]["left"] + bars[3]["right"]) / 2
            page.mouse.move(gap_x, y)
            watch_brush(page, plot)
            page.mouse.down()
            page.mouse.move(end_x, y, steps=8)
            page.wait_for_timeout(1500)
            page.mouse.up()
            wrong = brush_mismatches(page, plot)
            log = brush_log(page)
            down = next(e["t"] for e in log if e["what"] == "mousedown")
            up = next(e["t"] for e in log if e["what"] == "mouseup")
            vanished = [e["t"] - down for e in log if down < e["t"] < up and not e["shown"]]
            assert not vanished, (
                f"the second brush, pressed between two bars, vanished {vanished[0]} ms "
                "into the drag, while the pointer was still drawing it")
            assert wrong is not None, (
                "the second brush, pressed between two bars, was gone once the pointer let go")
            assert not wrong, "the second brush lit the wrong bars: " + ", ".join(
                f"{w['label']} {'lit outside the brush' if w['lit'] else 'unlit under it'}" for w in wrong)
        finally:
            if viewport:
                page.set_viewport_size(viewport)
