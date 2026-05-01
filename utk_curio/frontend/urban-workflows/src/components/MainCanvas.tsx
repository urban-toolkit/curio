import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect, useRef, useCallback } from "react";
import ReactFlow, {
    Background,
    BackgroundVariant,
    ConnectionMode,
    Edge,
    EdgeChange,
    NodeChange,
    useReactFlow,
} from "reactflow";

import { useFlowContext } from "../providers/FlowProvider";
import { useToastContext } from "../providers/ToastProvider";
import { NodeType, EdgeType } from "../constants";
import { getAllNodeTypes } from "../registry";
import UniversalNode from "./UniversalNode";
import { UserMenu } from "./login/UserMenu";
import BiDirectionalEdge from "./edges/BiDirectionalEdge";
import { RightClickMenu } from "./styles";
import { useRightClickMenu } from "../hook/useRightClickMenu";
import { useCode } from "../hook/useCode";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { buttonStyle } from "./styles";
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import "./MainCanvas.css";
import LLMChat from "./LLMChat";
import { useLLMContext } from "../providers/LLMProvider";
import { TrillGenerator } from "../TrillGenerator";

import html2canvas from "html2canvas";

import FloatingPanel from "./FloatingPanel";
import WorkflowGoal from "./menus/top/WorkflowGoal";

const CANVAS_EXTENT: [[number, number], [number, number]] = [[-2000, -2000], [6000, 6000]];

export function MainCanvas() {
    const { showToast } = useToastContext();
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
    } = useFlowContext();

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

    const { onContextMenu, showMenu, menuPosition } = useRightClickMenu();
    const { createCodeNode } = useCode();
    const { openAIRequest, AIModeRef, setAIMode } = useLLMContext();

    const nodeTypes = useMemo(() => {
        const types: Record<string, any> = {};
        for (const desc of getAllNodeTypes()) {
            if (desc.adapter) {
                types[desc.id] = UniversalNode;
            }
        }
        return types;
    }, []);

    const edgeTypes = useMemo(() => ({
        [EdgeType.BIDIRECTIONAL_EDGE]: BiDirectionalEdge,
        [EdgeType.UNIDIRECTIONAL_EDGE]: UniDirectionalEdge,
    }), []);

    const reactFlow = useReactFlow();
    const {getZoom, getViewport, setViewport, setCenter, screenToFlowPosition} = useReactFlow();

    const {
        setDashBoardMode,
        updatePositionWorkflow,
        updatePositionDashboard,
        workflowNameRef,
        workflowGoal
    } = useFlowContext();

    // Refs used inside callbacks so the callbacks don't need to list them as deps
    const selectedEdgeIdRef = useRef<string>("");
    const dashboardOnRef = useRef<boolean>(false);

    const [isComponentsSelected, setIsComponentsSelected] = useState<boolean>(false);

    const [floatingPanels, setFloatingPanels] = useState<any>({});

    // Selecting boxes to generate explanation
    const [selectedComponents, setSelectedComponents] = useState<any>({});

    const [dashboardOn, setDashboardOn] = useState<boolean>(false);
    const { dashboardPins } = useFlowContext();

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

        openAIRequest("default_preamble", "explanation_prompt", text).then((response: any) => {
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

        openAIRequest("default_preamble", "debug_prompt", text).then((response: any) => {
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
        setDashboardOn(value);
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
    }, [screenToFlowPosition, createCodeNode]);

    const handleNodesChange = useCallback((changes: NodeChange[]) => {
        const allowedChanges: NodeChange[] = [];
        const currentEdges = reactFlow.getEdges();

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
            }

            if (
                change.type === "position" &&
                change.position != undefined &&
                change.position.x != undefined
            ) {
                if (dashboardOnRef.current)
                    updatePositionDashboard(change.id, change);
                else
                    updatePositionWorkflow(change.id, change);
            }

            if (allowed) allowedChanges.push(change);
        }

        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    }, [reactFlow, showToast, updatePositionDashboard, updatePositionWorkflow, onNodesDelete, onNodesChange]);

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

        for (const change of changes) {
            if (
                change.type === "remove" &&
                (selected === change.id || prevSelectedId === change.id)
            ) {
                allowedChanges.push(change);
            } else if (change.type !== "remove") {
                allowedChanges.push(change);
            }
        }

        return onEdgesChange(allowedChanges);
    }, [onEdgesChange]);

    const handleEdgesDelete = useCallback((edges: Edge[]) => {
        const allowedEdges = edges.filter(edge => selectedEdgeIdRef.current === edge.id);
        return onEdgesDelete(allowedEdges);
    }, [onEdgesDelete]);

    const handleSelectionChange = useCallback((selection: { nodes: any[]; edges: any[] }) => {
        setSelectedComponents(selection);
        setIsComponentsSelected(selection.nodes.length + selection.edges.length > 1);
    }, []);

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

    // Filter nodes based on dashboard mode
    const filteredNodes = useMemo(() => {
        if (!dashboardOn) return nodes;
        return nodes.filter(node => dashboardPins[node.id]);
    }, [nodes, dashboardOn, dashboardPins]);


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
            style={{ width: "100vw", height: "100vh", backgroundColor: "#f0f0f0" }}
            onContextMenu={onContextMenu}
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
            <UserMenu />
            <ToolsMenu />
            <UpMenu
                setDashBoardMode={(value) => handleDashboardToggle(value)}
                setDashboardOn={handleDashboardToggle}
                dashboardOn={dashboardOn}
                setAIMode={setAIMode}
            />
            <RightClickMenu
                showMenu={showMenu}
                menuPosition={menuPosition}
                options={[
                    {
                        name: "Add comment box",
                        action: () => createCodeNode("COMMENTS"),
                    },
                ]}
            />
            <ReactFlow
                // zoomOnScroll={false}
                nodes={filteredNodes}
                edges={edges}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode="Shift"
                onSelectionChange={handleSelectionChange}
                onConnect={onConnect}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                isValidConnection={isValidConnection}
                connectionMode={ConnectionMode.Loose}
                minZoom={0.05}
                onlyRenderVisibleElements
                translateExtent={CANVAS_EXTENT}
            >
                <Background color="#a0a0a0" variant={BackgroundVariant.Dots} gap={20} size={2} />
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
        </>
        
    );
}