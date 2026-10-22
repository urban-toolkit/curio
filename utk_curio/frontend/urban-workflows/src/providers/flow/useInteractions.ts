// Interactions between linked nodes, and propagations between Data Pools.
import React, { useCallback, useEffect, useRef } from "react";
import type { Edge, Node, ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { isActiveSelect } from "../../utils/selectionMatch";
import type { IInteraction, IPropagation } from "./flowTypes";

type Link = { source: string; target: string };

/** The interaction edges among *edges*, by id: those whose both handles are `in/out`. */
function interactionLinks(edges: Edge[]): Map<string, Link> {
    const links = new Map<string, Link>();
    for (const edge of edges) {
        if (edge.sourceHandle == "in/out" && edge.targetHandle == "in/out") {
            links.set(edge.id, { source: edge.source, target: edge.target });
        }
    }
    return links;
}

/** Whether *interaction* holds a selection that picks something. */
function holdsSelection(interaction: IInteraction | undefined): boolean {
    return Object.values(interaction?.details ?? {}).some((detail: any) => isActiveSelect(detail));
}

export function useInteractions({
    interactions, setInteractions, nodes, edges, reactFlow, setNodes,
}: {
    interactions: IInteraction[];
    setInteractions: React.Dispatch<React.SetStateAction<IInteraction[]>>;
    nodes: Node[];
    edges: Edge[];
    reactFlow: ReactFlowInstance;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
}) {
    // Every node records its selections through this one callback, whether
    // it was built here or received from a collaborator: the node that
    // changed gets priority 1, every other node's latest selection 0.
    const interactionsCallback = useCallback((details: any, nodeId: string) => {
        setInteractions((prevInteractions: IInteraction[]) => {
            let newInteractions: IInteraction[] = [];
            let newNode = true;

            for(const interaction of prevInteractions){
                if(interaction.nodeId == nodeId){
                    newInteractions.push({nodeId: nodeId, details: details, priority: 1});
                    newNode = false;
                }else{
                    newInteractions.push({...interaction, priority: 0});
                }
            }

            if(newNode)
                newInteractions.push({nodeId: nodeId, details: details, priority: 1});

            return newInteractions;
        });
    }, [setInteractions]);

    // responsible for flow of already connected nodes
    const applyNewInteractions = useCallback(() => {
        let newInteractions = interactions.filter((interaction) => {
            return interaction.priority == 1;
        }); //priority == 1 means that this is a new or updated interaction

        let toSend: any = {}; // {nodeId -> {type: VisInteractionType, data: any}}
        let interactedIds: string[] = newInteractions.map(
            (interaction: IInteraction) => {
                return interaction.nodeId;
            }
        );
        let poolsIds: string[] = [];

        let interactionDict: any = {};

        // Each selection goes out with the node it came from, so a pool's echo
        // can say whose it is (utils/selectionEcho).
        for (const interaction of newInteractions) {
            interactionDict[interaction.nodeId] = {
                nodeId: interaction.nodeId,
                details: interaction.details,
                priority: interaction.priority,
            };
        }

        for (let i = 0; i < nodes.length; i++) {
            if (getUnversionedFlowNodeType(nodes[i]) == NodeType.DATA_POOL) {
                poolsIds.push(nodes[i].id);
            }
        }

        for (let i = 0; i < edges.length; i++) {
            let targetNode = reactFlow.getNode(edges[i].target) as Node;
            let sourceNode = reactFlow.getNode(edges[i].source) as Node;

                if (
                    edges[i].sourceHandle == "in/out" &&
                    edges[i].targetHandle == "in/out" &&
                    !(
                        getUnversionedFlowNodeType(targetNode) == NodeType.DATA_POOL &&
                        getUnversionedFlowNodeType(sourceNode) == NodeType.DATA_POOL
                    )
                ) {
                const sourcePool = poolsIds.includes(edges[i].source);
                const targetPool = poolsIds.includes(edges[i].target);
                const sourceInteracted = interactedIds.includes(edges[i].source);
                const targetInteracted = interactedIds.includes(edges[i].target);

                if (sourceInteracted && targetPool) {
                    // then the target is the pool

                    if (toSend[edges[i].target] == undefined) {
                        toSend[edges[i].target] = [
                            interactionDict[edges[i].source],
                        ];
                    } else {
                        toSend[edges[i].target].push(
                            interactionDict[edges[i].source]
                        );
                    }
                } else if (targetInteracted && sourcePool) {
                    // then the source is the pool
                    if (toSend[edges[i].source] == undefined) {
                        toSend[edges[i].source] = [
                            interactionDict[edges[i].target],
                        ];
                    } else {
                        toSend[edges[i].source].push(
                            interactionDict[edges[i].target]
                        );
                    }
                } else if (!sourcePool && !targetPool) {
                    // Direct interaction edge between two non-pool nodes
                    // (e.g. AutkMap ↔ AutkPlot linked brushing).
                    if (sourceInteracted) {
                        if (toSend[edges[i].target] == undefined) {
                            toSend[edges[i].target] = [
                                interactionDict[edges[i].source],
                            ];
                        } else {
                            toSend[edges[i].target].push(
                                interactionDict[edges[i].source]
                            );
                        }
                    }
                    if (targetInteracted) {
                        if (toSend[edges[i].source] == undefined) {
                            toSend[edges[i].source] = [
                                interactionDict[edges[i].target],
                            ];
                        } else {
                            toSend[edges[i].source].push(
                                interactionDict[edges[i].target]
                            );
                        }
                    }
                }
            }
        }

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (toSend[node.id] != undefined) {
                    return { ...node, data: { ...node.data, interactions: toSend[node.id] } };
                }
                return node;
            })
        );
    }, [interactions]);

    // propagations only happen with in/out
    const applyNewPropagation = useCallback((propagationObj: IPropagation) => {
        let sendTo: string[] = [];

        let edges = reactFlow.getEdges();

        for (const edge of edges) {
            if (
                edge.target == propagationObj.nodeId ||
                edge.source == propagationObj.nodeId
            ) {
                // if one of the endpoints of the edge is responsible for the propagation
                let targetNode = reactFlow.getNode(edge.target) as Node;
                let sourceNode = reactFlow.getNode(edge.source) as Node;

                if (
                    edge.sourceHandle == "in/out" &&
                    edge.targetHandle == "in/out" &&
                    getUnversionedFlowNodeType(targetNode) == NodeType.DATA_POOL &&
                    getUnversionedFlowNodeType(sourceNode) == NodeType.DATA_POOL
                ) {
                    if (edge.target != propagationObj.nodeId) {
                        sendTo.push(edge.target);
                    }

                    if (edge.source != propagationObj.nodeId) {
                        sendTo.push(edge.source);
                    }
                }
            }
        }

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (sendTo.includes(node.id)) {
                    const newPropagation = node.data.newPropagation != undefined
                        ? !node.data.newPropagation
                        : true;
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            propagation: { ...propagationObj.propagation },
                            newPropagation,
                        },
                    };
                }
                return { ...node, data: { ...node.data, propagation: undefined } };
            })
        );
    }, []);

    useEffect(() => {
        applyNewInteractions();
    }, [interactions]);

    // A selection follows the interaction edges as they change, however they
    // change: drawn, deleted with a node, opened with a dataflow, or received
    // from a collaborator or an agent. An edge that goes takes back from each
    // end what the other end delivered, and a new edge hands each end the
    // selection the other end already holds, by the routing rules above: a
    // pool takes a chart's selection, two views take each other's, and two
    // pools exchange none.
    const linksRef = useRef(new Map<string, Link>());
    const interactionsRef = useRef(interactions);
    interactionsRef.current = interactions;
    useEffect(() => {
        const links = interactionLinks(edges);
        const before = linksRef.current;
        linksRef.current = links;
        const removed = [...before].filter(([id]) => !links.has(id)).map(([, link]) => link);
        const added = [...links].filter(([id]) => !before.has(id)).map(([, link]) => link);
        if (removed.length === 0 && added.length === 0) return;

        const takeBack = new Map<string, Set<string>>();
        const giveUp = (holder: string, sender: string) =>
            takeBack.set(holder, new Set([...(takeBack.get(holder) ?? []), sender]));
        for (const { source, target } of removed) {
            giveUp(target, source);
            giveUp(source, target);
        }

        const latest = new Map(interactionsRef.current.map((interaction) => [interaction.nodeId, interaction]));
        const deliver = new Map<string, IInteraction>();
        const hand = (sender: string, receiver: string) => {
            const selection = latest.get(sender);
            if (holdsSelection(selection)) {
                deliver.set(receiver, { nodeId: sender, details: selection!.details, priority: 1 });
            }
        };
        const isPool = (id: string) => {
            const node = reactFlow.getNode(id);
            return node != null && getUnversionedFlowNodeType(node) == NodeType.DATA_POOL;
        };
        for (const { source, target } of added) {
            const sourcePool = isPool(source);
            const targetPool = isPool(target);
            if (!sourcePool) hand(source, target);
            if (!targetPool) hand(target, source);
        }
        if (takeBack.size === 0 && deliver.size === 0) return;

        setNodes((nds: any) =>
            nds.map((node: any) => {
                const given = deliver.get(node.id);
                if (given) return { ...node, data: { ...node.data, interactions: [given] } };
                const gone = takeBack.get(node.id);
                const held: IInteraction[] = Array.isArray(node.data?.interactions) ? node.data.interactions : [];
                if (!gone || !held.some((entry) => gone.has(entry?.nodeId))) return node;
                return { ...node, data: { ...node.data, interactions: held.filter((entry) => !gone.has(entry?.nodeId)) } };
            })
        );
    }, [edges]);

    return { applyNewPropagation, interactionsCallback };
}
