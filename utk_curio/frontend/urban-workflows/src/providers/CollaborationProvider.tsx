import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  ReactNode,
} from 'react';
import { io, Socket } from 'socket.io-client';
import { useParams } from 'react-router-dom';
import { v4 as uuidv4 } from 'uuid';
import { useFlowContext } from './FlowProvider';
import { PythonInterpreter } from '../PythonInterpreter';
import { BACKEND_URL } from '../utils/backendUrl';

// ── Types ────────────────────────────────────────────────────────────────────

export interface CollabUser {
  userId: string;
  color: string;
  name?: string;
}

export interface LockInfo {
  userId: string;
  color: string;
  name?: string;
}

export interface Conflict {
  conflictId: string;
  type: string;
  message?: string;
  entityId?: string;
  nodeId?: string;
  edgeId?: string;
  operation?: string;
  actor?: CollabUser;
  lockedBy?: LockInfo;
  requestedBy?: LockInfo;
  currentOwner?: CollabUser;
  deletedBy?: CollabUser;
  baseRevision?: number;
  serverRevision?: number;
  incomingNode?: any;
  currentNode?: any;
  incomingEdge?: any;
  currentEdge?: any;
  affectedNodeIds?: string[];
  changeSummary?: string[];
  timestamp: number;
}

export interface ActivityItem {
  id: string;
  kind: string;
  label: string;
  entityId?: string;
  timestamp: number;
  user: CollabUser;
  details?: any;
}

export interface CodeChangeProposal {
  proposalId: string;
  nodeId: string;
  node: any;
  currentNode?: any;
  proposedBy: CollabUser;
  requiredUserIds: string[];
  approvals: Record<string, { user: CollabUser; timestamp: number }>;
  comments: Record<string, { user: CollabUser; comment: string; timestamp: number }>;
  changeSummary?: string[];
  timestamp: number;
  status?: string;
}

export type ConflictResolutionAction = 'keep_mine' | 'accept_other' | 'manual' | 'cancel';

interface CollaborationContextProps {
  isConnected: boolean;
  myUserId: string;
  myUserName: string;
  myColor: string;
  sessionId: string;
  connectedUsers: CollabUser[];
  lockedNodes: Record<string, LockInfo>;
  conflicts: Conflict[];
  codeChangeProposals: CodeChangeProposal[];
  activityLog: ActivityItem[];
  setUserName: (name: string) => void;
  lockNode: (nodeId: string) => void;
  unlockNode: (nodeId: string) => void;
  dismissConflict: (nodeId: string) => void;
  resolveConflict: (conflict: Conflict, action: ConflictResolutionAction) => void;
  requestCodeChange: (nodeId: string, code: string) => void;
  approveCodeChange: (proposalId: string) => void;
  rejectCodeChange: (proposalId: string, comment: string) => void;
  syncNodeOutput: (nodeId: string, displayOutput: { code: string; content: string }) => void;
}

const CollaborationContext = createContext<CollaborationContextProps>({
  isConnected: false,
  myUserId: '',
  myUserName: '',
  myColor: '#3498db',
  sessionId: 'default',
  connectedUsers: [],
  lockedNodes: {},
  conflicts: [],
  codeChangeProposals: [],
  activityLog: [],
  setUserName: () => {},
  lockNode: () => {},
  unlockNode: () => {},
  dismissConflict: () => {},
  resolveConflict: () => {},
  requestCodeChange: () => {},
  approveCodeChange: () => {},
  rejectCodeChange: () => {},
  syncNodeOutput: () => {},
});

// ── Helpers ──────────────────────────────────────────────────────────────────

// Runtime-only fields in node.data — class instances or functions that must be
// recreated locally in each browser. Never sync them over the socket, and always
// reattach the local versions when receiving a remote node.
const RUNTIME_DATA_FIELDS = new Set([
  'pythonInterpreter',
  'outputCallback',
  'interactionsCallback',
  'propagationCallback',
]);

// Local-only stamps that must not bounce back to the server.
const LOCAL_ONLY_DATA_FIELDS = new Set(['_approvedCodeStamp']);

/**
 * Strip non-serializable / runtime-only fields from a node before sending over
 * the socket. The shared payload only carries plain-JSON state — accepted code,
 * output snapshot, position, etc. Local runtime callbacks are reattached on
 * receive via hydrateNodeForRuntime.
 */
function serializeNode(node: any): any {
  const data: Record<string, any> = {};
  for (const [k, v] of Object.entries(node.data || {})) {
    if (RUNTIME_DATA_FIELDS.has(k)) continue;
    if (LOCAL_ONLY_DATA_FIELDS.has(k)) continue;
    if (typeof v === 'function') continue;
    if (v !== null && typeof v === 'object' && typeof (v as any).interpretCode === 'function') continue;
    data[k] = v;
  }
  return { ...node, data };
}

/** Lightweight snapshot of the node fields that matter for collaboration.
 *  Position is intentionally excluded — node placement is local-only and
 *  shouldn't trigger updates or conflicts. */
function nodeFingerprintPayload(node: any): Record<string, any> {
  const d = node.data || {};
  return {
    input: d.input,
    source: d.source,
    defaultCode: d.defaultCode,
    content: d.content,
    code: d.code,
  };
}

function dataFingerprint(node: any): string {
  return JSON.stringify(nodeFingerprintPayload(node));
}

function summarizeNodeChange(previousFingerprint: string | undefined, node: any): string[] {
  if (!previousFingerprint) return ['node'];
  try {
    const previous = JSON.parse(previousFingerprint);
    const current = nodeFingerprintPayload(node);
    const labels: Record<string, string> = {
      input: 'input',
      source: 'source',
      defaultCode: 'default code',
      content: 'content',
      code: 'code',
    };
    return Object.keys(labels).filter((key) =>
      JSON.stringify(previous[key]) !== JSON.stringify(current[key])
    ).map((key) => labels[key]);
  } catch (_) {
    return ['node'];
  }
}

function upsertById<T extends { proposalId: string }>(items: T[], item: T): T[] {
  const index = items.findIndex((existing) => existing.proposalId === item.proposalId);
  if (index < 0) return [item, ...items];
  const next = [...items];
  next[index] = item;
  return next;
}

function outputDisplayForNode(output: any) {
  return {
    code: output ? 'success' : '',
    content: output?.path
      ? `Shared output available.\nSaved to file: ${output.path}\nType: ${output.dataType || 'unknown'}`
      : output
        ? 'Shared output available.'
        : 'No output available.',
    outputType: output?.dataType || '',
  };
}

function getOrCreateUserId(): string {
  const key = 'curio_collab_connectionId';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = uuidv4();
    sessionStorage.setItem(key, id);
  }
  return id;
}

function getInitialUserName(userId: string): string {
  return localStorage.getItem('curio_collab_userName') || `Analyst ${userId.slice(0, 4)}`;
}

// ── Provider ─────────────────────────────────────────────────────────────────

const CollaborationProvider = ({ children }: { children: ReactNode }) => {
  const {
    nodes,
    edges,
    setNodes,
    setEdges,
    outputs,
    setOutputs,
    setInteractions,
    applyNewOutput,
    applyNewPropagation,
  } = useFlowContext();

  const socketRef = useRef<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const myUserId = useRef(getOrCreateUserId()).current;
  const [myUserName, setMyUserName] = useState(getInitialUserName(myUserId));
  const [myColor, setMyColor] = useState('#3498db');

  const [connectedUsers, setConnectedUsers] = useState<CollabUser[]>([]);
  const [lockedNodes, setLockedNodes] = useState<Record<string, LockInfo>>({});
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [codeChangeProposals, setCodeChangeProposals] = useState<CodeChangeProposal[]>([]);
  const [activityLog, setActivityLog] = useState<ActivityItem[]>([]);

  // Track previous node/edge id-sets to diff local changes
  const prevNodeIds = useRef<Set<string>>(new Set());
  const prevEdgeIds = useRef<Set<string>>(new Set());
  const prevEdgeSnapshots = useRef<Map<string, any>>(new Map());

  // Track node data fingerprints to detect content changes
  const prevNodeData = useRef<Map<string, string>>(new Map());
  const nodeRevisions = useRef<Map<string, number>>(new Map());
  const edgeRevisions = useRef<Map<string, number>>(new Map());

  // Ids added/removed/updated by remote events — skip re-emitting them
  const remoteNodeAdds = useRef<Set<string>>(new Set());
  const remoteNodeRemoves = useRef<Set<string>>(new Set());
  const remoteNodeUpdates = useRef<Set<string>>(new Set());
  const remoteEdgeAdds = useRef<Set<string>>(new Set());
  const remoteEdgeRemoves = useRef<Set<string>>(new Set());
  const remoteOutputUpdates = useRef<Set<string>>(new Set());
  const pythonInterpreter = useRef(new PythonInterpreter()).current;

  const outputCallback = useCallback((nodeId: string, output: any) => {
    applyNewOutput({ nodeId, output });
  }, [applyNewOutput]);

  const interactionsCallback = useCallback((interactions: any, nodeId: string) => {
    setInteractions((prevInteractions: any[]) => {
      let newNode = true;
      const nextInteractions = prevInteractions.map((interaction: any) => {
        if (interaction.nodeId === nodeId) {
          newNode = false;
          return { nodeId, details: interactions, priority: 1 };
        }
        return { ...interaction, priority: 0 };
      });

      if (newNode) nextInteractions.push({ nodeId, details: interactions, priority: 1 });
      return nextInteractions;
    });
  }, [setInteractions]);

  const hydrateNodeForRuntime = useCallback((node: any, existingNode?: any) => {
    // Strip runtime-only fields off the incoming remote node — they cannot be
    // serialized and must always be reattached locally on receive.
    const remoteData: Record<string, any> = {};
    for (const [k, v] of Object.entries(node.data || {})) {
      if (RUNTIME_DATA_FIELDS.has(k)) continue;
      remoteData[k] = v;
    }
    const existingData = existingNode?.data || {};
    // data.code is the shared, accepted code. If the remote payload doesn't
    // carry one yet (newly added node), fall back to whatever local code we
    // already had so the editor doesn't lose the user's view of the node.
    const sharedCode =
      typeof remoteData.code === 'string'
        ? remoteData.code
        : existingData.code;

    return {
      ...node,
      // Position is local-only — preserve the user's current placement
      // instead of letting a remote node_added/node_updated payload move
      // their canvas. Only fall back to the remote position on first add
      // when there is no existing local node yet.
      position: existingNode?.position ?? node.position,
      data: {
        ...existingData,
        ...remoteData,
        nodeId: remoteData.nodeId || existingData.nodeId || node.id,
        code: sharedCode,
        // Always reattach runtime fields with the local instances. Remote
        // payloads strip these (they can't be serialized), and stale closures
        // from a previous mount of this provider would not be wired to the
        // current FlowProvider's setOutputs / applyNewOutput.
        pythonInterpreter,
        outputCallback,
        interactionsCallback,
        propagationCallback: applyNewPropagation,
      },
    };
  }, [applyNewPropagation, interactionsCallback, outputCallback, pythonInterpreter]);

  // Keep refs so socket handlers can read the latest values
  const outputsRef = useRef(outputs);
  useEffect(() => { outputsRef.current = outputs; }, [outputs]);
  const edgesRef = useRef(edges);
  useEffect(() => { edgesRef.current = edges; }, [edges]);

  // Track previous output fingerprints to detect local changes
  const prevOutputFingerprints = useRef<Map<string, string>>(new Map());

  // Anchor the room to the URL so two browsers on the same /dataflow/<id>
  // land in the same socket.io room. workflowName is per-browser local
  // state and would silently splinter users.
  const { id: dataflowId } = useParams<{ id?: string }>();
  const sessionId = dataflowId || 'default';

  // ── Socket setup ────────────────────────────────────────────────────────

  useEffect(() => {
    const socket = io(BACKEND_URL, { transports: ['polling', 'websocket'] });
    socketRef.current = socket;

    socket.on('connect', () => {
      setIsConnected(true);
      socket.emit('join_session', { sessionId, userId: myUserId, userName: myUserName });
    });

    socket.on('disconnect', () => setIsConnected(false));

    socket.on('session_state', (data: any) => {
      setMyColor(data.color);
      if (data.name) setMyUserName(data.name);
      setLockedNodes(data.lockedNodes || {});
      setConnectedUsers(data.connectedUsers || []);
      setActivityLog(data.activityLog || []);
      setCodeChangeProposals(data.codeChangeProposals || []);

      nodeRevisions.current = new Map(Object.entries(data.nodeRevisions || {}).map(([id, rev]) => [id, Number(rev)]));
      edgeRevisions.current = new Map(Object.entries(data.edgeRevisions || {}).map(([id, rev]) => [id, Number(rev)]));

      // Populate outputs[] from server-synced outputs
      const remoteOutputs: Record<string, any> = data.outputs || {};
      if (Object.keys(remoteOutputs).length > 0) {
        const entries = Object.entries(remoteOutputs).map(([nodeId, output]) => ({ nodeId, output }));
        entries.forEach((e) => remoteOutputUpdates.current.add(e.nodeId));
        setOutputs((prev: any[]) => {
          const existingIds = new Set(prev.map((o: any) => o.nodeId));
          const newEntries = entries.filter((e) => !existingIds.has(e.nodeId));
          return [...prev, ...newEntries];
        });
        setNodes((prev: any[]) => prev.map((node) => {
          const output = remoteOutputs[node.id];
          if (!output) return node;
          return {
            ...node,
            data: {
              ...node.data,
              output: outputDisplayForNode(output),
              lastOutput: output,
              outputRef: output?.path,
              outputDataType: output?.dataType,
            },
          };
        }));
      }

      // Apply existing graph so late joiners see the full canvas
      const remoteNodes: any[] = data.nodes || [];
      const remoteEdges: any[] = data.edges || [];

      if (remoteNodes.length > 0) {
        remoteNodes.forEach((n) => remoteNodeAdds.current.add(n.id));
        setNodes((prev: any[]) => {
          const remoteById = new Map(remoteNodes.map((n) => [n.id, n]));
          const existingIds = new Set(prev.map((n) => n.id));
          const updatedExisting = prev.map((n) => {
            const remoteNode = remoteById.get(n.id);
            return remoteNode ? hydrateNodeForRuntime(remoteNode, n) : n;
          });
          const safeNodes = remoteNodes
            .filter((n) => !existingIds.has(n.id))
            .map((n) => hydrateNodeForRuntime(n));
          const nextNodes = [...updatedExisting, ...safeNodes];
          prevNodeIds.current = new Set(nextNodes.map((n) => n.id));
          nextNodes.forEach((n) => prevNodeData.current.set(n.id, dataFingerprint(n)));
          return nextNodes;
        });
      }
      if (remoteEdges.length > 0) {
        remoteEdges.forEach((e) => remoteEdgeAdds.current.add(e.id));
        setEdges((prev: any[]) => {
          const existingIds = new Set(prev.map((e) => e.id));
          return [...prev, ...remoteEdges.filter((e) => !existingIds.has(e.id))];
        });
      }
    });

    socket.on('user_joined', (data: CollabUser) => {
      setConnectedUsers((prev) => {
        if (prev.some((u) => u.userId === data.userId)) return prev;
        return [...prev, data];
      });
    });

    socket.on('user_left', (data: { userId: string }) => {
      setConnectedUsers((prev) => prev.filter((u) => u.userId !== data.userId));
    });

    socket.on('user_updated', (data: CollabUser) => {
      if (data.userId === myUserId) {
        if (data.name) setMyUserName(data.name);
        if (data.color) setMyColor(data.color);
      }
      setConnectedUsers((prev) => prev.map((u) => u.userId === data.userId ? { ...u, ...data } : u));
    });

    socket.on('state_ack', (data: any) => {
      if (data.entity === 'node') {
        nodeRevisions.current.set(data.id, Number(data.revision || 0));
      } else if (data.entity === 'edge') {
        edgeRevisions.current.set(data.id, Number(data.revision || 0));
      }
    });

    socket.on('activity_recorded', (activity: ActivityItem) => {
      setActivityLog((prev) => [activity, ...prev.filter((item) => item.id !== activity.id)].slice(0, 50));
    });

    socket.on('conflict_resolved', (data: { conflictId: string }) => {
      setConflicts((prev) => prev.filter((c) => c.conflictId !== data.conflictId));
    });

    // ── Remote graph changes ──────────────────────────────────────────────

    socket.on('node_added', (data: any) => {
      const node = data.node;
      if (data.revision !== undefined) nodeRevisions.current.set(node.id, Number(data.revision));
      remoteNodeAdds.current.add(node.id);
      setNodes((prev: any[]) => {
        if (prev.some((n) => n.id === node.id)) return prev;
        return [...prev, hydrateNodeForRuntime(node)];
      });
    });

    socket.on('node_removed', (data: { nodeId: string }) => {
      nodeRevisions.current.set(data.nodeId, Number((data as any).revision || nodeRevisions.current.get(data.nodeId) || 0));
      remoteNodeRemoves.current.add(data.nodeId);
      setNodes((prev: any[]) => prev.filter((n) => n.id !== data.nodeId));
    });

    socket.on('edge_added', (data: any) => {
      const edge = data.edge;
      if (data.revision !== undefined) edgeRevisions.current.set(edge.id, Number(data.revision));
      remoteEdgeAdds.current.add(edge.id);
      setEdges((prev: any[]) => {
        if (prev.some((e) => e.id === edge.id)) return prev;
        return [...prev, edge];
      });

      // Propagate source node's output to the newly connected target node
      // using the synced outputs[] array as the source of truth
      if (edge.sourceHandle !== 'in/out' || edge.targetHandle !== 'in/out') {
        const srcOutput = outputsRef.current.find((o: any) => o.nodeId === edge.source);
        if (srcOutput) {
          setNodes((prev: any[]) => prev.map((n) => {
            if (n.id !== edge.target) return n;
            return { ...n, data: { ...n.data, input: srcOutput.output, source: edge.source } };
          }));
        }
      }
    });

    socket.on('edge_removed', (data: { edgeId: string }) => {
      edgeRevisions.current.set(data.edgeId, Number((data as any).revision || edgeRevisions.current.get(data.edgeId) || 0));
      remoteEdgeRemoves.current.add(data.edgeId);
      setEdges((prev: any[]) => prev.filter((e) => e.id !== data.edgeId));
    });

    socket.on('node_updated', (data: any) => {
      const node = data.node;
      if (data.revision !== undefined) nodeRevisions.current.set(node.id, Number(data.revision));
      remoteNodeUpdates.current.add(node.id);
      setNodes((prev: any[]) => prev.map((n) => {
        if (n.id !== node.id) return n;
        return hydrateNodeForRuntime(node, n);
      }));
    });

    // ── Output sync ─────────────────────────────────────────────────────

    socket.on('output_produced', (data: any) => {
      const { nodeId, output } = data;
      remoteOutputUpdates.current.add(nodeId);
      setOutputs((prev: any[]) => {
        const idx = prev.findIndex((o: any) => o.nodeId === nodeId);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = { nodeId, output };
          return updated;
        }
        return [...prev, { nodeId, output }];
      });

      setNodes((prev: any[]) => prev.map((n) => {
        if (n.id !== nodeId) return n;
        return {
          ...n,
          data: {
            ...n.data,
            output: outputDisplayForNode(output),
            lastOutput: output,
            outputRef: output?.path,
            outputDataType: output?.dataType,
          },
        };
      }));

      // Propagate output to downstream connected nodes
      const downstream = edgesRef.current
        .filter((e: any) => e.source === nodeId && !(e.sourceHandle === 'in/out' && e.targetHandle === 'in/out'))
        .map((e: any) => e.target);
      if (downstream.length > 0) {
        setNodes((prev: any[]) => prev.map((n) => {
          if (!downstream.includes(n.id)) return n;
          return { ...n, data: { ...n.data, input: output, source: nodeId } };
        }));
      }
    });

    // ── Execution display sync ───────────────────────────────────────────────

    socket.on('node_exec_display', (data: any) => {
      const { nodeId, displayOutput } = data;
      if (!nodeId || !displayOutput) return;
      setNodes((prev: any[]) => prev.map((n) => {
        if (n.id !== nodeId) return n;
        return { ...n, data: { ...n.data, output: displayOutput } };
      }));
    });

    // ── Lock events ───────────────────────────────────────────────────────

    socket.on('node_locked', (data: { nodeId: string; userId: string; color: string; name?: string }) => {
      setLockedNodes((prev) => ({
        ...prev,
        [data.nodeId]: { userId: data.userId, color: data.color, name: data.name },
      }));
    });

    socket.on('node_unlocked', (data: { nodeId: string }) => {
      setLockedNodes((prev) => {
        const next = { ...prev };
        delete next[data.nodeId];
        return next;
      });
    });

    socket.on('conflict_detected', (data: any) => {
      const conflictId = data.conflictId || `${data.type || 'conflict'}-${data.nodeId || data.edgeId || Date.now()}`;
      setConflicts((prev) => {
        if (prev.some((c) => c.conflictId === conflictId)) return prev;
        return [...prev, { ...data, conflictId, timestamp: data.timestamp || Date.now() }];
      });
    });

    const upsertProposal = (proposal: CodeChangeProposal) => {
      setCodeChangeProposals((prev) => upsertById(prev, proposal));
    };

    socket.on('code_change_requested', upsertProposal);
    socket.on('code_change_approved', upsertProposal);
    socket.on('code_change_rejected', (proposal: CodeChangeProposal) => {
      // Superseded proposals (a different proposal for this node was applied
      // first) are dropped silently — first-accept-wins.
      if (proposal.status === 'superseded') {
        setCodeChangeProposals((prev) => prev.filter((p) => p.proposalId !== proposal.proposalId));
        return;
      }
      upsertProposal(proposal);
    });
    socket.on('code_change_applied', (proposal: CodeChangeProposal & { node?: any; revision?: number }) => {
      setCodeChangeProposals((prev) => prev.filter((p) => p.proposalId !== proposal.proposalId));
      if (proposal.node) {
        if (proposal.revision !== undefined) nodeRevisions.current.set(proposal.node.id, Number(proposal.revision));
        remoteNodeUpdates.current.add(proposal.node.id);
        // Stamp the node so the local code editor knows accepted code arrived
        // and should be executed. The stamp is local-only (stripped on emit).
        const stamp = Date.now();
        setNodes((prev: any[]) => prev.map((n) => {
          if (n.id !== proposal.node.id) return n;
          const hydrated = hydrateNodeForRuntime(proposal.node, n);
          return { ...hydrated, data: { ...hydrated.data, _approvedCodeStamp: stamp } };
        }));
      }
    });

    return () => {
      socket.emit('leave_session', { sessionId, userId: myUserId });
      socket.disconnect();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Safety net: any time a node is missing one of the runtime fields (e.g. it
  // came in via session_state on a fresh page load and the editor would
  // otherwise crash on `data.pythonInterpreter.interpretCode`), patch it up
  // here before the editor renders.
  useEffect(() => {
    const isRuntimeMissing = (node: any) => {
      const d = node.data || {};
      const interpreter = d.pythonInterpreter;
      return (
        !interpreter ||
        typeof interpreter.interpretCode !== 'function' ||
        typeof d.outputCallback !== 'function' ||
        typeof d.interactionsCallback !== 'function' ||
        typeof d.propagationCallback !== 'function'
      );
    };

    if (!nodes.some(isRuntimeMissing)) return;

    setNodes((prev: any[]) => prev.map((node) => {
      if (!isRuntimeMissing(node)) return node;
      remoteNodeUpdates.current.add(node.id);
      const hydrated = hydrateNodeForRuntime(node, node);
      prevNodeData.current.set(hydrated.id, dataFingerprint(hydrated));
      return hydrated;
    }));
  }, [nodes, hydrateNodeForRuntime, setNodes]);

  // ── Detect local node changes and emit ──────────────────────────────────

  useEffect(() => {
    const currentIds = new Set(nodes.map((n) => n.id));

    for (const node of nodes) {
      if (!prevNodeIds.current.has(node.id)) {
        // New node
        if (remoteNodeAdds.current.has(node.id)) {
          remoteNodeAdds.current.delete(node.id);
        } else {
          socketRef.current?.emit('node_added', {
            sessionId,
            userId: myUserId,
            userName: myUserName,
            node: serializeNode(node),
          });
        }
        // Seed data fingerprint for this new node
        prevNodeData.current.set(node.id, dataFingerprint(node));
      } else {
        // Existing node — check if data changed (execution output, code, etc.)
        const fp = dataFingerprint(node);
        const prevFp = prevNodeData.current.get(node.id);
        if (prevFp !== undefined && prevFp !== fp) {
          if (remoteNodeUpdates.current.has(node.id)) {
            remoteNodeUpdates.current.delete(node.id);
          } else {
            socketRef.current?.emit('node_updated', {
              sessionId,
              userId: myUserId,
              userName: myUserName,
              node: serializeNode(node),
              baseRevision: nodeRevisions.current.get(node.id) || 0,
              changeSummary: summarizeNodeChange(prevFp, node),
            });
          }
          prevNodeData.current.set(node.id, fp);
        }
      }
    }

    for (const id of prevNodeIds.current) {
      if (!currentIds.has(id)) {
        prevNodeData.current.delete(id);
        if (remoteNodeRemoves.current.has(id)) {
          remoteNodeRemoves.current.delete(id);
        } else {
          socketRef.current?.emit('node_removed', {
            sessionId,
            userId: myUserId,
            userName: myUserName,
            nodeId: id,
            baseRevision: nodeRevisions.current.get(id) || 0,
          });
        }
      }
    }

    prevNodeIds.current = currentIds;
  }, [nodes]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Detect local edge changes and emit ──────────────────────────────────

  useEffect(() => {
    const currentIds = new Set(edges.map((e) => e.id));

    for (const edge of edges) {
      if (!prevEdgeIds.current.has(edge.id)) {
        if (remoteEdgeAdds.current.has(edge.id)) {
          remoteEdgeAdds.current.delete(edge.id);
        } else {
          socketRef.current?.emit('edge_added', {
            sessionId,
            userId: myUserId,
            userName: myUserName,
            edge,
          });
        }
      }
      prevEdgeSnapshots.current.set(edge.id, edge);
    }

    for (const id of prevEdgeIds.current) {
      if (!currentIds.has(id)) {
        if (remoteEdgeRemoves.current.has(id)) {
          remoteEdgeRemoves.current.delete(id);
        } else {
          const previousEdge = prevEdgeSnapshots.current.get(id);
          socketRef.current?.emit('edge_removed', {
            sessionId,
            userId: myUserId,
            userName: myUserName,
            edgeId: id,
            source: previousEdge?.source,
            target: previousEdge?.target,
            baseRevision: edgeRevisions.current.get(id) || 0,
          });
        }
        prevEdgeSnapshots.current.delete(id);
      }
    }

    prevEdgeIds.current = currentIds;
  }, [edges]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Detect local output changes and emit ────────────────────────────────

  useEffect(() => {
    for (const entry of outputs) {
      const fp = JSON.stringify(entry.output);
      const prevFp = prevOutputFingerprints.current.get(entry.nodeId);
      if (prevFp === fp) continue;
      prevOutputFingerprints.current.set(entry.nodeId, fp);

      if (remoteOutputUpdates.current.has(entry.nodeId)) {
        remoteOutputUpdates.current.delete(entry.nodeId);
      } else {
        socketRef.current?.emit('output_produced', {
          sessionId,
          userId: myUserId,
          userName: myUserName,
          nodeId: entry.nodeId,
          output: entry.output,
        });
      }
    }
  }, [outputs]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Lock API ────────────────────────────────────────────────────────────

  const lockNode = useCallback((nodeId: string) => {
    setLockedNodes((prev) => ({ ...prev, [nodeId]: { userId: myUserId, color: myColor, name: myUserName } }));
    socketRef.current?.emit('node_lock', { sessionId, userId: myUserId, userName: myUserName, nodeId });
  }, [myUserId, myColor, myUserName, sessionId]);

  const unlockNode = useCallback((nodeId: string) => {
    setLockedNodes((prev) => { const n = { ...prev }; delete n[nodeId]; return n; });
    socketRef.current?.emit('node_unlock', { sessionId, userId: myUserId, userName: myUserName, nodeId });
  }, [myUserId, myUserName, sessionId]);

  const dismissConflict = useCallback((nodeId: string) => {
    setConflicts((prev) => prev.filter((c) => c.nodeId !== nodeId && c.conflictId !== nodeId));
  }, []);

  const setUserName = useCallback((name: string) => {
    const nextName = name.trim().slice(0, 40) || `Analyst ${myUserId.slice(0, 4)}`;
    localStorage.setItem('curio_collab_userName', nextName);
    setMyUserName(nextName);
    socketRef.current?.emit('set_user_profile', { sessionId, userId: myUserId, userName: nextName });
  }, [myUserId, sessionId]);

  const applyServerVersion = useCallback((conflict: Conflict) => {
    const operation = conflict.operation;

    if (operation === 'node_updated') {
      if (conflict.currentNode) {
        remoteNodeUpdates.current.add(conflict.currentNode.id);
        setNodes((prev: any[]) => prev.map((n) =>
          n.id === conflict.currentNode.id ? hydrateNodeForRuntime(conflict.currentNode, n) : n
        ));
        if (conflict.serverRevision !== undefined) {
          nodeRevisions.current.set(conflict.currentNode.id, Number(conflict.serverRevision));
        }
      } else if (conflict.nodeId) {
        remoteNodeRemoves.current.add(conflict.nodeId);
        setNodes((prev: any[]) => prev.filter((n) => n.id !== conflict.nodeId));
      }
    } else if (operation === 'node_removed') {
      if (conflict.currentNode) {
        remoteNodeAdds.current.add(conflict.currentNode.id);
        remoteNodeUpdates.current.add(conflict.currentNode.id);
        setNodes((prev: any[]) => {
          if (prev.some((n) => n.id === conflict.currentNode.id)) {
            return prev.map((n) => n.id === conflict.currentNode.id ? hydrateNodeForRuntime(conflict.currentNode, n) : n);
          }
          return [...prev, hydrateNodeForRuntime(conflict.currentNode)];
        });
      }
    } else if (operation === 'edge_removed') {
      if (conflict.currentEdge) {
        remoteEdgeAdds.current.add(conflict.currentEdge.id);
        setEdges((prev: any[]) => {
          if (prev.some((e) => e.id === conflict.currentEdge.id)) return prev;
          return [...prev, conflict.currentEdge];
        });
      }
    } else if (operation === 'edge_added') {
      if (conflict.incomingEdge) {
        remoteEdgeRemoves.current.add(conflict.incomingEdge.id);
        setEdges((prev: any[]) => prev.filter((e) => e.id !== conflict.incomingEdge.id));
      }
    }
  }, [hydrateNodeForRuntime, setEdges, setNodes]);

  const resolveConflict = useCallback((conflict: Conflict, action: ConflictResolutionAction) => {
    const actorId = conflict.actor?.userId;
    const isActor = !!actorId && actorId === myUserId;

    // Local revert is only meaningful for the actor: their canvas may
    // already reflect the rejected action, so they need the server's view
    // back. Non-actors are already on the server's view; the server will
    // broadcast any state change resulting from the resolution.
    if (isActor && action !== 'keep_mine') {
      applyServerVersion(conflict);
    }
    setConflicts((prev) => prev.filter((c) => c.conflictId !== conflict.conflictId));
    socketRef.current?.emit('resolve_conflict', {
      sessionId,
      userId: myUserId,
      userName: myUserName,
      action,
      conflict,
    });
  }, [applyServerVersion, myUserId, myUserName, sessionId]);

  const syncNodeOutput = useCallback((nodeId: string, displayOutput: { code: string; content: string }) => {
    socketRef.current?.emit('node_exec_display', {
      sessionId,
      userId: myUserId,
      userName: myUserName,
      nodeId,
      displayOutput,
    });
  }, [myUserId, myUserName, sessionId]);

  const requestCodeChange = useCallback((nodeId: string, code: string) => {
    const node = nodes.find((n: any) => n.id === nodeId);
    if (!node) return;

    const currentCode = node.data?.code ?? node.data?.defaultCode ?? '';
    if (code === currentCode) return;

    const nextNode = {
      ...node,
      data: {
        ...(node.data || {}),
        code,
      },
    };

    socketRef.current?.emit('request_code_change', {
      sessionId,
      userId: myUserId,
      userName: myUserName,
      node: serializeNode(nextNode),
      baseRevision: nodeRevisions.current.get(nodeId) || 0,
      changeSummary: ['code'],
    });
  }, [myUserId, myUserName, nodes, sessionId]);

  const approveCodeChange = useCallback((proposalId: string) => {
    socketRef.current?.emit('approve_code_change', {
      sessionId,
      userId: myUserId,
      userName: myUserName,
      proposalId,
    });
  }, [myUserId, myUserName, sessionId]);

  const rejectCodeChange = useCallback((proposalId: string, comment: string) => {
    socketRef.current?.emit('reject_code_change', {
      sessionId,
      userId: myUserId,
      userName: myUserName,
      proposalId,
      comment,
    });
  }, [myUserId, myUserName, sessionId]);

  return (
    <CollaborationContext.Provider value={{
      isConnected,
      myUserId,
      myUserName,
      myColor,
      sessionId,
      connectedUsers,
      lockedNodes,
      conflicts,
      codeChangeProposals,
      activityLog,
      setUserName,
      lockNode,
      unlockNode,
      dismissConflict,
      resolveConflict,
      requestCodeChange,
      approveCodeChange,
      rejectCodeChange,
      syncNodeOutput,
    }}>
      {children}
    </CollaborationContext.Provider>
  );
};

export const useCollaborationContext = () => useContext(CollaborationContext);

export default CollaborationProvider;
