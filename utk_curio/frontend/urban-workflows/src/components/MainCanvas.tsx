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

import { useFlowContext } from "../providers/FlowProvider";
import { useCollab } from "../providers/CollaborationProvider";
import { usePackagePalette } from "../providers/PackagePaletteContext";
import { useToastContext } from "../providers/ToastProvider";
import { packageKeyFromCanonicalNodeType } from "../registry/packageKeys";
import { NodeType, EdgeType, CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { getFlowNodeCanonicalType } from "../utils/flowNodeCanonicalType";
import UniversalNode from "./UniversalNode";
import BiDirectionalEdge from "./edges/BiDirectionalEdge";
import { useCode } from "../hook/useCode";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { buttonStyle } from "./styles";
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import "./MainCanvas.css";
import LLMChat from "./LLMChat";
import { useLLMContext } from "../providers/LLMProvider";
import { TrillGenerator } from "../TrillGenerator";
import VersionBadge from "./VersionBadge";

import html2canvas from "html2canvas";

import FloatingPanel from "./FloatingPanel";
import WorkflowGoal from "./menus/top/WorkflowGoal";
import { DashboardPanel } from "./DashboardPanel";
import { CollaborationSidePanel } from "./collab/CollaborationSidePanel";

const CANVAS_EXTENT: [[number, number], [number, number]] = [[-2000, -2000], [6000, 6000]];

export function MainCanvas() {
    const { showToast } = useToastContext();
    const { setActivePackageKey } = usePackagePalette();
    const {
        nodes,
        edges,
        loading,
        onNodesChange,
        onEdgesChange,
        onConnect,
        isValidConnection,
        onEdgesDelete,
        onNodesDelete,
        markDirty,
    } = useFlowContext();
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
    const { llmRequest, AIModeRef, setAIMode } = useLLMContext();

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
        setDashBoardMode,
        updatePositionWorkflow,
        updatePositionDashboard,
        updateDataNode,
        workflowNameRef,
        workflowGoal,
        dashboardOn,
        dashboardLocked,
        dashboardPins,
        viewerMode,
    } = useFlowContext();

    // When real-time collaboration is on, a peer opening the owner's URL
    // lands in ``viewerMode === "shared"`` (loadSharedProject was the only
    // way to bypass the owner-only /api/projects/<id> 404). For collab to
    // be useful peers must be able to *edit*; their edits flow over the
    // socket to the owner, who persists. Without this gate, peers see the
    // canvas as read-only and the lock/proposal flow does nothing.
    const isSharedView = viewerMode === "shared" && !collab.enabled;

    // Refs used inside callbacks so the callbacks don't need to list them as deps
    const selectedEdgeIdRef = useRef<string>("");
    const dashboardOnRef = useRef<boolean>(false);
    const savedViewportRef = useRef<{ x: number; y: number; zoom: number } | null>(null);
    useEffect(() => { dashboardOnRef.current = dashboardOn; }, [dashboardOn]);
    useEffect(() => {
        if (dashboardOn) {
            savedViewportRef.current = getViewport();
            const pinnedNodes = Object.keys(dashboardPins)
                .filter(id => dashboardPins[id])
                .map(id => ({ id }));
            setTimeout(() => fitView({ duration: 300, padding: 0.08, nodes: pinnedNodes }), 50);
        } else {
            if (savedViewportRef.current) {
                setViewport(savedViewportRef.current, { duration: 300 });
            }
        }
    }, [dashboardOn]);

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

    const generateExplanation = async (_: React.MouseEvent<HTMLButtonElement>) => {

        // Take a screenshot for the explanation
        let image_url = await captureScreenshot();

        let trill_spec = TrillGenerator.generateTrill(selectedComponents.nodes, selectedComponents.edges, workflowNameRef.current, workflowGoal);

        let text = JSON.stringify(trill_spec)

        llmRequest("default_preamble", "explanation_prompt", text).then((response: any) => {
            console.log("Response:", response);

            setFloatingPanels((prev: any) => {
                let uniqueId = crypto.randomUUID()+"";
                
                return {
                    ...prev,
                    [uniqueId]: {
                        title: "Explanation from "+workflowNameRef.current,
                        imageUrl: image_url,
                        markdownText: response.result
                    }
                }
            });
        })
        .catch((error: any) => {
            console.error("Error:", error);
        });
    }

    const generateDebug = async (_: React.MouseEvent<HTMLButtonElement>) => {
        // Take a screenshot for the debugging
        let image_url = await captureScreenshot();

        let trill_spec = TrillGenerator.generateTrill(selectedComponents.nodes, selectedComponents.edges, workflowNameRef.current, workflowGoal);

        let text = JSON.stringify(trill_spec) + "\n\n" + ""

        llmRequest("default_preamble", "debug_prompt", text).then((response: any) => {
            console.log("Response:", response);

            setFloatingPanels((prev: any) => {
                let uniqueId = crypto.randomUUID()+"";
                
                return {
                    ...prev,
                    [uniqueId]: {
                        title: "Debugging "+workflowNameRef.current,
                        imageUrl: image_url,
                        markdownText: response.result
                    }
                }
            });
        })
        .catch((error: any) => {
            console.error("Error:", error);
        });

    }

    // Delete a floating box from the list based on the id
    const deleteFloatingPanel = (id: string) => {
        setFloatingPanels((prev: any) => {
            const next = { ...prev };
            delete next[id];
            return next;
        });
    }

    // Apply dashboard mode changes
    const handleDashboardToggle = useCallback((value: boolean) => {
        dashboardOnRef.current = value;
        setDashBoardMode(value);
    }, [setDashBoardMode]);

    const handleDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
    }, []);

    const handleDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        const type = event.dataTransfer.getData("application/reactflow") as NodeType;
        if (!type) return;
        const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        createCodeNode(type, { position });
        markDirty();
    }, [screenToFlowPosition, createCodeNode, markDirty]);

    const handleNodesChange = useCallback((changes: NodeChange[]) => {
        const allowedChanges: NodeChange[] = [];
        const currentEdges = reactFlow.getEdges();
        let dirty = false;

        for (const change of changes) {
            let allowed = true;

            if (change.type === "remove") {
                for (const edge of currentEdges) {
                    if (edge.source === change.id || edge.target === change.id) {
                        showToast(
                            "Connected boxes cannot be removed. Remove the edges first by selecting it and pressing backspace.",
                            "warning"
                        );
                        allowed = false;
                        break;
                    }
                }
                if (allowed) dirty = true;
            }

            if (
                change.type === "position" &&
                change.position != undefined &&
                change.position.x != undefined
            ) {
                if (dashboardOnRef.current) {
                    updatePositionDashboard(change.id, change);
                } else {
                    updatePositionWorkflow(change.id, change);
                }
                dirty = true;
                // Broadcast the new position to peers. Dashboard positions
                // are intentionally local-only — they're a per-user view of
                // the same nodes — so only the canvas-workflow position is
                // synced.
                if (!dashboardOnRef.current) {
                    collabRef.current.broadcastNodeUpdated({
                        nodeId: change.id,
                        patch: { position: change.position },
                    });
                }
            }

            if (allowed) allowedChanges.push(change);
        }

        if (dirty) markDirty();
        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    }, [reactFlow, showToast, updatePositionDashboard, updatePositionWorkflow, onNodesDelete, onNodesChange, markDirty]);

    const handleNodeDragStop = useCallback((_event: React.MouseEvent, node: any) => {
        if (!dashboardOnRef.current) return;
        updateDataNode(node.id, { ...node.data, dashboardX: node.position.x, dashboardY: node.position.y });
    }, [updateDataNode]);

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
        <>
        {!loading ? <div
            style={{ width: "100vw", height: "100vh", backgroundColor: dashboardOn ? "#ffffff" : "#f0f0f0" }}
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
            {!dashboardOn && <ToolsMenu />}
            {!dashboardOn && <UpMenu
                setDashBoardMode={(value) => handleDashboardToggle(value)}
                setDashboardOn={handleDashboardToggle}
                dashboardOn={dashboardOn}
                setAIMode={setAIMode}
            />}
            {!dashboardOn && <CollaborationSidePanel />}

            {dashboardOn && <DashboardPanel />}
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onDragOver={!dashboardOn && !isSharedView ? handleDragOver : undefined}
                onDrop={!dashboardOn && !isSharedView ? handleDrop : undefined}
                onNodesChange={handleNodesChange}
                onNodeDragStop={handleNodeDragStop}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode={dashboardOn ? null : "Shift"}
                panActivationKeyCode={null}
                onSelectionChange={handleSelectionChange}
                onConnect={!dashboardOn && !isSharedView ? onConnect : undefined}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                isValidConnection={isValidConnection}
                connectionMode={ConnectionMode.Loose}
                minZoom={0.05}

                translateExtent={CANVAS_EXTENT}
                panOnDrag={!dashboardOn || !dashboardLocked}
                zoomOnScroll={!dashboardOn || !dashboardLocked}
                zoomOnPinch={!dashboardOn || !dashboardLocked}
                zoomOnDoubleClick={!dashboardOn || !dashboardLocked}
                nodesDraggable={!isSharedView && (!dashboardOn || !dashboardLocked)}
                elementsSelectable={true}
                nodesConnectable={!isSharedView && !dashboardOn}
                edgesUpdatable={!isSharedView}
                deleteKeyCode={isSharedView ? null : undefined}
                style={dashboardOn ? { backgroundColor: "#ffffff" } : undefined}
            >
                {!dashboardOn && <Background color="#a0a0a0" variant={BackgroundVariant.Dots} gap={20} size={2} />}
                {!dashboardOn && <Controls />}
                {AIModeRef.current ? <WorkflowGoal /> : null}
                {AIModeRef.current ? <LLMChat /> : null}
            </ReactFlow>
            {isComponentsSelected ? (
                <button
                    id={"explainButton"}
                    style={{
                        bottom: "50px",
                        left: "30%",
                        position: "fixed",
                        zIndex: 10,
                        padding: "8px 16px",
                        backgroundColor: "#007bff",
                        color: "#fff",
                        border: "none",
                        borderRadius: "4px",
                        cursor: "pointer",
                    }}
                    onClick={generateExplanation}
                >
                    Explain
                </button>
            ) : null}
            {isComponentsSelected ? (
                <button
                    style={{
                        bottom: "50px",
                        left: "40%",
                        position: "fixed",
                        zIndex: 10,
                        padding: "8px 16px",
                        backgroundColor: "#007bff",
                        color: "#fff",
                        border: "none",
                        borderRadius: "4px",
                        cursor: "pointer",
                    }}
                    onClick={generateDebug}
                >
                    Debug
                </button>
            ) : null}
            <input hidden type="file" name="file" id="file" />

        </div> : loadingAnimation() }
        <VersionBadge />
        </>

    );
}