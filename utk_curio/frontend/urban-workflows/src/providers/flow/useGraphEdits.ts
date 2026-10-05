// Editing the graph: a node's content, adding a node, deleting nodes and
// edges, and pushing a node's output to the nodes it feeds.
import React, { useCallback } from "react";
import type { Edge, Node, NodeChange, ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { TrillGenerator } from "../../TrillGenerator";
import {
    ensureSlotArrays,
    inputSlotOf,
    setSlot,
    slotsFedBy,
    wiredInputSlots,
    nodeInputFromSlots,
    compactedHandles,
    withoutSlot,
} from "../../utils/inputSlots";
import { renumberInputReferences } from "../../utils/references/codeReferences";
import type { useCollab } from "../CollaborationProvider";
import { normalizeFlowInput } from "../../utils/flowOutputRef";
import { markSelectionEcho, SelectionEchoOptions } from "../../utils/selectionEcho";
import type { IOutput } from "./flowTypes";
import { nodeGrowsInputs } from "./growingInputs";

/** A growing node's data with *value* from *sourceId* in each of *slots*. */
function withSlotValues(node: Node, slots: number[], value: unknown, sourceId: string, edges: any[]): Node {
    const { inputList, sourceList } = ensureSlotArrays(node.data.inputSlots, node.data.sourceSlots);
    for (const slot of slots) setSlot(inputList, sourceList, slot, value, sourceId);
    const wired = Array.from(new Set([...wiredInputSlots(edges, node.id), ...slots])).sort((a, b) => a - b);
    return {
        ...node,
        data: { ...node.data, inputSlots: inputList, sourceSlots: sourceList, input: nodeInputFromSlots(inputList, wired) },
    };
}

export function useGraphEdits({
    setNodes, setEdges, reactFlow, workflowNameRef, collabRef, outputsRef, markNodeStaleRef, setOutputs,
}: {
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
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

                if (nodeGrowsInputs(node)) {
                    // Every circle this source feeds; the node reads them as one
                    // value once every wired circle holds one.
                    const prior = ensureSlotArrays(node.data.inputSlots, node.data.sourceSlots).sourceList;
                    const slots = slotsFedBy(currentEdges, node.id, sourceId, prior);
                    return withSlotValues(node, slots, inputPayload, sourceId, currentEdges);
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

                if (nodeGrowsInputs(node)) {
                    // The edge is not in the graph yet: its circle counts as wired.
                    const slot = inputSlotOf(targetHandle);
                    return slot >= 0 ? withSlotValues(node, [slot], normalized, outId, reactFlow.getEdges()) : node;
                }

                return { ...node, data: { ...node.data, input: normalized, source: outId } };
            })
        );
    };

    /**
     * A growing node's circles close up after some of its edges were deleted:
     * each surviving edge moves up one circle per deleted circle above it, the
     * values move with it, and the node's code is rewritten so every input
     * chip still names the same input. Deleted inputs' chips become
     * `[!! input ? !!]`. Peers get the moved edges and the new code from here;
     * they never rewrite on their own, so the code changes once.
     */
    const closeUpCircles = (target: Node, deleted: Edge[], deletedIds: Set<string>) => {
        const removed = deleted
            .map((e) => inputSlotOf(e.targetHandle))
            .filter((s) => s >= 0)
            .sort((a, b) => b - a);
        if (removed.length === 0) return;
        const survivors = reactFlow.getEdges().filter((e) => !deletedIds.has(e.id));
        const moved = new Map<string, string>();
        const handles = new Map(
            survivors.filter((e) => e.target === target.id).map((e) => [e.id, e.targetHandle ?? "in"] as [string, string]),
        );
        for (const slot of removed) {
            const step = compactedHandles(
                Array.from(handles, ([id, targetHandle]) => ({ id, target: target.id, targetHandle })),
                target.id,
                slot,
            );
            step.forEach((handle, id) => {
                handles.set(id, handle);
                moved.set(id, handle);
            });
        }

        const code: string = typeof target.data?.code === "string" ? target.data.code : "";
        const rewritten = removed.reduce((text, slot) => renumberInputReferences(text, slot), code);
        let inputSlots: unknown[] = target.data?.inputSlots ?? [];
        let sourceSlots: unknown[] = target.data?.sourceSlots ?? [];
        for (const slot of removed) {
            inputSlots = withoutSlot(inputSlots, slot);
            sourceSlots = withoutSlot(sourceSlots, slot);
        }
        const wired = Array.from(new Set(Array.from(handles.values()).map(inputSlotOf).filter((s) => s >= 0)))
            .sort((a, b) => a - b);

        if (moved.size > 0) {
            setEdges((eds) => eds.map((e) => (moved.has(e.id) ? { ...e, targetHandle: moved.get(e.id) } : e)));
            for (const edge of survivors) {
                if (!moved.has(edge.id)) continue;
                collabRef.current.broadcastEdgeRemoved(edge.id);
                collabRef.current.broadcastEdgeAdded({ edgeId: edge.id, edge: { ...edge, targetHandle: moved.get(edge.id) } });
            }
        }
        setNodes((nds) =>
            nds.map((node) => {
                if (node.id !== target.id) return node;
                const data = { ...node.data, inputSlots, sourceSlots, input: nodeInputFromSlots(inputSlots, wired) };
                if (rewritten !== code) {
                    data.code = rewritten;
                    data.defaultCode = rewritten;
                }
                return { ...node, data };
            }),
        );
        if (rewritten !== code) {
            collabRef.current.broadcastNodeUpdated({
                nodeId: target.id,
                patch: { data: { code: rewritten, defaultCode: rewritten } },
            });
        }
    };

    const onEdgesDelete = useCallback(
        (connections: Edge[]) => {
            const deletedIds = new Set(connections.map((c) => c.id));
            const growing = new Map<string, Edge[]>();
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
                    if (nodeGrowsInputs(targetNode)) {
                        growing.set(connection.target, [...(growing.get(connection.target) ?? []), connection]);
                        continue;
                    }
                    setNodes((nds: any) =>
                        nds.map((node: any) =>
                            node.id !== resetInput ? node : { ...node, data: { ...node.data, input: "", source: "" } },
                        )
                    );
                }
            }
            growing.forEach((deleted, targetId) => {
                const target = reactFlow.getNode(targetId);
                if (target) closeUpCircles(target, deleted, deletedIds);
            });
        },
        [setNodes, setEdges]
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
