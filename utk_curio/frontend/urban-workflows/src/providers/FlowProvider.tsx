import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useRef,
    useEffect,
    useMemo,
} from "react";
import {
    Connection,
    Edge,
    EdgeChange,
    Node,
    NodeChange,
    addEdge,
    useNodesState,
    useEdgesState,
    useReactFlow,
    getOutgoers,
    MarkerType,
    NodeRemoveChange,
} from "reactflow";
import { ConnectionValidator } from "../ConnectionValidator";
import { BoxType, EdgeType } from "../constants";
import { useProvenanceContext } from "./ProvenanceProvider";
import { TrillGenerator } from "../TrillGenerator";
import { applyDashboardLayout } from "../utils/dashboardLayout";
import { ensureMergeArrays, parseHandleIndex, setMergeSlot, clearMergeSlot } from "../utils/mergeFlowUtils";
import { useWorkflowOperations } from "../hook/useWorkflowOperations";
import { EventInterceptor } from "../logging/EventInterceptor";
import { SnapshotManager } from "logging/SnapshotManager";
import { EventBuffer } from "logging/EventBuffer";
import { nodeCodeRegistry } from "../hook/useBoxState";

export interface IOutput {
    nodeId: string;
    output: string;
}

export interface IInteraction {
    nodeId: string;
    details: any;
    priority: number;
}

export interface IPropagation {
    nodeId: string;
    propagation: any;
}

interface FlowContextProps {
    nodes: Node[];
    edges: Edge[];
    setOutputs: (updateFn: (outputs: IOutput[]) => IOutput[]) => void;
    setInteractions: (updateFn: (interactions: IInteraction[]) => IInteraction[]) => void;
    applyNewPropagation: (propagation: IPropagation) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean) => void;
    isValidConnection: (connection: Connection) => boolean;
    onEdgesDelete: (connections: Edge[]) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    setDashBoardMode: (value: boolean) => void;
    updatePositionWorkflow: (nodeId: string, position: any) => void;
    updatePositionDashboard: (nodeId: string, position: any) => void;
    applyNewOutput: (output: IOutput) => void;

    dashboardPins: { [key: string]: boolean };
    workflowNameRef: React.MutableRefObject<string>;
    setWorkflowName: (name: string) => void;
    allMinimized: number;
    setAllMinimized: (value: number) => void;
    expandStatus: 'expanded' | 'minimized';
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    suggestionsLeft: number;
    workflowGoal: string;
    setWorkflowGoal: (goal: string) => void;
    loading: boolean;

    applyRemoveChanges: (changes: NodeRemoveChange[]) => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateWarnings: (trill_spec: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    updateSubtasks: (trill: any) => void;
    cleanCanvas: () => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    updateKeywords: (trill: any) => void;
    restoreGraph: (nodes: Node[], edges: Edge[]) => void;

    getGraphState: () => { nodes: Node[]; edges: Edge[] };
}

export const FlowContext = createContext<FlowContextProps>({
    nodes: [],
    edges: [],
    setOutputs: () => { },
    setInteractions: () => { },
    applyNewPropagation: () => { },
    addNode: () => { },
    onNodesChange: () => { },
    onEdgesChange: () => { },
    onConnect: () => { },
    isValidConnection: () => true,
    onEdgesDelete: () => { },
    onNodesDelete: () => { },
    setPinForDashboard: () => { },
    setDashBoardMode: () => { },
    updatePositionWorkflow: () => { },
    updatePositionDashboard: () => { },
    applyNewOutput: () => { },

    dashboardPins: {},
    workflowNameRef: { current: "" },
    loading: false,
    suggestionsLeft: 0,
    workflowGoal: "",
    allMinimized: 0,
    expandStatus: 'expanded',
    setWorkflowGoal: () => {},

    applyRemoveChanges: () => { },
    setWorkflowName: () => { },
    setAllMinimized: () => { },
    setExpandStatus: () => { },
    eraseWorkflowSuggestions: () => {},
    updateDataNode: () => {},
    flagBasedOnKeyword: () => {},
    updateSubtasks: () => {},
    updateKeywords: () => {},
    updateDefaultCode: () => {},
    updateWarnings: () => {},
    cleanCanvas: () => {},
    acceptSuggestion: () => {},
    restoreGraph: () => { },

    getGraphState: () => ({ nodes: [], edges: [] }),
});

const FlowProvider = ({ children }: { children: ReactNode }) => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [outputs, setOutputs] = useState<IOutput[]>([]);
    const [interactions, setInteractions] = useState<IInteraction[]>([]);
    const eventInterceptor = EventInterceptor.getInstance();

    const [dashboardPins, setDashboardPins] = useState<any>({});

    const [positionsInDashboard, _setPositionsInDashboard] = useState<any>({});
    const positionsInDashboardRef = useRef(positionsInDashboard);
    const setPositionsInDashboard = (data: any) => {
        positionsInDashboardRef.current = data;
        _setPositionsInDashboard(data);
    };

    const [positionsInWorkflow, _setPositionsInWorkflow] = useState<any>({});
    const positionsInWorkflowRef = useRef(positionsInWorkflow);
    const setPositionsInWorkflow = (data: any) => {
        positionsInWorkflowRef.current = data;
        _setPositionsInWorkflow(data);
    };

    const reactFlow = useReactFlow();
    const { newBox, addWorkflow, deleteBox, newConnection, deleteConnection } =
        useProvenanceContext();

    const [loading, setLoading] = useState<boolean>(false);

    const [workflowName, _setWorkflowName] = useState<string>("DefaultWorkflow");
    const workflowNameRef = React.useRef(workflowName);
    const setWorkflowName = (data: any) => {
        workflowNameRef.current = data;
        _setWorkflowName(data);
    };

    const getGraphState = useCallback(() => {
        const rawNodes = reactFlow.getNodes();
        const nodes = rawNodes.map(node => ({
            ...node,
            data: {
                ...node.data,
                defaultCode: nodeCodeRegistry.get(node.id) ?? node.data.code ?? node.data.defaultCode,
            },
        }));
        return { nodes, edges: reactFlow.getEdges() };
    }, [reactFlow]);

    const initializeProvenance = async () => {
        setLoading(true);
        await addWorkflow(workflowNameRef.current);
        let empty_trill = TrillGenerator.generateTrill([], [], workflowNameRef.current);
        TrillGenerator.intializeProvenance(empty_trill);
        setLoading(false);
    };

    useEffect(() => {
        initializeProvenance();
    }, []);



    const setDashBoardMode = (value: boolean) => {
        if (value) {
            setNodes((nds) => {
                const nodesWithWorkflowPositions = nds.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        workflowPosition: node.data.workflowPosition || node.position,
                    },
                }));

                const updatedNodes = applyDashboardLayout(nodesWithWorkflowPositions, edges, dashboardPins);

                updatedNodes.forEach((node) => {
                    if (dashboardPins[node.id]) {
                        updatePositionDashboard(node.id, node.position);
                    }
                });

                return updatedNodes;
            });
        } else {
            setNodes((nds) => {
                const resetNodes = nds.map(node => {
                    const workflowPos = node.data.workflowPosition || node.position;
                    return {
                        ...node,
                        position: workflowPos,
                        data: {
                            ...node.data,
                            dashboardPosition: undefined,
                        },
                    };
                });
                return resetNodes;
            });
        }
    };

    const updatePositionWorkflow = (nodeId: string, change: any) => {
        setPositionsInWorkflow((prev: any) => ({
            ...prev,
            [nodeId]: change
        }));
    };

    const updatePositionDashboard = (nodeId: string, position: { x: number; y: number }) => {
        setPositionsInDashboard((prev: any) => ({
            ...prev,
            [nodeId]: position
        }));
    };

    const setPinForDashboard = (nodeId: string, value: boolean) => {
        setDashboardPins((prev: any) => ({ ...prev, [nodeId]: value }));
    };

    const addNode = useCallback(
        (node: Node, customWorkflowName?: string, provenance?: boolean) => {
            setNodes((prev: any) => {
                updatePositionWorkflow(node.id, {
                    id: node.id,
                    dragging: true,
                    position: { ...node.position },
                    positionAbsolute: { ...node.position },
                    type: "position"
                });
                return prev.concat(node);
            });

            eventInterceptor.capture({
                event_type: "NODE_ADDED",
                node_id: node.id,
                event_time: EventInterceptor.now(),
                event_data: {
                    nodeType: String(node.type ?? ""),
                    position: {
                        x: node.position?.x ?? 0,
                        y: node.position?.y ?? 0,
                    },
                    label: node.data?.label,
                },
            });

            if (provenance)
                newBox((customWorkflowName ? customWorkflowName : workflowNameRef.current), (node.type as string) + "-" + node.id);
        },
        [setNodes, eventInterceptor]
    );

    const restoreGraph = useCallback(
        (nodes: Node[], edges: Edge[]) => {
            nodes.forEach(node => {
                const code = node.data?.defaultCode;
                if (node.id && code) {
                    nodeCodeRegistry.set(node.id, code);
                } else if (node.id) {
                    nodeCodeRegistry.delete(node.id);
                }
            });
            setNodes(nodes);
            setEdges(edges);
            eventInterceptor.capture({
                event_type: "SESSION_RESTORED",
                node_id: null,
                event_time: EventInterceptor.now(),
                event_data: { nodeCount: nodes.length, edgeCount: edges.length },
            });
            EventBuffer.getInstance().flush();
            setTimeout(() => SnapshotManager.getInstance().takeSnapshot(), 100);
        },
        [setNodes, setEdges, eventInterceptor]
    );

    const applyOutput = (
        inBox: BoxType,
        inId: string,
        outId: string,
        sourceHandle: string,
        targetHandle: string
    ) => {
        if (sourceHandle == "in/out" && targetHandle == "in/out") return;

        let output = "";

        setOutputs((opts: any) =>
            opts.map((opt: any) => {
                if (opt.nodeId == outId) {
                    output = opt.output;
                }
                return opt;
            })
        );

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (node.id !== inId) return node;

                if (inBox == BoxType.MERGE_FLOW) {
                    const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                    const handleIndex = parseHandleIndex(targetHandle);
                    if (handleIndex >= 0) {
                        setMergeSlot(inputList, sourceList, handleIndex, output, outId);
                    }
                    return { ...node, data: { ...node.data, input: inputList, source: sourceList } };
                }

                return { ...node, data: { ...node.data, input: output, source: outId } };
            })
        );
    };

    const onEdgesDelete = useCallback(
        (connections: Edge[]) => {
            for (const connection of connections) {
                eventInterceptor.capture({
                    event_type: "EDGE_REMOVED",
                    node_id: null,
                    event_time: EventInterceptor.now(),
                    event_data: {
                        sourceNodeId: String(connection.source ?? ""),
                        targetNodeId: String(connection.target ?? ""),
                    },
                });

                const resetInput = connection.target;
                const targetNode = reactFlow.getNode(connection.target) as Node;

                if (
                    connection.sourceHandle != "in/out" &&
                    connection.targetHandle != "in/out"
                ) {
                    deleteConnection(
                        workflowNameRef.current,
                        targetNode.id,
                        targetNode.type as BoxType
                    );
                }

                if (
                    connection.sourceHandle != "in/out" ||
                    connection.targetHandle != "in/out"
                ) {
                    setNodes((nds: any) =>
                        nds.map((node: any) => {
                            if (node.id !== resetInput) return node;

                            if (targetNode.type === BoxType.MERGE_FLOW) {
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
        [setNodes, eventInterceptor]
    );

    const onNodesDelete = useCallback(
        (changes: NodeChange[]) => {
            setOutputs((opts: any) =>
                opts.filter((opt: any) => {
                    for (const change of changes) {
                        if (change.type === "remove" && 'id' in change) {
                            if (opt.nodeId === change.id) {
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
                        eventInterceptor.capture({
                            event_type: "NODE_REMOVED",
                            node_id: change.id,
                            event_time: EventInterceptor.now(),
                            event_data: {
                                nodeType: String(node.type ?? ""),
                                label: node.data?.label,
                            },
                        });

                        deleteBox(workflowNameRef.current, node.type + "_" + node.id);
                    }
                }
            }
        },
        [setOutputs, reactFlow, deleteBox, eventInterceptor]
    );

    const onConnect = useCallback(
        (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean) => {
            const nodes = custom_nodes ? custom_nodes : reactFlow.getNodes();
            const edges = custom_edges ? custom_edges : reactFlow.getEdges();
            const target = nodes.find(
                (node: any) => node.id === connection.target
            ) as Node;

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

            const isInHandle = (h: string | null | undefined): boolean => !!h && h.startsWith("in");
            const isInOutHandle = (h: string | null | undefined): boolean => h === "in/out";

            let validHandleCombination = true;

            if (
                (isInOutHandle(connection.sourceHandle) && !isInOutHandle(connection.targetHandle)) ||
                (isInOutHandle(connection.targetHandle) && !isInOutHandle(connection.sourceHandle))
            ) {
                validHandleCombination = false;
                alert("An in/out connection can only be connected to another in/out connection");
            }
            else if (
                (isInHandle(connection.sourceHandle) && connection.targetHandle !== "out") ||
                (isInHandle(connection.targetHandle) && connection.sourceHandle !== "out")
            ) {
                validHandleCombination = false;
                alert("An in connection can only be connected to an out connection");
            }
            else if (
                (connection.sourceHandle === "out" && !isInHandle(connection.targetHandle)) ||
                (connection.targetHandle === "out" && !isInHandle(connection.sourceHandle))
            ) {
                validHandleCombination = false;
                alert("An out connection can only be connected to an in connection");
            }

            if (validHandleCombination) {
                let inBox: BoxType | undefined = undefined;
                let outBox: BoxType | undefined = undefined;

                for (const elem of nodes) {
                    if (elem.id == connection.source) {
                        outBox = elem.type as BoxType;
                    }

                    if (elem.id == connection.target) {
                        inBox = elem.type as BoxType;
                    }
                }

                let allowConnection = ConnectionValidator.checkBoxCompatibility(
                    outBox,
                    inBox
                );

                if (!allowConnection) {
                    alert("Input and output types of these boxes are not compatible");
                }

                if (inBox === BoxType.MERGE_FLOW && allowConnection) {
                    const availableHandles = Array(5).fill(1).map((_, i) => `in_${i}`);
                    const usedHandles = new Set(
                        edges
                            .filter((edge: Edge) =>
                                edge.target === connection.target &&
                                availableHandles.includes(edge.targetHandle as string)
                            )
                            .map((edge: Edge) => edge.targetHandle)
                    );

                    if (usedHandles.size > 7) {
                        alert("Connection Limit Reached!\n\nMerge nodes can only accept up to 7 input connections.");
                        allowConnection = false;
                    } else if (usedHandles.has(connection.targetHandle)) {
                        alert("This input already has a connection.\n\nEach input handle can only accept one connection.");
                        allowConnection = false;
                    }
                }

                if (target.id === connection.source) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (connection.sourceHandle != "in/out" && hasCycle(target)) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (allowConnection) {
                    eventInterceptor.capture({
                        event_type: "EDGE_CREATED",
                        node_id: null,
                        event_time: EventInterceptor.now(),
                        event_data: {
                            sourceNodeId: String(connection.source ?? ""),
                            targetNodeId: String(connection.target ?? ""),
                            sourceHandle: connection.sourceHandle ?? null,
                            targetHandle: connection.targetHandle ?? null,
                        },
                    });

                    applyOutput(
                        inBox as BoxType,
                        connection.target as string,
                        connection.source as string,
                        connection.sourceHandle as string,
                        connection.targetHandle as string
                    );

                    setEdges((eds) => {
                        let customConnection: any = {
                            ...connection,
                            markerEnd: { type: MarkerType.ArrowClosed },
                        };

                        if (customConnection.data == undefined)
                            customConnection.data = {};

                        if (
                            connection.sourceHandle == "in/out" &&
                            connection.targetHandle == "in/out"
                        ) {
                            customConnection.markerStart = {
                                type: MarkerType.ArrowClosed,
                            };
                            customConnection.type = EdgeType.BIDIRECTIONAL_EDGE;
                        } else {
                            customConnection.type = EdgeType.UNIDIRECTIONAL_EDGE;

                            if (true)
                                newConnection(
                                    (custom_workflow ? custom_workflow : workflowNameRef.current),
                                    customConnection.source,
                                    outBox as BoxType,
                                    customConnection.target,
                                    inBox as BoxType
                                );
                        }

                        return addEdge(customConnection, eds);
                    });
                }
            }
        },
        [setEdges, reactFlow, eventInterceptor, newConnection]
    );

    const isValidConnection = useCallback(
        (connection: Connection) => {
            return true;
        },
        [reactFlow.getNodes, reactFlow.getEdges]
    );

    const applyNewOutput = (newOutput: IOutput) => {
        const currentEdges = reactFlow.getEdges();

        const nodesAffected: string[] = [];
        for (const edge of currentEdges) {
            if (edge.sourceHandle == "in/out" && edge.targetHandle == "in/out") continue;
            if (newOutput.nodeId == edge.source) {
                nodesAffected.push(edge.target);
            }
        }

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (!nodesAffected.includes(node.id)) return node;

                if (node.type == BoxType.MERGE_FLOW) {
                    const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                    const sourceIndex = sourceList.findIndex((s: any) => s === newOutput.nodeId);
                    if (sourceIndex >= 0) {
                        inputList[sourceIndex] = newOutput.output;
                    }
                    return { ...node, data: { ...node.data, input: inputList, source: sourceList } };
                }

                if (newOutput.output == undefined) {
                    return { ...node, data: { ...node.data, input: "", source: "" } };
                }
                return { ...node, data: { ...node.data, input: newOutput.output, source: newOutput.nodeId } };
            })
        );

        setOutputs((opts: any) => {
            let added = false;
            const newOpts = opts.map((opt: any) => {
                if (opt.nodeId == newOutput.nodeId) {
                    added = true;
                    return { ...opt, output: newOutput.output };
                }
                return opt;
            });
            if (!added) newOpts.push({ ...newOutput });
            return newOpts;
        });
    };

    const applyNewInteractions = useCallback(() => {
        let newInteractions = interactions.filter((interaction) => {
            return interaction.priority == 1;
        });

        let toSend: any = {};
        let interactedIds: string[] = newInteractions.map(
            (interaction: IInteraction) => {
                return interaction.nodeId;
            }
        );
        let poolsIds: string[] = [];

        let interactionDict: any = {};

        for (const interaction of newInteractions) {
            interactionDict[interaction.nodeId] = {
                details: interaction.details,
                priority: interaction.priority,
            };
        }

        for (let i = 0; i < nodes.length; i++) {
            if (nodes[i].type == BoxType.DATA_POOL) {
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
                    targetNode.type == BoxType.DATA_POOL &&
                    sourceNode.type == BoxType.DATA_POOL
                )
            ) {
                if (
                    interactedIds.includes(edges[i].source) &&
                    poolsIds.includes(edges[i].target)
                ) {
                    if (toSend[edges[i].target] == undefined) {
                        toSend[edges[i].target] = [
                            interactionDict[edges[i].source],
                        ];
                    } else {
                        toSend[edges[i].target].push(
                            interactionDict[edges[i].source]
                        );
                    }
                } else if (
                    interactedIds.includes(edges[i].target) &&
                    poolsIds.includes(edges[i].source)
                ) {
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

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (toSend[node.id] != undefined) {
                    return { ...node, data: { ...node.data, interactions: toSend[node.id] } };
                }
                return node;
            })
        );
    }, [interactions]);

    const applyNewPropagation = useCallback((propagationObj: IPropagation) => {
        let sendTo: string[] = [];

        let edges = reactFlow.getEdges();

        for (const edge of edges) {
            if (
                edge.target == propagationObj.nodeId ||
                edge.source == propagationObj.nodeId
            ) {
                let targetNode = reactFlow.getNode(edge.target) as Node;
                let sourceNode = reactFlow.getNode(edge.source) as Node;

                if (
                    edge.sourceHandle == "in/out" &&
                    edge.targetHandle == "in/out" &&
                    targetNode.type == BoxType.DATA_POOL &&
                    sourceNode.type == BoxType.DATA_POOL
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
    


    const workflowOps = useWorkflowOperations({
        nodes, edges,
        setNodes, setEdges,
        setOutputs, setInteractions,
        setDashboardPins, setPositionsInDashboard, setPositionsInWorkflow,
        setWorkflowName,
        workflowNameRef,
        onEdgesDelete, onNodesDelete, onNodesChange,
        onConnect, addNode,
    });

    return (
        <FlowContext.Provider
            value={{
                nodes,
                edges,
                setOutputs,
                setInteractions,
                applyNewPropagation,
                addNode,
                onNodesChange,
                onEdgesChange,
                onConnect,
                isValidConnection,
                onEdgesDelete,
                onNodesDelete,
                setPinForDashboard,
                setDashBoardMode,
                updatePositionWorkflow,
                updatePositionDashboard,
                applyNewOutput,

                dashboardPins,
                workflowNameRef,
                setWorkflowName,
                loading,

                getGraphState,
                restoreGraph,
                ...workflowOps,
            }}
        >
            {children}
        </FlowContext.Provider>
    );
};

export const useFlowContext = () => {
    const context = useContext(FlowContext);

    if (!context) {
        throw new Error("useFlowContext must be used within a FlowProvider");
    }

    return context;
};

export default FlowProvider;