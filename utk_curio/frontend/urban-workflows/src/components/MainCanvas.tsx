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
    NodeChange,
    useReactFlow,
    useStore,
    useStoreApi,
} from "reactflow";
import {
    CANVAS_TITLE_ATTR,
    fitViewWithMenuOffset,
    paletteRailRight,
    topOverlayBottom,
} from "../utils/fitViewWithMenuOffset";
import { computeTranslateExtent } from "../utils/canvasExtent";
import { notebookFlowProps } from "../utils/notebookLayout";
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
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { buttonStyle } from "./styles";
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import "./MainCanvas.css";
import { TrillGenerator } from "../TrillGenerator";
import VersionBadge from "./VersionBadge";

import html2canvas from "html2canvas";

import FloatingPanel from "./FloatingPanel";
import { CollaborationSidePanel } from "./collab/CollaborationSidePanel";
import {
    buildDatasetLoaderNodeOptions,
    hasDatasetDrag,
    readDatasetDragPayload,
} from "../services/datasetCatalog";
import {
    hasModelDrag,
    modelNodeForCanvas,
    readModelDragPayload,
    type ModelDropTemplate,
} from "../services/modelCatalog";
import { packageStarterCode } from "../adapters/node/packageNodeBehavior";
import { useStarterContext } from "../providers/StarterProvider";
import { getAllNodeTypes, getPaletteNodeTypes } from "../registry/nodeRegistry";
import type { NodeDescriptor } from "../registry/types";
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
import { scenarioCanvasView } from "../utils/scenarios/scenarioCanvasView";
import { BOX_WIDTH, boxLayout, CanvasScenarioLayers } from "./scenarios/ScenarioLayers";
import { ScenariosPanel } from "./scenarios/ScenariosPanel";
import { ScenarioUiContext, type ScenarioUi } from "./scenarios/scenarioUi";

const FILL_STYLE: React.CSSProperties = { width: "100%", height: "100%" };
const NOTEBOOK_SCROLLER_STYLE: React.CSSProperties = {
    width: "100%",
    height: "100%",
    overflowX: "hidden",
    overflowY: "auto",
};

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
        saveCurrentProject,
        notebookOn,
        notebookContentHeight,
        setNotebookPane,
        registerNotebookScroller,
        revealNodes,
        scenarios,
    } = useFlowContext();

    // The Scenarios panel, and the scenario it highlights (#662). Never saved.
    const [scenarioPanelOpen, setScenarioPanelOpen] = useState(false);
    const [highlightedScenario, setHighlightedScenario] = useState<string | null>(null);
    const scenarioUi = useMemo<ScenarioUi>(() => ({
        panelOpen: scenarioPanelOpen,
        setPanelOpen: setScenarioPanelOpen,
        highlighted: highlightedScenario,
        setHighlighted: setHighlightedScenario,
    }), [scenarioPanelOpen, highlightedScenario]);

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

    const isDraggingRef = useRef(false);
    const startPosRef = useRef<any>(null);
    const [boundingBox, setBoundingBox] = useState<any>(null);

    useEffect(() => {
        const handleMouseDown = (e: any) => {
            if (e.shiftKey && e.button === 0) {
                startPosRef.current = { x: e.clientX, y: e.clientY };
                isDraggingRef.current = true;
            }
        };

        const handleMouseMove = (e: any) => {
            if (!isDraggingRef.current || !startPosRef.current) return;
            const currentPos = { x: e.clientX, y: e.clientY };
            setBoundingBox({
                start_x: startPosRef.current.x,
                start_y: startPosRef.current.y,
                end_x: currentPos.x,
                end_y: startPosRef.current.y,
            });
        };

        const handleMouseUp = () => {
            isDraggingRef.current = false;
        };

        document.addEventListener("mousedown", handleMouseDown);
        document.addEventListener("mousemove", handleMouseMove);
        document.addEventListener("mouseup", handleMouseUp);

        return () => {
            document.removeEventListener("mousedown", handleMouseDown);
            document.removeEventListener("mousemove", handleMouseMove);
            document.removeEventListener("mouseup", handleMouseUp);
        };
    }, []);

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
    const {getZoom, getViewport, setViewport, setCenter, screenToFlowPosition, fitView} = useReactFlow();
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
    const flowStore = useStoreApi();
    useEffect(() => {
        if (!notebookOn) return;
        const hold = ([x, y, zoom]: readonly number[]) => {
            if (x !== 0 || y !== 0 || zoom !== 1) setViewport({ x: 0, y: 0, zoom: 1 });
        };
        hold(flowStore.getState().transform);
        return flowStore.subscribe((state, prev) => {
            if (state.transform !== prev.transform) hold(state.transform);
        });
    }, [notebookOn, flowStore, setViewport]);

    // The element the notebook scrolls in. Its size and the overlays fixed over
    // it (top bar, title chips, palette rail) decide where the column goes.
    const scrollerRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        const scroller = scrollerRef.current;
        if (!scroller) return;
        registerNotebookScroller(scroller);
        const measure = () => {
            const rect = scroller.getBoundingClientRect();
            const top = topOverlayBottom();
            const rail = paletteRailRight();
            setNotebookPane({
                width: scroller.clientWidth,
                top: top === null ? 0 : Math.max(0, top - rect.top),
                left: rail === null ? 0 : Math.max(0, rail - rect.left),
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
    // (see useWorkflowOperations.ts) before taking screenshots. Kept
    // unconditional — read-only from the outside and cheap — so e2e tests
    // don't need a separate build flag.
    useEffect(() => {
        (window as any).__curio_reactFlow = reactFlow;
        (window as any).__curio_fitViewWithMenuOffset = (options?: FitViewOptions) =>
            fitViewWithMenuOffset(reactFlow, options);
        return () => {
            if ((window as any).__curio_reactFlow === reactFlow) {
                delete (window as any).__curio_reactFlow;
                delete (window as any).__curio_fitViewWithMenuOffset;
            }
        };
    }, [reactFlow]);

    const {
        viewerMode,
    } = useFlowContext();

    // Ctrl/Cmd+Enter on a selected node (#223).
    useRunSelectedNodeShortcut();

    // When real-time collaboration is on, a peer opening the owner's URL
    // lands in ``viewerMode === "shared"`` (loadSharedProject was the only
    // way to bypass the owner-only /api/projects/<id> 404). For collab to
    // be useful peers must be able to *edit*; their edits flow over the
    // socket to the owner, who persists. Without this gate, peers see the
    // canvas as read-only and the lock/proposal flow does nothing.
    const isSharedView = viewerMode === "shared" && !collab.enabled;

    const [isComponentsSelected, setIsComponentsSelected] = useState<boolean>(false);

    const [floatingPanels, setFloatingPanels] = useState<any>({});

    // Selecting boxes to generate explanation
    const [selectedComponents, setSelectedComponents] = useState<any>({});

    const captureScreenshot = async (): Promise<string | null> => {
        const screenshotTarget = document.getElementsByClassName("react-flow__renderer")[0] as HTMLElement;

        if (!screenshotTarget) return null;
    
        return new Promise((resolve) => {
            html2canvas(screenshotTarget).then((canvas) => {
                canvas.toBlob((blob) => {
                    if (blob) {
                        const url = URL.createObjectURL(blob);
                        resolve(url); // Return the URL
                    } else {
                        resolve(null);
                    }
                });
            });
        });
    }

    const deleteFloatingPanel = (id: string) => {
        setFloatingPanels((prev: any) => {
            const next = { ...prev };
            delete next[id];
            return next;
        });
    }

    // Last dragover point, so a pointer that reports the same coordinate twice
    // (browsers fire dragover on a timer as well as on movement) costs nothing.
    const lastDragPointRef = useRef<{ x: number; y: number } | null>(null);

    const handleDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        // Dataset, model AND agent drags use effectAllowed="copy"; a "move"
        // dropEffect is an incompatible pair, so the browser cancels the drop
        // (handleDrop never fires and the agent silently fails to attach).
        // Node-creation drags keep "move".
        const wantsCopy =
            hasDatasetDrag(event.dataTransfer) ||
            hasModelDrag(event.dataTransfer) ||
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

    // A model dropped on the empty canvas becomes a node that runs it, as a
    // dataset becomes a Data Loading node. A drop on a node never gets here:
    // the node's own listener takes it (styles.tsx).
    const { getStarters } = useStarterContext();
    const handleModelCanvasDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const model = readModelDragPayload(event.dataTransfer);
        if (!model) return;
        const templates = (descriptors: NodeDescriptor[]): ModelDropTemplate[] =>
            descriptors.map((d) => ({
                nodeType: String(d.id),
                label: d.label,
                code: packageStarterCode(d, getStarters),
                packageName: d.package?.name,
            }));
        const node = modelNodeForCanvas(templates(getPaletteNodeTypes()), model);
        if (!node) {
            const elsewhere = modelNodeForCanvas(templates(getAllNodeTypes()), model);
            showToast(
                elsewhere?.packageName
                    ? `${model.name} needs a node that runs models: add ${elsewhere.packageName} to this project from the Node Catalog.`
                    : "No installed node runs a model.",
                "warning",
            );
            return;
        }
        const position = dropPosition(event);
        revealCreated(createCodeNode(node.nodeType, { position, code: node.code, modelRefs: node.modelRefs }));
        const article = /^[aeiou]/i.test(node.label) ? "an" : "a";
        showToast(`Created ${article} ${node.label} node for ${model.name}.`, "success");
        markDirty();
    }, [getStarters, dropPosition, revealCreated, createCodeNode, markDirty, showToast]);

    const handleDrop = useCallback((event: React.DragEvent) => {
        if (hasDatasetDrag(event.dataTransfer)) {
            handleCanvasDrop(event);
            return;
        }
        if (hasModelDrag(event.dataTransfer)) {
            handleModelCanvasDrop(event);
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
            attachAgentOnDrop({
                projectId,
                target,
                agentCoord,
                saveProject: saveCurrentProject,
                attach: (pid, coord, t) => agentsApi.attach(pid, coord, t),
            })
                .then(() => {
                    notifyAgentDockRefresh();
                    markDirty();
                    showToast(`Agent attached to ${where}.`, "success");
                })
                .catch((e: any) => showToast(e?.message || "Attach failed.", "error"));
            return;
        }
        event.preventDefault();
        const type = event.dataTransfer.getData("application/reactflow") as NodeType;
        if (!type) return;
        const position = dropPosition(event);
        revealCreated(createCodeNode(type, { position }));
        markDirty();
    }, [screenToFlowPosition, dropPosition, revealCreated, createCodeNode, markDirty, handleCanvasDrop, handleModelCanvasDrop, projectId, showToast, saveCurrentProject, reactFlow]);

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
        setSelectedComponents(selection);
        setIsComponentsSelected(selection.nodes.length + selection.edges.length > 1);
        const packageKey = selection.nodes
            .map((n) => packageKeyFromCanonicalNodeType(getFlowNodeCanonicalType(n)))
            .find((k): k is string => k != null);
        setActivePackageKey(packageKey ?? null);
    }, [setActivePackageKey]);

    // const handleWheel = (e: React.WheelEvent) => {

    //     // e.preventDefault();

    //     // Adjust this factor to control zoom speed (lower = smoother/slower)
    //     const zoomIntensity = 0.0015;

    //     const mouseScreen = { x: e.clientX, y: e.clientY };
    //     const mouseFlow = screenToFlowPosition(mouseScreen);

    //     const currentZoom = getZoom();
    //     const nextZoom = Math.min(Math.max(currentZoom * (1 - e.deltaY * zoomIntensity), 0.05), 2);
    //     const newX = mouseScreen.x - mouseFlow.x * nextZoom;
    //     const newY = mouseScreen.y - mouseFlow.y * nextZoom;

    //     setViewport({ x: newX, y: newY, zoom: nextZoom }, { duration: 200 });
    // };


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
        <ScenarioUiContext.Provider value={scenarioUi}>
        {!loading ? <div
            style={{ width: "100vw", height: "100vh", backgroundColor: "#f0f0f0" }}
            // onWheelCapture={handleWheel}
        >
            {Object.keys(floatingPanels).map((key, index) => (
                <FloatingPanel
                    key={key}
                    title={floatingPanels[key].title}
                    imageUrl={floatingPanels[key].imageUrl}
                    markdownText={floatingPanels[key].markdownText}
                    onClose={() => {deleteFloatingPanel(key)}}
                />
            ))}
            <ToolsMenu />
            <UpMenu />
            <CollaborationSidePanel />
            {!isSharedView ? <ScenariosPanel /> : null}
            <div
                className="curio-canvas-drop-target"
                style={{ width: "100%", height: "100%" }}
                onDragOver={!isSharedView ? handleDragOver : undefined}
                onDragLeave={!isSharedView ? handleDragLeave : undefined}
                onDrop={!isSharedView ? handleDrop : undefined}
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
                style={notebookOn ? { width: "100%", height: notebookContentHeight, minHeight: "100%" } : FILL_STYLE}
            >
            <ReactFlow
                nodes={scenarioView.nodes}
                edges={scenarioView.edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode={"Shift"}
                panActivationKeyCode={null}
                onSelectionChange={handleSelectionChange}
                onConnect={!isSharedView ? handleConnect : undefined}
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
                nodesConnectable={!isSharedView}
                edgesUpdatable={!isSharedView}
                // React Flow defaults to "Backspace" alone, so Windows users pressing
                // Delete got no response (#153). useKeyPress bails on isInputDOMNode,
                // so neither key can fire while the caret is in Monaco or an input.
                deleteKeyCode={isSharedView ? null : DEFAULT_DELETE_KEY_CODES}
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
        <VersionBadge />
        </ScenarioUiContext.Provider>
        </AgentAttachmentsProvider>
    );
}
