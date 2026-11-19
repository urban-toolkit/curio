// Interactions between linked nodes, and propagations between Data Pools.
import React, { useCallback, useEffect, useRef } from "react";
import type { Edge, Node, ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { isInteractionEdge } from "../../contracts/interactionEdges";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { isActiveSelect } from "../../utils/selectionMatch";
import type { IInteraction, IPropagation } from "./flowTypes";
import {
    deliveriesOver, interactionRoutes, routesOfEdge, sameDelivery, type InteractionRoute,
} from "./interactionRoutes";

/** Whether *interaction* holds a selection that picks something. */
function holdsSelection(interaction: IInteraction | undefined): boolean {
    return Object.values(interaction?.details ?? {}).some((detail: any) => isActiveSelect(detail));
}

/** The routes among *routes* out of *sender* into *receiver*. */
function routesBetween(routes: Iterable<InteractionRoute>, sender: string, receiver: string): InteractionRoute[] {
    return [...routes].filter((route) => route.from === sender && route.to === receiver);
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

        let toSend: Record<string, IInteraction[]> = {};
        let interactedIds: string[] = newInteractions.map(
            (interaction: IInteraction) => {
                return interaction.nodeId;
            }
        );
        let poolsIds: string[] = [];

        // Each selection goes out with the node it came from, so a pool's echo
        // can say whose it is (utils/selectionEcho).
        const detailsOf = new Map<string, unknown>();
        for (const interaction of newInteractions) {
            detailsOf.set(interaction.nodeId, interaction.details);
        }

        for (let i = 0; i < nodes.length; i++) {
            if (getUnversionedFlowNodeType(nodes[i]) == NodeType.DATA_POOL) {
                poolsIds.push(nodes[i].id);
            }
        }

        // What a route carries of its sender's selection (providers/flow/
        // interactionRoutes): every view's selects out of a node's own handle,
        // one view's out of that view's, to the view a view's handle names or
        // the whole node. A node gets each once, however many interaction
        // edges join the two.
        // A route that carries nothing leaves its receiver as it was.
        const send = (route: InteractionRoute) => {
            for (const delivery of deliveriesOver(route.from, detailsOf.get(route.from), [route])) {
                const list = toSend[route.to] ?? (toSend[route.to] = []);
                if (!list.some((held) => sameDelivery(held, delivery))) list.push(delivery);
            }
        };

        for (let i = 0; i < edges.length; i++) {
            let targetNode = reactFlow.getNode(edges[i].target) as Node;
            let sourceNode = reactFlow.getNode(edges[i].source) as Node;

                if (
                    isInteractionEdge(edges[i]) &&
                    !(
                        getUnversionedFlowNodeType(targetNode) == NodeType.DATA_POOL &&
                        getUnversionedFlowNodeType(sourceNode) == NodeType.DATA_POOL
                    )
                ) {
                const [forward, backward] = routesOfEdge(edges[i]);
                const sourcePool = poolsIds.includes(edges[i].source);
                const targetPool = poolsIds.includes(edges[i].target);
                const sourceInteracted = interactedIds.includes(edges[i].source);
                const targetInteracted = interactedIds.includes(edges[i].target);

                if (sourceInteracted && targetPool) {
                    // then the target is the pool
                    send(forward);
                } else if (targetInteracted && sourcePool) {
                    // then the source is the pool
                    send(backward);
                } else if (!sourcePool && !targetPool) {
                    // Direct interaction edge between two non-pool nodes
                    // (e.g. AutkMap ↔ AutkPlot linked brushing).
                    if (sourceInteracted) send(forward);
                    if (targetInteracted) send(backward);
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
                    isInteractionEdge(edge) &&
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
    // from a collaborator or an agent. Each edge is two routes, one each way,
    // out of a node's own handle or a view's and into one
    // (providers/flow/interactionRoutes). A route that goes takes back from
    // its receiver what its sender delivered over it, unless a route left
    // between the two still carries it; a new route hands its receiver what
    // the sender's latest selection gives it over every route between them,
    // by the routing rules above: a pool takes a chart's selection, two views
    // take each other's, and two pools exchange none. A new route that gives
    // nothing the receiver does not hold already hands nothing over.
    const routesRef = useRef(new Map<string, InteractionRoute>());
    const interactionsRef = useRef(interactions);
    interactionsRef.current = interactions;
    useEffect(() => {
        const routes = interactionRoutes(edges);
        const before = routesRef.current;
        routesRef.current = routes;
        const removed = [...before].filter(([key]) => !routes.has(key)).map(([, route]) => route);
        const added = [...routes].filter(([key]) => !before.has(key)).map(([, route]) => route);
        if (removed.length === 0 && added.length === 0) return;

        const latest = new Map(interactionsRef.current.map((interaction) => [interaction.nodeId, interaction]));
        // What *sender*'s latest selection gives *receiver* over the routes between them now.
        const carried = (sender: string, receiver: string) =>
            deliveriesOver(sender, latest.get(sender)?.details, routesBetween(routes.values(), sender, receiver));

        // By receiver, then sender: what the routes left between the two still carry.
        const takeBack = new Map<string, Map<string, IInteraction[]>>();
        for (const { from, to } of removed) {
            const bySender = takeBack.get(to) ?? new Map<string, IInteraction[]>();
            bySender.set(from, carried(from, to));
            takeBack.set(to, bySender);
        }

        const isPool = (id: string) => {
            const node = reactFlow.getNode(id);
            return node != null && getUnversionedFlowNodeType(node) == NodeType.DATA_POOL;
        };
        const deliver = new Map<string, IInteraction[]>();
        for (const { from, to } of added) {
            if (isPool(from) || !holdsSelection(latest.get(from))) continue;
            const given = carried(from, to);
            if (given.length > 0) deliver.set(to, given);
        }
        if (takeBack.size === 0 && deliver.size === 0) return;

        setNodes((nds: any) =>
            nds.map((node: any) => {
                const held: IInteraction[] = Array.isArray(node.data?.interactions) ? node.data.interactions : [];
                const given = deliver.get(node.id);
                if (given && !given.every((delivery) => held.some((entry) => sameDelivery(entry, delivery)))) {
                    return { ...node, data: { ...node.data, interactions: given } };
                }
                const gone = takeBack.get(node.id);
                if (!gone) return node;
                const kept = held.filter((entry) => {
                    const still = gone.get(entry?.nodeId);
                    return still === undefined || still.some((delivery) => sameDelivery(delivery, entry));
                });
                if (kept.length === held.length) return node;
                return { ...node, data: { ...node.data, interactions: kept } };
            })
        );
    }, [edges]);

    return { applyNewPropagation, interactionsCallback };
}
