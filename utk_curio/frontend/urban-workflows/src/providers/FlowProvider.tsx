import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useMemo,
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
import { NodeType, EdgeType } from "../constants";
import { getFlowNodeCanonicalType } from "../utils/flowNodeCanonicalType";
import { TrillGenerator } from "../TrillGenerator";
import { applyDashboardLayout } from "../utils/dashboardLayout";
import {
    ensureMergeArrays,
    parseHandleIndex,
    setMergeSlot,
    clearMergeSlot,
    mergeSlotForSource,
} from "../utils/mergeFlowUtils";
import { useWorkflowOperations } from "../hook/useWorkflowOperations";
import { useToastContext } from "./ToastProvider";
import { useCollab } from "./CollaborationProvider";
import { pythonInterpreter, jsInterpreter } from "../hook/useCode";
import { normalizeFlowInput } from "../utils/flowOutputRef";
import { DEFAULT_SAVE_OUTPUT_DATASET } from "../utils/saveOutputDataset";


export interface IOutput {
    nodeId: string;
    output: unknown;
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

interface PlayAllState {
    levels: string[][];
    currentLevel: number;
    pending: Set<string>;
}

interface FlowContextProps {
    nodes: Node[];
    edges: Edge[];
    outputs: IOutput[];
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
    dashboardOn: boolean;
    dashboardLocked: boolean;
    setDashboardLocked: React.Dispatch<React.SetStateAction<boolean>>;
    updatePositionWorkflow: (nodeId: string, position: any) => void;
    updatePositionDashboard: (nodeId: string, position: any) => void;
    applyNewOutput: (output: IOutput) => void;

    // NEW CODE
    dashboardPins: { [key: string]: boolean };
    workflowNameRef: React.MutableRefObject<string>;
    setWorkflowName: (name: string) => void;
    workflowDescriptionRef: React.MutableRefObject<string>;
    workflowDescription: string;
    setWorkflowDescription: (description: string) => void;
    allMinimized: number;
    setAllMinimized: (value: number) => void;
    expandStatus: 'expanded' | 'minimized';
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    suggestionsLeft: number;
    workflowGoal: string;
    setWorkflowGoal: (goal: string) => void;
    loading: boolean;

    applyRemoveChanges: (changes: NodeRemoveChange[]) => void;
    loadParsedTrill: (workflowName: string, task: string, node: any, edges: any, provenance?: boolean, merge?: boolean, packages?: string[], description?: string, datasets?: any[]) => void;
    packages: string[];
    setPackages: (pkgs: string[]) => void;
    addPackage: (pkg: string) => void;
    removePackage: (pkg: string) => void;
    dataflowDatasets: any[];
    setDataflowDatasets: React.Dispatch<React.SetStateAction<any[]>>;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateWarnings: (trill_spec: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    updateSubtasks: (trill: any) => void;
    cleanCanvas: () => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    updateKeywords: (trill: any) => void;

    // Project state
    projectId: string | null;
    projectName: string;
    projectDirty: boolean;
    projectSavedAt: Date | null;
    nodeExecStatus: Record<string, "stale" | "executed">;
    viewerMode: "owner" | "shared";

    // Project operations
    saveCurrentProject: (nameOverride?: string) => Promise<any>;
    saveAsNewProject: (name: string) => Promise<any>;
    loadProject: (id: string) => Promise<any>;
    loadSharedProject: (id: string) => Promise<any>;
    discardProject: () => void;
    markDirty: () => void;
    markNodeExecuted: (nodeId: string) => void;
    markNodeStale: (nodeId: string) => void;
    playAllNodes: () => void;
    playNodesUpTo: (targetNodeId: string) => void;
    signalNodeExecDone: (nodeId: string) => void;
    defaultSaveOutputDataset: boolean;
    setDefaultSaveOutputDataset: (value: boolean) => void;
}

// Stable context for NodeContainer — only updates when goal/minimized change, NOT on node drag
export interface NodeActionsContextProps {
    workflowNameRef: React.MutableRefObject<string>;
    workflowName: string;
    applyRemoveChanges: (changes: any[]) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    allMinimized: number;
    setAllMinimized: (value: number) => void;
    expandStatus: 'expanded' | 'minimized';
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    workflowGoal: string;
    acceptSuggestion: (nodeId: string) => void;
    setWorkflowName: (name: string) => void;
}

export const NodeActionsContext = createContext<NodeActionsContextProps>({
    workflowNameRef: { current: "" },
    workflowName: "DefaultWorkflow",
    applyRemoveChanges: () => {},
    setPinForDashboard: () => {},
    allMinimized: 0,
    setAllMinimized: () => {},
    expandStatus: 'expanded',
    setExpandStatus: () => {},
    updateDataNode: () => {},
    updateDefaultCode: () => {},
    workflowGoal: "",
    acceptSuggestion: () => {},
    setWorkflowName: () => {},
});

export const useNodeActionsContext = () => useContext(NodeActionsContext);

export const FlowContext = createContext<FlowContextProps>({
    nodes: [],
    edges: [],
    outputs: [],
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
    dashboardOn: false,
    dashboardLocked: true,
    setDashboardLocked: () => { },
    updatePositionWorkflow: () => { },
    updatePositionDashboard: () => { },
    applyNewOutput: () => { },

    // NEW CODE
    dashboardPins: {},
    workflowNameRef: { current: "" },
    workflowDescriptionRef: { current: "" },
    workflowDescription: "",
    setWorkflowDescription: () => {},
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
    loadParsedTrill: async () => { },
    packages: [],
    setPackages: () => {},
    addPackage: () => {},
    removePackage: () => {},
    dataflowDatasets: [],
    setDataflowDatasets: () => {},

    // Project defaults
    projectId: null,
    projectName: "",
    projectDirty: false,
    projectSavedAt: null,
    nodeExecStatus: {},
    viewerMode: "owner",
    saveCurrentProject: async () => {},
    saveAsNewProject: async () => {},
    loadProject: async () => {},
    loadSharedProject: async () => {},
    discardProject: () => {},
    markDirty: () => {},
    markNodeExecuted: () => {},
    markNodeStale: () => {},
    playAllNodes: () => {},
    playNodesUpTo: () => {},
    signalNodeExecDone: () => {},
    defaultSaveOutputDataset: false,
    setDefaultSaveOutputDataset: () => {},
});

function computeTopologicalLevels(nodes: Node[], edges: Edge[]): string[][] {
    const directedEdges = edges.filter(
        e => !(e.sourceHandle === "in/out" && e.targetHandle === "in/out")
    );

    const inDegree = new Map<string, number>();
    const successors = new Map<string, string[]>();
    for (const n of nodes) { inDegree.set(n.id, 0); successors.set(n.id, []); }
    for (const e of directedEdges) {
        inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
        successors.get(e.source)!.push(e.target);
    }

    const roots = nodes.filter(n => inDegree.get(n.id) === 0);
    const isolated = roots.filter(n => (successors.get(n.id)?.length ?? 0) === 0).map(n => n.id);
    const sources  = roots.filter(n => (successors.get(n.id)?.length ?? 0) > 0).map(n => n.id);

    if (isolated.length === 0 && sources.length === 0) return [];

    const levels: string[][] = [];
    if (isolated.length > 0) levels.push(isolated);
    if (sources.length > 0) levels.push(sources);

    const remaining = new Map(inDegree);
    const visited = new Set([...isolated, ...sources]);
    let queue = sources;

    while (queue.length > 0) {
        const next: string[] = [];
        for (const id of queue) {
            for (const succ of successors.get(id) ?? []) {
                remaining.set(succ, (remaining.get(succ) ?? 0) - 1);
                if (remaining.get(succ) === 0 && !visited.has(succ)) {
                    next.push(succ);
                    visited.add(succ);
                }
            }
        }
        if (next.length > 0) levels.push(next);
        queue = next;
    }
    return levels;
}

const FlowProvider = ({ children }: { children: ReactNode }) => {
    const { showToast } = useToastContext();
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [outputs, _setOutputs] = useState<IOutput[]>([]);
    const outputsRef = useRef<IOutput[]>([]);
    const playAllStateRef = useRef<PlayAllState | null>(null);
    const markNodeExecutedRef = useRef<(nodeId: string) => void>(() => {});
    const markNodeStaleRef = useRef<(nodeId: string) => void>(() => {});
    const markDirtyRef = useRef<() => void>(() => {});
    const [defaultSaveOutputDataset, setDefaultSaveOutputDataset] = useState(
        DEFAULT_SAVE_OUTPUT_DATASET,
    );

    // Collaboration broadcasters. The provider may be a no-op (when
    // --collab is off or no project is loaded), in which case every
    // broadcast call is a noop too. We hold the latest value in a ref
    // so the mutation callbacks below don't have to list `collab` in
    // their dependency arrays and risk re-creating themselves on every
    // presence change.
    const collab = useCollab();
    const collabRef = useRef(collab);
    collabRef.current = collab;

    const setOutputs = useCallback((fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => {
        _setOutputs((prev) => {
            const next = typeof fnOrValue === "function" ? fnOrValue(prev) : fnOrValue;
            outputsRef.current = next;
            return next;
        });
    }, []);
    const [interactions, setInteractions] = useState<IInteraction[]>([]);

    const [dashboardPins, setDashboardPins] = useState<any>({}); // {[nodeId] -> boolean}
    const [dashboardOn, setDashboardOn] = useState<boolean>(false);
    const [dashboardLocked, setDashboardLocked] = useState<boolean>(true);

    const positionsInDashboardRef = useRef<any>({});
    const setPositionsInDashboard = (data: any) => {
        positionsInDashboardRef.current = typeof data === 'function' ? data(positionsInDashboardRef.current) : data;
    };

    const positionsInWorkflowRef = useRef<any>({});
    const setPositionsInWorkflow = (data: any) => {
        positionsInWorkflowRef.current = typeof data === 'function' ? data(positionsInWorkflowRef.current) : data;
    };

    const reactFlow = useReactFlow();
    const [loading, setLoading] = useState<boolean>(false);

    const [workflowName, _setWorkflowName] = useState<string>("DefaultDataflow");
    const workflowNameRef = React.useRef(workflowName);
    const setWorkflowName = useCallback((data: any) => {
        workflowNameRef.current = data;
        _setWorkflowName(data);
    }, []);

    const [workflowDescription, _setWorkflowDescription] = useState<string>("");
    const workflowDescriptionRef = React.useRef(workflowDescription);
    const setWorkflowDescription = useCallback((data: string) => {
        workflowDescriptionRef.current = data || "";
        _setWorkflowDescription(data || "");
    }, []);

    const initializeProvenance = () => {
        setLoading(true);
        try {
            const empty_trill = TrillGenerator.generateTrill(
                [],
                [],
                workflowNameRef.current,
            );
            TrillGenerator.intializeProvenance(empty_trill);
        } catch (e) {
            console.error("initializeProvenance failed:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        initializeProvenance();
    }, []);

    const setDashBoardMode = (value: boolean) => {
        setDashboardOn(value);
        if (value) {
            setDashboardLocked(true);
            // When entering dashboard mode, apply the automatic layout
            setNodes((nds) => {
                // Save current positions as workflow positions if not already set
                const nodesWithWorkflowPositions = nds.map(node => ({
                    ...node,
                    data: {
                        ...node.data,
                        workflowPosition: node.data.workflowPosition || node.position,
                    },
                }));

                const updatedNodes = applyDashboardLayout(nodesWithWorkflowPositions, edges, dashboardPins);

                // Update positions in the dashboard state
                updatedNodes.forEach((node) => {
                    if (dashboardPins[node.id]) {
                        updatePositionDashboard(node.id, node.position);
                    }
                });

                return updatedNodes.map(node => ({
                    ...node,
                    style: dashboardPins[node.id] ? node.style : { display: 'none' },
                }));
            });
            setEdges(eds => eds.map(e => ({ ...e, hidden: true })));
        } else {
            // When exiting dashboard mode, reset to workflow positions
            setNodes((nds) => {
                return nds.map(node => {
                    const workflowPos = node.data.workflowPosition || node.position;
                    return {
                        ...node,
                        style: undefined,
                        position: workflowPos,
                        data: {
                            ...node.data,
                            dashboardPosition: undefined,
                        },
                    };
                });
            });
            setEdges(eds => eds.map(e => ({ ...e, hidden: false })));
        }
    };

    const updatePositionWorkflow = useCallback((nodeId: string, change: any) => {
        positionsInWorkflowRef.current = { ...positionsInWorkflowRef.current, [nodeId]: change };
    }, []);

    const updatePositionDashboard = useCallback((nodeId: string, position: { x: number; y: number }) => {
        positionsInDashboardRef.current = { ...positionsInDashboardRef.current, [nodeId]: position };
    }, []);

    const setPinForDashboard = useCallback((nodeId: string, value: boolean) => {
        setDashboardPins((prev: any) => ({ ...prev, [nodeId]: value }));
        setNodes((nds: Node[]) =>
            nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, dashboardPinned: value } } : n)
        );
    }, [setDashboardPins, setNodes]);

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

    // Push a source node's cached output to every direct downstream consumer.
    const propagateDownstreamInputs = (sourceId: string, rawOutput: unknown) => {
        const currentEdges = reactFlow.getEdges();
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

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (!nodesAffected.includes(node.id)) return node;

                if (getFlowNodeCanonicalType(node) == NodeType.MERGE_FLOW) {
                    const { inputList, sourceList } = ensureMergeArrays(node.data.input, node.data.source);
                    const sourceIndex = mergeSlotForSource(
                        currentEdges,
                        node.id,
                        sourceId,
                        sourceList,
                    );
                    if (sourceIndex >= 0) {
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

        const entry = outputsRef.current.find((opt) => opt.nodeId === outId);
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

                            if (getFlowNodeCanonicalType(targetNode) === NodeType.MERGE_FLOW) {
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

    const onConnect = useCallback(
        (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean) => {
            console.log(
                "onConnect triggered:",
                connection.source,
                connection.sourceHandle,
                connection.target,
                connection.targetHandle
            );
            markDirtyRef.current();

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
                        outNodeType = getFlowNodeCanonicalType(elem) as NodeType;
                    }

                    if (elem.id == connection.target) {
                        inNodeType = getFlowNodeCanonicalType(elem) as NodeType;
                    }
                }

                let allowConnection = ConnectionValidator.checkBoxCompatibility(
                    outNodeType,
                    inNodeType
                );

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

    function triggerLevel(levelIndex: number) {
        const state = playAllStateRef.current;
        if (!state) return;
        const levelNodeIds = state.levels[levelIndex];
        if (!levelNodeIds?.length) { playAllStateRef.current = null; return; }
        state.pending = new Set(levelNodeIds);
        state.currentLevel = levelIndex;
        setNodes((nds: Node[]) =>
            nds.map((node: Node) =>
                levelNodeIds.includes(node.id)
                    ? { ...node, data: { ...node.data, triggerExec: (node.data.triggerExec ?? 0) + 1 } }
                    : node
            )
        );
    }

    const signalNodeExecDone = useCallback((nodeId: string) => {
        const state = playAllStateRef.current;
        if (!state) return;
        state.pending.delete(nodeId);
        if (state.pending.size === 0) {
            const next = state.currentLevel + 1;
            if (next < state.levels.length) triggerLevel(next);
            else playAllStateRef.current = null;
        }
    }, [setNodes]);

    function playAllNodes() {
        if (playAllStateRef.current != null) return;
        const allNodes = reactFlow.getNodes();
        const allEdges = reactFlow.getEdges();
        const levels = computeTopologicalLevels(allNodes, allEdges);
        if (!levels.length) return;
        const visitedIds = new Set(levels.flat());
        const cyclic = allNodes.filter(n => !visitedIds.has(n.id));
        if (cyclic.length > 0) {
            showToast(`${cyclic.length} node(s) skipped due to cycles in the graph`, "warning");
        }
        playAllStateRef.current = { levels, currentLevel: 0, pending: new Set() };
        triggerLevel(0);
    }

    function playNodesUpTo(targetNodeId: string) {
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();

        const directedEdges = currentEdges.filter(
            e => !(e.sourceHandle === "in/out" && e.targetHandle === "in/out")
        );

        const predecessors = new Map<string, string[]>();
        for (const n of currentNodes) predecessors.set(n.id, []);
        for (const e of directedEdges) {
            predecessors.get(e.target)?.push(e.source);
        }

        const ancestorIds = new Set<string>();
        const queue = [targetNodeId];
        while (queue.length > 0) {
            const id = queue.shift()!;
            for (const pred of predecessors.get(id) ?? []) {
                if (!ancestorIds.has(pred)) {
                    ancestorIds.add(pred);
                    queue.push(pred);
                }
            }
        }
        ancestorIds.add(targetNodeId);

        // Also include degree-0 nodes (no directed edges at all)
        const directedEdgeNodeIds = new Set<string>();
        for (const e of directedEdges) {
            directedEdgeNodeIds.add(e.source);
            directedEdgeNodeIds.add(e.target);
        }
        for (const n of currentNodes) {
            if (!directedEdgeNodeIds.has(n.id)) ancestorIds.add(n.id);
        }

        // Skip ancestors that already ran successfully; always keep the target
        const subgraphNodes = currentNodes.filter(n =>
            ancestorIds.has(n.id) &&
            (n.id === targetNodeId || n.data.output?.code !== "success")
        );
        const subgraphNodeIds = new Set(subgraphNodes.map(n => n.id));
        const subgraphEdges = currentEdges.filter(
            e => subgraphNodeIds.has(e.source) && subgraphNodeIds.has(e.target)
        );

        const levels = computeTopologicalLevels(subgraphNodes, subgraphEdges);
        if (!levels.length) return;

        playAllStateRef.current = { levels, currentLevel: 0, pending: new Set() };
        triggerLevel(0);
    }

    // a box generated a new output. Propagate it to directly connected boxes
    const applyNewOutput = (newOutput: IOutput) => {
        propagateDownstreamInputs(newOutput.nodeId, newOutput.output);

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

        markNodeExecutedRef.current(newOutput.nodeId);
        signalNodeExecDone(newOutput.nodeId);
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
            if (getFlowNodeCanonicalType(nodes[i]) == NodeType.DATA_POOL) {
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
                        getFlowNodeCanonicalType(targetNode) == NodeType.DATA_POOL &&
                        getFlowNodeCanonicalType(sourceNode) == NodeType.DATA_POOL
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
                    getFlowNodeCanonicalType(targetNode) == NodeType.DATA_POOL &&
                    getFlowNodeCanonicalType(sourceNode) == NodeType.DATA_POOL
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
    // during JSON serialisation. Without this, downstream lifecycle
    // adapters would call ``data.outputCallback(...)`` against undefined
    // (caught now by the defensive ``typeof`` guards in
    // ``adapters/node/*``, but never producing visible output).
    // -----------------------------------------------------------------
    useEffect(() => {
        if (!collab.enabled) return;
        const localOutputCallback = (nodeId: string, output: any) => {
            applyNewOutput({ nodeId, output });
        };
        const localInteractionsCallback = (newInteractions: any, nodeId: string) => {
            setInteractions((prev: IInteraction[]) => {
                const next = prev.filter((i) => i.nodeId !== nodeId);
                next.push({ nodeId, details: newInteractions, priority: 0 });
                return next;
            });
        };
        const rebuildNodeData = (data: any) => ({
            ...data,
            outputCallback: localOutputCallback,
            interactionsCallback: localInteractionsCallback,
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
    }, [collab.enabled, collab.onRemote, setNodes, setEdges, setInteractions]);
    // NEW CODE

    // Workflow operations extracted into a dedicated hook
    // NOTE: markNodeExecutedRef/markNodeStaleRef are updated here so functions defined earlier
    // (applyNewOutput, onEdgesDelete, onConnect) can access them without stale closures.
    const workflowOps = useWorkflowOperations({
        nodes, edges,
        setNodes, setEdges,
        setOutputs, outputsRef, setInteractions,
        setDashboardPins, setPositionsInDashboard, setPositionsInWorkflow,
        setWorkflowName,
        workflowNameRef,
        setWorkflowDescription,
        workflowDescriptionRef,
        onEdgesDelete, onNodesDelete, onNodesChange,
        onConnect, addNode,
    });

    markNodeExecutedRef.current = workflowOps.markNodeExecuted;
    markNodeStaleRef.current = workflowOps.markNodeStale;
    markDirtyRef.current = workflowOps.markDirty;

    const nodeActionsValue = useMemo<NodeActionsContextProps>(() => ({
        workflowNameRef,
        workflowName,
        applyRemoveChanges: workflowOps.applyRemoveChanges,
        setPinForDashboard,
        allMinimized: workflowOps.allMinimized,
        setAllMinimized: workflowOps.setAllMinimized,
        expandStatus: workflowOps.expandStatus,
        setExpandStatus: workflowOps.setExpandStatus,
        updateDataNode: workflowOps.updateDataNode,
        updateDefaultCode: workflowOps.updateDefaultCode,
        workflowGoal: workflowOps.workflowGoal,
        acceptSuggestion: workflowOps.acceptSuggestion,
        setWorkflowName,
    }), [
        workflowNameRef,
        workflowName,
        workflowOps.applyRemoveChanges,
        setPinForDashboard,
        workflowOps.allMinimized,
        workflowOps.setAllMinimized,
        workflowOps.expandStatus,
        workflowOps.setExpandStatus,
        workflowOps.updateDataNode,
        workflowOps.updateDefaultCode,
        workflowOps.workflowGoal,
        workflowOps.acceptSuggestion,
        setWorkflowName,
    ]);

    return (
        <NodeActionsContext.Provider value={nodeActionsValue}>
        <FlowContext.Provider
            value={{
                nodes,
                edges,
                outputs,
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
                playAllNodes,
                playNodesUpTo,
                signalNodeExecDone,

                // NEW CODE
                dashboardPins,
                dashboardOn,
                dashboardLocked,
                setDashboardLocked,
                workflowNameRef,
                setWorkflowName,
                workflowDescriptionRef,
                workflowDescription,
                setWorkflowDescription,
                loading,

                ...workflowOps,
                defaultSaveOutputDataset,
                setDefaultSaveOutputDataset,

            }}
        >
            {children}
        </FlowContext.Provider>
        </NodeActionsContext.Provider>
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
