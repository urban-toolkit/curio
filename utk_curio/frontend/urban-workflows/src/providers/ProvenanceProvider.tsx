import React, { createContext, useContext, ReactNode, useState, useRef, useEffect } from "react";
import { formatDate } from "../utils/formatters";
import { historyApi, type RunNote } from "../api/historyApi";
import { afterCommit, serverHistory, subscribeServerHistory, type ServerHistory } from "./history/serverHistory";

/**
 * One entry of a node's history: a run, or an edit, which ran nothing: one
 * made in the node's body (a Map Editor node's action, or an entry of its list
 * switched off or deleted), or an agent's change the user applied. Each holds
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
    /** What an edit changed, as the drawer lists it: "Remove building_id 119", or the agent that made it: "Node Builder". */
    label?: string;
    /**
     * An edit's code before it, when the entry it descends from does not hold
     * it (the first edit of a node, or one after its code changed with no
     * entry): what Undo puts back.
     */
    before?: string;
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
    /**
     * Files an edit of *nodeId*, one made in its body or an agent's applied
     * change: the code it left, named by *label*, and the code it replaced
     * (*before*), kept when the entry it descends from does not hold it.
     */
    nodeEditProv: (nodeId: string, code: string, label: string, before?: string) => void;
    /**
     * Files an agent's applied change to *nodeId*'s code, named after the
     * agent, on a canvas bound to no dataflow's doc. On a bound one the server
     * wrote the change, and recorded it as it did.
     */
    agentEditProv: (nodeId: string, code: string, agent: string, before?: string) => void;
    provenanceGraphNodes: Record<string, NodeExecRecord[]>;
    provenanceGraphNodesRef: React.MutableRefObject<Record<string, NodeExecRecord[]>>;
    selectedParentExecRef: React.MutableRefObject<Record<string, number | null>>;
    /** Counts the changes of the entry in use that filed nothing, so a view of it renders again. */
    selectedRevision?: number;
    setSelectedExec: (nodeId: string, execId: number | null) => void;
    /** A loaded dataflow's histories, and each node's code as it loaded, by node id. */
    loadNodeProvenance: (data: Record<string, NodeExecRecord[]>, codes?: Record<string, string>) => void;
    /** The entries recorded here, for a save to carry: from now on they are
     *  the save's, and the canvas binding to the dataflow's doc sends none of
     *  them. */
    getAllNodeProvenance: () => Record<string, NodeExecRecord[]>;
    /**
     * On a canvas bound to the dataflow's doc: the entry of *nodeId* this tab
     * put back or stepped to (null: before the first), while the node holds
     * the *code* it left; undefined when it chose none, or the code changed.
     */
    chosenEntry: (nodeId: string, code: string) => number | null | undefined;
    chooseEntry: (nodeId: string, entryId: number | null, code: string) => void;
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

/** A time a run was filed with, as the server keeps it: ISO 8601, in UTC. */
function isoTime(text: string): string {
    const at = new Date(text);
    return Number.isNaN(at.getTime()) ? text : at.toISOString();
}

function runNote(record: NodeExecRecord): RunNote {
    return {
        code: record.code,
        inputs: record.inputs,
        outputs: record.outputs,
        startTime: isoTime(record.startTime),
        endTime: isoTime(record.endTime),
    };
}

export const ProvenanceContext = createContext<ProvenanceContextProps>({
    nodeExecProv: () => {},
    nodeEditProv: () => {},
    agentEditProv: () => {},
    provenanceGraphNodes: {},
    provenanceGraphNodesRef: { current: {} },
    selectedParentExecRef: { current: {} },
    setSelectedExec: () => {},
    loadNodeProvenance: () => {},
    getAllNodeProvenance: () => ({}),
    chosenEntry: () => undefined,
    chooseEntry: () => {},
});

/**
 * The nodes' histories. On a canvas bound to no dataflow's doc they are
 * recorded here, and a save carries them. On a bound one the server keeps
 * them (`providers/history/serverHistory.ts`): each run and each edit made in
 * a node's body is sent to it, after every change this tab made before it,
 * and the drawers read them from there. When the canvas binds, the runs no
 * save carried are sent, and what was recorded here goes.
 */
const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
    const [provenanceGraphNodes, _setProvenanceGraphNodes] = useState<Record<string, NodeExecRecord[]>>({});
    const provenanceGraphNodesRef = useRef<Record<string, NodeExecRecord[]>>(provenanceGraphNodes);
    const setProvenanceGraphNodes = (data: Record<string, NodeExecRecord[]>) => {
        provenanceGraphNodesRef.current = data;
        _setProvenanceGraphNodes(data);
    };

    const execIdCounterRef = useRef<number>(1);
    const selectedParentExecRef = useRef<Record<string, number | null>>({});
    /** The entries filed here that no save has carried yet. */
    const unsentRef = useRef<Array<{ nodeId: string; record: NodeExecRecord }>>([]);
    /** What this tab sends the server, in the order it made it. */
    const sendingRef = useRef<Promise<void>>(Promise.resolve());
    const chosenRef = useRef<Record<string, { id: number | null; code: string }>>({});

    /** Send *write* to the server once the change that made it is with it. */
    const send = (server: ServerHistory, what: string, write: () => Promise<unknown>) => {
        sendingRef.current = sendingRef.current.then(async () => {
            await afterCommit();
            await server.whenKept();
            try {
                await write();
            } catch (error) {
                console.warn(`[history] ${what} was not recorded:`, error);
            }
        });
    };

    /** Add *record* to *nodeId*'s history; the node's next entry branches from it. */
    const file = (nodeId: string, record: NodeExecRecord) => {
        const next = { ...provenanceGraphNodesRef.current };
        next[nodeId] = [...(next[nodeId] || []), record];
        setProvenanceGraphNodes(next);
        unsentRef.current = [...unsentRef.current, { nodeId, record }];

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

        const record: NodeExecRecord = {
            id: 0,
            parentId,
            code: activity_source_code,
            inputs: Array.isArray(types_input) ? types_input : [],
            outputs: Array.isArray(types_output) ? types_output : [],
            startTime: activityexec_start_time,
            endTime: activityexec_end_time,
        };

        const server = serverHistory();
        if (server) {
            if (server.reads()) send(server, "A run", () => historyApi.noteRun(server.projectId, nodeId, runNote(record)));
            return;
        }
        file(nodeId, { ...record, id: execIdCounterRef.current++ });
    };

    // An edit runs nothing: it reads and returns no data, and starts and ends at once.
    const nodeEditProv = (nodeId: string, code: string, label: string, before?: string) => {
        const server = serverHistory();
        if (server) {
            if (server.reads()) send(server, "An edit", () => historyApi.noteEdit(server.projectId, nodeId, label));
            return;
        }
        const at = formatDate(new Date());
        const parentId = selectedParentExecRef.current[nodeId] ?? null;
        const parent = (provenanceGraphNodesRef.current[nodeId] ?? []).find((record) => record.id === parentId);
        file(nodeId, {
            id: execIdCounterRef.current++,
            parentId,
            code,
            inputs: [],
            outputs: [],
            startTime: at,
            endTime: at,
            kind: "edit",
            label,
            // The code it replaced, where no entry before it holds it: what Undo puts back.
            ...(before !== undefined && before !== parent?.code ? { before } : {}),
        });
    };

    const agentEditProv = (nodeId: string, code: string, agent: string, before?: string) => {
        if (serverHistory()) return;
        nodeEditProv(nodeId, code, agent, before);
    };

    // Which entry is in use changes with no entry filed (a put back, an Undo
    // or a Redo): the drawer reads it again.
    const [selectedRevision, setSelectedRevision] = useState(0);
    const setSelectedExec = (nodeId: string, execId: number | null) => {
        selectedParentExecRef.current[nodeId] = execId;
        setSelectedRevision((revision) => revision + 1);
    };

    const chooseEntry = (nodeId: string, entryId: number | null, code: string) => {
        chosenRef.current[nodeId] = { id: entryId, code };
        setSelectedRevision((revision) => revision + 1);
    };
    const chosenEntry = (nodeId: string, code: string) => {
        const chosen = chosenRef.current[nodeId];
        return chosen && chosen.code === code ? chosen.id : undefined;
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
        unsentRef.current = [];
        return provenanceGraphNodesRef.current;
    };

    // The canvas bound to its dataflow's doc: the server keeps the history
    // from here on. The runs filed before it that no save carried go to it,
    // and the entries recorded here go (`useDataflowDoc` drops the versions).
    useEffect(() => subscribeServerHistory(() => {
        const server = serverHistory();
        if (!server) return;
        const runs = unsentRef.current.filter(({ record }) => record.kind !== "edit");
        unsentRef.current = [];
        if (server.reads()) {
            for (const { nodeId, record } of runs) {
                send(server, "A run", () => historyApi.noteRun(server.projectId, nodeId, runNote(record)));
            }
        }
        selectedParentExecRef.current = {};
        chosenRef.current = {};
        setProvenanceGraphNodes({});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }), []);

    return (
        <ProvenanceContext.Provider
            value={{
                nodeExecProv,
                nodeEditProv,
                agentEditProv,
                provenanceGraphNodes,
                provenanceGraphNodesRef,
                selectedParentExecRef,
                selectedRevision,
                setSelectedExec,
                loadNodeProvenance,
                getAllNodeProvenance,
                chosenEntry,
                chooseEntry,
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
