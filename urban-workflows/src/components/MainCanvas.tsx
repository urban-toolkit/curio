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

import ProjectList from "./ProjectList";

import './MainCanvas.css';


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

    const [selectedProject, setSelectedProject] = useState<string>("");

    const handleProjectSelect = (projectName: string) => {
      setSelectedProject(projectName);
      console.log("Project:", projectName);
    };
   
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

    const [previousProject, setPreviousProject] = useState("");

    const [newEdges, setNewEdges] = useState(edges); 

    const [nodeTexts, setNodeTexts] = useState({});

    function separateEdgeId(edgeId:any) {
        const parts = edgeId.split(/out|in/);
        
        const result = {
            in: null,
            out: null
        };
    
        if (parts[0]?.trim()) {
            result.in = parts[0].trim().replace(/^reactflow__edge-/, '').replace(/^[-]+/, ''); 
        }
        if (parts[1]?.trim()) {
            result.out = parts[1].trim().replace(/^reactflow__edge-/, '').replace(/^[-]+/, ''); 
        }
    
        return result;
    }
    

    useEffect(() => {
        if (selectedProject && selectedProject !== previousProject) {
            fetch(`http://localhost:5002/getProjectItems?name=${selectedProject}`)
                .then(async (response) => {
                    if (!response.ok) {
                        throw new Error('response was not ok');
                    }
                    return response.json();
                })
                .then((project) => {
                    project.forEach((item) => {
                        createCodeNode(item.boxType, null, true, item.id, item.code);

                        if (item.dependency) {
                            console.log(item)
                            const infos = separateEdgeId(item.dependency)
                            console.log(infos)
                            setNewEdges(
                                prevEdges => [
                                    ...prevEdges,
                                    {
                                        "source": infos.in,
                                        "sourceHandle": "out",
                                        "target": infos.out,
                                        "targetHandle": "in",
                                        "markerEnd": {
                                            "type": "arrow"
                                        },
                                        "id": item.dependency,
                                        "selected": true
                                    } as unknown as Edge
                                ]
                            );
                        }
                    });


                })
                .catch((error) => {
                    console.error('Error fetching project items:', error);
                });

            setPreviousProject(selectedProject);

        }
    }, [selectedProject, previousProject]);





    useEffect(() => {
        console.log(edges);
        setNewEdges(prevEdges => {
            // Cria um conjunto de IDs já existentes
            const existingIds = new Set(prevEdges.map(edge => edge.id));
    
            // Filtra as novas arestas para incluir apenas aquelas com IDs únicos
            const uniqueEdges = edges.filter(edge => !existingIds.has(edge.id));
    
            return [
                ...prevEdges,
                ...uniqueEdges 
            ];
        });
    }, [edges]);

    








    // useEffect(() => {
    //     let observer;
    
    //     let observerCallback = (mutationsList) => {
    //         mutationsList.forEach((mutation) => {
    //             let updateNodeText = (dataId, textContent) => {
    //                 if (dataId) {
    //                     let timestamp = new Date().toISOString(); // Obtém a data e hora atual
    //                     setNodeTexts((prevState) => ({
    //                         ...prevState,
    //                         [dataId]: {
    //                             text: textContent,
    //                             updatedAt: timestamp,
    //                         },
    //                     }));
    //                 }
    //             };
    
    //             // Captura e concatena textos dentro da div.view-lines
    //             if (
    //                 mutation.type === "childList" &&
    //                 mutation.target.classList.contains("view-lines")
    //             ) {
    //                 let viewLinesDiv = mutation.target;
    //                 let ancestorDiv = viewLinesDiv.closest(
    //                     "div[class*='react-flow__node react-flow__node']"
    //                 );
    
    //                 if (ancestorDiv && ancestorDiv.hasAttribute("data-id")) {
    //                     let dataId = ancestorDiv.getAttribute("data-id");
    //                     // Concatena textos de cada div.view-line com um '\n' entre elas
    //                     let concatenatedText = Array.from(
    //                         viewLinesDiv.querySelectorAll("div.view-line")
    //                     )
    //                         .map((viewLine) =>
    //                             Array.from(
    //                                 viewLine.querySelectorAll("span[class^='mtk']")
    //                             )
    //                                 .map((span) => span.textContent)
    //                                 .join("") // Concatena texto de todos os spans em uma única linha
    //                         )
    //                         .join("\n"); // Adiciona uma nova linha entre as view-lines
    
    //                     updateNodeText(dataId, concatenatedText);
    //                 }
    //             }
    
    //             // Captura e concatena textos dentro das div.ace_line
    //             if (
    //                 mutation.type === "childList" &&
    //                 mutation.target.classList.contains("ace_line")
    //             ) {
    //                 let aceLineParent = mutation.target.parentNode;
    //                 let ancestorDiv = aceLineParent.closest(
    //                     "div[class*='react-flow__node react-flow__node']"
    //                 );
    
    //                 if (ancestorDiv && ancestorDiv.hasAttribute("data-id")) {
    //                     let dataId = ancestorDiv.getAttribute("data-id");
    //                     let concatenatedText = Array.from(
    //                         aceLineParent.querySelectorAll(".ace_line")
    //                     )
    //                         .map((aceLine) => aceLine.textContent)
    //                         .join("\n");
    
    //                     updateNodeText(dataId, concatenatedText);
    //                 }
    //             }
    //         });
    //     };
    
    //     observer = new MutationObserver(observerCallback);
    
    //     observer.observe(document.body, {
    //         childList: true,
    //         subtree: true,
    //         characterData: true,
    //     });
    
    //     return () => {
    //         if (observer) observer.disconnect();
    //     };
    // }, []); // Garante execução única devido ao array de dependências vazio.
    
    
    
    // useEffect(() => {
    //     let observer;
    
    //     let observerCallback = (mutationsList) => {
    //         mutationsList.forEach((mutation) => {
    //             let updateNodeText = (dataId, textContent) => {
    //                 if (dataId) {
    //                     let timestamp = new Date().toISOString(); // Obtém a data e hora atual
    //                     setNodeTexts((prevState) => ({
    //                         ...prevState,
    //                         [dataId]: {
    //                             text: textContent,
    //                             updatedAt: timestamp,
    //                         },
    //                     }));
    //                 }
    //             };
    
    //             // Captura e concatena textos dentro das div.ace_line_group
    //             if (
    //                 mutation.type === "childList" &&
    //                 mutation.target.classList.contains("ace_line_group")
    //             ) {
    //                 let aceLineGroupDiv = mutation.target;
    //                 let ancestorDiv = aceLineGroupDiv.closest(
    //                     "div[class*='react-flow__node react-flow__node']"
    //                 );
    
    //                 if (ancestorDiv && ancestorDiv.hasAttribute("data-id")) {
    //                     let dataId = ancestorDiv.getAttribute("data-id");
    
    //                     // Processa todos os ace_line_group
    //                     let concatenatedText = Array.from(
    //                         document.querySelectorAll("div.ace_line_group")
    //                     )
    //                         .map((lineGroup) =>
    //                             Array.from(lineGroup.querySelectorAll("div.ace_line"))
    //                                 .map((aceLine) =>
    //                                     Array.from(aceLine.childNodes)
    //                                         .map((node) =>
    //                                             node.nodeType === Node.TEXT_NODE
    //                                                 ? node.textContent.trim() // Texto direto no nó
    //                                                 : node.textContent // Texto de elementos
    //                                         )
    //                                         .join("") // Concatena texto dentro de ace_line
    //                                 )
    //                                 .join(" ") // Concatena texto entre ace_line com espaços
    //                         )
    //                         .join("\n"); // Adiciona uma nova linha entre ace_line_group
    
    //                     updateNodeText(dataId, concatenatedText);
    //                 }
    //             }
    //         });
    //     };
    
    //     observer = new MutationObserver(observerCallback);
    
    //     observer.observe(document.body, {
    //         childList: true,
    //         subtree: true,
    //         characterData: true,
    //     });
    
    //     return () => {
    //         if (observer) observer.disconnect();
    //     };
    // }, []); // Garante execução única devido ao array de dependências vazio.
    



    useEffect(() => {
        let observer;
    
        const observerCallback = (mutationsList) => {
            mutationsList.forEach((mutation) => {
                const updateNodeText = (dataId, textContent) => {
                    if (dataId) {
                        const timestamp = new Date().toISOString(); // Obtém a data e hora atual
                        setNodeTexts((prevState) => ({
                            ...prevState,
                            [dataId]: {
                                text: textContent,
                                updatedAt: timestamp,
                            },
                        }));
                    }
                };
    
                // Processa o texto das div.view-line
                if (
                    mutation.type === "childList" &&
                    mutation.target.classList.contains("view-lines")
                ) {
                    const viewLinesDiv = mutation.target;
                    const ancestorDiv = viewLinesDiv.closest(
                        "div[class*='react-flow__node react-flow__node']"
                    );
    
                    if (ancestorDiv && ancestorDiv.hasAttribute("data-id")) {
                        const dataId = ancestorDiv.getAttribute("data-id");
    
                        // Concatena os textos das view-line sem duplicação
                        const concatenatedText = Array.from(
                            viewLinesDiv.querySelectorAll("div.view-line")
                        )
                            .map((viewLine) => viewLine.textContent.trim()) // Obtém apenas o texto interno da linha
                            .join("\n"); // Adiciona uma nova linha entre as view-line
    
                        updateNodeText(dataId, concatenatedText);
                    }
                }
    
                // Processa o texto das div.ace_line_group
                if (
                    mutation.type === "childList" &&
                    mutation.target.classList.contains("ace_line_group")
                ) {
                    const aceLineGroupDiv = mutation.target;
                    const ancestorDiv = aceLineGroupDiv.closest(
                        "div[class*='react-flow__node react-flow__node']"
                    );
    
                    if (ancestorDiv && ancestorDiv.hasAttribute("data-id")) {
                        const dataId = ancestorDiv.getAttribute("data-id");
    
                        // Concatena os textos das ace_line dentro de cada ace_line_group
                        const concatenatedText = Array.from(
                            document.querySelectorAll("div.ace_line_group")
                        )
                            .map((lineGroup) =>
                                Array.from(lineGroup.querySelectorAll("div.ace_line"))
                                    .map((aceLine) =>
                                        Array.from(aceLine.childNodes)
                                            .map((node) =>
                                                node.nodeType === Node.TEXT_NODE
                                                    ? node.textContent.trim() // Texto direto no nó
                                                    : node.textContent.trim() // Texto de elementos
                                            )
                                            .join("") // Concatena texto dentro de ace_line
                                    )
                                    .join(" ") // Concatena texto entre ace_line com espaços
                            )
                            .join("\n"); // Adiciona uma nova linha entre ace_line_group
    
                        updateNodeText(dataId, concatenatedText);
                    }
                }
            });
        };
    
        observer = new MutationObserver(observerCallback);
    
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
        });
    
        return () => {
            if (observer) observer.disconnect();
        };
    }, []); // Garante execução única devido ao array de dependências vazio.
    
    











    useEffect(() => {
        const checkUpdates = () => {
            console.log("checando");
            Object.entries(nodeTexts).forEach(([dataId, { text, updatedAt }]) => {
                if (updatedAt) {
                    const lastUpdated = new Date(updatedAt);
                    const now = new Date();
                    const diffInMinutes = (now - lastUpdated) / (1000 * 60); // Diferença em minutos
    
                    if (diffInMinutes <= 1) {
                        console.log(`Elemento ${dataId}: Atualizado a menos de 2 minutos`);
                        console.log(text)

                        const projectData = {
                            id: dataId, 
                            code: text
                        };
    
                        fetch('http://localhost:5002/updateProjectItem', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify(projectData)
                        })
                        .then(response => {
                            if (!response.ok) {
                                throw new Error(`Error: ${response.statusText}`);
                            }
                            return response.json();
                        })
                        .then(data => {
                            console.log(data);
                        })
                        .catch(error => {
                            console.error(error);
                        });






                    } else {
                        console.log(`Elemento ${dataId}: Atualizado a mais de 2 minutos`);
                    }
                }
            });
        };
    
        const intervalId = setInterval(checkUpdates, 20000);
    
        return () => clearInterval(intervalId); // Cleanup para evitar múltiplos intervalos
    }, [nodeTexts]);
    
    

    useEffect(() => {
        console.log("Node texts:", nodeTexts);
    }, [nodeTexts]);



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


                    let infos = separateEdgeId(selected)

                    const projectData = {
                        id: infos.in, // ID do projeto a ser atualizado
                        dependency: selected
                    };

                    fetch('http://localhost:5002/updateProjectItem', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(projectData)
                    })
                    .then(response => {
                        if (!response.ok) {
                            throw new Error(`Error: ${response.statusText}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        console.log(data);
                    })
                    .catch(error => {
                        console.error(error);
                    });

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
                        <ProjectList onSelectProject={handleProjectSelect} />
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
