import "reactflow/dist/style.css";
import React, { useMemo, useState, useEffect } from "react";
import ReactFlow, {
    Background,
    ConnectionMode,
    Controls,
    Edge,
    EdgeChange,
    NodeChange,
    useReactFlow,
} from "reactflow";

import { useFlowContext } from "../providers/FlowProvider";
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
import { ToolsMenu, UpMenu } from "components/menus";
import UniDirectionalEdge from "./edges/UniDirectionalEdge";
import "./MainCanvas.css";

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
    objectEdgeTypes[EdgeType.UNIDIRECTIONAL_EDGE] = UniDirectionalEdge;

    const edgeTypes = useMemo(() => objectEdgeTypes, []);

    const reactFlow = useReactFlow();
    const {screenToFlowPosition} = useReactFlow();

    const {
        setDashBoardMode,
        updatePositionWorkflow,
        updatePositionDashboard,
    } = useFlowContext();

    const [selectedEdgeId, setSelectedEdgeId] = useState<string>(""); // can only remove selected edges

    const [dashboardOn, setDashboardOn] = useState<boolean>(false);
    const { dashboardPins } = useFlowContext();

    // Apply dashboard mode changes
    const handleDashboardToggle = (value: boolean) => {
        setDashboardOn(value);
        setDashBoardMode(value);
    };

    // Filter nodes based on dashboard mode
    const filteredNodes = useMemo(() => {
        if (!dashboardOn) return nodes;
        return nodes.filter(node => dashboardPins[node.id]);
    }, [nodes, dashboardOn, dashboardPins]);

    const [fileMenuOpen, setFileMenuOpen] = useState(false);
    const closeFileMenu = () => setFileMenuOpen(false);
    return (
        <div
            style={{ width: "100vw", height: "100vh" }}
            onContextMenu={onContextMenu}
            onClick={closeFileMenu}
        >
            <ReactFlow
                nodes={filteredNodes}
                edges={edges}
                onDragOver={(event) => {
                    event.preventDefault();
                    event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => {
                    event.preventDefault();
            
                    const type = event.dataTransfer.getData("application/reactflow") as BoxType;
                    if (!type) return;
            
                    // const bounds = event.currentTarget.getBoundingClientRect();
                    // const position = {
                    //     x: event.clientX,
                    //     y: event.clientY,
                    // };

                    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
            
                    createCodeNode(type, {position})
                }}
                onNodesChange={(changes: NodeChange[]) => {

                    let allowedChanges: NodeChange[] = [];

                    let edges = reactFlow.getEdges();

                    for (const change of changes) {
                        let allowed = true;

                        if (change.type == "remove") {
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
                        }

                        if (
                            change.type == "position" &&
                            change.position != undefined &&
                            change.position.x != undefined
                        ) {
                            if (dashboardOn)
                                updatePositionDashboard(change.id, change);
                            else updatePositionWorkflow(change.id, change);
                        }

                        if (allowed) allowedChanges.push(change);
                    }

                    onNodesDelete(allowedChanges);
                    return onNodesChange(allowedChanges);
                }}
                onEdgesChange={(changes: EdgeChange[]) => {
                    let selected = "";
                    let allowedChanges = [];

                    for (const change of changes) {
                        if (
                            change.type == "select" &&
                            change.selected == true
                        ) {
                            setSelectedEdgeId(change.id);
                            selected = change.id;
                        } else if (change.type == "select") {
                            setSelectedEdgeId("");
                            selected = "";
                        }
                    }

                    for (const change of changes) {
                        if (
                            change.type == "remove" &&
                            (selected == change.id ||
                                selectedEdgeId == change.id)
                        ) {
                            allowedChanges.push(change);
                        } else if (change.type != "remove") {
                            allowedChanges.push(change);
                        }
                    }

                    return onEdgesChange(allowedChanges);
                }}
                onEdgesDelete={(edges: Edge[]) => {
                    console.log("edges", edges);

                    let allowedEdges: Edge[] = [];

                    for (const edge of edges) {
                        if (selectedEdgeId == edge.id) {
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
                minZoom={0.05}
                fitView
            >
                <UserMenu />
                <ToolsMenu />
                <UpMenu 
                    setDashBoardMode={(value) => handleDashboardToggle(value)}
                    setDashboardOn={handleDashboardToggle}
                    dashboardOn={dashboardOn}
                    fileMenuOpen={fileMenuOpen}
                    setFileMenuOpen={setFileMenuOpen}
                />
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
                <Background />
                <Controls />
            </ReactFlow>
            <input hidden type="file" name="file" id="file" />

        </div>
    );
}