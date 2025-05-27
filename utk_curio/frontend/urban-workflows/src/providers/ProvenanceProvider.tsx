import React, { createContext, useContext, ReactNode, useState } from "react";
import { BoxType } from "../constants";

interface ProvenanceContextProps {
    addUser: (user_name: string, user_type: string, user_IP: string) => void;
    addWorkflow: (workflow_name: string) => void;
    newBox: (workflow_name: string, activity_name: string) => void;
    deleteBox: (workflow_name: string, activity_name: string) => void;
    newConnection: (
        workflow_name: string,
        sourceNodeId: string,
        sourceNodeType: BoxType,
        targetNodeId: string,
        targetNodeType: BoxType
    ) => void;
    deleteConnection: (
        workflow_name: string,
        targetNodeId: string,
        targetNodeType: BoxType
    ) => void;
    boxExecProv: (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        activity_name: string,
        types_input: any,
        types_output: any,
        activity_source_code: string
    ) => void;
    provenanceGraphBoxesRef: any;
    truncateDB: () => void;
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    addUser: () => {},
    addWorkflow: () => {},
    newBox: () => {},
    deleteBox: () => {},
    newConnection: () => {},
    deleteConnection: () => {},
    boxExecProv: () => {},
    provenanceGraphBoxesRef: {},
    truncateDB: () => {},
});

const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
    const [provenanceGraphBoxes, _setProvenanceGraphBoxes] = useState<any>({}); // workflow_name -> activity_name -> nodes[]
    const provenanceGraphBoxesRef = React.useRef(provenanceGraphBoxes);
    const setProvenanceGraphBoxes = (data: any) => {
        provenanceGraphBoxesRef.current = data;
        _setProvenanceGraphBoxes(data);
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

    const newBox = (workflow_name: string, activity_name: string) => {
        fetch(process.env.BACKEND_URL + "/newBoxProv", {
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

    const deleteBox = (workflow_name: string, activity_name: string) => {
        fetch(process.env.BACKEND_URL + "/deleteBoxProv", {
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
        sourceNodeType: BoxType,
        targetNodeId: string,
        targetNodeType: BoxType
    ) => {

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
        targetNodeType: BoxType
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

    const boxExecProv = (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        activity_name: string,
        types_input: any,
        types_output: any,
        activity_source_code: string
    ) => {
        fetch(process.env.BACKEND_URL + "/boxExecProv", {
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
                },
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        }).then((value: any) => {
            getBoxGraph(workflow_name, activity_name);
        });
    };

    const getBoxGraph = (workflow_name: string, activity_name: string) => {
        // Call after writing the running provenance in the database

        fetch(process.env.BACKEND_URL + "/getBoxGraph", {
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

                let workflows = Object.keys(provenanceGraphBoxesRef.current);

                for (const workflow of workflows) {
                    if (newProvenanceGraphs[workflow] == undefined)
                        newProvenanceGraphs[workflow] = {};

                    let activities = Object.keys(
                        provenanceGraphBoxesRef.current[workflow]
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
                                provenanceGraphBoxesRef.current[workflow][
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

                setProvenanceGraphBoxes(newProvenanceGraphs);
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
                newBox,
                truncateDB,
                deleteBox,
                newConnection,
                boxExecProv,
                provenanceGraphBoxesRef,
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
