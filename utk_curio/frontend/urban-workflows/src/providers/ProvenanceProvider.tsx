import React, { createContext, useContext, ReactNode, useState, useRef } from "react";

export interface NodeExecRecord {
    id: number;
    parentId: number | null;
    code: string;
    inputs: string[];
    outputs: string[];
    startTime: string;
    endTime: string;
}

interface ProvenanceContextProps {
    nodeExecProv: (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        nodeId: string,
        types_input: any,
        types_output: any,
        activity_source_code: string,
        inputData?: string,
        outputData?: string,
        interaction?: boolean
    ) => void;
    provenanceGraphNodes: Record<string, NodeExecRecord[]>;
    provenanceGraphNodesRef: React.MutableRefObject<Record<string, NodeExecRecord[]>>;
    selectedParentExecRef: React.MutableRefObject<Record<string, number | null>>;
    setSelectedExec: (nodeId: string, execId: number | null) => void;
    loadNodeProvenance: (data: Record<string, NodeExecRecord[]>) => void;
    getAllNodeProvenance: () => Record<string, NodeExecRecord[]>;
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    nodeExecProv: () => {},
    provenanceGraphNodes: {},
    provenanceGraphNodesRef: { current: {} },
    selectedParentExecRef: { current: {} },
    setSelectedExec: () => {},
    loadNodeProvenance: () => {},
    getAllNodeProvenance: () => ({}),
});

const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
    const [provenanceGraphNodes, _setProvenanceGraphNodes] = useState<Record<string, NodeExecRecord[]>>({});
    const provenanceGraphNodesRef = useRef<Record<string, NodeExecRecord[]>>(provenanceGraphNodes);
    const setProvenanceGraphNodes = (data: Record<string, NodeExecRecord[]>) => {
        provenanceGraphNodesRef.current = data;
        _setProvenanceGraphNodes(data);
    };

    const execIdCounterRef = useRef<number>(1);
    const selectedParentExecRef = useRef<Record<string, number | null>>({});

    const nodeExecProv = (
        activityexec_start_time: string,
        activityexec_end_time: string,
        _workflow_name: string,
        nodeId: string,
        types_input: any,
        types_output: any,
        activity_source_code: string,
        _inputData: string = "",
        _outputData: string = "",
        _interaction: boolean = false
    ) => {
        const parentId = selectedParentExecRef.current[nodeId] ?? null;
        const newId = execIdCounterRef.current++;

        const record: NodeExecRecord = {
            id: newId,
            parentId,
            code: activity_source_code,
            inputs: Array.isArray(types_input) ? types_input : [],
            outputs: Array.isArray(types_output) ? types_output : [],
            startTime: activityexec_start_time,
            endTime: activityexec_end_time,
        };

        const next = { ...provenanceGraphNodesRef.current };
        next[nodeId] = [...(next[nodeId] || []), record];
        setProvenanceGraphNodes(next);

        selectedParentExecRef.current[nodeId] = newId;
    };

    const setSelectedExec = (nodeId: string, execId: number | null) => {
        selectedParentExecRef.current[nodeId] = execId;
    };

    const loadNodeProvenance = (data: Record<string, NodeExecRecord[]>) => {
        if (!data) return;
        let maxId = 0;
        Object.values(data).flat().forEach((r: NodeExecRecord) => {
            if (r.id > maxId) maxId = r.id;
        });
        execIdCounterRef.current = maxId + 1;
        setProvenanceGraphNodes(data);
    };

    const getAllNodeProvenance = (): Record<string, NodeExecRecord[]> => {
        return provenanceGraphNodesRef.current;
    };

    return (
        <ProvenanceContext.Provider
            value={{
                nodeExecProv,
                provenanceGraphNodes,
                provenanceGraphNodesRef,
                selectedParentExecRef,
                setSelectedExec,
                loadNodeProvenance,
                getAllNodeProvenance,
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
