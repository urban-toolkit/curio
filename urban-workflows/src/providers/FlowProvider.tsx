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
    applyNodeChanges
} from "reactflow";
import { ConnectionValidator } from "../ConnectionValidator";
import { BoxType, EdgeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "./ProvenanceProvider";
import { useWorkFlowContext } from "./WorkflowProvider";
import { useUserContext } from "./UserProvider";

export interface IOutput {
    nodeId: string;
    output: string;
}

export interface IInteraction{
    nodeId: string;
    details: any;
    priority: number; // used to solve conflicts of interactions 1 has more priority than 0
}

// propagating interactions between pools at different resolutions
export interface IPropagation{
    nodeId: string;
    propagation: any; // {[index]: [interaction value]}
}

// applyNewOutputs = useCallback((newOutNodeId: string, newOutput: string)

interface FlowContextProps {
    nodes: Node[];
    edges: Edge[];
    workflowName: string;
    setOutputs: (updateFn: (outputs: IOutput[]) => IOutput[]) => void;
    setInteractions: (updateFn: (interactions: IInteraction[]) => IInteraction[]) => void;
    applyNewPropagation: (propagation: IPropagation) => void;
    addNode: (node: Node, saveProvDB: boolean) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection) => void;
    isValidConnection: (connection: Connection) => boolean;
    onEdgesDelete: (connections: Edge[]) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    setPinForDashboard: (nodeId: string, value: boolean) => void;
    setDashBoardMode: (value: boolean) => void;
    updatePositionWorkflow: (nodeId:string, position: any) => void;
    updatePositionDashboard: (nodeId:string, position: any) => void;
    applyNewOutput: (output: IOutput) => void;
}

export const FlowContext = createContext<FlowContextProps>({
    nodes: [],
    edges: [],
    workflowName: "DefaultWorkflow",
    setOutputs: () => { },
    setInteractions: () => {},
    applyNewPropagation: () => {},
    addNode: () => { },
    onNodesChange: () => { },
    onEdgesChange: () => { },
    onConnect: () => { },
    isValidConnection: () => true,
    onEdgesDelete: () => {},
    onNodesDelete: () => {},
    setPinForDashboard: () => {},
    setDashBoardMode: () => {},
    updatePositionWorkflow: () => {},
    updatePositionDashboard: () => {},
    applyNewOutput: () => {},
});

const FlowProvider = ({ children }: { children: ReactNode }) => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    
    const [outputs, setOutputs] = useState<IOutput[]>([]);

    const [interactions, setInteractions] = useState<IInteraction[]>([]);

    const [dashboardPins, setDashboardPins] = useState<any>({}); // {[nodeId] -> boolean}

    const [positionsInDashboard, _setPositionsInDashboard] = useState<any>({}); // [nodeId] -> change
    const positionsInDashboardRef = useRef(positionsInDashboard);
    const setPositionsInDashboard = (data: string) => {
        positionsInDashboardRef.current = data;
        _setPositionsInDashboard(data);
    };

    const [positionsInWorkflow, _setPositionsInWorkflow] = useState<any>({}); // [nodeId] -> change
    const positionsInWorkflowRef = useRef(positionsInWorkflow);
    const setPositionsInWorkflow = (data: string) => {
        positionsInWorkflowRef.current = data;
        _setPositionsInWorkflow(data);
    };

    const reactFlow = useReactFlow();
    const { newBox, addWorkflow, deleteBox, newConnection, deleteConnection } = useProvenanceContext();

    // const [workflowName, setWorkflowName] = useState<string>("DefaultWorkflow");
    const { workflowName, workflowID, setWorkflowID, setWorkflowName, getWorkflowNames } = useWorkFlowContext();
  
    useEffect(() => {
        if (workflowID === "-1") {
            addWorkflow(workflowName);
        }
    }, [workflowID, workflowName]);

    const setDashBoardMode = (value: boolean) => {

        // setNodes((nds: any) => 
        //     nds.map((node: any) => {
        //         if(dashboardPins[node.id] == true){
        //             node.data = {
        //                 ...node.data,
        //                 hidden: false
        //             };         
        //         }else{
        //             node.data = {
        //                 ...node.data,
        //                 hidden: value
        //             };    
        //         }

        //         // Detect nodes by having the class react-flow__node
        //         // The node id is in the attribute data-id

        //         let position = {...node.position};

        //         if(value){
        //             if(positionsInDashboardRef.current[node.id] != undefined){
        //                 position = {...positionsInDashboardRef.current[node.id]};
        //             }
        //         }else{
        //             if(positionsInWorkflowRef.current[node.id] != undefined){
        //                 position = {...positionsInWorkflowRef.current[node.id]};
        //             }
        //         }

        //         return {
        //             ...node, 
        //             position
        //         };
        //     })
        // );

        const nodesDiv = document.querySelectorAll('.react-flow__node');

        // Hide each element
        nodesDiv.forEach(element => {
            if(value){

                // @ts-ignore
                if(!dashboardPins[element.getAttribute('data-id')]){
                    // @ts-ignore
                    element.style.display = 'none';
                }else{
                    // @ts-ignore
                    element.style.display = 'block';

                    // @ts-ignore
                    if(positionsInDashboardRef.current[element.getAttribute('data-id')] != undefined){
                        setNodes((oldNodes) => {
                            // @ts-ignore
                            console.log(positionsInDashboardRef.current[element.getAttribute('data-id')]);
                            // @ts-ignore
                            return applyNodeChanges([positionsInDashboardRef.current[element.getAttribute('data-id')]], oldNodes)
                        });
                    }
                }
            }else{
                // @ts-ignore
                element.style.display = 'block';

                // @ts-ignore
                if(positionsInWorkflowRef.current[element.getAttribute('data-id')] != undefined){
                    // @ts-ignore
                    console.log(positionsInWorkflowRef.current[element.getAttribute('data-id')]);
                    // @ts-ignore
                    setNodes((oldNodes) => applyNodeChanges([positionsInWorkflowRef.current[element.getAttribute('data-id')]], oldNodes));
                }
            }
        });

        const edgesPath = document.querySelectorAll('.react-flow__edge-path');

        // Hide each element
        edgesPath.forEach(element => {
            if(value){
                // @ts-ignore
                element.style.display = 'none';
            }else{
                // @ts-ignore
                element.style.display = 'block';
            }
        });

        const edgesInteraction = document.querySelectorAll('.react-flow__edge-interaction');

        // Hide each element
        edgesInteraction.forEach(element => {
            if(value){
                // @ts-ignore
                element.style.display = 'none';
            }else{
                // @ts-ignore
                element.style.display = 'block';
            }
        });
    }

    const updatePositionWorkflow = (nodeId:string, change: any) => {
        setPositionsInWorkflow({
            ...positionsInWorkflowRef.current,
            [nodeId]: {...change}
        })
    }

    const updatePositionDashboard = (nodeId:string, change: any) => {
        setPositionsInDashboard({
            ...positionsInDashboardRef.current,
            [nodeId]: {...change}
        });
    }

    // TODO: implement listener for position changes in nodes. 

    const setPinForDashboard = (nodeId: string, value: boolean) => {
        let newDashboardPins: any = {};
        let nodesIds = Object.keys(dashboardPins);
        
        for(const id of nodesIds){
            newDashboardPins[id] = dashboardPins[id];
        }

        newDashboardPins[nodeId] = value;

        setDashboardPins(newDashboardPins);
    }

    const addNode = useCallback(
        (node: Node, saveProvDB: boolean) => {
            setNodes((prev: any) => {
                node.position
                updatePositionWorkflow(node.id, {
                    id: node.id,
                    dragging: true,
                    position: {...node.position},
                    positionAbsolute: {...node.position},
                    type: "position"
                });
                return prev.concat(node)
            });
            if(saveProvDB){
                newBox(workflowName, (node.type as string) + "_" + node.id, "");
            }
        },
        [setNodes,workflowName]
    );

    // updates a single box with the new input (new connections)
    const applyOutput = (inBox: BoxType, inId: string, outId: string, sourceHandle: string, targetHandle: string) => {
        
        if(sourceHandle == "in/out" && targetHandle == "in/out")
            return

        let getOutput = outId;
        let setInput = inId;

        let output = "";

        setOutputs((opts: any) => 
            opts.map((opt: any) => {

                if(opt.nodeId == getOutput){
                    output = opt.output;
                }

                return opt;
            })
        );

        setNodes((nds: any) => 
            nds.map((node: any) => {

                if(node.id == setInput){

                    // Merge Flow box is the only box that allows multiple 'in' connections
                    if(inBox == BoxType.MERGE_FLOW){
                        let inputList = node.data.input;
                        let sourceList = node.data.source;

                        if(inputList == undefined || inputList == ""){
                            inputList = [output];
                        }else{
                            inputList = [...inputList, output];
                        }

                        if(sourceList == undefined || sourceList == ""){
                            sourceList = [getOutput];
                        }else{
                            sourceList = [...sourceList, getOutput];
                        }

                        node.data = {
                            ...node.data,
                            input: inputList,
                            source: sourceList
                        };

                    }else{
                        node.data = {
                            ...node.data,
                            input: output,
                            source: getOutput
                        };
                    }
                }

                return node;
            })
        );

    }

    const onEdgesDelete = useCallback((connections: Edge[]) => {

        for(const connection of connections){

            let resetInput = connection.target;
            let targetNode = reactFlow.getNode(connection.target) as Node;

            // skiping syncronized connections
            if(connection.sourceHandle != "in/out" && connection.targetHandle != "in/out"){
                deleteConnection(workflowName, targetNode.id, targetNode.type as BoxType);
            }

            // skiping syncronized connections
            if(connection.sourceHandle != "in/out" || connection.targetHandle != "in/out"){
                setNodes((nds: any) => 
                    nds.map((node: any) => {
        
                        if(node.id == resetInput){
                            if(targetNode.type = BoxType.MERGE_FLOW){
                                let inputList: string[] = [];
                                let sourceList: string[] = [];

                                if(Array.isArray(node.data.source)){
                                    for(let i = 0; i < node.data.source.length; i++){
                                        if(connection.source != node.data.source[i]){
                                            inputList.push(node.data.input[i]);
                                            sourceList.push(node.data.source[i]);
                                        }
                                    }
                                }

                                node.data = {
                                    ...node.data,
                                    input: inputList,
                                    source: sourceList
                                };
                            }else{
                                node.data = {
                                    ...node.data,
                                    input: "",
                                    source: ""
                                };
                            }

                        }
        
                        return node;
                    })
                );
            }
        }

    }, [setNodes, workflowName]);

    const onNodesDelete = useCallback((changes: NodeChange[]) => {
        setOutputs((opts: any) => 
            opts.filter((opt: any) => {
                for(const change of changes){
                    // @ts-ignore
                    if(opt.nodeId == change.id && change.type == "remove"){ // node was removed
                        return false;
                    }
                }

                return true;
            })
        );

        for(const change of changes){
            if(change.type == "remove"){
                let node = reactFlow.getNode(change.id) as Node;
                deleteBox(workflowName, node.type+"_"+node.id);
            }
        }

    }, [setOutputs, workflowName]);

    const onConnect = useCallback(
        (connection: Connection) => {
            const nodes = getNodes();
            const edges = getEdges();
            const target = nodes.find(
                (node) => node.id === connection.target
            ) as Node;
            const hasCycle = (node: Node, visited = new Set()) => {
                if (visited.has(node.id)) return false;

                visited.add(node.id);

                for (const outgoer of getOutgoers(node, nodes, edges)) {
                    if (outgoer.id === connection.source) return true;
                    if (hasCycle(outgoer, visited)) return true;
                }
            };

            let validHandleCombination = true;

            if ((connection.sourceHandle == "in/out" && connection.targetHandle != "in/out") || (connection.targetHandle == "in/out" && connection.sourceHandle != "in/out")) {
                validHandleCombination = false;
                alert("An in/out connection can only be connected to another in/out connection");
            }else if((connection.sourceHandle == "in" && connection.targetHandle != "out") || (connection.targetHandle == "in" && connection.sourceHandle != "out")){
                validHandleCombination = false;
                alert("An in connection can only be connected to an out connection");
            }else if((connection.sourceHandle == "out" && connection.targetHandle != "in") || (connection.targetHandle == "out" && connection.sourceHandle != "in")){
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

                if (!allowConnection)
                    alert("Input and output types of these boxes are not compatible");

                // Checking cycles
                if (target.id === connection.source) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (hasCycle(target)) {
                    alert("Cycles are not allowed");
                    allowConnection = false;
                }

                if (allowConnection){
                    applyOutput(inBox as BoxType, connection.target as string, connection.source as string, connection.sourceHandle as string, connection.targetHandle as string);

                    setEdges((eds) => {

                        let customConnection: any = {
                            ...connection,
                            markerEnd: {type: MarkerType.Arrow}
                        };

                        if(connection.sourceHandle == "in/out" && connection.targetHandle == "in/out"){
                            customConnection.markerStart = {type: MarkerType.Arrow};
                            customConnection.type = EdgeType.BIDIRECTIONAL_EDGE;
                        }else{ // only do provenance for in and out connections
                            newConnection(workflowName, customConnection.source, outBox as BoxType, customConnection.target, inBox as BoxType);
                        }

                        return addEdge(customConnection, eds)
                    });
                } 
            }

        },
        [setEdges,workflowName]
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

            if(edges[i].sourceHandle == "in/out" && edges[i].targetHandle == "in/out"){ // in 'in/out' connection a DATA_POOL is always some of the ends
                continue;
            }

            if(newOutput.nodeId == sourceId){ // directly affected by new output
                nodesAffected.push(targetId);
            }
        }

        setNodes((nds: any) => 
            nds.map((node: any) => {

                if(nodesAffected.includes(node.id)){
                    if(node.type == BoxType.MERGE_FLOW){
                        
                        if(Array.isArray(node.data.input)){

                            let foundSource = false;
                            let inputList: string[] = [];
                            let sourceList: string[] = [];

                            for(let i = 0; i < node.data.input.length; i++){
                                if(node.data.source[i] == newOutput.nodeId){ // updating new value
                                    inputList.push(newOutput.output);
                                    sourceList.push(newOutput.nodeId);
                                    foundSource = true;
                                }else{
                                    inputList.push(node.data.input[i]);
                                    sourceList.push(node.data.source[i]);
                                }
                            }

                            if(!foundSource){ // adding new value
                                inputList.push(newOutput.output);
                                sourceList.push(newOutput.nodeId);
                            }

                            node.data = {
                                ...node.data,
                                input: inputList,
                                source: sourceList
                            };
                        }else{
                            node.data = {
                                ...node.data,
                                input: [newOutput.output],
                                source: [newOutput.nodeId]
                            };
                        }

                    }else{
                        if(newOutput.output == undefined){
                            node.data = {
                                ...node.data,
                                input: "",
                                source: ""
                            };
                        }else{
                            node.data = {
                                ...node.data,
                                input: newOutput.output,
                                source: newOutput.nodeId
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

                if(opt.nodeId == newOutput.nodeId){
                    added = true;
                    return {
                        ...opt,
                        output: newOutput.output
                    }
                }

                return opt;
            });

            if(!added)
                newOpts.push({...newOutput});

            return newOpts;
        });

    };

    // responsible for flow of already connected
    const applyNewInteractions = useCallback(() => {

        let newInteractions = interactions.filter((interaction) => {return interaction.priority == 1}); //priority == 1 means that this is a new or updated interaction 

        let toSend: any = {}; // {nodeId -> {type: VisInteractionType, data: any}}
        let interactedIds: string[] = newInteractions.map((interaction: IInteraction) => {return interaction.nodeId});
        let poolsIds: string[] = [];

        let interactionDict: any = {};

        for(const interaction of newInteractions){
            interactionDict[interaction.nodeId] = {details: interaction.details, priority: interaction.priority};
        }

        for(let i = 0; i < nodes.length; i++){
            if(nodes[i].type == BoxType.DATA_POOL){
                poolsIds.push(nodes[i].id);
            }
        }

        for(let i = 0; i < edges.length; i++){

            let targetNode = reactFlow.getNode(edges[i].target) as Node;
            let sourceNode = reactFlow.getNode(edges[i].source) as Node;

            if(edges[i].sourceHandle == "in/out" && edges[i].targetHandle == "in/out" && !(targetNode.type == BoxType.DATA_POOL && sourceNode.type == BoxType.DATA_POOL)){
                if(interactedIds.includes(edges[i].source) && poolsIds.includes(edges[i].target)){ // then the target is the pool
                    
                    if(toSend[edges[i].target] == undefined){
                        toSend[edges[i].target] = [interactionDict[edges[i].source]];
                    }else{
                        toSend[edges[i].target].push(interactionDict[edges[i].source])
                    }
                }else if(interactedIds.includes(edges[i].target) && poolsIds.includes(edges[i].source)){ // then the source is the pool
                    if(toSend[edges[i].source] == undefined){
                        toSend[edges[i].source] = [interactionDict[edges[i].target]];
                    }else{
                        toSend[edges[i].source].push(interactionDict[edges[i].target])
                    }
                }
            }
        }

        setNodes((nds: any) => 
            nds.map((node: any) => {

                if(toSend[node.id] != undefined){

                    node.data = {
                        ...node.data,
                        interactions: toSend[node.id]
                    }
                }
               
                return node;
            })
        );

    }, [interactions]);

    // propagations only happen with in/out
    const applyNewPropagation = useCallback((propagationObj: IPropagation) => {

        let sendTo: string[] = [];

        let edges = reactFlow.getEdges();

        for(const edge of edges){
            if(edge.target == propagationObj.nodeId || edge.source == propagationObj.nodeId){ // if one of the extremities of the edge is responsible for the propagation
                let targetNode = reactFlow.getNode(edge.target) as Node;
                let sourceNode = reactFlow.getNode(edge.source) as Node;
    
                if(edge.sourceHandle == "in/out" && edge.targetHandle == "in/out" && targetNode.type == BoxType.DATA_POOL && sourceNode.type == BoxType.DATA_POOL){
                    if(edge.target != propagationObj.nodeId){
                        sendTo.push(edge.target);    
                    }

                    if(edge.source != propagationObj.nodeId){
                        sendTo.push(edge.source);    
                    }
                }
            }
        }

        setNodes((nds: any) => 
            nds.map((node: any) => {

                if(sendTo.includes(node.id)){

                    let newPropagation = true;
                    if(node.data.newPropagation != undefined){
                        newPropagation = !node.data.newPropagation;
                    }

                    node.data = {
                        ...node.data,
                        propagation: {...propagationObj.propagation},
                        newPropagation: newPropagation
                    }
                }else{
                    node.data = {
                        ...node.data,
                        propagation: undefined
                    }
                }

                return node;
            })
        );

    }, []);

    useEffect(() => {
        applyNewInteractions();
    }, [interactions]);


    const [lastCode, setLastCode] = useState<{ [key: string]: string }>({});

    useEffect(() => {
        const updateBoxCode = (batchData) => {
            if (batchData.length > 0) {
                fetch(process.env.BACKEND_URL + "/updateBoxCode", {
                    method: "POST",
                    body: JSON.stringify({ data: batchData }),
                    headers: {
                        "Content-type": "application/json; charset=UTF-8",
                    }
                });
            }
        };
    
        const intervalId = setInterval(() => {
            let batchData = [];
            let hasChanges = false;
    
            nodes.forEach(node => {
                const activityKey = `${node.type}_${node.id}`;
                const currentCode = node?.data?.code;
    
                if (lastCode[activityKey] !== currentCode) {
                    if(lastCode[activityKey]!== undefined) {
                        hasChanges = true;
                    }
                    setLastCode(prevState => {
                        const updatedState = { ...prevState };
                        nodes.forEach(node => {
                            updatedState[`${node.type}_${node.id}`] = node?.data?.code;
                        });
                        return updatedState;
                    });
                }
            });
    
            if (hasChanges) {
                batchData = nodes.map(node => ({
                    workflow_name: workflowName,
                    activity_name: `${node.type}_${node.id}`,
                    code: node?.data?.code
                }));

                updateBoxCode(batchData);
            }
        }, 100 * 60);
    
        return () => clearInterval(intervalId);
    }, [nodes, lastCode,workflowName]);


    return (
        <FlowContext.Provider
            value={{
                nodes,
                edges,
                workflowName,
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
