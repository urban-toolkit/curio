import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect } from "react";
import ReactFlow, {
    Background,
    ConnectionMode,
    Controls,
    Edge,
    EdgeChange,
    NodeChange,
    XYPosition,
    useReactFlow,
} from "reactflow";

import { useFlowContext } from "../providers/FlowProvider";
import { ToolsMenu } from "./tools-menu";
import ComputationAnalysisBox from "./ComputationAnalysisBox";
import DataTransformationBox from "./DataTransformationBox";
import { BoxType, EdgeType } from "../constants";
import DataLoadingBox from "./DataLoadingBox";
import VegaBox from "./VegaBox";
import TextBox from "./TextBox";
import DataExportBox from "./DataExportBox";
import DataCleaningBox from "./DataCleaning";
import FlowSwitchBox from "./FlowSwitch";
import UtkBox from "./UtkBox";
import TableBox from "./TableBox";
import ImageBox from "./ImageBox";
import ConstantBox from "./ConstantBox";
import { UserMenu } from "./login/UserMenu";
import DataPoolBox from "./DataPoolBox";
import BiDirectionalEdge from "./edges/BiDirectionalEdge";
import MergeFlowBox from "./MergeFlowBox";
import { RightClickMenu } from "./styles";
import CommentsBox from "./CommentsBox";
import { useRightClickMenu } from "../hook/useRightClickMenu";
import { useCode } from "../hook/useCode";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { buttonStyle } from "./styles";

import './MainCanvas.css';
import WorkflowList from "./WorkFlowList";
import { useWorkFlowContext } from "../providers/WorkflowProvider";
import { faL } from "@fortawesome/free-solid-svg-icons";
import { useUserContext } from "../providers/UserProvider";

export function MainCanvas() {
    const {
        nodes,
        edges,
        onNodesChange,
        onEdgesChange,
        onConnect,
        isValidConnection,
        onEdgesDelete,
        onNodesDelete,
    } = useFlowContext();

    const { onContextMenu, showMenu, menuPosition } = useRightClickMenu();
    const { createCodeNode } = useCode();
   
    let objectTypes: any = {};
    objectTypes[BoxType.COMPUTATION_ANALYSIS] = ComputationAnalysisBox;
    objectTypes[BoxType.DATA_TRANSFORMATION] = DataTransformationBox;
    objectTypes[BoxType.DATA_LOADING] = DataLoadingBox;
    objectTypes[BoxType.VIS_VEGA] = VegaBox;
    objectTypes[BoxType.VIS_TEXT] = TextBox;
    objectTypes[BoxType.DATA_EXPORT] = DataExportBox;
    objectTypes[BoxType.DATA_CLEANING] = DataCleaningBox;
    objectTypes[BoxType.FLOW_SWITCH] = FlowSwitchBox;
    objectTypes[BoxType.VIS_UTK] = UtkBox;
    objectTypes[BoxType.VIS_TABLE] = TableBox;
    objectTypes[BoxType.VIS_IMAGE] = ImageBox;
    objectTypes[BoxType.CONSTANTS] = ConstantBox;
    objectTypes[BoxType.DATA_POOL] = DataPoolBox;
    objectTypes[BoxType.MERGE_FLOW] = MergeFlowBox;

    const nodeTypes = useMemo(() => objectTypes, []);

    let objectEdgeTypes: any = {};
    objectEdgeTypes[EdgeType.BIDIRECTIONAL_EDGE] = BiDirectionalEdge;

    const edgeTypes = useMemo(() => objectEdgeTypes, []);

    const reactFlow = useReactFlow();
    const { setDashBoardMode, updatePositionWorkflow, updatePositionDashboard } = useFlowContext();

    const [selectedEdgeId, setSelectedEdgeId] = useState<string>(""); // can only remove selected edges
    
    const [dashboardOn, setDashboardOn] = useState<boolean>(false); 

    const [newEdges, setNewEdges] = useState(edges); 

    const { workflowName, workflowID, setWorkflowID, setWorkflowName, getWorkflowNames } = useWorkFlowContext();



    useEffect(() => {
        setNewEdges(prevEdges => {
            const existingIds = new Set(prevEdges.map(edge => edge.id));
            const uniqueEdges = edges.filter(edge => !existingIds.has(edge.id));
    
            return [
                ...prevEdges,
                ...uniqueEdges 
            ];
        });
    }, [edges]);


    //Recreate workflow using DB
    useEffect(() => {
        console.log("New Workflow Name:", workflowName, "Workflow ID:", workflowID);
        if (workflowName !== "" && workflowID !== "-1") {
            fetch(`http://localhost:5002/getActivitiesByWorkflowIds?workflow_id=${workflowID}`)
                .then(async (response) => {
                    if (!response.ok) {
                        throw new Error('Response was not ok');
                    }
                    return response.json();
                })
                .then((workflow) => {
                    let x = 100
                    let y = 100
                    workflow.reverse().forEach((node: any) => { //Reversing to plot in the right position
                        let boxType: string = node.activity_name.replace(/[^A-Z_]+/, '').slice(0, -1);
                        let node_id: string = node.activity_name.replace(/[A-Z_]/g, '');


                        createCodeNode(boxType, null, node_id, node.code, false, {x:x,y:y})

                        x = x + 800

                        if (node.input_relation_id) {
                            let input_relation_id = node.input_relation_id
                            let activity_input = node_id
                            let activity_output = workflow.find((item: any) => item.output_relation_id === input_relation_id)['activity_name'].replace(/[A-Z_]/g, '')

                            setNewEdges(
                                prevEdges => [
                                    ...prevEdges,
                                    {
                                        "source": activity_output,
                                        "sourceHandle": "out",
                                        "target": activity_input,
                                        "targetHandle": "in",
                                        "markerEnd": {
                                            "type": "arrow"
                                        },
                                        "id": `reactflow__edge-${activity_input}out${activity_output}in`,
                                        "selected": true
                                    } as unknown as Edge
                                ]
                            );
                        }
                    })
                })
        }
    }, [workflowName, workflowID]);


    return (
        <div style={{ width: "100vw", height: "100vh" }} onContextMenu={onContextMenu}>
            <ReactFlow
                nodes={nodes}
                edges={newEdges}
                onNodesChange={(changes: NodeChange[]) => {

                    let allowedChanges: NodeChange[] = [];

                    let edges = reactFlow.getEdges();

                    for (const change of changes) {
                        let allowed = true;

                        if(change.type == "remove"){
                            for (const edge of edges) {
                                if (edge.source == change.id || edge.target == change.id){
                                    alert("Connect boxes cannot be removed. Remove the edges first");
                                    allowed = false;
                                    break
                                }
                            }
                        }

                        if(change.type == "position" && change.position != undefined && change.position.x != undefined){
                            if(dashboardOn)
                                updatePositionDashboard(change.id, change);
                            else
                                updatePositionWorkflow(change.id, change);
                        }

                        if(allowed)
                            allowedChanges.push(change);
                    }

                    onNodesDelete(allowedChanges);
                    return onNodesChange(allowedChanges);
                }}
                onEdgesChange={(changes: EdgeChange[]) => {
                    let selected = "";
                    let allowedChanges = [];

                    for(const change of changes){
                        if(change.type == "select" && change.selected == true){
                            setSelectedEdgeId(change.id);
                            selected = change.id;
                        }else if(change.type == "select"){
                            setSelectedEdgeId("");
                            selected = "";
                        }
                    }

                    for(const change of changes){
                        if(change.type == "remove" && (selected == change.id || selectedEdgeId == change.id)){
                            allowedChanges.push(change);
                        }else if(change.type != "remove"){
                            allowedChanges.push(change);
                        }
                    }

                    return onEdgesChange(allowedChanges);
                }}
                onEdgesDelete={(edges: Edge[]) => {
                
                    console.log("edges", edges);

                    let allowedEdges: Edge[] = [];

                    for(const edge of edges){
                        if(selectedEdgeId == edge.id){
                            allowedEdges.push(edge);
                        }
                    }

                    return onEdgesDelete(allowedEdges);
                }}
                onConnect={onConnect}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                isValidConnection={isValidConnection}
                connectionMode={ConnectionMode.Loose}
                fitView
            >
                <UserMenu />
                <div style={{ position: "absolute", top: "10px", left: "10px", zIndex: 100 }}>
                    <ToolsMenu />
                    <div style={{ marginTop: "500px" }}>
                        <WorkflowList
                            onSelectWorkflow={(workflowID: string, workflowName: string): void => {
                                setWorkflowName(workflowName);
                                setWorkflowID(workflowID);
                            }}
                        />
                    </div>
                </div>
                <RightClickMenu
                  showMenu={showMenu}
                  menuPosition={menuPosition}
                  options={[
                    {
                      name: "Add comment box",
                      action: () => createCodeNode("COMMENTS"),
                    },
                  ]}
                />
                <button className="nowheel nodrag" style={{...buttonStyle, position: "fixed", right: "10px", color: "#888787", fontWeight: "bold", bottom: "20px", zIndex: 100, ...(dashboardOn ? {boxShadow: "0px 0px 5px 0px red"} : {boxShadow: "0px 0px 5px 0px black"})}} onClick={() => {setDashBoardMode(!dashboardOn); setDashboardOn(!dashboardOn);}}>Dashboard mode</button>
                <Background />
                <Controls />
            </ReactFlow>
        </div>
    );
}
