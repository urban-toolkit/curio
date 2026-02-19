import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useRef,
    useEffect,
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


export interface IOutput {
    nodeId: string;
    output: string;
}

export interface IInteraction {
    nodeId: string;
    details: any;
    priority: number; // used to solve conflicts of interactions 1 has more priority than 0
}

// propagating interactions between pools at different resolutions
export interface IPropagation {
    nodeId: string;
    propagation: any; // {[index]: [interaction value]}
}

// applyNewOutputs = useCallback((newOutNodeId: string, newOutput: string)

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

    // NEW CODE
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
    loadParsedTrill: (workflowName: string, task: string, node: any, edges: any, provenance?: boolean, merge?: boolean) => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateWarnings: (trill_spec: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    updateSubtasks: (trill: any) => void;
    cleanCanvas: () => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    updateKeywords: (trill: any) => void;
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

    // NEW CODE
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
    loadParsedTrill: async () => { }
});

const FlowProvider = ({ children }: { children: ReactNode }) => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [outputs, setOutputs] = useState<IOutput[]>([]);
    const [interactions, setInteractions] = useState<IInteraction[]>([]);

    const [dashboardPins, setDashboardPins] = useState<any>({}); // {[nodeId] -> boolean}

    const [positionsInDashboard, _setPositionsInDashboard] = useState<any>({}); // [nodeId] -> change
    const positionsInDashboardRef = useRef(positionsInDashboard);
    const setPositionsInDashboard = (data: any) => {
        positionsInDashboardRef.current = data;
        _setPositionsInDashboard(data);
    };

    const [positionsInWorkflow, _setPositionsInWorkflow] = useState<any>({}); // [nodeId] -> change
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

    const initializeProvenance = async () => {
        setLoading(true);
        await addWorkflow(workflowNameRef.current);
        let empty_trill = TrillGenerator.generateTrill([], [], workflowNameRef.current);
        TrillGenerator.intializeProvenance(empty_trill);
        setLoading(false);
    }

    useEffect(() => {
        initializeProvenance();
    }, []);

    const setDashBoardMode = (value: boolean) => {
        if (value) {
            // When entering dashboard mode, apply the automatic layout
            setNodes((nds) => {
                console.log('Current nodes before dashboard layout:', nds.map(n => ({
                    id: n.id,
                    type: n.type,
                    position: n.position,
                    pinned: dashboardPins[n.id]
                })));

                // Save current positions as workflow positions if not already set
                const nodesWithWorkflowPositions = nds.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        workflowPosition: node.data.workflowPosition || node.position,
                    },
                }));

                console.log('Applying dashboard layout to nodes:', nodesWithWorkflowPositions.length);
                console.log('Dashboard pins:', dashboardPins);

                const updatedNodes = applyDashboardLayout(nodesWithWorkflowPositions, edges, dashboardPins);

                console.log('Updated nodes after layout:', updatedNodes.map(n => ({
                    id: n.id,
                    type: n.type,
                    position: n.position,
                    data: n.data
                })));

                // Update positions in the dashboard state
                updatedNodes.forEach((node) => {
                    if (dashboardPins[node.id]) {
                        console.log(`Updating dashboard position for node ${node.id}:`, node.position);
                        updatePositionDashboard(node.id, node.position);
                    }
                });

                return updatedNodes;
            });
        } else {
            // When exiting dashboard mode, reset to workflow positions
            setNodes((nds) => {
                const resetNodes = nds.map(node => {
                    const workflowPos = node.data.workflowPosition || node.position;
                    console.log(`Resetting node ${node.id} to workflow position:`, workflowPos);
                    return {
                        ...node,
                        position: workflowPos,
                        data: {
                            ...node.data,
                            // Clear temporary dashboard position
                            dashboardPosition: undefined,
                        },
                    };
                });
                console.log('Nodes after reset:', resetNodes);
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
            console.log("add node");
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

            if (provenance) // If there should be provenance tracking
                newBox((customWorkflowName ? customWorkflowName : workflowNameRef.current), (node.type as string) + "-" + node.id);
        },
        [setNodes]
    );

    // updates a single box with the new input (new connections)
    const applyOutput = (
        inBox: BoxType,
        inId: string,
        outId: string,
        sourceHandle: string,
        targetHandle: string
    ) => {
        if (sourceHandle == "in/out" && targetHandle == "in/out") return;

        // Look up the current output value for the source node
        const outputEntry = outputs.find(opt => opt.nodeId === outId);
        const output = outputEntry?.output ?? "";

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
                const resetInput = connection.target;
                const targetNode = reactFlow.getNode(connection.target) as Node;

                // skiping syncronized connections
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

                // skiping syncronized connections
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
                        deleteBox(workflowNameRef.current, node.type + "_" + node.id);
                    }
                }
            }
        },
        [setOutputs, reactFlow, deleteBox]
    );

    const onConnect = useCallback(
        (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean) => {
            console.log(
                "onConnect triggered:",
                connection.source,
                connection.sourceHandle,
                connection.target,
                connection.targetHandle
            );

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

            // accept string, null, or undefined:
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
                // Check compatibility between inputs and outputs
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


                // Checking cycles
                if (target.id === connection.source) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (connection.sourceHandle != "in/out" && hasCycle(target)) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (allowConnection) {
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

                            if (true)  //Changed provenance to always persist connections; monitor for potential side effects.
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
        [setEdges]
    );

    // Checking for cycles and invalid connections between types of boxes
    const isValidConnection = useCallback(
        (connection: Connection) => {
            return true;
        },
        [reactFlow.getNodes, reactFlow.getEdges]
    );

    // a box generated a new output. Propagate it to directly connected boxes
    const applyNewOutput = (newOutput: IOutput) => {
        const currentEdges = reactFlow.getEdges();

        // Find which nodes are directly downstream of the output source
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
                } else if (
                    interactedIds.includes(edges[i].target) &&
                    poolsIds.includes(edges[i].source)
                ) {
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
    // NEW CODE

    // Workflow operations extracted into a dedicated hook
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

                // NEW CODE
                dashboardPins,
                workflowNameRef,
                setWorkflowName,
                loading,

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