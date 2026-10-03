// Connecting two nodes: onConnect checks the handles, the node types, merge
// slots, occupied inputs and cycles, then adds the edge.
import React, { useCallback } from "react";
import { Connection, Edge, Node, ReactFlowInstance, addEdge, getOutgoers, MarkerType } from "reactflow";
import { ConnectionValidator } from "../../ConnectionValidator";
import { NodeType, EdgeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { TrillGenerator } from "../../TrillGenerator";
import { parseHandleIndex } from "../../utils/mergeFlowUtils";
import type { useToastContext } from "../ToastProvider";
import type { useCollab } from "../CollaborationProvider";
import type { IOutput } from "./flowTypes";
import type { useGraphEdits } from "./useGraphEdits";

export function useConnect({
    markDirtyRef, reactFlow, showToast, markNodeStaleRef, applyOutput, setEdges,
    workflowNameRef, collabRef, outputsRef, propagateDownstreamInputs,
}: {
    markDirtyRef: React.MutableRefObject<() => void>;
    reactFlow: ReactFlowInstance;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    markNodeStaleRef: React.MutableRefObject<(nodeId: string) => void>;
    applyOutput: ReturnType<typeof useGraphEdits>["applyOutput"];
    setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
    workflowNameRef: React.MutableRefObject<string>;
    collabRef: React.MutableRefObject<ReturnType<typeof useCollab>>;
    outputsRef: React.MutableRefObject<IOutput[]>;
    propagateDownstreamInputs: ReturnType<typeof useGraphEdits>["propagateDownstreamInputs"];
}) {
    const onConnect = useCallback(
        (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean) => {
            console.log(
                "onConnect triggered:",
                connection.source,
                connection.sourceHandle,
                connection.target,
                connection.targetHandle
            );
            markDirtyRef.current();

            const nodes = custom_nodes ? custom_nodes : reactFlow.getNodes();
            // `!== undefined`, not truthiness: loadParsedTrill passes an
            // accumulating array that legitimately starts empty, and `[]` is
            // truthy anyway — the old `custom_edges ? …` made every load-time
            // merge-handle resolution see an empty graph (dev/64).
            const edges = custom_edges !== undefined ? custom_edges : reactFlow.getEdges();
            const target = nodes.find(
                (node: any) => node.id === connection.target
            ) as Node;
            const sourceNode = nodes.find(
                (node: any) => node.id === connection.source
            ) as Node | undefined;

            // Projects saved before #186 was fixed contain provenance versions whose
            // edges name nodes that version does not hold. Clicking one replays those
            // edges through here with an empty node list, and the cycle checks below
            // dereference `target` - which is how a click in the provenance graph took
            // the whole canvas down with an uncaught TypeError (#195). React Flow
            // cannot render an edge with a missing endpoint anyway, so drop it.
            if (!target || !sourceNode) {
                console.warn(
                    `[FlowProvider] onConnect: dropping edge ${connection.source} -> ` +
                    `${connection.target}; endpoint not on the canvas`,
                );
                return;
            }
            const hasCycle = (node: Node, visited = new Set()) => {
                if (visited.has(node.id)) return false;

                visited.add(node.id);

                let checkEdges = edges.filter((edge: any) => {
                    return edge.sourceHandle;
                });

                for (const outgoer of getOutgoers(node, nodes, checkEdges)) {
                    if (outgoer.id === connection.source) return true;
                    if (hasCycle(outgoer, visited)) return true;
                }
            };

            // accept string, null, or undefined:
            const isInHandle = (h: string | null | undefined): boolean => !!h && h.startsWith("in") && h !== "in/out";
            const isInOutHandle = (h: string | null | undefined): boolean => h === "in/out";


            let validHandleCombination = true;

            if (
                (isInOutHandle(connection.sourceHandle) && !isInOutHandle(connection.targetHandle)) ||
                (isInOutHandle(connection.targetHandle) && !isInOutHandle(connection.sourceHandle))
            ) {
                validHandleCombination = false;
                showToast("An in/out connection can only be connected to another in/out connection", "warning");
            }
            else if (
                (isInHandle(connection.sourceHandle) && connection.targetHandle !== "out") ||
                (isInHandle(connection.targetHandle) && connection.sourceHandle !== "out")
            ) {
                validHandleCombination = false;
                showToast("An in connection can only be connected to an out connection", "warning");
            }
            else if (
                (connection.sourceHandle === "out" && !isInHandle(connection.targetHandle)) ||
                (connection.targetHandle === "out" && !isInHandle(connection.sourceHandle))
            ) {
                validHandleCombination = false;
                showToast("An out connection can only be connected to an in connection", "warning");
            }


            if (validHandleCombination) {
                // Check compatibility between inputs and outputs
                let inNodeType: NodeType | undefined = undefined;
                let outNodeType: NodeType | undefined = undefined;

                for (const elem of nodes) {
                    if (elem.id == connection.source) {
                        // Unversioned so NodeType enum comparisons (and the
                        // descriptor-proxy validator, which accepts both forms)
                        // work for `curio.builtin/...@1` dispatcher ids (dev/64).
                        outNodeType = getUnversionedFlowNodeType(elem) as NodeType;
                    }

                    if (elem.id == connection.target) {
                        inNodeType = getUnversionedFlowNodeType(elem) as NodeType;
                    }
                }

                // Edges reconstructed when loading a saved dataflow were already
                // validated when the user created them. Re-running the type check
                // here is wrong on load: the node-descriptor registry may not be
                // populated yet (package bootstrap is async), so
                // ``checkBoxCompatibility`` would return false and silently drop a
                // valid edge — and the toast would fire mid-render (setState on
                // ToastProvider during FlowProvider render). Trust persisted edges.
                let allowConnection = skipValidation
                    ? true
                    : ConnectionValidator.checkBoxCompatibility(outNodeType, inNodeType);

                if (!allowConnection) {
                    showToast("Input and output types of these boxes are not compatible", "warning");
                }

                // Resolve merge target handle before validation / applyOutput. Imported
                // trills set `in_0`/`in_1` explicitly; manual drags may omit it.
                let resolvedConnection: Connection = connection;
                if (inNodeType === NodeType.MERGE_FLOW && allowConnection) {
                    const availableHandles = Array(5).fill(1).map((_, i) => `in_${i}`);
                    const usedHandles = new Set(
                        edges
                            .filter((edge: Edge) =>
                                edge.target === connection.target &&
                                availableHandles.includes(edge.targetHandle as string)
                            )
                            .map((edge: Edge) => edge.targetHandle)
                    );

                    let targetHandle = connection.targetHandle;
                    if (!targetHandle || targetHandle === "in" || parseHandleIndex(targetHandle) < 0) {
                        const nextFree = availableHandles.find((h) => !usedHandles.has(h));
                        if (!nextFree) {
                            showToast(
                                "Connection limit reached. Merge nodes can only accept up to 5 input connections.",
                                "warning",
                            );
                            allowConnection = false;
                        } else {
                            targetHandle = nextFree;
                            resolvedConnection = { ...connection, targetHandle };
                        }
                    }

                    if (allowConnection) {
                        if (usedHandles.size >= availableHandles.length) {
                            showToast(
                                "Connection limit reached. Merge nodes can only accept up to 5 input connections.",
                                "warning",
                            );
                            allowConnection = false;
                        } else if (usedHandles.has(resolvedConnection.targetHandle)) {
                            showToast(
                                "This input already has a connection. Each input handle can only accept one connection.",
                                "warning",
                            );
                            allowConnection = false;
                        }
                    }
                }


                // dev/67-3 (DEC-051): one edge per rendered input handle —
                // the merge slot machinery above is the ONLY multi-edge
                // surface. Before this guard, a second edge into an occupied
                // handle silently overwrote `data.input` (last writer wins),
                // and deleting either edge blanked the input for both. The
                // load path only warns: persisted edges are surfaced, never
                // dropped.
                if (
                    allowConnection &&
                    inNodeType !== NodeType.MERGE_FLOW &&
                    isInHandle(connection.targetHandle)
                ) {
                    const handleOccupied = edges.some(
                        (edge: Edge) =>
                            edge.target === connection.target &&
                            (edge.targetHandle ?? "in") === (connection.targetHandle ?? "in"),
                    );
                    if (handleOccupied) {
                        if (skipValidation) {
                            console.warn(
                                `[FlowProvider] persisted multi-input edge into ` +
                                `${connection.target} (${connection.targetHandle}) — ` +
                                `only one input is honored at runtime; route flows ` +
                                `through a Merge node`,
                            );
                        } else {
                            showToast(
                                "This input already has a connection — route multiple flows through a Merge node.",
                                "warning",
                            );
                            allowConnection = false;
                        }
                    }
                }

                // Checking cycles
                if (target.id === connection.source) {
                    showToast("Cycles are not allowed in the dataflow", "warning");
                    allowConnection = false;
                }

                if (connection.sourceHandle != "in/out" && hasCycle(target)) {
                    showToast("Cycles are not allowed in the dataflow", "warning");
                    allowConnection = false;
                }

                if (allowConnection) {
                    const conn = inNodeType === NodeType.MERGE_FLOW ? resolvedConnection : connection;
                    markNodeStaleRef.current(conn.target as string);
                    applyOutput(
                        inNodeType as NodeType,
                        conn.target as string,
                        conn.source as string,
                        conn.sourceHandle as string,
                        conn.targetHandle as string
                    );

                    setEdges((eds) => {
                        let customConnection: any = {
                            ...conn,
                            markerEnd: { type: MarkerType.ArrowClosed },
                        };

                        // Ensure an id exists before storing in provenance — user-dragged
                        // connections arrive as Connection (no id); addEdge assigns one later
                        // but addNewVersionProvenance is called before that.
                        if (!customConnection.id) {
                            customConnection.id = `reactflow__edge-${conn.source}${conn.sourceHandle || ''}-${conn.target}${conn.targetHandle || ''}`;
                        }

                        if (customConnection.data == undefined)
                            customConnection.data = {};

                        if (
                            conn.sourceHandle == "in/out" &&
                            conn.targetHandle == "in/out"
                        ) {
                            customConnection.markerStart = {
                                type: MarkerType.ArrowClosed,
                            };
                            customConnection.type = EdgeType.BIDIRECTIONAL_EDGE;
                        } else {
                            customConnection.type = EdgeType.UNIDIRECTIONAL_EDGE;

                            if (provenance !== false) {
                                TrillGenerator.addNewVersionProvenance(
                                    reactFlow.getNodes(),
                                    [...reactFlow.getEdges(), customConnection],
                                    workflowNameRef.current, "", "Connection added"
                                );
                            }
                        }

                        collabRef.current.broadcastEdgeAdded({
                            edgeId: customConnection.id,
                            edge: customConnection,
                        });

                        const nextEdges = addEdge(customConnection, eds);
                        const sourceId = conn.source as string;
                        const cached = outputsRef.current.find((o) => o.nodeId === sourceId);
                        if (cached?.output != null && cached.output !== "") {
                            // Edge is in the graph now — fan out to all downstream nodes
                            // (merge slots, multiple pools) using the live edge list.
                            queueMicrotask(() => {
                                propagateDownstreamInputs(sourceId, cached.output);
                            });
                        }
                        return nextEdges;
                    });
                }
            }
        },
        [setEdges]
    );

    // Checking for cycles and invalid connections between types of boxes
    const isValidConnection = useCallback(
        (connection: Connection) => {
            return true;
        },
        [reactFlow.getNodes, reactFlow.getEdges]
    );

    return { onConnect, isValidConnection };
}
