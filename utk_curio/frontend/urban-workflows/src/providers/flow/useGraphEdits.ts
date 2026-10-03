// Editing the graph: a node's content, adding a node, deleting nodes and
// edges, and pushing a node's output to the nodes it feeds.
import React, { useCallback } from "react";
import type { Edge, Node, NodeChange, ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { TrillGenerator } from "../../TrillGenerator";
import {
    ensureMergeArrays,
    parseHandleIndex,
    setMergeSlot,
    clearMergeSlot,
    mergeSlotsForSource,
} from "../../utils/mergeFlowUtils";
import type { useCollab } from "../CollaborationProvider";
import { normalizeFlowInput } from "../../utils/flowOutputRef";
import { markSelectionEcho, SelectionEchoOptions } from "../../utils/selectionEcho";
import type { IOutput } from "./flowTypes";

export function useGraphEdits({
    setNodes, reactFlow, workflowNameRef, collabRef, outputsRef, markNodeStaleRef, setOutputs,
}: {
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    reactFlow: ReactFlowInstance;
    workflowNameRef: React.MutableRefObject<string>;
    collabRef: React.MutableRefObject<ReturnType<typeof useCollab>>;
    outputsRef: React.MutableRefObject<IOutput[]>;
    markNodeStaleRef: React.MutableRefObject<(nodeId: string) => void>;
    setOutputs: (fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => void;
}) {
    // The bridge's content path (dev/51): both fields, one provider-state
    // update — ``defaultCode`` drives the Monaco editor's value and ``code``
    // is what TrillGenerator serializes on save.
    const applyNodeContent = useCallback(
        (nodeId: string, content: string) => {
            setNodes((nds: Node[]) =>
                nds.map((n) =>
                    n.id === nodeId
                        ? { ...n, data: { ...n.data, code: content, defaultCode: content } }
                        : n,
                ),
            );
        },
        [setNodes],
    );

    const addNode = useCallback(
        (node: Node, customWorkflowName?: string, provenance?: boolean) => {
            console.log("add node");
            setNodes((prev: any) => prev.concat(node));

            if (provenance) {
                TrillGenerator.addNewVersionProvenance(
                    [...reactFlow.getNodes(), node],
                    reactFlow.getEdges(),
                    workflowNameRef.current, "", "Node added"
                );
            }

            // socket.io-client serialises the payload as JSON, which silently
            // drops the runtime callbacks on ``data`` (outputCallback,
            // interpreters, …). That's intentional — the receiver re-attaches
            // its own local callbacks in the remote-graph handler. Position
            // and other ReactFlow-required fields MUST be included though;
            // omitting ``position`` makes the receiver throw inside
            // ``createNodeInternals`` when it walks the nodes array.
            collabRef.current.broadcastNodeAdded({
                nodeId: node.id,
                node: {
                    id: node.id,
                    type: node.type,
                    position: node.position,
                    sourcePosition: node.sourcePosition,
                    targetPosition: node.targetPosition,
                    width: node.width,
                    height: node.height,
                    data: node.data,
                },
            });
        },
        [setNodes]
    );

    /**
     * Push a source node's cached output to every direct downstream consumer.
     *
     * *edgesOverride* names the graph to read instead of React Flow's store.
     * The store is written from an effect, so right after a load it is still a
     * render behind and reports no edges at all; a restore that read it then
     * silently reached nobody. On the canvas that showed up as nodes waiting for
     * a Play, which hid it. The dashboard has no Play, so the caller passes the
     * edges the load just built.
     */
    const propagateDownstreamInputs = (
        sourceId: string,
        rawOutput: unknown,
        edgesOverride?: readonly { source?: unknown; target?: unknown; sourceHandle?: unknown; targetHandle?: unknown }[],
        options?: SelectionEchoOptions,
    ) => {
        const currentEdges = (edgesOverride ?? reactFlow.getEdges()) as any[];
        const nodesAffected: string[] = [];
        for (const edge of currentEdges) {
            if (edge.sourceHandle == "in/out" && edge.targetHandle == "in/out") continue;
            if (sourceId == edge.source) {
                nodesAffected.push(edge.target);
            }
        }
        if (!nodesAffected.length) return;

        const normalized = normalizeFlowInput(rawOutput);
        const inputPayload = normalized === "" ? "" : normalized;
        // Tag this delivery, not the output: normalizeFlowInput returns a fresh
        // object, so the cached output a later connection reads stays untagged
        // and draws like any new input.
        if (options?.selectionEcho && inputPayload !== "") markSelectionEcho(inputPayload, options.selectionSource);

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (!nodesAffected.includes(node.id)) return node;

                if (getUnversionedFlowNodeType(node) == NodeType.MERGE_FLOW) {
                    const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                    // Fill EVERY slot this source feeds — one source can be wired
                    // to multiple slots of the same merge node.
                    const sourceIndices = mergeSlotsForSource(
                        currentEdges,
                        node.id,
                        sourceId,
                        sourceList,
                    );
                    for (const sourceIndex of sourceIndices) {
                        setMergeSlot(inputList, sourceList, sourceIndex, inputPayload, sourceId);
                    }
                    return { ...node, data: { ...node.data, input: inputList, source: sourceList } };
                }

                if (inputPayload === "") {
                    return { ...node, data: { ...node.data, input: "", source: "" } };
                }
                return { ...node, data: { ...node.data, input: inputPayload, source: sourceId } };
            })
        );
    };

    // updates a single box with the new input (new connections)
    const applyOutput = (
        inNodeType: NodeType,
        inId: string,
        outId: string,
        sourceHandle: string,
        targetHandle: string
    ) => {
        if (sourceHandle == "in/out" && targetHandle == "in/out") return;

        // Why: previously this read `outputs` via a side effect inside a
        // setOutputs reducer. React Flow's setNodes (zustand) flushes its
        // reducer immediately, but React's useState setOutputs queues its
        // reducer for later — so setNodes ran first with `output = ""` and
        // wrote an empty data.input, then setOutputs ran and mutated
        // `output` after no one was reading it. Read synchronously from
        // outputsRef instead.
        const entry = outputsRef.current.find((opt: any) => opt.nodeId === outId);
        const raw = entry?.output;
        const normalized =
            raw != null && raw !== "" ? normalizeFlowInput(raw) : "";

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (node.id !== inId) return node;

                if (inNodeType == NodeType.MERGE_FLOW) {
                    const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                    const handleIndex = parseHandleIndex(targetHandle);
                    if (handleIndex >= 0) {
                        setMergeSlot(inputList, sourceList, handleIndex, normalized, outId);
                    }
                    return { ...node, data: { ...node.data, input: inputList, source: sourceList } };
                }

                return { ...node, data: { ...node.data, input: normalized, source: outId } };
            })
        );
    };

    const onEdgesDelete = useCallback(
        (connections: Edge[]) => {
            for (const connection of connections) {
                collabRef.current.broadcastEdgeRemoved(connection.id);
                const resetInput = connection.target;
                const targetNode = reactFlow.getNode(connection.target) as Node;
                markNodeStaleRef.current(connection.target);

                // skiping syncronized connections
                if (
                    connection.sourceHandle != "in/out" &&
                    connection.targetHandle != "in/out"
                ) {
                    TrillGenerator.addNewVersionProvenance(
                        reactFlow.getNodes(),
                        reactFlow.getEdges().filter((e: Edge) => e.id !== connection.id),
                        workflowNameRef.current, "", "Connection deleted"
                    );
                }

                // skiping syncronized connections
                if (
                    connection.sourceHandle != "in/out" ||
                    connection.targetHandle != "in/out"
                ) {
                    setNodes((nds: any) =>
                        nds.map((node: any) => {
                            if (node.id !== resetInput) return node;

                            if (getUnversionedFlowNodeType(targetNode) === NodeType.MERGE_FLOW) {
                                const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                                const handleIndex = parseHandleIndex(connection.targetHandle);
                                if (handleIndex >= 0) {
                                    clearMergeSlot(inputList, sourceList, handleIndex);
                                }
                                return { ...node, data: { ...node.data, input: inputList, source: sourceList } };
                            }

                            return { ...node, data: { ...node.data, input: "", source: "" } };
                        })
                    );
                }
            }
        },
        [setNodes]
    );

    const onNodesDelete = useCallback(
        (changes: NodeChange[]) => {
            setOutputs((opts: any) =>
                opts.filter((opt: any) => {
                    for (const change of changes) {
                        if (change.type === "remove" && 'id' in change) {
                            if (opt.nodeId === change.id) {
                                // node was removed
                                return false;
                            }
                        }
                    }
                    return true;
                })
            );

            for (const change of changes) {
                if (change.type === "remove" && 'id' in change) {
                    const node = reactFlow.getNode(change.id) as Node;
                    if (node) {
                        TrillGenerator.addNewVersionProvenance(
                            reactFlow.getNodes().filter((n: Node) => n.id !== change.id),
                            reactFlow.getEdges(),
                            workflowNameRef.current, "", "Node deleted"
                        );
                    }
                    collabRef.current.broadcastNodeRemoved(change.id);
                }
            }
        },
        [setOutputs, reactFlow]
    );

    return { applyNodeContent, addNode, propagateDownstreamInputs, applyOutput, onEdgesDelete, onNodesDelete };
}
