// Collaboration, receive side: peers' node and edge changes, applied to this
// canvas.
import React, { useEffect } from "react";
import type { Edge, Node } from "reactflow";
import type { useCollab } from "../CollaborationProvider";
import { pythonInterpreter, jsInterpreter } from "../../hook/useCode";
import type { SelectionEchoOptions } from "../../utils/selectionEcho";
import type { IOutput, IPropagation } from "./flowTypes";

export function useCollaborationSync({
    collab, applyNewOutput, interactionsCallback, applyNewPropagation, setNodes, setEdges,
}: {
    collab: ReturnType<typeof useCollab>;
    applyNewOutput: (newOutput: IOutput) => void;
    interactionsCallback: (interactions: any, nodeId: string) => void;
    applyNewPropagation: (propagationObj: IPropagation) => void;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
}) {
    // -----------------------------------------------------------------
    // Collaboration: receive-side graph synchronization.
    //
    // Remote ``node_added`` / ``node_removed`` / ``edge_added`` /
    // ``edge_removed`` events are applied via ``setNodes`` / ``setEdges``
    // *directly* — not through the local ``addNode`` / ``onConnect`` /
    // ``onEdgesDelete`` / ``onNodesDelete`` handlers — so the apply path
    // doesn't re-broadcast and bounce the same change around the room.
    //
    // Non-serializable callbacks on ``node.data`` (outputCallback,
    // interactionsCallback, propagationCallback, interpreters) are
    // re-attached on the receive side because socket.io strips functions
    // during JSON serialisation. Without this, downstream behavior
    // adapters would call ``data.outputCallback(...)`` against undefined
    // (caught now by the defensive ``typeof`` guards in
    // ``adapters/node/*``, but never producing visible output).
    // -----------------------------------------------------------------
    useEffect(() => {
        if (!collab.enabled) return;
        const localOutputCallback = (nodeId: string, output: any, options?: SelectionEchoOptions) => {
            applyNewOutput({ nodeId, output, ...options });
        };
        const rebuildNodeData = (data: any) => ({
            ...data,
            outputCallback: localOutputCallback,
            interactionsCallback,
            propagationCallback: applyNewPropagation,
            pythonInterpreter,
            jsInterpreter,
        });

        const unsubs: Array<() => void> = [];

        unsubs.push(collab.onRemote("node_added", (payload: any) => {
            const remote = payload?.node;
            if (!remote || !remote.id) return;
            // ReactFlow throws inside ``createNodeInternals`` if a node
            // lands in its store without ``position``. Refuse the payload
            // rather than crash the whole canvas; log so the gap is
            // visible in the network panel.
            const pos = remote.position;
            if (!pos || typeof pos.x !== "number" || typeof pos.y !== "number") {
                console.warn(
                    "[collab] node_added rejected: missing/invalid position",
                    remote,
                );
                return;
            }
            setNodes((nds) => {
                if (nds.some((n) => n.id === remote.id)) return nds;
                return nds.concat({
                    ...remote,
                    data: rebuildNodeData(remote.data || {}),
                });
            });
        }));

        unsubs.push(collab.onRemote("node_removed", (payload: any) => {
            const id = payload?.nodeId;
            if (!id) return;
            setNodes((nds) => nds.filter((n) => n.id !== id));
            // Cascade-remove incident edges so the receiver matches the
            // sender's view (ReactFlow auto-cascades these on the sender
            // side via its internal node-delete flow).
            setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
        }));

        unsubs.push(collab.onRemote("edge_added", (payload: any) => {
            const remote = payload?.edge;
            if (!remote || !remote.id) return;
            setEdges((eds) => {
                if (eds.some((e) => e.id === remote.id)) return eds;
                return eds.concat(remote);
            });
        }));

        unsubs.push(collab.onRemote("edge_removed", (payload: any) => {
            const id = payload?.edgeId;
            if (!id) return;
            setEdges((eds) => eds.filter((e) => e.id !== id));
        }));

        // Apply remote node patches (currently just position drags). Routing
        // through ``setNodes`` does not re-fire ReactFlow's ``onNodesChange``
        // — that only dispatches on internal events — so the apply does not
        // bounce back as a new broadcast.
        unsubs.push(collab.onRemote("node_updated", (payload: any) => {
            const id = payload?.nodeId;
            const patch = payload?.patch;
            if (!id || !patch) return;
            setNodes((nds) =>
                nds.map((n) => {
                    if (n.id !== id) return n;
                    const next: any = { ...n };
                    if (patch.position && typeof patch.position.x === "number" &&
                        typeof patch.position.y === "number") {
                        next.position = { x: patch.position.x, y: patch.position.y };
                    }
                    if (patch.data && typeof patch.data === "object") {
                        // Preserve runtime callbacks attached on the
                        // receiver side — peers only ship serialisable
                        // data fields.
                        next.data = { ...n.data, ...patch.data };
                    }
                    return next;
                }),
            );
        }));

        return () => unsubs.forEach((u) => u());
    }, [collab.enabled, collab.onRemote, setNodes, setEdges, interactionsCallback]);
}
