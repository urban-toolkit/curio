/**
 * Real-time collaboration provider.
 *
 * It follows the currently-loaded project via
 * ``projectPackagesStore.subscribe``, opening one socket per project id once a
 * tab is signed in, emitting ``join_session`` on connect, and tearing the
 * socket down when the user navigates to a different project (or away from
 * the canvas). Every backend serves the socket: the dataflow's Yjs doc
 * travels on it (``collab/docProvider.ts``), whatever ``--collab`` says. With
 * ``enable_collab=false`` from ``/api/config/public`` the room's own controls,
 * the people panel and its button, stay hidden (``enabled``).
 *
 * Identity is anchored in the backend Bearer token sent through the
 * Socket.IO ``auth`` handshake. We never trust user-supplied identity
 * fields in event payloads.
 *
 * The join answers with this tab's participant id and the role its account
 * has on the dataflow: owner, editor (invited by the owner) or watcher. The
 * room's user list carries every participant's role, and this tab's own role
 * is read from its own entry there, so a change the owner makes to the
 * editors reaches it with the list (``roles_changed``). Every "is this me?"
 * compares participant ids (``collab/participants.ts``). A join the server
 * refuses (a hosted guest's to an example) closes the socket for that
 * dataflow, and its canvas stays its own, bound to no doc.
 *
 * Once joined, the tab syncs the dataflow's doc, which ``DataflowDocContext``
 * hands the canvas. A change of the tab's role, either way, and a doc the
 * server built anew, start the doc again from the server's. A Curio with no
 * sign-in (``curio_no_auth``, or no projects page) starts no doc: each canvas
 * stays its own there.
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
import { backendUrl } from "../utils/backendUrl";
import { collabSocketTarget } from "../utils/collabSocketTarget";
import { roleIn, writesDoc, type RoomRole } from "./collab/participants";
import { DataflowDocProvider } from "./collab/docProvider";
import { CONNECTION_DROPPED_EVENT, DataflowDocContext, type DocBinding } from "./collab/docContext";
import { remoteCursorStyle } from "./collab/presence";

export type { RoomRole } from "./collab/participants";

const BACKEND_URL = backendUrl();
// The backend's --collab-namespace, until /api/config/public reports it.
const DEFAULT_NAMESPACE = "/collab";
/** The style element that colors everyone else's cursor in the code editors. */
const CURSOR_STYLE_ID = "curio-remote-cursors";

export interface CollabUser {
    user_id: number;
    username: string;
    name?: string;
    profile_image?: string | null;
    /** This participant's id in the room: one per tab. */
    participant_id?: string;
    role?: RoomRole;
}

export interface NodeLock {
    user_id: number;
    username: string;
    name?: string;
    /** The participant that holds the lock. */
    participant_id?: string;
    since: number;
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
    /** Whether collaboration's own controls show: the people panel, its
     *  button, the editors' lock chips (`--collab`). */
    enabled: boolean;
    connected: boolean;
    /** This tab's participant id in the room, once its join answered. */
    participantId: string | null;
    /** This tab's role on the dataflow, from its own entry in `users`; null
     *  until it has joined. */
    role: RoomRole | null;
    users: CollabUser[];
    lockedNodes: Record<string, NodeLock>;
    activity: ActivityEntry[];

    /** Whether the right-docked side panel is currently visible. */
    panelOpen: boolean;
    /** Toggle the side panel from anywhere in the tree (UpMenu trigger). */
    setPanelOpen: (open: boolean) => void;

    lockNode: (nodeId: string) => void;
    unlockNode: (nodeId: string) => void;
    resolveConflict: (payload: Record<string, unknown>) => void;

    broadcastOutputProduced: (payload: OutputBroadcast) => void;
    signalExecDisplay: (nodeId: string) => void;

    /**
     * Subscribe to incoming remote events. Returns an unsubscribe fn.
     * Event names mirror the backend's outgoing events: ``output_produced``,
     * ``conflict_resolved``, ``node_exec_display`` (``events.py``), and
     * ``connection_dropped`` (``dataflow_docs.py``).
     */
    onRemote: (event: string, handler: RemoteHandler) => () => void;
}

const NOOP_VALUE: CollabContextValue = {
    enabled: false,
    connected: false,
    participantId: null,
    role: null,
    users: [],
    lockedNodes: {},
    activity: [],

    panelOpen: false,
    setPanelOpen: () => undefined,

    lockNode: () => undefined,
    unlockNode: () => undefined,
    resolveConflict: () => undefined,

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
    "roles_changed",
    "node_locked",
    "node_unlocked",
    "output_produced",
    "node_exec_display",
    "conflict_resolved",
    CONNECTION_DROPPED_EVENT,
] as const;

export const CollaborationProvider: React.FC<{ children: React.ReactNode }> = ({
    children,
}) => {
    const [configLoaded, setConfigLoaded] = useState<boolean>(false);
    const [enabled, setEnabled] = useState<boolean>(false);
    const [connected, setConnected] = useState<boolean>(false);
    const [users, setUsers] = useState<CollabUser[]>([]);
    const [lockedNodes, setLockedNodes] = useState<Record<string, NodeLock>>({});
    const [activity, setActivity] = useState<ActivityEntry[]>([]);
    const [participantId, setParticipantId] = useState<string | null>(null);
    // Panel visibility is owned by the provider so the UpMenu trigger can
    // toggle it without prop-drilling through MainCanvas.
    const [panelOpen, setPanelOpen] = useState<boolean>(true);
    // This tab's role is its own entry's in the room's list, so every list
    // the server sends (a join, a leave, a change of editors) keeps it current.
    const role = useMemo(() => roleIn(users, participantId), [users, participantId]);
    // The dataflow's doc on this tab, once the room has joined it.
    const [docBinding, setDocBinding] = useState<DocBinding | null>(null);

    const socketRef = useRef<Socket | null>(null);
    const namespaceRef = useRef<string>(DEFAULT_NAMESPACE);
    // The flag as the doc's writers read it: read before any socket opens.
    const enabledRef = useRef<boolean>(false);
    // A Curio with no sign-in (the shared guest signed in for everyone, or no
    // projects page): each canvas stays its own, bound to no doc.
    const noSignInRef = useRef<boolean>(false);
    const projectIdRef = useRef<string | undefined>(getCurrentProjectId());
    // The dataflow whose room refused this tab: no socket is opened for it
    // again until another dataflow opens.
    const refusedProjectRef = useRef<string | undefined>(undefined);
    const remoteHandlersRef = useRef<Map<string, Set<RemoteHandler>>>(new Map());
    const docProviderRef = useRef<DataflowDocProvider | null>(null);

    // ------------------------------------------------------------------
    // Read the flag and the namespace once.
    // ------------------------------------------------------------------
    useEffect(() => {
        let cancelled = false;
        authApi
            .getPublicConfig()
            .then((cfg) => {
                if (cancelled) return;
                namespaceRef.current = cfg.collab_namespace || DEFAULT_NAMESPACE;
                enabledRef.current = Boolean(cfg.enable_collab);
                noSignInRef.current = Boolean(cfg.curio_no_auth || cfg.skip_project_page || cfg.curio_no_project);
                setEnabled(Boolean(cfg.enable_collab));
                setConfigLoaded(true);
            })
            .catch(() => {
                if (cancelled) return;
                setEnabled(false);
                setConfigLoaded(true);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    /** Drop the doc this tab holds. */
    const dropDoc = useCallback(() => {
        const provider = docProviderRef.current;
        docProviderRef.current = null;
        provider?.destroy();
        setDocBinding(null);
    }, []);

    /** Start the dataflow's doc on *socket*, joined to *projectId*'s room, as a
     *  tab with *role*: the doc the tab holds, synced again, unless *fresh*
     *  or the tab's role changed whether it writes (`writesDoc`). */
    const startDoc = useCallback((socket: Socket, projectId: string, role: RoomRole | null, fresh = false) => {
        const prior = docProviderRef.current;
        const writes = writesDoc(role, enabledRef.current);
        if (!fresh && prior && prior.projectId === projectId && prior.canWrite === writes) {
            prior.attach(socket);
            return;
        }
        dropDoc();
        const provider: DataflowDocProvider = new DataflowDocProvider(projectId, {
            canWrite: writes,
            onSynced: () => {
                if (docProviderRef.current === provider) setDocBinding({ provider, synced: true });
            },
            // The server holds another doc: this tab starts again from it.
            onReload: () => {
                if (docProviderRef.current !== provider || socketRef.current !== socket) return;
                startDoc(socket, projectId, role, true);
            },
            // The tab watches now: what it did not send is dropped, and its doc
            // is the server's again.
            onReadOnly: () => {
                if (docProviderRef.current !== provider || socketRef.current !== socket) return;
                startDoc(socket, projectId, "watcher", true);
            },
        });
        docProviderRef.current = provider;
        setDocBinding({ provider, synced: false });
        provider.attach(socket);
    }, [dropDoc]);

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
        dropDoc();
        setConnected(false);
        setParticipantId(null);
        setUsers([]);
        setLockedNodes({});
        setActivity([]);
    }, [dropDoc]);

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
                        error?: string;
                        participant_id?: string;
                        role?: RoomRole;
                        snapshot?: {
                            users: CollabUser[];
                            locks: Record<string, NodeLock>;
                            activity: ActivityEntry[];
                        };
                    }) => {
                        if (ack && ack.ok && ack.snapshot) {
                            setParticipantId(ack.participant_id ?? null);
                            setUsers(ack.snapshot.users);
                            setLockedNodes(ack.snapshot.locks);
                            setActivity(ack.snapshot.activity);
                            if (socketRef.current === socket && !noSignInRef.current) {
                                startDoc(socket, projectId, ack.role ?? null);
                            }
                        } else if (ack && ack.ok === false && socketRef.current === socket) {
                            // Refused: this tab is not in the room, so it keeps
                            // no socket for it. Nothing is retried for the
                            // same dataflow.
                            refusedProjectRef.current = projectId;
                            closeSocket();
                        }
                    },
                );
            });
            socket.on("disconnect", () => {
                setConnected(false);
                // A reconnected socket is a new participant, named by its next join.
                setParticipantId(null);
                docProviderRef.current?.detach();
            });
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
            // The owner invited or removed an editor: everyone's roles, this
            // tab's among them.
            socket.on("roles_changed", (payload: { users: CollabUser[] }) => {
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
        [closeSocket, startDoc],
    );

    const connectFor = useCallback(
        (projectId: string) => {
            closeSocket();
            const token = getToken();
            if (!token) {
                // No token → don't even try; backend would refuse the handshake.
                return;
            }
            const { url, path } = collabSocketTarget(BACKEND_URL, namespaceRef.current);
            const s = io(url, {
                path,
                auth: { token },
                transports: ["websocket", "polling"],
                reconnection: true,
            });
            socketRef.current = s;
            installSocketListeners(s);
        },
        [closeSocket, installSocketListeners],
    );

    // Follow the current project once the namespace is known. On every
    // project change close the socket and reconnect with the new room.
    // Closing is the whole story - the backend's ``disconnect`` handler
    // releases this sid's locks, emits ``user_left`` to the old room and
    // clears its presence in the doc, so there is nothing to send first.
    useEffect(() => {
        if (!configLoaded) return;
        // With no sign-in a tab binds no doc, so without the people panel it
        // has nothing to join a room for.
        if (noSignInRef.current && !enabledRef.current) return;
        const reconcile = () => {
            const nextId = getCurrentProjectId();
            const prevId = projectIdRef.current;
            projectIdRef.current = nextId;
            if (nextId !== prevId) refusedProjectRef.current = undefined;
            if (nextId === prevId && socketRef.current) return;
            if (!nextId) {
                closeSocket();
                return;
            }
            // The room refused this tab: it stays out until another dataflow opens.
            if (nextId === refusedProjectRef.current) return;
            connectFor(nextId);
        };
        const unsub = subscribeProject(reconcile);
        reconcile();
        return () => {
            unsub();
            closeSocket();
        };
    }, [configLoaded, closeSocket, connectFor]);

    // A change of this tab's role, either way, starts the doc again: an
    // editor made a watcher drops what it did not send, and a watcher made an
    // editor takes the server's doc before it writes.
    useEffect(() => {
        const provider = docProviderRef.current;
        const socket = socketRef.current;
        if (!provider || !socket || !role) return;
        if (provider.canWrite !== writesDoc(role, enabledRef.current)) startDoc(socket, provider.projectId, role, true);
    }, [role, startDoc]);

    // Everyone else's cursor in the code editors, in their color.
    useEffect(() => {
        const awareness = docBinding?.provider.awareness;
        if (!awareness || typeof document === "undefined") return;
        let style = document.getElementById(CURSOR_STYLE_ID) as HTMLStyleElement | null;
        if (!style) {
            style = document.createElement("style");
            style.id = CURSOR_STYLE_ID;
            document.head.appendChild(style);
        }
        const paint = () => {
            if (style) style.textContent = remoteCursorStyle(awareness);
        };
        paint();
        awareness.on("change", paint);
        return () => {
            awareness.off("change", paint);
            if (style) style.textContent = "";
        };
    }, [docBinding?.provider]);

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
    const resolveConflict = useCallback(
        (payload: Record<string, unknown>) => _emit("resolve_conflict", payload),
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
            participantId,
            role,
            users,
            lockedNodes,
            activity,

            panelOpen,
            setPanelOpen,

            lockNode,
            unlockNode,
            resolveConflict,

            broadcastOutputProduced,
            signalExecDisplay,

            onRemote,
        }),
        [
            enabled,
            connected,
            participantId,
            role,
            users,
            lockedNodes,
            activity,
            panelOpen,
            lockNode,
            unlockNode,
            resolveConflict,
            broadcastOutputProduced,
            signalExecDisplay,
            onRemote,
        ],
    );

    return (
        <CollabContext.Provider value={value}>
            <DataflowDocContext.Provider value={docBinding}>{children}</DataflowDocContext.Provider>
        </CollabContext.Provider>
    );
};
