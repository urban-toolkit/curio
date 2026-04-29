import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect, useRef, useCallback } from "react";
import ReactFlow, {
    Background,
    BackgroundVariant,
    ConnectionMode,
    Controls,
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
import BiDirectionalEdge from "./edges/BiDirectionalEdge";
import { useCode } from "../hook/useCode";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { buttonStyle } from "./styles";
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import { useCollaborationContext } from "../providers/CollaborationProvider";
import "./MainCanvas.css";
import LLMChat from "./LLMChat";
import { useLLMContext } from "../providers/LLMProvider";
import { TrillGenerator } from "../TrillGenerator";

import html2canvas from "html2canvas";

import FloatingPanel from "./FloatingPanel";
import WorkflowGoal from "./menus/top/WorkflowGoal";
import { DashboardPanel } from "./DashboardPanel";

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
        markDirty,
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

    const { createCodeNode } = useCode();
    const { llmRequest, AIModeRef, setAIMode } = useLLMContext();

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
    const {getZoom, getViewport, setViewport, setCenter, screenToFlowPosition, fitView} = useReactFlow();

    // Test hook: expose the ReactFlow instance so Playwright can force a
    // deterministic viewport (e.g. fitView with duration: 0) before taking
    // screenshots. Kept unconditional — read-only from the outside and
    // cheap — so e2e tests don't need a separate build flag.
    useEffect(() => {
        (window as any).__curio_reactFlow = reactFlow;
        return () => {
            if ((window as any).__curio_reactFlow === reactFlow) {
                delete (window as any).__curio_reactFlow;
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
    } = useFlowContext();

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

    const {
        isConnected,
        connectedUsers,
        conflicts,
        codeChangeProposals,
        activityLog,
        dismissConflict,
        resolveConflict,
        approveCodeChange,
        rejectCodeChange,
        myUserId,
        myUserName,
        myColor,
        setUserName
    } = useCollaborationContext();
    const [nameDraft, setNameDraft] = useState(myUserName);
    const [proposalComments, setProposalComments] = useState<Record<string, string>>({});

    useEffect(() => {
        setNameDraft(myUserName);
    }, [myUserName]);

    const shortId = (id?: string) => id ? id.slice(0, 6) : "unknown";
    const userLabel = (user?: { name?: string; userId?: string }) =>
        user?.name || (user?.userId ? `User ${shortId(user.userId)}` : "Unknown user");
    const formatTime = (timestamp?: number) =>
        timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
    const conflictTitle = (type: string) => {
        if (type === "node_edit") return "Concurrent node edit";
        if (type === "node_delete") return "Node delete conflict";
        if (type === "node_deleted") return "Deleted node changed";
        if (type === "edge_dependency") return "Downstream dependency changed";
        if (type === "edge_deleted") return "Edge already deleted";
        if (type === "node_lock") return "Node already being edited";
        return "Collaboration conflict";
    };
    const allUsers = [
        { userId: myUserId, name: myUserName, color: myColor },
        ...connectedUsers.filter((u) => u.userId !== myUserId)
    ];
    const allUserNames = new Map(allUsers.map((u) => [u.userId, userLabel(u)]));
    const commitUserName = () => setUserName(nameDraft);

    return (
        <>
        {!loading ? <div
            style={{ width: "100vw", height: "100vh", backgroundColor: dashboardOn ? "#ffffff" : "#f0f0f0" }}
            // onWheelCapture={handleWheel}
        >
            <div style={{
                position: "fixed",
                top: 8,
                right: 12,
                zIndex: 1000,
                width: 340,
                maxHeight: "calc(100vh - 24px)",
                overflowY: "auto",
                background: "rgba(255,255,255,0.96)",
                border: "1px solid #d9dee7",
                borderRadius: 8,
                boxShadow: "0 6px 24px rgba(15,23,42,0.18)",
                padding: 10,
                fontSize: 12,
                color: "#172033"
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <div style={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: isConnected ? "#2f9e44" : "#c92a2a",
                        flex: "0 0 auto"
                    }} title={isConnected ? "Connected" : "Disconnected"} />
                    <input
                        value={nameDraft}
                        onChange={(event) => setNameDraft(event.target.value)}
                        onBlur={commitUserName}
                        onKeyDown={(event) => {
                            if (event.key === "Enter") {
                                commitUserName();
                                (event.currentTarget as HTMLInputElement).blur();
                            }
                        }}
                        style={{
                            minWidth: 0,
                            flex: 1,
                            border: "1px solid #cfd6e4",
                            borderRadius: 6,
                            padding: "5px 7px",
                            fontSize: 12,
                            fontWeight: 600
                        }}
                        aria-label="User name"
                    />
                    <span style={{ color: "#667085", fontVariantNumeric: "tabular-nums" }}>
                        {shortId(myUserId)}
                    </span>
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: conflicts.length ? 10 : 8 }}>
                    {allUsers.map((u) => (
                        <div key={u.userId} title={userLabel(u)} style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 5,
                            maxWidth: 150,
                            border: "1px solid #e5e7eb",
                            borderRadius: 999,
                            padding: "3px 7px 3px 4px",
                            background: "#fff"
                        }}>
                            <span style={{
                                width: 18,
                                height: 18,
                                borderRadius: "50%",
                                background: u.color,
                                color: "#fff",
                                display: "inline-flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: 9,
                                fontWeight: 700,
                                flex: "0 0 auto"
                            }}>
                                {(u.name || u.userId).slice(0, 2).toUpperCase()}
                            </span>
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {u.userId === myUserId ? "You" : userLabel(u)}
                            </span>
                        </div>
                    ))}
                </div>

                {codeChangeProposals.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
                        {codeChangeProposals.map((proposal) => {
                            const required = proposal.requiredUserIds || [];
                            const approvals = proposal.approvals || {};
                            const comments = proposal.comments || {};
                            const acceptedCount = required.filter((uid) => approvals[uid]).length;
                            const missing = required.filter((uid) => !approvals[uid]);
                            const needsMyDecision = required.includes(myUserId);
                            const myApproved = Boolean(approvals[myUserId]);
                            const myComment = proposalComments[proposal.proposalId] ?? comments[myUserId]?.comment ?? "";
                            const proposedCode =
                                proposal.node?.data?.code ??
                                proposal.node?.data?.defaultCode ??
                                "";

                            return (
                                <div key={proposal.proposalId} style={{
                                    border: "1px solid #fedf89",
                                    background: "#fffbeb",
                                    borderRadius: 8,
                                    padding: 9
                                }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                                        <strong style={{ color: "#92400e" }}>Code change needs approval</strong>
                                        <span style={{ color: "#92400e", fontVariantNumeric: "tabular-nums" }}>
                                            {acceptedCount}/{required.length}
                                        </span>
                                    </div>
                                    <div style={{ color: "#4b5563", lineHeight: 1.35 }}>
                                        <strong>{userLabel(proposal.proposedBy)}</strong> changed code on node <strong>{shortId(proposal.nodeId)}</strong>.
                                        The shared node will not update until every required user accepts.
                                    </div>
                                    {proposal.changeSummary && proposal.changeSummary.length > 0 && (
                                        <div style={{ marginTop: 7, color: "#344054" }}>
                                            Changed: <strong>{proposal.changeSummary.join(", ")}</strong>
                                        </div>
                                    )}
                                    {proposedCode && (
                                        <pre style={{
                                            marginTop: 7,
                                            marginBottom: 0,
                                            maxHeight: 120,
                                            overflow: "auto",
                                            background: "#111827",
                                            color: "#f9fafb",
                                            borderRadius: 6,
                                            padding: 7,
                                            fontSize: 10,
                                            whiteSpace: "pre-wrap"
                                        }}>
                                            {proposedCode}
                                        </pre>
                                    )}
                                    {missing.length > 0 && (
                                        <div style={{ marginTop: 7, color: "#344054" }}>
                                            Waiting for: <strong>{missing.map((uid) => allUserNames.get(uid) || shortId(uid)).join(", ")}</strong>
                                        </div>
                                    )}
                                    {Object.values(comments).length > 0 && (
                                        <div style={{ marginTop: 7, color: "#344054", display: "flex", flexDirection: "column", gap: 4 }}>
                                            {Object.values(comments).map((entry: any) => (
                                                <div key={entry.user?.userId || entry.timestamp}>
                                                    <strong>{userLabel(entry.user)}:</strong> {entry.comment || "No comment"}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    {needsMyDecision ? (
                                        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 9 }}>
                                            <textarea
                                                value={myComment}
                                                onChange={(event) => setProposalComments((prev) => ({
                                                    ...prev,
                                                    [proposal.proposalId]: event.target.value
                                                }))}
                                                placeholder="Comment if you do not accept this code change"
                                                style={{
                                                    width: "100%",
                                                    minHeight: 46,
                                                    resize: "vertical",
                                                    border: "1px solid #fbbf24",
                                                    borderRadius: 6,
                                                    padding: 6,
                                                    fontSize: 11
                                                }}
                                            />
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                                <button
                                                    onClick={() => approveCodeChange(proposal.proposalId)}
                                                    disabled={myApproved}
                                                    style={{
                                                        ...buttonStyle,
                                                        padding: "4px 8px",
                                                        fontSize: 11,
                                                        opacity: myApproved ? 0.55 : 1
                                                    }}
                                                >
                                                    {myApproved ? "Accepted" : "Accept code"}
                                                </button>
                                                <button
                                                    onClick={() => rejectCodeChange(proposal.proposalId, myComment)}
                                                    style={{ ...buttonStyle, padding: "4px 8px", fontSize: 11, backgroundColor: "#b45309" }}
                                                >
                                                    Comment / do not accept
                                                </button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div style={{ marginTop: 7, color: "#667085" }}>
                                            {proposal.proposedBy?.userId === myUserId
                                                ? "Waiting for other users to accept your code change."
                                                : "You are not required for this approval."}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                {conflicts.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
                        {conflicts.map((c) => (
                            <div key={c.conflictId} style={{
                                border: "1px solid #f1aeb5",
                                background: "#fff5f5",
                                borderRadius: 8,
                                padding: 9
                            }}>
                                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                                    <strong style={{ color: "#9f1239" }}>{conflictTitle(c.type)}</strong>
                                    <button
                                        onClick={() => dismissConflict(c.conflictId)}
                                        style={{
                                            border: "none",
                                            background: "transparent",
                                            color: "#9f1239",
                                            cursor: "pointer",
                                            fontWeight: 700
                                        }}
                                        aria-label="Dismiss conflict"
                                    >
                                        x
                                    </button>
                                </div>
                                <div style={{ color: "#4b5563", lineHeight: 1.35 }}>
                                    {c.message || "A collaboration conflict needs attention."}
                                </div>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 7, color: "#344054" }}>
                                    <span>By: <strong>{userLabel(c.actor || c.requestedBy)}</strong></span>
                                    <span>Current: <strong>{userLabel(c.currentOwner || c.lockedBy || c.deletedBy)}</strong></span>
                                    {c.nodeId && <span>Node: <strong>{shortId(c.nodeId)}</strong></span>}
                                    {c.edgeId && <span>Edge: <strong>{shortId(c.edgeId)}</strong></span>}
                                    {c.serverRevision !== undefined && <span>Server rev: <strong>{c.serverRevision}</strong></span>}
                                    {c.baseRevision !== undefined && <span>My base: <strong>{c.baseRevision}</strong></span>}
                                </div>
                                {c.changeSummary && c.changeSummary.length > 0 && (
                                    <div style={{ marginTop: 7, color: "#344054" }}>
                                        Changed: <strong>{c.changeSummary.join(", ")}</strong>
                                    </div>
                                )}
                                {c.affectedNodeIds && c.affectedNodeIds.length > 0 && (
                                    <div style={{ marginTop: 7, color: "#344054" }}>
                                        Affects: <strong>{c.affectedNodeIds.map(shortId).join(", ")}</strong>
                                    </div>
                                )}
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 9 }}>
                                    <button onClick={() => resolveConflict(c, "keep_mine")} style={{ ...buttonStyle, padding: "4px 8px", fontSize: 11 }}>
                                        Keep mine
                                    </button>
                                    <button onClick={() => resolveConflict(c, "accept_other")} style={{ ...buttonStyle, padding: "4px 8px", fontSize: 11, backgroundColor: "#475467" }}>
                                        Accept other
                                    </button>
                                    <button onClick={() => resolveConflict(c, "manual")} style={{ ...buttonStyle, padding: "4px 8px", fontSize: 11, backgroundColor: "#7c3aed" }}>
                                        Manual
                                    </button>
                                    <button onClick={() => resolveConflict(c, "cancel")} style={{ ...buttonStyle, padding: "4px 8px", fontSize: 11, backgroundColor: "#b42318" }}>
                                        Cancel
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                <div>
                    <div style={{ fontWeight: 700, marginBottom: 5 }}>Activity</div>
                    {activityLog.length === 0 ? (
                        <div style={{ color: "#667085" }}>No recent activity</div>
                    ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                            {activityLog.slice(0, 8).map((item) => (
                                <div key={item.id} style={{
                                    display: "grid",
                                    gridTemplateColumns: "auto 1fr auto",
                                    alignItems: "center",
                                    gap: 6,
                                    borderTop: "1px solid #eef2f7",
                                    paddingTop: 5
                                }}>
                                    <span style={{
                                        width: 8,
                                        height: 8,
                                        borderRadius: "50%",
                                        background: item.user?.color || "#98a2b3"
                                    }} />
                                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                        <strong>{userLabel(item.user)}</strong> {item.label.replace(userLabel(item.user), "").trim()}
                                    </span>
                                    <span style={{ color: "#667085", fontVariantNumeric: "tabular-nums" }}>{formatTime(item.timestamp)}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

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

            {dashboardOn && <DashboardPanel />}
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onDragOver={!dashboardOn ? handleDragOver : undefined}
                onDrop={!dashboardOn ? handleDrop : undefined}
                onNodesChange={handleNodesChange}
                onNodeDragStop={handleNodeDragStop}
                onEdgesChange={handleEdgesChange}
                onEdgesDelete={handleEdgesDelete}
                selectionKeyCode={dashboardOn ? null : "Shift"}
                onSelectionChange={handleSelectionChange}
                onConnect={!dashboardOn ? onConnect : undefined}
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
                nodesDraggable={!dashboardOn || !dashboardLocked}
                elementsSelectable={true}
                nodesConnectable={!dashboardOn}
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
        </>

    );
}
