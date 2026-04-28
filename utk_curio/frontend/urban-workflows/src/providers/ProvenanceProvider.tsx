/**
 * ProvenanceProvider — dual-mode provenance tracking for Curio.
 *
 * Server mode  : every workflow event (new box, connection, execution) is sent
 *                to the backend provenance API, which stores it in a database.
 *                The provenance graph is fetched back after each execution.
 *
 * Pyodide mode : no backend is available, so execution records are written to
 *                IndexedDB (curio_provenance) instead. On mount the provider
 *                re-reads IndexedDB and rebuilds provenanceGraphBoxesRef so the
 *                BoxProvenance panel can show history from a previous session.
 *
 * All seven public functions check `pyodideMode` and return early (skipping the
 * fetch) when running client-side, keeping the interface identical for callers.
 */
import React, { createContext, useContext, ReactNode, useState, useEffect } from "react";
import { BoxType } from "../constants";
import { appendExecRecord, getAllExecRecords, clearExecRecords } from "../services/IndexedDBProvenance";

interface ProvenanceContextProps {
    addUser: (user_name: string, user_type: string, user_IP: string) => void;
    addWorkflow: (workflow_name: string) => Promise<void>;
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
        activity_source_code: string,
        inputData: string,
        outputData: string,
        interaction: boolean
    ) => void;
    provenanceGraphBoxesRef: any;
    truncateDB: () => void;
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    addUser: () => {},
    addWorkflow: () => new Promise((resolve, reject) => {resolve()}),
    newBox: () => {},
    deleteBox: () => {},
    newConnection: () => {},
    deleteConnection: () => {},
    boxExecProv: () => {},
    provenanceGraphBoxesRef: {},
    truncateDB: () => {},
});

/* When Pyodide mode is on there is no backend, skip all provenance network calls. */
const pyodideMode = process.env.PYODIDE_ENABLED === 'true';

const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
    const [provenanceGraphBoxes, _setProvenanceGraphBoxes] = useState<any>({}); // workflow_name -> activity_name -> nodes[]
    const provenanceGraphBoxesRef = React.useRef(provenanceGraphBoxes);
    const setProvenanceGraphBoxes = (data: any) => {
        provenanceGraphBoxesRef.current = data;
        _setProvenanceGraphBoxes(data);
    };

    // In Pyodide mode, load persisted execution records from IndexedDB on mount
    // and rebuild provenanceGraphBoxesRef so BoxProvenance can render history.
    useEffect(() => {
        if (!pyodideMode) return;
        getAllExecRecords().then(flat => {
            const rebuilt: any = {};
            for (const [key, records] of Object.entries(flat)) {
                const sep = key.indexOf('__');
                const workflow = key.slice(0, sep);
                const activity = key.slice(sep + 2);
                if (!rebuilt[workflow]) rebuilt[workflow] = {};
                rebuilt[workflow][activity] = records;
            }
            setProvenanceGraphBoxes(rebuilt);
        }).catch(() => {});
    }, []);

    const addUser = (user_name: string, user_type: string, user_IP: string) => {
        if (pyodideMode) return;
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
        if (pyodideMode) return;
        console.log("workflow_name", workflow_name);
        console.log("activity_name", activity_name);

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
        if (pyodideMode) return;
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
        if (pyodideMode) {
            // clear previous session's execution records for a fresh workflow
            await clearExecRecords().catch(() => {});
            setProvenanceGraphBoxes({});
            return;
        }
        try {
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
        } catch (err) {
            console.warn('[Curio] addWorkflow: provenance backend unreachable, skipping:', err);
        }
    };

    const newConnection = (
        workflow_name: string,
        sourceNodeId: string,
        sourceNodeType: BoxType,
        targetNodeId: string,
        targetNodeType: BoxType
    ) => {
        if (pyodideMode) return;
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
        targetNodeType: BoxType
    ) => {
        if (pyodideMode) return;
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
        activity_source_code: string,
        inputData: string = "",
        outputData: string = "",
        interaction: boolean = false
    ) => {
        if (pyodideMode) {
            const record = {
                inputs: Array.isArray(types_input) ? types_input : [String(types_input ?? '')],
                outputs: Array.isArray(types_output) ? types_output : [String(types_output ?? '')],
                code: activity_source_code,
            };
            appendExecRecord(workflow_name, activity_name, record).then(updated => {
                const current = provenanceGraphBoxesRef.current;
                const updatedGraph = {
                    ...current,
                    [workflow_name]: {
                        ...(current[workflow_name] ?? {}),
                        [activity_name]: updated,
                    },
                };
                setProvenanceGraphBoxes(updatedGraph);
            }).catch(() => {});
            return;
        }
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
                    inputData,
                    outputData,
                    interaction
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
        if (pyodideMode) return;
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
