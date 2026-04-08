import React, { createContext, useContext, ReactNode, useState } from "react";
import { NodeType } from "../constants";

interface ProvenanceContextProps {
    addUser: (user_name: string, user_type: string, user_IP: string) => void;
    addWorkflow: (workflow_name: string) => Promise<void>;
    newNode: (workflow_name: string, activity_name: string) => void;
    deleteNode: (workflow_name: string, activity_name: string) => void;
    newConnection: (
        workflow_name: string,
        sourceNodeId: string,
        sourceNodeType: NodeType,
        targetNodeId: string,
        targetNodeType: NodeType
    ) => void;
    deleteConnection: (
        workflow_name: string,
        targetNodeId: string,
        targetNodeType: NodeType
    ) => void;
    nodeExecProv: (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        activity_name: string,
        types_input: any,
        types_output: any,
        activity_source_code: string,
        inputData?: string,
        outputData?: string,
        interaction?: boolean
    ) => void;
    provenanceGraphNodesRef: any;
    truncateDB: () => void;
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    addUser: () => {},
    addWorkflow: () => new Promise((resolve, reject) => {resolve()}),
    newNode: () => {},
    deleteNode: () => {},
    newConnection: () => {},
    deleteConnection: () => {},
    nodeExecProv: () => {},
    provenanceGraphNodesRef: {},
    truncateDB: () => {},
});

const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
    const [provenanceGraphNodes, _setProvenanceGraphNodes] = useState<any>({}); // workflow_name -> activity_name -> nodes[]
    const provenanceGraphNodesRef = React.useRef(provenanceGraphNodes);
    const setProvenanceGraphNodes = (data: any) => {
        provenanceGraphNodesRef.current = data;
        _setProvenanceGraphNodes(data);
    };

    const addUser = (user_name: string, user_type: string, user_IP: string) => {
        fetch(process.env.BACKEND_URL + "/saveUserProv", {
            method: "POST",
            body: JSON.stringify({
                user: {
                    user_name,
                    user_type,
                    user_IP,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const newNode = (workflow_name: string, activity_name: string) => {
        console.log("workflow_name", workflow_name);
        console.log("activity_name", activity_name);

        fetch(process.env.BACKEND_URL + "/newNodeProv", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    workflow_name,
                    activity_name,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const deleteNode = (workflow_name: string, activity_name: string) => {
        fetch(process.env.BACKEND_URL + "/deleteNodeProv", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    workflow_name,
                    activity_name,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const addWorkflow = async (workflow_name: string) => {
        await fetch(process.env.BACKEND_URL + "/truncateDBProv", {
            method: "GET",
        });

        await fetch(process.env.BACKEND_URL + "/saveWorkflowProv", {
            method: "POST",
            body: JSON.stringify({
                workflow: workflow_name,
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const newConnection = (
        workflow_name: string,
        sourceNodeId: string,
        sourceNodeType: NodeType,
        targetNodeId: string,
        targetNodeType: NodeType
    ) => {
        if (!workflow_name || !sourceNodeId || !sourceNodeType || !targetNodeId || !targetNodeType) {
            console.error("[newConnection] Missing or invalid data in payload", {
                workflow_name, sourceNodeId, sourceNodeType, targetNodeId, targetNodeType,
            });
            return;
        }

        fetch(process.env.BACKEND_URL + "/newConnectionProv", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    workflow_name,
                    sourceNodeId,
                    sourceNodeType,
                    targetNodeId,
                    targetNodeType,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const deleteConnection = (
        workflow_name: string,
        targetNodeId: string,
        targetNodeType: NodeType
    ) => {
        fetch(process.env.BACKEND_URL + "/deleteConnectionProv", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    workflow_name,
                    targetNodeId,
                    targetNodeType,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        });
    };

    const nodeExecProv = (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        activity_name: string,
        types_input: any,
        types_output: any,
        activity_source_code: string,
        inputData: string = "",
        outputData: string = "",
        interaction: boolean = false
    ) => {
        fetch(process.env.BACKEND_URL + "/nodeExecProv", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    activityexec_start_time,
                    activityexec_end_time,
                    workflow_name,
                    activity_name,
                    types_input,
                    types_output,
                    activity_source_code,
                    inputData,
                    outputData,
                    interaction
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        }).then((value: any) => {
            getNodeGraph(workflow_name, activity_name);
        });
    };

    const getNodeGraph = (workflow_name: string, activity_name: string) => {
        // Call after writing the running provenance in the database

        fetch(process.env.BACKEND_URL + "/getNodeGraph", {
            method: "POST",
            body: JSON.stringify({
                data: {
                    workflow_name,
                    activity_name,
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        })
            .then((response) => response.json())
            .then((json: any) => {
                let newProvenanceGraphs: any = {};
                let added = false;

                let workflows = Object.keys(provenanceGraphNodesRef.current);

                for (const workflow of workflows) {
                    if (newProvenanceGraphs[workflow] == undefined)
                        newProvenanceGraphs[workflow] = {};

                    let activities = Object.keys(
                        provenanceGraphNodesRef.current[workflow] || {}
                    );

                    for (const activity of activities) {
                        if (
                            workflow == workflow_name &&
                            activity == activity_name
                        ) {
                            newProvenanceGraphs[workflow][activity] =
                                json["graph"];
                            added = true;
                        } else {
                            // TODO: replicate array of objects
                            newProvenanceGraphs[workflow][activity] =
                                provenanceGraphNodesRef.current[workflow][
                                    activity
                                ].map((obj: any) => {
                                    return { ...obj };
                                });
                        }
                    }
                }

                if (!added) {
                    if (newProvenanceGraphs[workflow_name] == undefined)
                        newProvenanceGraphs[workflow_name] = {};

                    newProvenanceGraphs[workflow_name][activity_name] =
                        json["graph"];
                }

                setProvenanceGraphNodes(newProvenanceGraphs);
            });
    };

    // for test purposes (TODO: temporary)
    const truncateDB = () => {
        fetch(process.env.BACKEND_URL + "/truncateDBProv", {
            method: "GET",
        });
    };

    return (
        <ProvenanceContext.Provider
            value={{
                addUser,
                addWorkflow,
                newNode,
                truncateDB,
                deleteNode,
                newConnection,
                nodeExecProv,
                provenanceGraphNodesRef,
                deleteConnection,
            }}
        >
            {children}
        </ProvenanceContext.Provider>
    );
};

export const useProvenanceContext = () => {
    const context = useContext(ProvenanceContext);

    if (!context) {
        throw new Error(
            "useProvenanceContext must be used within a ProvenanceProvider"
        );
    }

    return context;
};

export default ProvenanceProvider;
