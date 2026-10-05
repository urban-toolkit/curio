// Interactions between linked nodes, and propagations between Data Pools.
import React, { useCallback, useEffect } from "react";
import type { Edge, Node, ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import type { IInteraction, IPropagation } from "./flowTypes";

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

    return { applyNewPropagation, interactionsCallback };
}
