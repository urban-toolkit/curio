import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect, useRef, useCallback } from "react";
import ReactFlow, {
    Background,
    BackgroundVariant,
    ConnectionMode,
    Controls,
    Edge,
    EdgeChange,
    FitViewOptions,
    NodeChange,
    useReactFlow,
} from "reactflow";
import { fitViewWithMenuOffset } from "../utils/fitViewWithMenuOffset";
import { computeTranslateExtent } from "../utils/canvasExtent";

import { useFlowContext } from "../providers/FlowProvider";
import { useCollab } from "../providers/CollaborationProvider";
import { usePackagePalette } from "../providers/PackagePaletteContext";
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
import { agentsApi } from "../api/agentsApi";
import { readAgentDragCoord, notifyAgentDockRefresh, resolveAgentDropTarget, hasAgentDrag, type AgentDropTarget } from "../utils/agentCatalogEvents";
import { clearAgentDropHover, setAgentDropHoverEdgeId } from "../utils/agentDropHover";
import { attachAgentOnDrop } from "../utils/agentDropAttach";
import { AgentDockOverlay } from "./agents/attach/AgentDockOverlay";
import { AgentAttachmentsProvider } from "./agents/attach/AgentAttachmentsProvider";

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
    } = useFlowContext();

    // How far the viewport may pan, tracking the nodes rather than a fixed box
    // (#234). Two memos on purpose: React Flow re-applies `translateExtent`
    // through an effect keyed on the value's IDENTITY, so handing it a fresh
    // array every render would call `d3Zoom.translateExtent()` on every frame
    // of a drag. `computeTranslateExtent` rounds to a coarse grid, and keying
    // the tuple on those four numbers keeps the identity stable until a node
    // actually crosses a boundary.
    const [extentMinX, extentMinY, extentMaxX, extentMaxY] = useMemo(() => {
        const [[minX, minY], [maxX, maxY]] = computeTranslateExtent(nodes);
        return [minX, minY, maxX, maxY];
    }, [nodes]);
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

    // Refs used inside callbacks so the callbacks don't need to list them as deps
    const selectedEdgeIdRef = useRef<string>("");

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
        // Dataset AND agent drags use effectAllowed="copy"; a "move" dropEffect is
        // an incompatible pair, so the browser cancels the drop (handleDrop never
        // fires and the agent silently fails to attach). Node-creation drags keep
        // "move".
        const wantsCopy =
            hasDatasetDrag(event.dataTransfer) || hasAgentDrag(event.dataTransfer);
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
            nodes: reactFlow.getNodes(),
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
            const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
            createCodeNode(NodeType.DATA_LOADING, buildDatasetLoaderNodeOptions(dataset, position));
            showToast(
                `Created a Data Loading node for ${dataset.title}.`,
                "success",
                viewDatasetDetailsToast(openDatasetDetails, dataset.datasetId),
            );
            markDirty();
        }
    }, [screenToFlowPosition, createCodeNode, markDirty, showToast, openDatasetDetails]);

    const handleDrop = useCallback((event: React.DragEvent) => {
        if (hasDatasetDrag(event.dataTransfer)) {
            handleCanvasDrop(event);
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
                nodes: reactFlow.getNodes(),
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
        const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        createCodeNode(type, { position });
        markDirty();
    }, [screenToFlowPosition, createCodeNode, markDirty, handleCanvasDrop, projectId, showToast, saveCurrentProject, reactFlow]);

    const handleNodesChange = useCallback((changes: NodeChange[]) => {
        const allowedChanges: NodeChange[] = [];
        const currentEdges = reactFlow.getEdges();
        let dirty = false;

        for (const change of changes) {
            let allowed = true;

            if (change.type === "remove") {
                // Removing a wired node is refused on purpose. Say how much is
                // in the way: the old copy told the user to "remove the edges"
                // without saying how many there were or which, so on a busy
                // canvas it read as the key simply not working.
                const attached = currentEdges.filter(
                    (edge) => edge.source === change.id || edge.target === change.id,
                );
                if (attached.length > 0) {
                    const count = attached.length;
                    showToast(
                        `This node still has ${count} connection${count === 1 ? "" : "s"}. ` +
                        `Select ${count === 1 ? "it" : "them"} and press Delete or Backspace, ` +
                        "then remove the node.",
                        "warning"
                    );
                    allowed = false;
                }
                if (allowed) dirty = true;
            }

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

            if (allowed) allowedChanges.push(change);
        }

        if (dirty) markDirty();
        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    }, [reactFlow, showToast, onNodesDelete, onNodesChange, markDirty]);

    const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
        let selected = "";
        const allowedChanges: EdgeChange[] = [];
        const prevSelectedId = selectedEdgeIdRef.current;

        for (const change of changes) {
            if (change.type === "select" && change.selected === true) {
                selectedEdgeIdRef.current = change.id;
                selected = change.id;
            } else if (change.type === "select") {
                selectedEdgeIdRef.current = "";
            }
        }

        let dirty = false;
        for (const change of changes) {
            if (
                change.type === "remove" &&
                (selected === change.id || prevSelectedId === change.id)
            ) {
                allowedChanges.push(change);
                dirty = true;
            } else if (change.type !== "remove") {
                allowedChanges.push(change);
            }
        }

        if (dirty) markDirty();
        return onEdgesChange(allowedChanges);
    }, [onEdgesChange, markDirty]);

    const handleEdgesDelete = useCallback((edges: Edge[]) => {
        const allowedEdges = edges.filter(edge => selectedEdgeIdRef.current === edge.id);
        if (allowedEdges.length > 0) markDirty();
        return onEdgesDelete(allowedEdges);
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
        <>
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
            <div
                className="curio-canvas-drop-target"
                style={{ width: "100%", height: "100%" }}
                onDragOver={!isSharedView ? handleDragOver : undefined}
                onDragLeave={!isSharedView ? handleDragLeave : undefined}
                onDrop={!isSharedView ? handleDrop : undefined}
            >
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode={"Shift"}
                panActivationKeyCode={null}
                onSelectionChange={handleSelectionChange}
                onConnect={!isSharedView ? onConnect : undefined}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                isValidConnection={isValidConnection}
                connectionMode={ConnectionMode.Loose}
                minZoom={0.05}
                translateExtent={translateExtent}
                nodesDraggable={!isSharedView}
                elementsSelectable={true}
                nodesConnectable={!isSharedView}
                edgesUpdatable={!isSharedView}
                // React Flow defaults to "Backspace" alone, so Windows users pressing
                // Delete got no response (#153). useKeyPress bails on isInputDOMNode,
                // so neither key can fire while the caret is in Monaco or an input.
                deleteKeyCode={isSharedView ? null : DEFAULT_DELETE_KEY_CODES}
            >
                <Background color="#a0a0a0" variant={BackgroundVariant.Dots} gap={20} size={2} />
                <Controls />
            </ReactFlow>
            {!isSharedView ? <AgentDockOverlay /> : null}
            </div>

        </div> : loadingAnimation() }
        <VersionBadge />
        </>
        </AgentAttachmentsProvider>
    );
}
