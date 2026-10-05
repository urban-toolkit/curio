/**
 * #629: with collaboration on, a selection made on a node that arrived from a
 * collaborator reaches the nodes linked to it, as it does without collaboration.
 *
 * Drives the REAL FlowProvider with collaboration enabled. A peer adds a chart,
 * a Data Pool and the interaction edge between them; the chart's
 * `interactionsCallback` (re-attached on receipt, since the socket strips
 * functions) then records a selection, which must land on the pool.
 * Harness as in connectionFanInGuard.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';

// jsdom polyfills ReactFlow needs.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

// Mocks: replace the heavy and IO collaborators, keep reactflow REAL.
jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    persistDataflowForInstall: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    applyRemoveChanges: jest.fn(),
    applyReviewedRemovals: jest.fn(),
    allMinimized: false,
    setAllMinimized: jest.fn(),
    expandStatus: {},
    setExpandStatus: jest.fn(),
    updateDataNode: jest.fn(),
    updateDefaultCode: jest.fn(),
    workflowGoal: '',
    acceptSuggestion: jest.fn(),
  }),
}));

jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

// The peer's events, by name. `onRemote` registers a handler here; the test
// fires them as the socket would.
const mockHandlers: Record<string, (payload: any) => void> = {};
const mockNoop = () => undefined;
// One object for every render: the receive effect depends on `onRemote`.
const mockCollab = {
  enabled: true,
  lockedNodes: {},
  currentUserId: null,
  lockNode: mockNoop,
  unlockNode: mockNoop,
  signalExecDisplay: mockNoop,
  broadcastOutputProduced: mockNoop,
  broadcastNodeAdded: mockNoop,
  broadcastNodeRemoved: mockNoop,
  broadcastEdgeAdded: mockNoop,
  broadcastEdgeRemoved: mockNoop,
  onRemote: (event: string, handler: (payload: any) => void) => {
    mockHandlers[event] = handler;
    return () => {
      if (mockHandlers[event] === handler) delete mockHandlers[event];
    };
  },
};
jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => mockCollab,
}));

jest.mock('../../hook/useCode', () => ({
  pythonInterpreter: {},
  jsInterpreter: {},
}));

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE, VisInteractionType } from '../../constants';

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={ctx.nodes}
        edges={ctx.edges}
        onNodesChange={ctx.onNodesChange}
        onEdgesChange={ctx.onEdgesChange}
      />
    </div>
  );
};

function renderFlow() {
  return render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

// A node as a peer's `node_added` carries it: plain JSON, no callbacks.
function remoteNode(id: string, nodeType: string, x: number) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [] },
  };
}

async function fromPeer(event: string, payload: any) {
  expect(typeof mockHandlers[event]).toBe('function');
  await act(async () => {
    mockHandlers[event](payload);
  });
  await flush();
}

const nodeById = (id: string) => api.nodes.find((n: any) => n.id === id) as any;

afterEach(() => {
  for (const key of Object.keys(mockHandlers)) delete mockHandlers[key];
});

describe('collaboration: a selection on a received node reaches linked nodes (#629)', () => {
  test("a chart received from a peer sends its selection to the pool it is linked to", async () => {
    renderFlow();
    await flush();

    await fromPeer('node_added', { node: remoteNode('chart', 'curio.builtin/vis-vega@1', 0) });
    await fromPeer('node_added', { node: remoteNode('pool', 'curio.builtin/data-pool@1', 400) });
    await fromPeer('edge_added', {
      edge: { id: 'chart-pool', source: 'chart', target: 'pool', sourceHandle: 'in/out', targetHandle: 'in/out' },
    });

    expect(nodeById('chart')).toBeDefined();
    expect(nodeById('pool')).toBeDefined();
    expect(api.edges.map((e: any) => e.id)).toEqual(['chart-pool']);
    expect(typeof nodeById('chart').data.interactionsCallback).toBe('function');

    const details = { highlight: { type: VisInteractionType.POINT, data: [2], priority: 1 } };
    await act(async () => {
      nodeById('chart').data.interactionsCallback(details, 'chart');
    });
    await flush();

    expect(nodeById('pool').data.interactions).toEqual([
      expect.objectContaining({ nodeId: 'chart', details, priority: 1 }),
    ]);
  });
});
