import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect, useRef, useCallback } from "react";
import ReactFlow, {
    Background,
    BackgroundVariant,
    Connection,
    ConnectionMode,
    Controls,
    Edge,
    EdgeChange,
    FitViewOptions,
    type Node as FlowNode,
    NodeChange,
    useReactFlow,
    useStore,
    useStoreApi,
    type XYPosition,
} from "reactflow";
import {
    CANVAS_TITLE_ATTR,
    fitViewWithMenuOffset,
    fitViewWithMenuOffsetNow,
    setViewportNow,
    topOverlayBottom,
} from "../utils/fitViewWithMenuOffset";
import { computeTranslateExtent } from "../utils/canvasExtent";
import { notebookFlowProps } from "../utils/notebookLayout";
import { useGraphEditGates } from "../hook/useGraphEditGates";
import { NotebookRunAll } from "./notebook/NotebookRunAll";
import { usePosition } from "../hook/usePosition";

import { useFlowContext } from "../providers/FlowProvider";
import { useCollab } from "../providers/CollaborationProvider";
import { usePackagePalette } from "../providers/packages/PackagePaletteContext";
import { useToastContext } from "../providers/ToastProvider";
import {
    useDatasetDetails,
    viewDatasetDetailsToast,
} from "./datasets/catalog/datasetDetailsContext";
import { packageKeyFromCanonicalNodeType } from "../registry/packageKeys";
import { NodeType, EdgeType, CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { getFlowNodeCanonicalType } from "../utils/flowNodeCanonicalType";
import { DEFAULT_DELETE_KEY_CODES } from "./canvasKeyBindings";
import { useRunSelectedNodeShortcut } from "../hook/useRunSelectedNodeShortcut";
import { useViewportMotionHint } from "../hook/useViewportMotionHint";
import UniversalNode from "./UniversalNode";
import BiDirectionalEdge from "./edges/BiDirectionalEdge";
import { useCode } from "../hook/useCode";
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import "./MainCanvas.css";
import VersionBadge from "./VersionBadge";
import { CollaborationSidePanel } from "./collab/CollaborationSidePanel";
import { CanvasSidePanels } from "./layout/CanvasSidePanels";
import {
    buildDatasetLoaderNodeOptions,
    hasDatasetDrag,
    readDatasetDragPayload,
} from "../services/datasetCatalog";
import {
    hasModelDrag,
    packageCardNodeOptions,
    readModelDragPayload,
} from "../services/packages/modelApplication";
import {
    endPackageCardDrag,
    hasPackageCardDrag,
    readPackageCardDragPayload,
    type PackageCardNode,
} from "../services/packages/packageCardDrag";
import type { PackageAddRequest } from "../services/packages/packageAddRequests";
import { useModelCatalogDrawer } from "../providers/modelCatalog";
import { usePackageCardDrop } from "./packages/usePackageCardDrop";
import { useHostedGuest } from "./apiSettings/useHostedGuest";
import { endScenarioDrag, hasScenarioDrag, readScenarioDragPayload } from "../services/scenarioCatalog/scenarioDrag";
import { useScenarioDrop } from "./scenarios/useScenarioDrop";
import { packageStarterCode } from "../adapters/node/packageNodeBehavior";
import { useStarterContext } from "../providers/StarterProvider";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import {
  agentsApi,
  readAgentDragCoord,
  notifyAgentDockRefresh,
  resolveAgentDropTarget,
  hasAgentDrag,
  type AgentDropTarget,
} from "../services/agents";
import { clearAgentDropHover, setAgentDropHoverEdgeId } from "../utils/agentDropHover";
import { attachAgentOnDrop } from "../utils/agentDropAttach";
import { AgentDockOverlay } from "./agents/attach/AgentDockOverlay";
import { AgentAttachmentsProvider } from "../providers/agents";
import { isDrawnHidden } from "../utils/hiddenNodes";
import { isNodeDragRegion, keepPaneOffNodes } from "../utils/nodeDragRegion";
import { useSharedView } from "../hook/useSharedView";
import { frameNodesInView, revealRectInView } from "../utils/focusDatasetNodes";
import { scenarioCanvasView } from "../utils/scenarios/scenarioCanvasView";
import { BOX_WIDTH, boxLayout } from "./scenarios/ScenarioLayers";
import { CanvasScenarioLayers } from "./scenarios/CanvasScenarioLayers";
import { useScenarioUi } from "./scenarios/scenarioUi";

const FILL_STYLE: React.CSSProperties = { width: "100%", height: "100%" };
// The notebook is a white page, as a Jupyter notebook is, under its cells.
const NOTEBOOK_SCROLLER_STYLE: React.CSSProperties = {
    width: "100%",
    height: "100%",
    overflowX: "hidden",
    overflowY: "auto",
    backgroundColor: "#ffffff",
};
// React Flow's own view in the notebook view, where the page scrolls instead.
const NOTEBOOK_VIEWPORT = { x: 0, y: 0, zoom: 1 };

export function MainCanvas() {
    const { showToast } = useToastContext();
    const { openDatasetDetails } = useDatasetDetails();
    const { setActivePackageKey } = usePackagePalette();
    const {
        nodes,
        edges,
        loading,
        projectId,
        onNodesChange,
        onEdgesChange,
        onConnect,
        isValidConnection,
        onEdgesDelete,
        onNodesDelete,
        markDirty,
        requestProjectSave,
        notebookOn,
        notebookContentHeight,
        setNotebookPane,
        registerNotebookScroller,
        revealNodes,
        scenarios,
        packages: dataflowPackages,
    } = useFlowContext();
    const hostedGuest = useHostedGuest();

    // The scenario pointed at in the Scenario Catalog drawer's In project tab
    // (#662), whose fixed context the canvas marks. Never saved.
    const { highlighted: highlightedScenario } = useScenarioUi();

    // What React Flow draws: the flow's own nodes and edges, with collapsed
    // scenarios hidden and their members marked, plus the boxes, frames and
    // stand-in edges the scenario layers draw beside it. The flow's state
    // itself never holds any of it (#662). The notebook view shows every node
    // as a cell: a hidden member would leave an empty slot, and the boxes and
    // frames are placed by canvas positions the cells do not have.
    const scenarioView = useMemo(
        () => scenarioCanvasView(nodes, edges, notebookOn ? [] : scenarios ?? [], { fixedFor: highlightedScenario }),
        [nodes, edges, scenarios, highlightedScenario, notebookOn],
    );

    // How far the viewport may pan, tracking the nodes rather than a fixed box
    // (#234). Two memos on purpose: React Flow re-applies `translateExtent`
    // through an effect keyed on the value's IDENTITY, so handing it a fresh
    // array every render would call `d3Zoom.translateExtent()` on every frame
    // of a drag. `computeTranslateExtent` rounds to a coarse grid, and keying
    // the tuple on those four numbers keeps the identity stable until a node
    // actually crosses a boundary. A collapsed scenario's box counts as a node.
    const [extentMinX, extentMinY, extentMaxX, extentMaxY] = useMemo(() => {
        const boxes = scenarioView.boxes.map((box) => ({
            id: box.scenario.id,
            position: { x: box.x, y: box.y },
            positionAbsolute: { x: box.x, y: box.y },
            width: BOX_WIDTH,
            height: boxLayout(box).height,
            data: {},
        }));
        const [[minX, minY], [maxX, maxY]] = computeTranslateExtent(
            boxes.length > 0 ? [...nodes, ...boxes] : nodes,
        );
        return [minX, minY, maxX, maxY];
    }, [nodes, scenarioView.boxes]);
    const translateExtent = useMemo(
        () =>
            [
                [extentMinX, extentMinY],
                [extentMaxX, extentMaxY],
            ] as [[number, number], [number, number]],
        [extentMinX, extentMinY, extentMaxX, extentMaxY],
    );

    const collab = useCollab();
    const collabRef = useRef(collab);
    collabRef.current = collab;

    const { createCodeNode } = useCode();

    // One stable RF type avoids remounting editors when ``loadInstalledPackages`` re-registers manifests.
    const nodeTypes = useMemo(
        () => ({ [CURIO_UNIVERSAL_NODE_TYPE]: UniversalNode }),
        [],
    );

    const edgeTypes = useMemo(() => ({
        [EdgeType.BIDIRECTIONAL_EDGE]: BiDirectionalEdge,
        [EdgeType.UNIDIRECTIONAL_EDGE]: UniDirectionalEdge,
    }), []);

    const reactFlow = useReactFlow();
    const { setViewport, screenToFlowPosition } = useReactFlow();
    const viewportMotionHint = useViewportMotionHint();

    // The notebook view holds React Flow on its own pane: zoom 1, no gestures,
    // and a translate extent equal to the pane, so the page scrolls instead.
    // Memoized on the pane's size, as `translateExtent` is above, because
    // React Flow re-applies the extent whenever its identity changes.
    const flowWidth = useStore((s) => s.width);
    const flowHeight = useStore((s) => s.height);
    const notebookProps = useMemo(
        () => (notebookOn ? notebookFlowProps(flowWidth, flowHeight) : null),
        [notebookOn, flowWidth, flowHeight],
    );
    // In the notebook view the page scrolls and React Flow's own view stays at
    // the origin. The settings above stop gestures but not a call that sets
    // the view (a load's fit, a framing helper), so a view that moves is put
    // back. React Flow 11 lands `setViewport` a frame or two later, through a
    // d3 transition, so the check runs on every change of the view. It also
    // runs again when `setViewport` changes, which it does once React Flow's
    // zoom is ready: before that, it does nothing.
    //
    // The view is put back at once (`setViewportNow`), not through
    // `setViewport`: on a page that drew no frame for a while, a fit's view
    // stayed until one came (#996). A change is put back once the call that
    // made it has returned, in a microtask: setting d3's zoom from inside its
    // own zoom event would end a transition in its last tick without ending
    // its gesture. Only while the hold is on, so nothing it asked for lands
    // after the view is left; useNotebookView then sets the canvas view back
    // at once.
    const flowStore = useStoreApi();
    useEffect(() => {
        if (!notebookOn) return;
        let holding = true;
        const hold = () => {
            const [x, y, zoom] = flowStore.getState().transform;
            if (!holding || (x === 0 && y === 0 && zoom === 1)) return;
            if (!setViewportNow(flowStore, NOTEBOOK_VIEWPORT)) setViewport(NOTEBOOK_VIEWPORT);
        };
        hold();
        const unsubscribe = flowStore.subscribe((state, prev) => {
            if (state.transform !== prev.transform) queueMicrotask(hold);
        });
        return () => {
            holding = false;
            unsubscribe();
        };
    }, [notebookOn, flowStore, setViewport]);

    // The element the notebook scrolls in. Its size and the overlays fixed over
    // its top (top bar, title chips) decide where the cells go. The notebook
    // view has no palette rail (its (+) opens the rail as a row), so the cells
    // run from the left margin.
    const scrollerRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        const scroller = scrollerRef.current;
        if (!scroller) return;
        registerNotebookScroller(scroller);
        const measure = () => {
            const rect = scroller.getBoundingClientRect();
            const top = topOverlayBottom();
            setNotebookPane({
                width: scroller.clientWidth,
                top: top === null ? 0 : Math.max(0, top - rect.top),
                left: 0,
            });
        };
        measure();
        const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
        observer?.observe(scroller);
        const title = document.querySelector(`[${CANVAS_TITLE_ATTR}]`);
        if (title) observer?.observe(title);
        window.addEventListener("resize", measure);
        return () => {
            observer?.disconnect();
            window.removeEventListener("resize", measure);
            registerNotebookScroller(null);
        };
    }, [loading, registerNotebookScroller, setNotebookPane]);

    // Where a dropped node goes. On the canvas, under the pointer. In the
    // notebook view the pointer is on a page, not on the canvas, so the node
    // takes the next free canvas spot and its cell is scrolled into view.
    const { getPosition } = usePosition();
    const dropPosition = useCallback(
        (event: React.DragEvent) =>
            notebookOn ? getPosition() : screenToFlowPosition({ x: event.clientX, y: event.clientY }),
        [notebookOn, getPosition, screenToFlowPosition],
    );
    const revealCreated = useCallback((node: { id: string } | undefined | void) => {
        if (node && node.id) revealNodes([node.id]);
    }, [revealNodes]);

    // Test hook: expose the ReactFlow instance and a menu-aware fitView so
    // Playwright can force the same shifted viewport the in-app loader uses
    // (see useWorkflowOperations.ts) before taking screenshots. A fit without
    // a duration measures the nodes React Flow has not measured yet, is set at
    // once and returns the viewport it set (null while a node has no size), so
    // a helper can wait for that viewport without an animation frame (#1012).
    // Kept unconditional (read-only from the outside and cheap), so e2e tests
    // don't need a separate build flag.
    useEffect(() => {
        (window as any).__curio_reactFlow = reactFlow;
        (window as any).__curio_fitViewWithMenuOffset = (options?: FitViewOptions) =>
            options?.duration
                ? fitViewWithMenuOffset(reactFlow, options)
                : fitViewWithMenuOffsetNow(reactFlow, flowStore, options);
        return () => {
            if ((window as any).__curio_reactFlow === reactFlow) {
                delete (window as any).__curio_reactFlow;
                delete (window as any).__curio_fitViewWithMenuOffset;
            }
        };
    }, [reactFlow, flowStore]);

    // Ctrl/Cmd+Enter on a selected node (#223).
    useRunSelectedNodeShortcut();

    // A read-only canvas: another user's dataflow, with collaboration off.
    // When real-time collaboration is on, a peer opening the owner's URL
    // lands in ``viewerMode === "shared"`` (loadSharedProject was the only
    // way to bypass the owner-only /api/projects/<id> 404). For collab to
    // be useful peers must be able to *edit*; their edits flow over the
    // socket to the owner, who persists. Without this gate, peers see the
    // canvas as read-only and the lock/proposal flow does nothing.
    const isSharedView = useSharedView();
    // Nodes are added (dropped), connected and deleted, and connections
    // removed, on the canvas only, by whoever edits it; the notebook view
    // changes no graph. A node's Delete node tool reads the same rule.
    const graphEdits = useGraphEditGates();

    // React Flow gives a node that drags the `nopan` class, which keeps its
    // pane's gestures off the node: a press there does not pan the view and a
    // double-click does not zoom it 2x at the pointer. A read-only canvas's
    // nodes do not drag, so they get the class here, and the double-click
    // below reaches them as it reaches an editable canvas's nodes.
    const drawnNodes = useMemo(
        () => (isSharedView && !notebookOn ? keepPaneOffNodes(scenarioView.nodes) : scenarioView.nodes),
        [isSharedView, notebookOn, scenarioView.nodes],
    );

    // A double-click where a press drags a node (its header, its card's edge)
    // zooms the view onto it, framed as a focus frames its nodes, on an
    // editable canvas and on a read-only one, where a node would drag if it
    // could. Inside an editor, an output, a chart or a map the double-click
    // stays theirs. The notebook view keeps its zoom at 1.
    const handleNodeDoubleClick = useCallback((event: React.MouseEvent, node: FlowNode) => {
        if (notebookOn) return;
        if (!isNodeDragRegion(event.target, event.currentTarget)) return;
        frameNodesInView(reactFlow, [node.id]);
    }, [notebookOn, reactFlow]);

    // Last dragover point, so a pointer that reports the same coordinate twice
    // (browsers fire dragover on a timer as well as on movement) costs nothing.
    const lastDragPointRef = useRef<{ x: number; y: number } | null>(null);

    const handleDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        // Dataset, model, package card, scenario AND agent drags use
        // effectAllowed="copy"; a "move" dropEffect is an incompatible pair, so
        // the browser cancels the drop (handleDrop never fires and the agent
        // silently fails to attach). Node-creation drags keep "move".
        const wantsCopy =
            hasDatasetDrag(event.dataTransfer) ||
            hasModelDrag(event.dataTransfer) ||
            hasPackageCardDrag(event.dataTransfer) ||
            hasScenarioDrag(event.dataTransfer) ||
            hasAgentDrag(event.dataTransfer);
        event.dataTransfer.dropEffect = wantsCopy ? "copy" : "move";

        // Tell the edges which connection would receive this drop (#296). Only
        // for agent drags: a dataset or node-creation drag pays nothing, which
        // is what keeps this off the hot path for every other kind of drag.
        if (!hasAgentDrag(event.dataTransfer)) {
            clearAgentDropHover();
            return;
        }
        const last = lastDragPointRef.current;
        if (last && last.x === event.clientX && last.y === event.clientY) return;
        lastDragPointRef.current = { x: event.clientX, y: event.clientY };
        const target = resolveAgentDropTarget({
            // A collapsed scenario's members keep their old size while hidden.
            nodes: reactFlow.getNodes().filter((n) => !isDrawnHidden(n)),
            flowPoint: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
            clientX: event.clientX,
            clientY: event.clientY,
        });
        setAgentDropHoverEdgeId(target.kind === "connection" ? target.targetId : null);
    }, [reactFlow, screenToFlowPosition]);

    const handleDragLeave = useCallback((event: React.DragEvent) => {
        // dragleave bubbles from descendants, so a pointer crossing from the
        // pane onto a node fires one here with relatedTarget still inside the
        // drop target. Only a relatedTarget outside it - or null, which is how
        // leaving the window reports - is a real exit.
        const next = event.relatedTarget as Node | null;
        if (next && event.currentTarget.contains(next)) return;
        lastDragPointRef.current = null;
        clearAgentDropHover();
    }, []);

    // The end of a drag that never reaches the canvas: Escape cancels it, the
    // pointer is released over another application, or the drop lands outside
    // the window. None of those fire dragleave on the pane, and dragend fires on
    // the drag SOURCE, so the listener has to be global. Capture phase so
    // nothing downstream can swallow it.
    useEffect(() => {
        const clear = () => {
            lastDragPointRef.current = null;
            clearAgentDropHover();
        };
        window.addEventListener("dragend", clear, true);
        window.addEventListener("drop", clear, true);
        return () => {
            window.removeEventListener("dragend", clear, true);
            window.removeEventListener("drop", clear, true);
        };
    }, []);

    const handleCanvasDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const dataset = readDatasetDragPayload(event.dataTransfer);
        if (dataset) {
            const position = dropPosition(event);
            revealCreated(createCodeNode(NodeType.DATA_LOADING, buildDatasetLoaderNodeOptions(dataset, position)));
            showToast(
                `Created a Data Loading node for ${dataset.title}.`,
                "success",
                viewDatasetDetailsToast(openDatasetDetails, dataset.datasetId),
            );
            markDirty();
        }
    }, [dropPosition, revealCreated, createCodeNode, markDirty, showToast, openDatasetDetails]);

    // A model dragged onto the empty canvas is its package's card (it carries
    // both drags): the card drop below makes its package's node. Only a model
    // whose package has no node at all gets here.
    const { getStarters } = useStarterContext();
    const handleModelCanvasDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const model = readModelDragPayload(event.dataTransfer);
        if (model) showToast(`${model.name} has no node to add.`, "warning");
    }, [showToast]);

    // A package's card from the Node Catalog drawer becomes one of the
    // package's nodes: its one node, or the one picked from a menu of its
    // nodes at the drop point (usePackageCardDrop). A model's card from the
    // Model Catalog drawer or the Models palette is its package's card: its
    // one node runs the model, opening with its template's code, which names
    // the model. A package the dataflow has not added goes through the
    // drawer's own Add first (the review, then the install of its libraries),
    // and the node is made once it is added; a model dropped from the Models
    // palette with the Model Catalog drawer closed opens that drawer on its
    // Add. A hosted guest's drop is refused, since guests never install.
    const { openModelCatalogDrawer } = useModelCatalogDrawer();
    const openModelCatalogOnAdd = useCallback(
        (addRequest: PackageAddRequest) => openModelCatalogDrawer({ addRequest }),
        [openModelCatalogDrawer],
    );
    const createPackageNode = useCallback((node: PackageCardNode, position: XYPosition) => {
        const starter = node.model
            ? packageStarterCode(tryGetNodeDescriptor(node.nodeType as NodeType), getStarters)
            : undefined;
        revealCreated(createCodeNode(node.nodeType as NodeType, { position, ...packageCardNodeOptions(node, starter) }));
        const article = /^[aeiou]/i.test(node.label) ? "an" : "a";
        showToast(
            node.model
                ? `Created ${article} ${node.label} node for ${node.model.name}.`
                : `Created ${article} ${node.label} node.`,
            "success",
        );
        markDirty();
    }, [getStarters, revealCreated, createCodeNode, showToast, markDirty]);
    const { drop: dropPackageCard, menu: packageNodeMenu } = usePackageCardDrop({
        dataflowPackages,
        hostedGuest,
        createNode: createPackageNode,
        showToast,
        openModelCatalog: openModelCatalogOnAdd,
    });
    const handlePackageCardCanvasDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const card = readPackageCardDragPayload(event.dataTransfer);
        endPackageCardDrag();
        if (!card) return;
        dropPackageCard({ card, position: dropPosition(event), at: { x: event.clientX, y: event.clientY } });
    }, [dropPosition, dropPackageCard]);

    // A scenario from the Scenario Catalog arrives as a copy: its box where it
    // was dropped, its context as fixed data (useScenarioDrop). The notebook
    // view shows its cells. On the canvas the box is drawn beside React Flow,
    // not in its store, so no fit of nodes frames it: once it is drawn, the
    // view moves as far as it takes to bring the box into sight (#769).
    const dropScenario = useScenarioDrop();
    const [boxToReveal, setBoxToReveal] = useState<string | null>(null);
    const handleScenarioCanvasDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const scenario = readScenarioDragPayload(event.dataTransfer);
        endScenarioDrag();
        if (!scenario) return;
        void dropScenario(scenario, dropPosition(event)).then((dropped) => {
            if (!dropped || revealNodes(dropped.nodes)) return;
            setBoxToReveal(dropped.scenario);
        });
    }, [dropScenario, dropPosition, revealNodes]);
    useEffect(() => {
        if (!boxToReveal) return;
        const box = scenarioView.boxes.find((b) => b.scenario.id === boxToReveal);
        if (!box) return;
        setBoxToReveal(null);
        revealRectInView(reactFlow, { x: box.x, y: box.y, width: BOX_WIDTH, height: boxLayout(box).height });
    }, [boxToReveal, scenarioView.boxes, reactFlow]);

    const handleDrop = useCallback((event: React.DragEvent) => {
        if (hasDatasetDrag(event.dataTransfer)) {
            handleCanvasDrop(event);
            return;
        }
        if (hasPackageCardDrag(event.dataTransfer)) {
            handlePackageCardCanvasDrop(event);
            return;
        }
        if (hasModelDrag(event.dataTransfer)) {
            handleModelCanvasDrop(event);
            return;
        }
        if (hasScenarioDrag(event.dataTransfer)) {
            handleScenarioCanvasDrop(event);
            return;
        }
        const agentCoord = readAgentDragCoord(event.dataTransfer);
        if (agentCoord) {
            event.preventDefault();
            clearAgentDropHover();
            lastDragPointRef.current = null;
            // Node first, then edge, then canvas, hit-tested against node
            // geometry (reliable regardless of which DOM layer received the
            // drop) and then the DOM for edges. The SAME resolver feeds the
            // drag-over highlight, so what lights up under the pointer and what
            // actually receives the drop cannot disagree (#296).
            const target: AgentDropTarget = resolveAgentDropTarget({
                nodes: reactFlow.getNodes().filter((n) => !isDrawnHidden(n)),
                flowPoint: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
                clientX: event.clientX,
                clientY: event.clientY,
            });
            const where =
                target.kind === "node"
                    ? "the node"
                    : target.kind === "connection"
                        ? "the connection"
                        : "the canvas";
            // For a node target, persist the graph first so the (possibly
            // freshly-added) node is in the saved spec the backend validates
            // against — otherwise the attach 400s. See attachAgentOnDrop.
            // Through the save queue, so it never goes out beside another
            // save of this dataflow (#909, #941).
            attachAgentOnDrop({
                projectId,
                target,
                agentCoord,
                saveProject: requestProjectSave,
                attach: (pid, coord, t) => agentsApi.attach(pid, coord, t),
                // A hosted guest's drop that would save says to sign in.
                hostedGuest,
            })
                .then(() => {
                    notifyAgentDockRefresh();
                    markDirty();
                    showToast(`Agent attached to ${where}.`, "success");
                })
                // A refusal says how to show itself (the sign-in note is a warning).
                .catch((e: any) => showToast(e?.message || "Attach failed.", e?.toastVariant ?? "error"));
            return;
        }
        event.preventDefault();
        const type = event.dataTransfer.getData("application/reactflow") as NodeType;
        if (!type) return;
        const position = dropPosition(event);
        revealCreated(createCodeNode(type, { position }));
        markDirty();
    }, [screenToFlowPosition, dropPosition, revealCreated, createCodeNode, markDirty, handleCanvasDrop, handleModelCanvasDrop, handlePackageCardCanvasDrop, handleScenarioCanvasDrop, projectId, showToast, requestProjectSave, reactFlow, hostedGuest]);

    // The Delete key reaches these through React Flow, which sends the
    // selected edges plus every edge attached to a deleted node first, then
    // the nodes (#155). Both are applied as sent.
    const handleNodesChange = useCallback((changes: NodeChange[]) => {
        let dirty = false;

        for (const change of changes) {
            if (change.type === "remove") dirty = true;

            if (
                change.type === "position" &&
                change.position != undefined &&
                change.position.x != undefined
            ) {
                dirty = true;
                collabRef.current.broadcastNodeUpdated({
                    nodeId: change.id,
                    patch: { position: change.position },
                });
            }
        }

        if (dirty) markDirty();
        onNodesDelete(changes);
        return onNodesChange(changes);
    }, [onNodesDelete, onNodesChange, markDirty]);

    // A connection can move its target further down the notebook's column; the
    // view follows it there rather than leaving the cell to vanish off screen.
    const handleConnect = useCallback((connection: Connection) => {
        onConnect(connection);
        if (connection.target) revealNodes([connection.target], { ifMoved: true });
    }, [onConnect, revealNodes]);

    const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
        if (changes.some((change) => change.type === "remove")) markDirty();
        return onEdgesChange(changes);
    }, [onEdgesChange, markDirty]);

    const handleEdgesDelete = useCallback((edges: Edge[]) => {
        if (edges.length > 0) markDirty();
        return onEdgesDelete(edges);
    }, [onEdgesDelete, markDirty]);

    const handleSelectionChange = useCallback((selection: { nodes: any[]; edges: any[] }) => {
        const packageKey = selection.nodes
            .map((n) => packageKeyFromCanonicalNodeType(getFlowNodeCanonicalType(n)))
            .find((k): k is string => k != null);
        setActivePackageKey(packageKey ?? null);
    }, [setActivePackageKey]);

    // A Shift-drag on the empty canvas draws React Flow's selection box, and
    // the browser would also select the text of every node and panel the
    // pointer crosses. So text selection is refused from the press until the
    // button comes up, wherever the pointer is by then, as a drag that pans
    // the canvas refuses it (d3's dragDisable); the press itself goes on as
    // before. Text selected before the box goes too: the box selects nodes.
    const handleSelectionStart = useCallback(() => {
        window.getSelection()?.removeAllRanges();
        const refuseTextSelection = (event: Event) => event.preventDefault();
        window.addEventListener("selectstart", refuseTextSelection, true);
        window.addEventListener(
            "mouseup",
            () => window.removeEventListener("selectstart", refuseTextSelection, true),
            { capture: true, once: true },
        );
    }, []);

    const loadingAnimation = () => {
        return <div id="plug-loader" role="status" aria-live="polite" aria-busy="true">
                <style>{`
                    #plug-loader {
                    position: fixed;
                    inset: 0;
                    background: #000;             
                    display: grid;                 
                    place-items: center;      
                    z-index: 9999;               
                    }
                    #plug-loader .spinner {
                    width: 64px;
                    height: 64px;
                    border-radius: 50%;
                    border: 6px solid rgba(255,255,255,0.15);
                    border-top-color: #fff;        /* visible on black */
                    animation: plug-rotate 0.9s linear infinite;
                    }
                    @keyframes plug-rotate {
                    to { transform: rotate(360deg); }
                    }
                    #plug-loader .sr-only {
                    position: absolute;
                    width: 1px; height: 1px;
                    padding: 0; margin: -1px;
                    overflow: hidden; clip: rect(0,0,1px,1px);
                    white-space: nowrap; border: 0;
                    }
                `}</style>
                <div className="spinner" />
                <span className="sr-only">Loading…</span>
            </div>
    }

    return (
        <AgentAttachmentsProvider enabled={!isSharedView}>
        {!loading ? <div
            style={{ width: "100vw", height: "100vh", backgroundColor: "#f0f0f0" }}
        >
            {/* The notebook view adds no nodes, so it has no rail, only the
                rail's Run all. */}
            {!notebookOn ? <ToolsMenu /> : <NotebookRunAll />}
            <UpMenu />
            <CanvasSidePanels>
                <CollaborationSidePanel />
            </CanvasSidePanels>
            <div
                className="curio-canvas-drop-target"
                style={{ width: "100%", height: "100%" }}
                onDragOver={graphEdits.drop ? handleDragOver : undefined}
                onDragLeave={graphEdits.drop ? handleDragLeave : undefined}
                onDrop={graphEdits.drop ? handleDrop : undefined}
            >
            {/* Present in both views so switching never remounts React Flow:
                on the canvas both fill the window and change nothing; in the
                notebook view the outer one scrolls and the inner one is as
                tall as the column. React Flow always fills its parent (its own
                100% size wins over a `style` passed to it), so the height goes
                on the parent. */}
            <div
                ref={scrollerRef}
                className="curio-flow-scroller"
                data-curio-notebook={notebookOn ? "true" : undefined}
                style={notebookOn ? NOTEBOOK_SCROLLER_STYLE : FILL_STYLE}
            >
            <div
                className="curio-flow-sizer"
                style={notebookOn ? { position: "relative", width: "100%", height: notebookContentHeight, minHeight: "100%" } : FILL_STYLE}
            >
            <ReactFlow
                nodes={drawnNodes}
                edges={scenarioView.edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode={"Shift"}
                panActivationKeyCode={null}
                onSelectionChange={handleSelectionChange}
                onSelectionStart={handleSelectionStart}
                onNodeDoubleClick={handleNodeDoubleClick}
                onConnect={graphEdits.connect ? handleConnect : undefined}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                isValidConnection={isValidConnection}
                connectionMode={ConnectionMode.Loose}
                minZoom={0.05}
                translateExtent={translateExtent}
                onMoveStart={viewportMotionHint.onMoveStart}
                onMove={viewportMotionHint.onMove}
                onMoveEnd={viewportMotionHint.onMoveEnd}
                nodesDraggable={!isSharedView}
                elementsSelectable={true}
                // Set here, not left to React Flow's default: it keeps a value
                // the notebook view's props set until another one replaces it.
                edgesFocusable={true}
                nodesConnectable={graphEdits.connect}
                edgesUpdatable={graphEdits.connect}
                // React Flow defaults to "Backspace" alone, so Windows users pressing
                // Delete got no response (#153). useKeyPress bails on isInputDOMNode,
                // so neither key can fire while the caret is in Monaco or an input.
                // No key deletes in the notebook view or on a read-only canvas.
                deleteKeyCode={graphEdits.delete ? DEFAULT_DELETE_KEY_CODES : null}
                {...(notebookProps ?? {})}
                // The version badge owns the bottom-right corner, and the
                // attribution drawn there sat under it (#509). The other three
                // canvases already hide it.
                proOptions={{ hideAttribution: true }}
            >
                {!notebookOn && <Background color="#a0a0a0" variant={BackgroundVariant.Dots} gap={20} size={2} />}
                {!notebookOn && <Controls />}
                {!notebookOn && <CanvasScenarioLayers view={scenarioView} editable={!isSharedView} />}
            </ReactFlow>
            </div>
            </div>
            {!isSharedView ? <AgentDockOverlay /> : null}
            </div>

        </div> : loadingAnimation() }
        {packageNodeMenu}
        <VersionBadge />
        </AgentAttachmentsProvider>
    );
}
