/**
 * The history the server keeps, as the drawers and the Map Editor read it:
 * read when they mount and again whenever the server says it changed
 * (`HISTORY_CHANGED_EVENT`), which it tells the owner's and the editors'
 * tabs only. A watcher's read is refused with the server's sentence.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { historyApi, type ServerEntries, type ServerVersions } from "../../api/historyApi";
import { useCollab } from "../CollaborationProvider";
import { type NodeExecRecord, useProvenanceContext } from "../ProvenanceProvider";
import { HISTORY_CHANGED_EVENT, type ServerHistory, useServerHistory } from "./serverHistory";

export interface HistoryRead<T> {
    /** The last answer, or null before the first. */
    data: T | null;
    /** Why the history cannot be read: the server's refusal, or the failure. */
    error: string | null;
    /** Read it again now. */
    reload: () => void;
}

/** What *read* answers for *server*'s dataflow, read again whenever the
 *  history changes. *key* names what is read: another key starts afresh. */
function useHistoryRead<T>(
    server: ServerHistory | null,
    key: string,
    read: (projectId: string) => Promise<T>,
): HistoryRead<T> {
    const projectId = server?.projectId ?? null;
    const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({
        key: "",
        data: null,
        error: null,
    });
    const readRef = useRef(read);
    readRef.current = read;
    // Only the newest read's answer is kept.
    const lastRef = useRef(0);
    const reload = useCallback(() => {
        if (!projectId) return;
        const mine = ++lastRef.current;
        readRef.current(projectId).then(
            (data) => {
                if (lastRef.current === mine) setState({ key, data, error: null });
            },
            (error) => {
                if (lastRef.current !== mine) return;
                setState({ key, data: null, error: (error as Error)?.message || "The history could not be read." });
            },
        );
    }, [projectId, key]);

    useEffect(() => {
        reload();
    }, [reload]);

    const { onRemote } = useCollab();
    useEffect(() => {
        if (!projectId || typeof onRemote !== "function") return undefined;
        return onRemote(HISTORY_CHANGED_EVENT, (payload: unknown) => {
            const named = (payload as { projectId?: string } | null)?.projectId;
            if (!named || named === projectId) reload();
        });
    }, [onRemote, projectId, reload]);

    const current = state.key === key && projectId !== null;
    return { data: current ? state.data : null, error: current ? state.error : null, reload };
}

/** The dataflow's versions, while the canvas is bound to its doc. */
export function useServerVersions(server: ServerHistory | null): HistoryRead<ServerVersions> {
    return useHistoryRead(server, server ? `versions:${server.projectId}` : "", historyApi.versions);
}

export interface NodeEntries {
    /** The server's history, while the canvas is bound to the dataflow's doc. */
    server: ServerHistory | null;
    /** The node's runs and edits, in the order they were made. */
    records: readonly NodeExecRecord[];
    /** The entry its next one branches from. */
    currentId: number | null;
    /** Whether the records are read (always, for a canvas bound to no doc). */
    loaded: boolean;
    /** Why the server's history cannot be read (a watcher's tab). */
    error: string | null;
    reload: () => void;
}

const NO_ENTRIES: NodeExecRecord[] = [];

/**
 * A node's entries and the one its next entry branches from, while it holds
 * *code*: the browser's on a canvas bound to no doc, the server's on a bound
 * one, where the entry this tab put back or stepped to stays the one in use
 * until the node's code changes (`chosenEntry`).
 */
export function useNodeEntries(nodeId: string, code: string | undefined): NodeEntries {
    const server = useServerHistory();
    const { provenanceGraphNodes, selectedParentExecRef, chosenEntry } = useProvenanceContext();
    const read = useHistoryRead<ServerEntries>(
        server,
        server ? `entries:${server.projectId}:${nodeId}` : "",
        (projectId) => historyApi.entries(projectId, nodeId),
    );
    if (!server) {
        return {
            server: null,
            records: provenanceGraphNodes[nodeId] ?? NO_ENTRIES,
            currentId: selectedParentExecRef.current[nodeId] ?? null,
            loaded: true,
            error: null,
            reload: read.reload,
        };
    }
    const chosen = code === undefined ? undefined : chosenEntry(nodeId, code);
    return {
        server,
        records: read.data?.entries ?? NO_ENTRIES,
        currentId: chosen !== undefined ? chosen : read.data?.current ?? null,
        loaded: read.data !== null || read.error !== null,
        error: read.error,
        reload: read.reload,
    };
}
