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
    applyNodeChanges,
    NodeRemoveChange,
} from "reactflow";
import { ConnectionValidator } from "../ConnectionValidator";
import { BoxType, EdgeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "./ProvenanceProvider";
import { TrillGenerator } from "../TrillGenerator";
import { applyDashboardLayout } from "../utils/dashboardLayout";


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
    workflowNameRef: React.MutableRefObject<string>;
    suggestionsLeft: number;
    allMinimized: number;
    workflowGoal: string;
    loading: boolean;
    expandStatus: 'expanded' | 'minimized';
    dashboardPins: { [key: string]: boolean };
    setWorkflowGoal: (goal: string) => void;
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
    applyRemoveChanges: (changes: NodeRemoveChange[]) => void;
    eraseWorkflowSuggestions: () => void;
    acceptSuggestion: (nodeId: string) => void;
    flagBasedOnKeyword: (keywordIndex?: number) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    cleanCanvas: () => void;
    updateSubtasks: (trill: any) => void;
    updateKeywords: (trill: any) => void;
    updateDataNode: (nodeId: string, newData: any) => void;
    updateDefaultCode: (nodeId: string, content: string) => void;
    updateWarnings: (trill_spec: any) => void;
    setDashBoardMode: (value: boolean) => void;
    updatePositionWorkflow: (nodeId: string, position: any) => void;
    updatePositionDashboard: (nodeId: string, position: any) => void;
    applyNewOutput: (output: IOutput) => void;
    setWorkflowName: (name: string) => void;
    setAllMinimized: (value: number) => void;
    setExpandStatus: (value: 'expanded' | 'minimized') => void;
    loadParsedTrill: (workflowName: string, task: string, node: any, edges: any, provenance?: boolean, merge?: boolean) => void;
}

export const FlowContext = createContext<FlowContextProps>({
    nodes: [],
    edges: [],
    workflowNameRef: { current: "" },
    suggestionsLeft: 0,
    workflowGoal: "",
    allMinimized: 0,
    expandStatus: 'expanded',
    dashboardPins: {},
    loading: false,
    setWorkflowGoal: () => {},
    setOutputs: () => { },
    setInteractions: () => { },
    applyNewPropagation: () => { },
    addNode: () => { },
    onNodesChange: () => { },
    onEdgesChange: () => { },
    onConnect: () => { },
    isValidConnection: () => true,
    onEdgesDelete: () => { },
    applyRemoveChanges: () => { },
    onNodesDelete: () => { },
    setPinForDashboard: () => { },
    setDashBoardMode: () => { },
    updatePositionWorkflow: () => { },
    updatePositionDashboard: () => { },
    applyNewOutput: () => { },
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
    const [allMinimized, setAllMinimized] = useState<number>(0);
    const [expandStatus, setExpandStatus] = useState<'expanded' | 'minimized'>('expanded');
    const [fitViewOnLoad, setFitViewOnLoad] = useState(false);
    const [suggestionsLeft, setSuggestionsLeft] = useState<number>(0); // Number of suggestions left
    const [workflowGoal, setWorkflowGoal] = useState("");

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

    useEffect(() => {
        if (fitViewOnLoad) {
            const timeout = setTimeout(() => {
                const currentNodes = reactFlow.getNodes();
                if (currentNodes.length > 0) {
                    reactFlow.fitView({ padding: 0.2 });
                    setFitViewOnLoad(false);
                }
            }, 100); // small delay to ensure render cycle

            return () => clearTimeout(timeout);
        }
    }, [fitViewOnLoad]);

    const updateDataNode = (nodeId: string, newData: any) => {
        let copy_newData = {...newData};

        console.log("updateDataNode");

        setNodes(prevNodes => {

            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(newNode.id == nodeId)
                    newNode.data = copy_newData;
            
                newNodes.push(newNode);
            }

            return [...newNodes];
        });
    }

    const loadParsedTrill = async (workflowName: string, task: string, loaded_nodes: any, loaded_edges: any, provenance?: boolean, merge?: boolean) => {

        // setWorkflowGoal(task);

        if (!merge) {
            setWorkflowName(workflowName);
            await addWorkflow(workflowName); // reseting provenance with new workflow
            console.log("loadParsedTrill reseting nodes")
            setNodes(prevNodes => []); // Reseting nodes
        }

        let current_nodes_ids = [];

        if (merge) {
            for (const node of nodes) {
                current_nodes_ids.push(node.id);
            }

            for (const node of loaded_nodes) { // adding new nodes one by one
                if (!current_nodes_ids.includes(node.id)) { // if the node already exist do not include it again
                    addNode(node, workflowName, provenance);
                }
            }
        } else {
            for (const node of loaded_nodes) { // adding new nodes one by one
                addNode(node, workflowName, provenance);
            }
        }

        if (!merge) {
            // onEdgesDelete(edges);
            setEdges(prevEdges => []) // Reseting edges
        }

        let current_edges_ids = [];

        for (const edge of edges) {
            current_edges_ids.push(edge.id);
        }

        console.log("loadParsedTrill second");
        setNodes((prevNodes: any) => { // Guarantee that previous nodes were added

            if (merge) {
                for (const edge of loaded_edges) {
                    if (!current_edges_ids.includes(edge.id)) { // if the edge already exist do not include it again
                        onConnect(edge, prevNodes, undefined, workflowName, provenance);
                    }
                }
            } else {
                for (const edge of loaded_edges) {
                    onConnect(edge, prevNodes, undefined, workflowName, provenance);
                }
            }


            if (!merge) {
                setOutputs([]);
                setInteractions([]);
                setDashboardPins({});
                setPositionsInDashboard({});
                setPositionsInWorkflow({});
            }

            setFitViewOnLoad(true);

            return prevNodes;
        })

        // TODO: Unset dashboardMode (setDashBoardMode)
    }

    const updateDefaultCode = (nodeId: string, content: string) => {
        console.log("updateDefaultCode");
        setNodes(prevNodes => {

            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(node.id == nodeId){
                    node.data.defaultCode = content;
                }

                newNodes.push(newNode);
            }

            return newNodes;
        });
    }

    const updateKeywords = (trill_spec: any) => { // Given a trill specification with nodes and edges with the same IDs as the current nodes and edges attach the keywords.

        let node_to_keywords: any = {};
        let edge_to_keywords: any = {};

        if(trill_spec.dataflow != undefined){
            for(const node of trill_spec.dataflow.nodes){
                if(node.metadata != undefined && node.metadata.keywords != undefined){
                    node_to_keywords[node.id] = [...node.metadata.keywords];
                }
            }

            for(const edge of trill_spec.dataflow.edges){
                if(edge.metadata != undefined && edge.metadata.keywords != undefined){
                    edge_to_keywords[edge.id] = [...edge.metadata.keywords];
                } 
            }
        }

        console.log("updateKeywords");
        setNodes(prevNodes => {

            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(node_to_keywords[newNode.id] != undefined)
                    newNode.data.keywords = node_to_keywords[newNode.id]

                newNodes.push(newNode);
            }

            return newNodes;
        });

        setEdges(prevEdges => {

            let newEdges = [];

            for(const edge of prevEdges){
                let newEdge = {...edge};

                if(edge_to_keywords[newEdge.id] != undefined)
                    newEdge.data.keywords = edge_to_keywords[newEdge.id]

                newEdges.push(newEdge);
            }

            return newEdges;
        });

    }

    const updateSubtasks = (trill_spec: any) => { // Given a trill specification update the nodes subtasks
       
        let node_to_goal: any = {};

        if(trill_spec.dataflow != undefined){
            for(const node of trill_spec.dataflow.nodes){
                if(node.goal != undefined){
                    node_to_goal[node.id] = node.goal;
                }
            }
        }

        console.log("updateSubtasks");
        setNodes(prevNodes => {

            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(node_to_goal[newNode.id] != undefined)
                    newNode.data.goal = node_to_goal[newNode.id]

                newNodes.push(newNode);
            }

            return newNodes;
        });

    }

    const updateWarnings = (trill_spec: any) => { // Given a trill specification update the nodes warnings

        let node_to_warning: any = {};

        if(trill_spec.dataflow != undefined){
            for(const node of trill_spec.dataflow.nodes){
                if(node.warnings != undefined){
                    node_to_warning[node.id] = node.warnings;
                }
            }
        }

        console.log("updateWarnings");
        setNodes(prevNodes => {

            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(node_to_warning[newNode.id] != undefined)
                    newNode.data.warnings = node_to_warning[newNode.id]

                newNodes.push(newNode);
            }

            return newNodes;
        });

    }

    const cleanCanvas = () => {

        let edgesWithProvenance = [];

        for(const edge of edges){
            if((edge.data && !(edge.data.suggestionType != "none" && edge.data.suggestionType != undefined)) || !edge.data)
                edgesWithProvenance.push(edge);
        }

        onEdgesDelete(edgesWithProvenance); // deleting provenance of non-suggestions

        setEdges(prevNodes => []);

        for(const node of nodes){
            if((node.data && !(node.data.suggestionType != "none" && node.data.suggestionType != undefined)) || !node.data) // not a suggestion have to erase provenance
                deleteNode(node.id);

        }

        console.log("cleanCanvas");
        setNodes(prevNodes => []);

        setOutputs([]);
        setInteractions([]);
        setDashboardPins({});
        setPositionsInDashboard({});
        setPositionsInWorkflow({});
 
        setSuggestionsLeft(0);

    }

    // Considering provenance
    const deleteNode = (nodeId: string) => {
        const change: NodeRemoveChange = {
            id: nodeId,
            type: "remove",
        };

        onNodesDelete([change]);
    };

    // Go through all suggestions and flag the nodes that do not dependent on any other node in workflow suggestions
    const flagAcceptableSuggestions = (nodes: any, edges: any) => {
        
        let dependOn = []; // all nodes that depend on some other node suggested node
        let suggestedNodes = []; // all ids of suggested nodes

        for(const node of nodes){
            if(node.data.suggestionType == "workflow"){
                suggestedNodes.push(node.id);
            }
        }

        setSuggestionsLeft(suggestedNodes.length); // Updating number of suggestions left

        for(const edge of edges){
            if(suggestedNodes.includes(edge.source)) // The node depends on some other suggested node
                dependOn.push(edge.target);
        }

        let nodesToUpdate = []; // Which nodes need to have their suggestionAcceptable flag flipped

        for(const node of nodes){
            if(!dependOn.includes(node.id) && node.data.suggestionType == "workflow"){ // It means that the node can be accepted as a suggestion
                if(!node.data.suggestionAcceptable) // Check if the flag needs to be flipped
                    nodesToUpdate.push(node.id);
            }else if(node.data.suggestionType == "connection"){ // Connection suggestions does not care about dependencies
                if(!node.data.suggestionAcceptable) // Check if the flag needs to be flipped
                    nodesToUpdate.push(node.id);
            }else{
                if(node.data.suggestionAcceptable) // Check if the flag needs to be flipped
                    nodesToUpdate.push(node.id);
            }
        }

        if(nodesToUpdate.length > 0){

            console.log("flagAcceptableSuggestions");
            setNodes(prevNodes => {
                let newNodes = [];
    
                for(const node of prevNodes){
                    let newNode = {...node};

                    if(nodesToUpdate.includes(newNode.id))
                        newNode.data.suggestionAcceptable = !newNode.data.suggestionAcceptable; // flip the flag

                    newNodes.push(newNode);
                }
    
                return newNodes;
            });
        }

    }

    // Accept the suggestion for adding a specific node
    const acceptSuggestion = (nodeId: string) => {

        console.log("acceptSuggestion");
        setNodes(prevNodes => {
            let newNodes = [];
            let suggestions = []; // ids of all suggestion nodes
            let acceptedConnectionSuggestion = false; // if a connection suggestion is accepted all others are canceled
            let acceptedConnectionSuggestionId = "";

            for(const node of prevNodes){

                let newNode = {...node};

                if(newNode.id == nodeId){
                    newNode.data.suggestionAcceptable = false;

                    if(newNode.data.suggestionType == "connection"){
                        acceptedConnectionSuggestion = true;
                        acceptedConnectionSuggestionId = newNode.id;
                    }

                    newNode.data.suggestionType = "none";

                    newBox(workflowNameRef.current, (newNode.type as string) + "-" + newNode.id); // Provenance of the accepted suggestion
                }

                newNodes.push(newNode);
            }
    
            let filteredNewNodes = newNodes.filter((node) => { // if acceptedConnectionSuggestion remove the other connection suggestions
                return !(node.data.suggestionType == "connection" && acceptedConnectionSuggestion)
            }); 

            for(const node of filteredNewNodes){
                if(node.data.suggestionType != "none" && node.data.suggestionType != undefined) // it is a suggestion
                    suggestions.push(node.id);
            }

            setEdges(prevEdges => {
                let newEdges = [];

                for(const edge of prevEdges){
                    let newEdge = {...edge};

                    if(!(acceptedConnectionSuggestion && newEdge.data.suggestionType == "connection") || (acceptedConnectionSuggestionId == newEdge.source || acceptedConnectionSuggestionId == newEdge.target)){ // if a connection suggestion was accepted only maintain the edge that connects the suggestion
                        if(!suggestions.includes(edge.source) && !suggestions.includes(edge.target)) // if the source and target of an edge is not suggestion, the edge is not suggestion anymore
                            newEdge.data.suggestionType = "none";
    
                        newEdges.push(newEdge);
                    }

                }

                return newEdges;
            })

            return filteredNewNodes;
        });

    }

    // If keywordIndex is undefied all components are unflagged
    const flagBasedOnKeyword = (keywordIndex?: number) => {
        console.log("flagBasedOnKeyword");
        setNodes(prevNodes => {
            let newNodes = [];

            for(const node of prevNodes){
                let newNode = {...node};

                if(newNode.data.keywords != undefined && keywordIndex != undefined && newNode.data.keywords.includes(keywordIndex))
                    newNode.data.keywordHighlighted = true;
                else
                    newNode.data.keywordHighlighted = false;

                newNodes.push(newNode);
            }

            return newNodes;
        });
    
        setEdges(prevEdges =>
            prevEdges.map(edge => ({
              ...edge,
              data: {
                ...edge.data,
                keywordHighlighted:
                  edge.data.keywords !== undefined &&
                  keywordIndex !== undefined &&
                  edge.data.keywords.includes(keywordIndex),
              },
            }))
          );

    }

    useEffect(() => {
        flagAcceptableSuggestions(nodes, edges);
    }, [nodes, edges]);

    // Erase all nodes and edges that are suggestions if the use added a node or an edge
    const eraseWorkflowSuggestions = () => {
        
        setEdges(prevEdges => {
            let newEdges = [];

            for(const edge of prevEdges){
                if(edge.data.suggestionType != "workflow"){
                    newEdges.push({...edge});
                }
            }

            return newEdges;
        });

        setEdges((prevEdges: any) => { // Making sure that the removal of nodes happen after the removal of nodes
            console.log("eraseWorkflowSuggestions");
            setNodes((prevNodes: any) => {
                let newNodes = [];
    
                for(const node of prevNodes){
                    if(node.data.suggestionType != "workflow"){
                        let copy_node = {...node};
                        copy_node.data.suggestionAcceptable = false; // The node is not a suggestion. Reseting the flag.

                        newNodes.push({...copy_node});
                    }
                }
    
                return newNodes;
            });

            return prevEdges;
        });

        setSuggestionsLeft(0);
    }
    
    const setDashBoardMode = (value: boolean) => {
        console.log(`=== Dashboard mode ${value ? 'enabled' : 'disabled'} ===`);
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
                const nodesWithWorkflowPositions = nds.map(node => {
                    const workflowPos = node.data.workflowPosition || node.position;
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            workflowPosition: workflowPos
                        }
                    };
                });
                
                console.log('Applying dashboard layout to nodes:', nodesWithWorkflowPositions.length);
                console.log('Dashboard pins:', dashboardPins);
                
                // Apply the dashboard layout to pinned nodes
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
                            dashboardPosition: undefined
                        }
                    };
                });
                console.log('Nodes after reset:', resetNodes);
                return resetNodes;
            });
        }
    };

    const updatePositionDashboard = (nodeId: string, position: { x: number; y: number }) => {
        setPositionsInDashboard((prev: any) => ({
            ...prev,
            [nodeId]: position
        }));
    };

    const updatePositionWorkflow = (nodeId: string, change: any) => {
        setPositionsInWorkflow((prev: any) => ({
            ...prev,
            [nodeId]: change
        }));
    };

    const setPinForDashboard = (nodeId: string, value: boolean) => {
        let newDashboardPins: any = {};
        let nodesIds = Object.keys(dashboardPins);

        for (const id of nodesIds) {
            newDashboardPins[id] = dashboardPins[id];
        }

        newDashboardPins[nodeId] = value;

        setDashboardPins(newDashboardPins);
    };

    const addNode = useCallback(
        (node: Node, customWorkflowName?: string, provenance?: boolean) => {
            console.log("add node");
            setNodes((prev: any) => {
                node.position
                updatePositionWorkflow(node.id, {
                    id: node.id,
                    dragging: true,
                    position: { ...node.position },
                    positionAbsolute: { ...node.position },
                    type: "position"
                });
                return prev.concat(node)
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

        let getOutput = outId;
        let setInput = inId;

        let output = "";

        setOutputs((opts: any) =>
            opts.map((opt: any) => {
                if (opt.nodeId == getOutput) {
                    output = opt.output;
                }

                return opt;
            })
        );

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (node.id == setInput) {
                    // Merge Flow box is the only box that allows multiple 'in' connections
                    if (inBox == BoxType.MERGE_FLOW) {
                        // Initialize fixed-size arrays for position-semantic behavior
                        let inputList = Array.isArray(node.data.input) ? [...node.data.input] : [undefined, undefined];
                        let sourceList = Array.isArray(node.data.source) ? [...node.data.source] : [undefined, undefined];

                        // Ensure arrays are exactly size 5
                        while (inputList.length < 6) inputList.push(undefined);
                        while (sourceList.length < 6) sourceList.push(undefined);

                        const match = targetHandle?.match(/^in_(\d)$/);
                        const handleIndex = match ? parseInt(match[1], 10) : -1;

                        if (handleIndex >= 0) {
                            while (inputList.length <= handleIndex) inputList.push(undefined);
                            while (sourceList.length <= handleIndex) sourceList.push(undefined);

                            inputList[handleIndex] = output;
                            sourceList[handleIndex] = getOutput;
                        }

                        node.data = {
                            ...node.data,
                            input: inputList,
                            source: sourceList,
                        };
                    } else {
                        node.data = {
                            ...node.data,
                            input: output,
                            source: getOutput,
                        };
                    }
                }

                return node;
            })
        );
    };

    const onEdgesDelete = useCallback(
        (connections: Edge[]) => {
            for (const connection of connections) {
                let resetInput = connection.target;
                let targetNode = reactFlow.getNode(connection.target) as Node;

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
                            if (node.id == resetInput) {
                                if (targetNode.type === BoxType.MERGE_FLOW) {
                                    let inputList = Array.isArray(node.data.input) ? [...node.data.input] : [undefined, undefined];
                                    let sourceList = Array.isArray(node.data.source) ? [...node.data.source] : [undefined, undefined];

                                    while (inputList.length < 6) inputList.push(undefined);
                                    while (sourceList.length < 6) sourceList.push(undefined);

                                    const match = connection.targetHandle?.match(/^in_(\d)$/);
                                    const handleIndex = match ? parseInt(match[1], 10) : -1;



                                    if (handleIndex >= 0) {
                                        // Clear the specific position
                                        while (inputList.length <= handleIndex) inputList.push(undefined);
                                        while (sourceList.length <= handleIndex) sourceList.push(undefined);

                                        inputList[handleIndex] = undefined;
                                        sourceList[handleIndex] = undefined;
                                    }

                                    node.data = {
                                        ...node.data,
                                        input: inputList,
                                        source: sourceList,
                                    };
                                } else {
                                    node.data = {
                                        ...node.data,
                                        input: "",
                                        source: "",
                                    };
                                }
                            }

                            return node;
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
                "🔥 onConnect triggered:",
                connection.source,
                connection.sourceHandle,
                connection.target,
                connection.targetHandle
            );

            const nodes = custom_nodes ? custom_nodes : getNodes();
            const edges = custom_edges ? custom_edges : getEdges();
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

    const { getNodes, getEdges } = useReactFlow();

    // Checking for cycles and invalid connections between types of boxes
    const isValidConnection = useCallback(
        (connection: Connection) => {
            return true;
        },
        [getNodes, getEdges]
    );

    // a box generated a new output. Propagate it to directly connected boxes
    const applyNewOutput = (newOutput: IOutput) => {
        let nodesAffected: string[] = [];

        let edges = reactFlow.getEdges();

        for (let i = 0; i < edges.length; i++) {
            let targetId = edges[i].target;
            let sourceId = edges[i].source;

            if (
                edges[i].sourceHandle == "in/out" &&
                edges[i].targetHandle == "in/out"
            ) {
                // in 'in/out' connection a DATA_POOL is always some of the ends
                continue;
            }

            if (newOutput.nodeId == sourceId) {
                // directly affected by new output
                nodesAffected.push(targetId);
            }
        }

        setNodes((nds: any) =>
            nds.map((node: any) => {
                if (nodesAffected.includes(node.id)) {
                    if (node.type == BoxType.MERGE_FLOW) {
                        let inputList = Array.isArray(node.data.input) ? [...node.data.input] : [undefined, undefined];
                        let sourceList = Array.isArray(node.data.source) ? [...node.data.source] : [undefined, undefined];

                        while (inputList.length < 6) inputList.push(undefined);
                        while (sourceList.length < 6) sourceList.push(undefined);

                        for (let i = 0; i < sourceList.length; i++) {
                            if (sourceList[i] === newOutput.nodeId) {
                                inputList[i] = newOutput.output;
                                break;
                            }
                        }

                        node.data = {
                            ...node.data,
                            input: inputList,
                            source: sourceList,
                        };
                    } else {
                        if (newOutput.output == undefined) {
                            node.data = {
                                ...node.data,
                                input: "",
                                source: "",
                            };
                        } else {
                            node.data = {
                                ...node.data,
                                input: newOutput.output,
                                source: newOutput.nodeId,
                            };
                        }
                    }
                }

                return node;
            })
        );

        setOutputs((opts: any) => {
            let added = false;

            let newOpts = opts.map((opt: any) => {
                if (opt.nodeId == newOutput.nodeId) {
                    added = true;
                    return {
                        ...opt,
                        output: newOutput.output,
                    };
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
                    node.data = {
                        ...node.data,
                        interactions: toSend[node.id],
                    };
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
                    let newPropagation = true;
                    if (node.data.newPropagation != undefined) {
                        newPropagation = !node.data.newPropagation;
                    }

                    node.data = {
                        ...node.data,
                        propagation: { ...propagationObj.propagation },
                        newPropagation: newPropagation,
                    };
                } else {
                    node.data = {
                        ...node.data,
                        propagation: undefined,
                    };
                }

                return node;
            })
        );
    }, []);

    useEffect(() => {
        applyNewInteractions();
    }, [interactions]);

    const applyRemoveChanges = (changes: NodeRemoveChange[]) => {
        let allowedChanges: NodeRemoveChange[] = [];

        let edges = reactFlow.getEdges();

        for (const change of changes) {
            let allowed = true;

            for (const edge of edges) {
                if (
                    edge.source == change.id ||
                    edge.target == change.id
                ) {
                    alert(
                        "Connected boxes cannot be removed. Remove the edges first by selecting it and pressing backspace."
                    );
                    allowed = false;
                    break;
                }
            }

            if (allowed) allowedChanges.push(change);
        }

        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    };

    return (
        <FlowContext.Provider
            value={{
                nodes,
                edges,
                workflowNameRef,
                allMinimized,
                expandStatus,
                dashboardPins,
                suggestionsLeft,
                workflowGoal,
                loading,
                setWorkflowGoal,
                setExpandStatus,
                setOutputs,
                setInteractions,
                applyNewPropagation,
                addNode,
                onNodesChange,
                applyRemoveChanges,
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
                setWorkflowName,
                loadParsedTrill,
                updateDataNode,
                updateWarnings,
                updateDefaultCode,
                updateKeywords,
                updateSubtasks,
                cleanCanvas,
                flagBasedOnKeyword,
                acceptSuggestion,
                eraseWorkflowSuggestions,
                setAllMinimized
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