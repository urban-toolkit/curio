// Connecting two nodes: onConnect checks the handles, the node types, input
// circles, occupied inputs and cycles, then adds the edge.
import React, { useCallback } from "react";
import { Connection, Edge, Node, ReactFlowInstance, addEdge, getOutgoers, MarkerType } from "reactflow";
import { ConnectionValidator } from "../../ConnectionValidator";
import { NodeType, EdgeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { TrillGenerator } from "../../TrillGenerator";
import { inputSlotOf, slotHandleId, wiredInputSlots } from "../../utils/inputSlots";
import type { useToastContext } from "../ToastProvider";
import type { useCollab } from "../CollaborationProvider";
import type { IOutput } from "./flowTypes";
import type { useGraphEdits } from "./useGraphEdits";
import { nodeGrowsInputs, nodeInputCapacity } from "./growingInputs";

/** *base*, or *base* with a suffix when an edge already has that id. */
function uniqueEdgeId(base: string, edges: Edge[]): string {
    let id = base;
    for (let n = 2; edges.some((e) => e.id === id); n += 1) id = `${base}-${n}`;
    return id;
}

export function useConnect({
    markDirtyRef, reactFlow, showToast, markNodeStaleRef, applyOutput, setEdges,
    workflowNameRef, collabRef, outputsRef,
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
}) {
    // A new edge hands what its source holds to its own target alone, once:
    // the nodes the source already feeds get nothing.
    //
    // *sourceAddedByLoad*: a saved edge that `loadParsedTrill` replays, from a
    // node that load added. Any output that node holds is one the load
    // restored, and `hydrateRestoredOutputs` passes it down, so the edge does
    // not hand it over too.
    const onConnect = useCallback(
        (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean, sourceAddedByLoad?: boolean) => {
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
            // input circle resolution see an empty graph (dev/64).
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

                let resolvedConnection: Connection = connection;

                // A node that grows its circles takes the edge on a free
                // circle: the one it was dropped on, or else the free circle
                // at the bottom, up to the template's maximum. A saved edge
                // keeps the circle it names.
                const growing = nodeGrowsInputs(target);
                if (allowConnection && growing && isInHandle(connection.targetHandle ?? "in")) {
                    const wired = wiredInputSlots(edges, connection.target as string);
                    const requested = inputSlotOf(connection.targetHandle);
                    const bottom = wired.length > 0 ? wired[wired.length - 1] + 1 : 0;
                    const slot = skipValidation || (requested >= 0 && requested <= bottom && !wired.includes(requested))
                        ? requested
                        : bottom;
                    const capacity = nodeInputCapacity(target);
                    if (!skipValidation && (slot < 0 || slot >= capacity)) {
                        showToast(`This node takes at most ${capacity} input${capacity === 1 ? "" : "s"}.`, "warning");
                        allowConnection = false;
                    } else {
                        resolvedConnection = { ...connection, targetHandle: slotHandleId(Math.max(slot, 0)) };
                    }
                }

                // dev/67-3 (DEC-051): one edge per rendered input handle.
                // Before this guard, a second edge into an occupied handle
                // silently overwrote `data.input` (last writer wins), and
                // deleting either edge blanked the input for both. The load
                // path only warns: persisted edges are surfaced, never
                // dropped.
                if (
                    allowConnection &&
                    !growing &&
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
                                `[FlowProvider] persisted second edge into ` +
                                `${connection.target} (${connection.targetHandle}): ` +
                                `only one input is honored at runtime`,
                            );
                        } else {
                            showToast(
                                "This input already has a connection. The node takes one input here.",
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
                    const conn = growing ? resolvedConnection : connection;
                    const sourceId = conn.source as string;
                    // A restored output reaches the target from
                    // hydrateRestoredOutputs alone, its circle or port included.
                    // A source with nothing to give still sets up the target's
                    // circle or port here, as any new edge does.
                    const held = outputsRef.current.find((o) => o.nodeId === sourceId)?.output;
                    const restoredByLoad = !!sourceAddedByLoad && held != null && held !== "";
                    markNodeStaleRef.current(conn.target as string);
                    if (!restoredByLoad) {
                        applyOutput(
                            inNodeType as NodeType,
                            conn.target as string,
                            sourceId,
                            conn.sourceHandle as string,
                            conn.targetHandle as string,
                            edges,
                        );
                    }

                    setEdges((eds) => {
                        let customConnection: any = {
                            ...conn,
                            markerEnd: { type: MarkerType.ArrowClosed },
                        };

                        // Ensure an id exists before storing in provenance — user-dragged
                        // connections arrive as Connection (no id); addEdge assigns one later
                        // but addNewVersionProvenance is called before that.
                        // Unique, because closing up circles keeps an edge's
                        // id while its handle changes, so the id built from
                        // the handles can already be taken.
                        if (!customConnection.id) {
                            customConnection.id = uniqueEdgeId(
                                `reactflow__edge-${conn.source}${conn.sourceHandle || ''}-${conn.target}${conn.targetHandle || ''}`,
                                eds,
                            );
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

                        return addEdge(customConnection, eds);
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
