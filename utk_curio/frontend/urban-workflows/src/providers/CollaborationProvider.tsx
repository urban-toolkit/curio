/**
 * Real-time collaboration provider.
 *
 * Disabled by default: when the backend reports ``enable_collab=false``
 * via ``/api/config/public``, this provider renders children with a
 * no-op context value and never opens a socket.
 *
 * When enabled, it follows the currently-loaded project via
 * ``projectPackagesStore.subscribe`` — opening one socket per project
 * id, emitting ``join_session`` on connect, and tearing the socket
 * down when the user navigates to a different project (or away from
 * the canvas).
 *
 * Identity is anchored in the backend Bearer token sent through the
 * Socket.IO ``auth`` handshake. We never trust user-supplied identity
 * fields in event payloads.
 */

import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { io, Socket } from "socket.io-client";

import { authApi, getToken } from "../utils/authApi";
import {
    getCurrentProjectId,
    subscribe as subscribeProject,
} from "../registry/projectPackagesStore";

const BACKEND_URL = process.env.BACKEND_URL || "";
const NAMESPACE = "/collab";

export interface CollabUser {
    user_id: number;
    username: string;
    name?: string;
    profile_image?: string | null;
    sid?: string;
}

export interface NodeLock {
    user_id: number;
    username: string;
    name?: string;
    sid: string;
    since: number;
}

export interface CodeProposal {
    id: string;
    nodeId: string;
    kind: "code" | "grammar";
    oldValue: string | null;
    newValue: string;
    proposed_by: { user_id: number; username: string; sid: string };
    approvals: string[];
    rejections: string[];
    created_at: number;
}

export interface ActivityEntry {
    kind: string;
    ts: number;
    payload: Record<string, unknown>;
}

export interface OutputBroadcast {
    nodeId: string;
    nodeType?: string;
    output: { code: string; content: unknown; [k: string]: unknown };
}

/** Listener callback for "a peer applied a remote change" events. */
export type RemoteHandler<T = unknown> = (payload: T) => void;

export interface CollabContextValue {
    enabled: boolean;
    connected: boolean;
    currentUserId: number | null;
    users: CollabUser[];
    lockedNodes: Record<string, NodeLock>;
    proposals: CodeProposal[];
    activity: ActivityEntry[];

    lockNode: (nodeId: string) => void;
    unlockNode: (nodeId: string) => void;
    requestCodeChange: (
        nodeId: string,
        oldValue: string | null,
        newValue: string,
        kind?: "code" | "grammar",
    ) => void;
    approveCodeChange: (proposalId: string) => void;
    rejectCodeChange: (proposalId: string) => void;
    resolveConflict: (payload: Record<string, unknown>) => void;

    broadcastNodeAdded: (payload: Record<string, unknown>) => void;
    broadcastNodeUpdated: (payload: Record<string, unknown>) => void;
    broadcastNodeRemoved: (nodeId: string) => void;
    broadcastEdgeAdded: (payload: Record<string, unknown>) => void;
    broadcastEdgeRemoved: (edgeId: string) => void;
    broadcastOutputProduced: (payload: OutputBroadcast) => void;
    signalExecDisplay: (nodeId: string) => void;

    /**
     * Subscribe to incoming remote events. Returns an unsubscribe fn.
     * Event names mirror the backend ``events.py`` outgoing event list:
     * ``node_added``, ``node_updated``, ``node_removed``,
     * ``edge_added``, ``edge_removed``, ``output_produced``,
     * ``code_change_applied``, ``conflict_resolved``,
     * ``node_exec_display``.
     */
    onRemote: (event: string, handler: RemoteHandler) => () => void;
}

const NOOP_VALUE: CollabContextValue = {
    enabled: false,
    connected: false,
    currentUserId: null,
    users: [],
    lockedNodes: {},
    proposals: [],
    activity: [],

    lockNode: () => undefined,
    unlockNode: () => undefined,
    requestCodeChange: () => undefined,
    approveCodeChange: () => undefined,
    rejectCodeChange: () => undefined,
    resolveConflict: () => undefined,

    broadcastNodeAdded: () => undefined,
    broadcastNodeUpdated: () => undefined,
    broadcastNodeRemoved: () => undefined,
    broadcastEdgeAdded: () => undefined,
    broadcastEdgeRemoved: () => undefined,
    broadcastOutputProduced: () => undefined,
    signalExecDisplay: () => undefined,

    onRemote: () => () => undefined,
};

const CollabContext = createContext<CollabContextValue>(NOOP_VALUE);

/**
 * Hook for any component that wants to talk to the collaboration layer.
 * Safe to call without a provider mounted — returns a no-op value so
 * the rest of the app keeps working off-canvas, in tests, and when
 * collaboration is disabled.
 */
export function useCollab(): CollabContextValue {
    return useContext(CollabContext);
}

const REMOTE_EVENTS = [
    "user_joined",
    "user_left",
    "node_locked",
    "node_unlocked",
    "node_added",
    "node_updated",
    "node_removed",
    "edge_added",
    "edge_removed",
    "code_change_proposed",
    "code_change_voted",
    "code_change_applied",
    "code_change_rejected",
    "output_produced",
    "node_exec_display",
    "conflict_resolved",
] as const;

export const CollaborationProvider: React.FC<{ children: React.ReactNode }> = ({
    children,
}) => {
    const [enabled, setEnabled] = useState<boolean>(false);
    const [connected, setConnected] = useState<boolean>(false);
    const [users, setUsers] = useState<CollabUser[]>([]);
    const [lockedNodes, setLockedNodes] = useState<Record<string, NodeLock>>({});
    const [proposals, setProposals] = useState<CodeProposal[]>([]);
    const [activity, setActivity] = useState<ActivityEntry[]>([]);
    const [currentUserId, setCurrentUserId] = useState<number | null>(null);

    const socketRef = useRef<Socket | null>(null);
    const projectIdRef = useRef<string | undefined>(getCurrentProjectId());
    const remoteHandlersRef = useRef<Map<string, Set<RemoteHandler>>>(new Map());

    // ------------------------------------------------------------------
    // Read the flag once. If disabled we never open a socket.
    // ------------------------------------------------------------------
    useEffect(() => {
        let cancelled = false;
        authApi
            .getPublicConfig()
            .then((cfg) => {
                if (!cancelled) setEnabled(Boolean(cfg.enable_collab));
            })
            .catch(() => {
                if (!cancelled) setEnabled(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const closeSocket = useCallback(() => {
        const s = socketRef.current;
        if (s) {
            try {
                s.removeAllListeners();
                s.disconnect();
            } catch {
                /* socket already gone */
            }
        }
        socketRef.current = null;
        setConnected(false);
        setUsers([]);
        setLockedNodes({});
        setProposals([]);
        setActivity([]);
    }, []);

    const installSocketListeners = useCallback(
        (socket: Socket) => {
            socket.on("connect", () => {
                setConnected(true);
                const projectId = projectIdRef.current;
                if (!projectId) return;
                socket.emit(
                    "join_session",
                    { projectId },
                    (ack: {
                        ok: boolean;
                        snapshot?: {
                            users: CollabUser[];
                            locks: Record<string, NodeLock>;
                            proposals: CodeProposal[];
                            activity: ActivityEntry[];
                        };
                    }) => {
                        if (ack && ack.ok && ack.snapshot) {
                            setUsers(ack.snapshot.users);
                            setLockedNodes(ack.snapshot.locks);
                            setProposals(ack.snapshot.proposals);
                            setActivity(ack.snapshot.activity);
                        }
                    },
                );
            });
            socket.on("disconnect", () => setConnected(false));
            socket.on("connect_error", () => setConnected(false));

            // Presence
            socket.on("user_joined", (payload: { users: CollabUser[] }) => {
                if (payload && Array.isArray(payload.users)) {
                    setUsers(payload.users);
                }
            });
            socket.on("user_left", (payload: { users: CollabUser[] }) => {
                if (payload && Array.isArray(payload.users)) {
                    setUsers(payload.users);
                }
            });

            // Locks
            socket.on(
                "node_locked",
                (payload: { nodeId: string; lock: NodeLock }) => {
                    setLockedNodes((prev) => ({
                        ...prev,
                        [payload.nodeId]: payload.lock,
                    }));
                },
            );
            socket.on("node_unlocked", (payload: { nodeId: string }) => {
                setLockedNodes((prev) => {
                    const next = { ...prev };
                    delete next[payload.nodeId];
                    return next;
                });
            });

            // Proposals
            socket.on("code_change_proposed", (proposal: CodeProposal) => {
                setProposals((prev) =>
                    prev.some((p) => p.id === proposal.id)
                        ? prev
                        : [...prev, proposal],
                );
            });
            socket.on(
                "code_change_voted",
                (vote: {
                    proposalId: string;
                    approvals: string[];
                    rejections: string[];
                }) => {
                    setProposals((prev) =>
                        prev.map((p) =>
                            p.id === vote.proposalId
                                ? {
                                      ...p,
                                      approvals: vote.approvals,
                                      rejections: vote.rejections,
                                  }
                                : p,
                        ),
                    );
                },
            );
            const dropProposal = (proposalId: string) =>
                setProposals((prev) => prev.filter((p) => p.id !== proposalId));
            socket.on("code_change_applied", (proposal: CodeProposal) => {
                dropProposal(proposal.id);
            });
            socket.on(
                "code_change_rejected",
                (payload: { proposalId: string }) => {
                    dropProposal(payload.proposalId);
                },
            );

            // Activity log: every relayed event also bumps the activity feed.
            const recordActivity = (kind: string) =>
                setActivity((prev) =>
                    [
                        ...prev,
                        { kind, ts: Date.now() / 1000, payload: {} },
                    ].slice(-200),
                );
            socket.on("conflict_resolved", () => recordActivity("conflict_resolved"));

            // Fan-out to consumer-registered handlers.
            for (const ev of REMOTE_EVENTS) {
                socket.on(ev, (payload: unknown) => {
                    const handlers = remoteHandlersRef.current.get(ev);
                    if (!handlers) return;
                    for (const h of handlers) {
                        try {
                            h(payload);
                        } catch {
                            /* never let a consumer break the dispatch loop */
                        }
                    }
                });
            }
        },
        [],
    );

    const connectFor = useCallback(
        (projectId: string) => {
            closeSocket();
            const token = getToken();
            if (!token) {
                // No token → don't even try; backend would refuse the handshake.
                return;
            }
            const url = `${BACKEND_URL}${NAMESPACE}`;
            const s = io(url, {
                auth: { token },
                transports: ["websocket", "polling"],
                reconnection: true,
            });
            socketRef.current = s;
            installSocketListeners(s);
        },
        [closeSocket, installSocketListeners],
    );

    // Follow the current project. When enabled flips on, take whatever
    // project is already loaded; on every project change emit
    // leave_session and reconnect with the new room.
    useEffect(() => {
        if (!enabled) {
            closeSocket();
            return;
        }
        const reconcile = () => {
            const nextId = getCurrentProjectId();
            const prevId = projectIdRef.current;
            projectIdRef.current = nextId;
            if (nextId === prevId && socketRef.current) return;
            if (!nextId) {
                closeSocket();
                return;
            }
            connectFor(nextId);
        };
        const unsub = subscribeProject(reconcile);
        reconcile();
        return () => {
            unsub();
            closeSocket();
        };
    }, [enabled, closeSocket, connectFor]);

    // Resolve the local user's id from /api/auth/me once after enabling.
    useEffect(() => {
        if (!enabled) {
            setCurrentUserId(null);
            return;
        }
        let cancelled = false;
        authApi
            .getMe()
            .then((me) => {
                if (!cancelled) setCurrentUserId(me.id);
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [enabled]);

    // ------------------------------------------------------------------
    // Outbound helpers (no-op when not connected; safe to call from any
    // component without guarding).
    // ------------------------------------------------------------------
    const _emit = useCallback(
        (event: string, payload: Record<string, unknown>) => {
            const s = socketRef.current;
            const projectId = projectIdRef.current;
            if (!s || !s.connected || !projectId) return;
            s.emit(event, { projectId, ...payload });
        },
        [],
    );

    const lockNode = useCallback(
        (nodeId: string) => _emit("node_lock", { nodeId }),
        [_emit],
    );
    const unlockNode = useCallback(
        (nodeId: string) => _emit("node_unlock", { nodeId }),
        [_emit],
    );
    const requestCodeChange = useCallback(
        (
            nodeId: string,
            oldValue: string | null,
            newValue: string,
            kind: "code" | "grammar" = "code",
        ) =>
            _emit("request_code_change", {
                nodeId,
                kind,
                oldValue,
                newValue,
            }),
        [_emit],
    );
    const approveCodeChange = useCallback(
        (proposalId: string) => _emit("approve_code_change", { proposalId }),
        [_emit],
    );
    const rejectCodeChange = useCallback(
        (proposalId: string) => _emit("reject_code_change", { proposalId }),
        [_emit],
    );
    const resolveConflict = useCallback(
        (payload: Record<string, unknown>) => _emit("resolve_conflict", payload),
        [_emit],
    );

    const broadcastNodeAdded = useCallback(
        (payload: Record<string, unknown>) => _emit("node_added", payload),
        [_emit],
    );
    const broadcastNodeUpdated = useCallback(
        (payload: Record<string, unknown>) => _emit("node_updated", payload),
        [_emit],
    );
    const broadcastNodeRemoved = useCallback(
        (nodeId: string) => _emit("node_removed", { nodeId }),
        [_emit],
    );
    const broadcastEdgeAdded = useCallback(
        (payload: Record<string, unknown>) => _emit("edge_added", payload),
        [_emit],
    );
    const broadcastEdgeRemoved = useCallback(
        (edgeId: string) => _emit("edge_removed", { edgeId }),
        [_emit],
    );
    const broadcastOutputProduced = useCallback(
        (payload: OutputBroadcast) =>
            _emit("output_produced", payload as unknown as Record<string, unknown>),
        [_emit],
    );
    const signalExecDisplay = useCallback(
        (nodeId: string) => _emit("node_exec_display", { nodeId }),
        [_emit],
    );

    const onRemote = useCallback(
        (event: string, handler: RemoteHandler) => {
            const map = remoteHandlersRef.current;
            let bucket = map.get(event);
            if (!bucket) {
                bucket = new Set();
                map.set(event, bucket);
            }
            bucket.add(handler);
            return () => {
                const b = map.get(event);
                if (!b) return;
                b.delete(handler);
                if (b.size === 0) map.delete(event);
            };
        },
        [],
    );

    const value: CollabContextValue = useMemo(
        () => ({
            enabled,
            connected,
            currentUserId,
            users,
            lockedNodes,
            proposals,
            activity,

            lockNode,
            unlockNode,
            requestCodeChange,
            approveCodeChange,
            rejectCodeChange,
            resolveConflict,

            broadcastNodeAdded,
            broadcastNodeUpdated,
            broadcastNodeRemoved,
            broadcastEdgeAdded,
            broadcastEdgeRemoved,
            broadcastOutputProduced,
            signalExecDisplay,

            onRemote,
        }),
        [
            enabled,
            connected,
            currentUserId,
            users,
            lockedNodes,
            proposals,
            activity,
            lockNode,
            unlockNode,
            requestCodeChange,
            approveCodeChange,
            rejectCodeChange,
            resolveConflict,
            broadcastNodeAdded,
            broadcastNodeUpdated,
            broadcastNodeRemoved,
            broadcastEdgeAdded,
            broadcastEdgeRemoved,
            broadcastOutputProduced,
            signalExecDisplay,
            onRemote,
        ],
    );

    return (
        <CollabContext.Provider value={value}>{children}</CollabContext.Provider>
    );
};
