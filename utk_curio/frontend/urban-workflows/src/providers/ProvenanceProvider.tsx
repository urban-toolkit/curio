import React, { createContext, useContext, ReactNode, useState, useRef } from "react";
import { formatDate } from "../utils/formatters";

/**
 * One entry of a node's history: a run, or an edit made in the node's body (a
 * Map Edits node's Apply, Remove or put back), which ran nothing. Each holds
 * the node's code as it left it, and descends from the entry the node's next
 * one branches from (`selectedParentExecRef`), so the history is a tree.
 */
export interface NodeExecRecord {
    id: number;
    parentId: number | null;
    code: string;
    /** The kinds of data the run read and returned, as `mapTypes` (utils/formatters) names them. None for an edit. */
    inputs: string[];
    outputs: string[];
    startTime: string;
    endTime: string;
    /** "edit" for an edit; a run has none. */
    kind?: "edit";
    /** What an edit changed, as the drawer lists it: "height 60 on building_id 34". */
    label?: string;
}

interface ProvenanceContextProps {
    nodeExecProv: (
        activityexec_start_time: string,
        activityexec_end_time: string,
        workflow_name: string,
        nodeId: string,
        types_input: string[],
        types_output: string[],
        activity_source_code: string,
        inputData?: string,
        outputData?: string,
        interaction?: boolean
    ) => void;
    /** Files an edit made in *nodeId*'s body: the code it left, named by *label*. */
    nodeEditProv: (nodeId: string, code: string, label: string) => void;
    provenanceGraphNodes: Record<string, NodeExecRecord[]>;
    provenanceGraphNodesRef: React.MutableRefObject<Record<string, NodeExecRecord[]>>;
    selectedParentExecRef: React.MutableRefObject<Record<string, number | null>>;
    setSelectedExec: (nodeId: string, execId: number | null) => void;
    /** A loaded dataflow's histories, and each node's code as it loaded, by node id. */
    loadNodeProvenance: (data: Record<string, NodeExecRecord[]>, codes?: Record<string, string>) => void;
    getAllNodeProvenance: () => Record<string, NodeExecRecord[]>;
}

/**
 * The entry a node's next one branches from after a dataflow loads: its
 * newest entry whose code is the node's code, or its newest entry when none
 * is, so a reload continues the history where it stood.
 */
export function entryToContinue(records: readonly NodeExecRecord[], code: string | undefined): number | null {
    const newest = (list: readonly NodeExecRecord[]) =>
        list.reduce<NodeExecRecord | null>((best, record) => (best === null || record.id > best.id ? record : best), null);
    const same = code === undefined ? null : newest(records.filter((record) => record.code === code));
    return (same ?? newest(records))?.id ?? null;
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    nodeExecProv: () => {},
    nodeEditProv: () => {},
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

    /** Add *record* to *nodeId*'s history; the node's next entry branches from it. */
    const file = (nodeId: string, record: NodeExecRecord) => {
        const next = { ...provenanceGraphNodesRef.current };
        next[nodeId] = [...(next[nodeId] || []), record];
        setProvenanceGraphNodes(next);

        selectedParentExecRef.current[nodeId] = record.id;
    };

    const nodeExecProv = (
        activityexec_start_time: string,
        activityexec_end_time: string,
        _workflow_name: string,
        nodeId: string,
        types_input: string[],
        types_output: string[],
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

        file(nodeId, record);
    };

    // An edit runs nothing: it reads and returns no data, and starts and ends at once.
    const nodeEditProv = (nodeId: string, code: string, label: string) => {
        const at = formatDate(new Date());
        file(nodeId, {
            id: execIdCounterRef.current++,
            parentId: selectedParentExecRef.current[nodeId] ?? null,
            code,
            inputs: [],
            outputs: [],
            startTime: at,
            endTime: at,
            kind: "edit",
            label,
        });
    };

    const setSelectedExec = (nodeId: string, execId: number | null) => {
        selectedParentExecRef.current[nodeId] = execId;
    };

    const loadNodeProvenance = (data: Record<string, NodeExecRecord[]>, codes: Record<string, string> = {}) => {
        if (!data) return;
        let maxId = 0;
        Object.values(data).flat().forEach((r: NodeExecRecord) => {
            if (r.id > maxId) maxId = r.id;
        });
        execIdCounterRef.current = maxId + 1;
        // Each node's history continues where it stood, not from a new root.
        const continued: Record<string, number | null> = {};
        for (const [nodeId, records] of Object.entries(data)) {
            if (!Array.isArray(records) || records.length === 0) continue;
            continued[nodeId] = entryToContinue(records, codes[nodeId]);
        }
        selectedParentExecRef.current = continued;
        setProvenanceGraphNodes(data);
    };

    const getAllNodeProvenance = (): Record<string, NodeExecRecord[]> => {
        return provenanceGraphNodesRef.current;
    };

    return (
        <ProvenanceContext.Provider
            value={{
                nodeExecProv,
                nodeEditProv,
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
